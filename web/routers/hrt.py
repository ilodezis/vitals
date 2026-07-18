"""Endpoints for the HRT/TRT domain: compound catalog, dose log, side effects."""
from __future__ import annotations

from datetime import date as date_type
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import timedelta

from vitals.enums import CycleKind, Domain, DoseUnit, HrtInjectionSite
from vitals.i18n import current_lang
from vitals.services import (
    alerts_service,
    hrt_cycle_service,
    hrt_reminders,
    hrt_service,
    hrt_template_service,
)
from vitals.services.conflict_engine import ConflictBlocked
from vitals.utils.timeutils import today_local
from web.deps import get_session, require_auth
from web.templating import templates

router = APIRouter(prefix="/hrt", tags=["hrt"])


def _redirect(request: Request) -> RedirectResponse:
    response = RedirectResponse(url="/hrt", status_code=status.HTTP_303_SEE_OTHER)
    if "hx-request" in request.headers:
        response.headers["HX-Redirect"] = "/hrt"
    return response


def _optional_float(value: Optional[str]) -> Optional[float]:
    """Form floats arrive as strings and empty fields as ''. Treat blank as
    None so an omitted volume/dose doesn't become 0.0."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    return float(value)


def _parse_date(value: str) -> date_type:
    """Date parse that fails as a ValueError — the browser's type=date can't
    send garbage, but HTMX/API clients can, and that should be a 422, not a
    500 from a naked ``fromisoformat``."""
    try:
        return date_type.fromisoformat((value or "").strip())
    except ValueError:
        raise ValueError(f"invalid date: {value!r}") from None


@router.get("", response_class=HTMLResponse)
async def hrt_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    """HRT dashboard: active cycle + release curve, compounds, dose log, side effects."""
    today = today_local()
    await hrt_reminders.refresh_all(db)
    await db.commit()
    compounds = await hrt_service.list_compounds(db, active_only=True)
    # key → display name in the active language, so logs/plans show a human name
    # (e.g. "Тестостерон энантат") rather than the raw slug. Covers inactive rows
    # too, so a deactivated compound's history still reads nicely.
    lang = current_lang.get()
    all_compounds = await hrt_service.list_compounds(db, active_only=False)
    compound_names = {
        c.key: ((c.name_ru or c.name) if lang == "ru" else (c.name or c.name_ru))
        for c in all_compounds
    }
    doses = await hrt_service.list_doses(db, limit=200)
    side_effects = await hrt_service.list_side_effects(db)
    alerts = await alerts_service.list_active(db, domain=Domain.HRT.value)
    last = await hrt_service.last_dose(db)

    active_cycle = await hrt_cycle_service.active_cycle(db)
    planned = await hrt_cycle_service.planned_administrations(
        db, start=today, end=today + timedelta(days=21)
    )
    # A 90-day window (30 back, 60 forward) for the server-rendered release
    # sparkline — actual doses behind, planned projection ahead.
    release = await hrt_cycle_service.release_series(
        db, start=today - timedelta(days=30), end=today + timedelta(days=60),
    )

    cycle_templates = await hrt_template_service.list_templates(db)
    # Pre-rendered share JSON per template — the UI shows it in a copyable
    # <textarea>, so sharing needs no JS beyond select-and-copy.
    template_exports = {
        tp.id: hrt_template_service.export_template_json(tp) for tp in cycle_templates
    }

    return templates.TemplateResponse(
        request,
        "hrt/index.html",
        {
            "username": username,
            "compounds": compounds,
            "compound_names": compound_names,
            "doses": doses,
            "side_effects": side_effects,
            "alerts": alerts,
            "last_dose": last,
            "active_cycle": active_cycle,
            "cycles": await hrt_cycle_service.list_cycles(db),
            "cycle_templates": cycle_templates,
            "template_exports": template_exports,
            "planned": planned[:12],
            "release": release,
            "release_sparkline": _sparkline(release),
            "cycle_kinds": [k.value for k in CycleKind],
            # Kind-dependent bloodwork cadence, surfaced on the active-cycle card
            # so the kinds visibly differ beyond the label.
            "panel_window": (
                hrt_reminders.PANEL_WINDOW_BY_KIND.get(active_cycle.kind, 90)
                if active_cycle else None
            ),
            "site_counts": hrt_service.site_frequency(doses),
            "sites": [s.value for s in HrtInjectionSite],
            "units": [u.value for u in DoseUnit],
            "today": today.isoformat(),
            "today_date": today,
        },
    )


def _sparkline(series: list[dict], width: int = 640, height: int = 90) -> dict:
    """Turn a release series into an inline-SVG polyline (points string + peak).
    Server-rendered so the curve needs no JS/Chart.js and always draws."""
    points = [p["total_mg"] for p in series]
    peak = max(points) if points else 0.0
    n = len(points)
    if n < 2 or peak <= 0:
        return {"points": "", "peak": round(peak, 1), "today_x": 0}
    step_x = width / (n - 1)
    coords = []
    for i, v in enumerate(points):
        x = round(i * step_x, 1)
        y = round(height - (v / peak) * (height - 6) - 3, 1)
        coords.append(f"{x},{y}")
    # x-position of "today" (the 31st point in the 30-back window).
    today_x = round(min(30, n - 1) * step_x, 1)
    return {"points": " ".join(coords), "peak": round(peak, 1), "today_x": today_x}


@router.post("/dose")
async def add_dose(
    request: Request,
    id: Optional[int] = Form(None),
    date: str = Form(...),
    compound_key: str = Form(...),
    dose: Optional[str] = Form(None),
    unit: Optional[str] = Form(None),
    volume_ml: Optional[str] = Form(None),
    concentration_mg_ml: Optional[str] = Form(None),
    brand: Optional[str] = Form(None),
    lab: Optional[str] = Form(None),
    batch: Optional[str] = Form(None),
    site: Optional[str] = Form(None),
    note: Optional[str] = Form(None),
    override: bool = Form(False),
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    on_date = date_type.fromisoformat(date)
    kwargs = dict(
        compound_key=compound_key,
        on_date=on_date,
        dose=_optional_float(dose),
        unit=unit or None,
        volume_ml=_optional_float(volume_ml),
        concentration_mg_ml=_optional_float(concentration_mg_ml),
        brand=brand,
        lab=lab,
        batch=batch,
        site=site,
        note=note,
        override=override,
    )
    try:
        if id is not None:
            await hrt_service.update_dose(db, id, **kwargs)
        else:
            await hrt_service.log_dose(db, **kwargs)
        await db.commit()
    except ConflictBlocked as e:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"violations": [v.to_dict() for v in e.violations]},
        )
    except ValueError as e:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"error": str(e)},
        )
    return _redirect(request)


@router.post("/cycle")
async def add_cycle(
    request: Request,
    kind: str = Form(...),
    start_date: str = Form(...),
    name: Optional[str] = Form(None),
    end_date: Optional[str] = Form(None),
    note: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    try:
        start = _parse_date(start_date)
        end = _parse_date(end_date) if end_date else None
        await hrt_cycle_service.add_cycle(
            db, kind=kind, start_date=start, name=name, end_date=end, note=note
        )
        await db.commit()
    except ValueError as e:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"error": str(e)}
        )
    return _redirect(request)


@router.post("/cycle/{cycle_id}/item")
async def add_cycle_item(
    request: Request,
    cycle_id: int,
    compound_key: str = Form(...),
    dose: float = Form(...),
    interval_days: float = Form(...),
    duration_days: Optional[str] = Form(None),
    start_week: Optional[str] = Form(None),
    unit: Optional[str] = Form(None),
    note: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    # The form captures a single flat segment; ramps / multi-segment schedules go
    # through the API/MCP where the full JSON schedule can be supplied.
    segment: dict = {"dose": dose, "interval_days": interval_days}
    dur = _optional_float(duration_days)
    if dur:
        segment["duration_days"] = int(dur)
    try:
        # The form speaks weeks (week 1 = the cycle start); the model stores
        # days. Whole weeks only — silently flooring 2.5 to 10 days would give
        # a grid the user never asked for.
        week = _optional_float(start_week)
        if week is not None and (week < 1 or week != int(week)):
            raise ValueError("start_week must be a whole number >= 1")
        offset_days = int((week - 1) * 7) if week else 0
        await hrt_cycle_service.add_cycle_item(
            db, cycle_id, compound_key=compound_key, schedule=[segment],
            unit=unit or None, start_offset_days=offset_days, note=note,
        )
        await db.commit()
    except ValueError as e:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"error": str(e)}
        )
    return _redirect(request)


@router.post("/cycle/{cycle_id}/close")
async def close_cycle(
    request: Request,
    cycle_id: int,
    end_date: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    try:
        end = _parse_date(end_date) if end_date else today_local()
        await hrt_cycle_service.close_cycle(db, cycle_id, end_date=end)
        await db.commit()
    except ValueError as e:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"error": str(e)}
        )
    return _redirect(request)


@router.post("/cycle/{cycle_id}/delete")
async def delete_cycle(
    request: Request,
    cycle_id: int,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    await hrt_cycle_service.delete_cycle(db, cycle_id)
    await db.commit()
    return _redirect(request)


@router.post("/cycle/item/{item_id}/edit")
async def edit_cycle_item(
    request: Request,
    item_id: int,
    dose: Optional[str] = Form(None),
    interval_days: Optional[str] = Form(None),
    duration_days: Optional[str] = Form(None),
    start_week: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    """Inline edit of a plan item. Dose/interval/duration rebuild the schedule
    only when both dose and interval are supplied (the form only offers them for
    single flat-segment items — a multi-segment/ramp schedule is edited via MCP,
    here only the start week changes)."""
    try:
        week = _optional_float(start_week)
        if week is not None and (week < 1 or week != int(week)):
            raise ValueError("start_week must be a whole number >= 1")
        offset = int((week - 1) * 7) if week is not None else None

        d = _optional_float(dose)
        interval = _optional_float(interval_days)
        schedule: Optional[list[dict]] = None
        if d is not None and interval is not None:
            segment: dict = {"dose": d, "interval_days": interval}
            dur = _optional_float(duration_days)
            if dur:
                segment["duration_days"] = int(dur)
            schedule = [segment]

        item = await hrt_cycle_service.update_cycle_item(
            db, item_id, schedule=schedule, start_offset_days=offset,
        )
        if item is None:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND, content={"error": "item not found"}
            )
        await db.commit()
    except ValueError as e:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"error": str(e)}
        )
    return _redirect(request)


@router.post("/cycle/item/{item_id}/delete")
async def delete_cycle_item(
    request: Request,
    item_id: int,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    await hrt_cycle_service.delete_cycle_item(db, item_id)
    await db.commit()
    return _redirect(request)


@router.post("/cycle/{cycle_id}/save-template")
async def save_cycle_template(
    request: Request,
    cycle_id: int,
    name: str = Form(...),
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    try:
        await hrt_template_service.save_cycle_as_template(db, cycle_id, name=name)
        await db.commit()
    except ValueError as e:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"error": str(e)}
        )
    return _redirect(request)


@router.post("/template/{template_id}/create-cycle")
async def create_cycle_from_template(
    request: Request,
    template_id: int,
    start_date: str = Form(...),
    name: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    try:
        start = _parse_date(start_date)
        await hrt_template_service.create_cycle_from_template(
            db, template_id, start_date=start, name=name
        )
        await db.commit()
    except ValueError as e:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"error": str(e)}
        )
    return _redirect(request)


@router.post("/template/{template_id}/delete")
async def delete_template(
    request: Request,
    template_id: int,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    await hrt_template_service.delete_template(db, template_id)
    await db.commit()
    return _redirect(request)


@router.get("/template/{template_id}/export")
async def export_template(
    template_id: int,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    """The portable share payload as a .json download."""
    template = await hrt_template_service.get_template(db, template_id)
    if template is None:
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"error": "not found"})
    payload = hrt_template_service.export_template(template)
    safe_name = "".join(
        ch if ch.isalnum() or ch in "-_" else "_" for ch in template.name
    )[:64] or "template"
    return JSONResponse(
        content=payload,
        headers={
            "Content-Disposition": f'attachment; filename="hrt_template_{safe_name}.json"'
        },
    )


@router.post("/template/import")
async def import_template(
    request: Request,
    payload: str = Form(...),
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    try:
        await hrt_template_service.import_template(db, payload)
        await db.commit()
    except ValueError as e:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"error": str(e)}
        )
    return _redirect(request)


@router.get("/release.json")
async def release_json(
    days_back: int = 30,
    days_forward: int = 60,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    today = today_local()
    series = await hrt_cycle_service.release_series(
        db, start=today - timedelta(days=days_back),
        end=today + timedelta(days=days_forward),
    )
    return JSONResponse(content={"series": series, "today": today.isoformat()})


@router.post("/side-effect")
async def add_side_effect(
    request: Request,
    date: str = Form(...),
    effect_type: str = Form(...),
    severity: int = Form(...),
    note: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    on_date = date_type.fromisoformat(date)
    try:
        await hrt_service.log_side_effect(
            db, on_date=on_date, effect_type=effect_type, severity=severity, note=note
        )
        await db.commit()
    except ValueError as e:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"error": str(e)},
        )
    return _redirect(request)


@router.post("/dose/{id}/delete")
async def delete_dose(
    request: Request,
    id: int,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    await hrt_service.delete_dose(db, id)
    await db.commit()
    return _redirect(request)


@router.post("/side-effect/{id}/delete")
async def delete_side_effect(
    request: Request,
    id: int,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    await hrt_service.delete_side_effect(db, id)
    await db.commit()
    return _redirect(request)
