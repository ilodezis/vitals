"""Endpoints for the GLP-1 protocol: injections, dose phases, side effects."""
from __future__ import annotations

from datetime import date as date_type
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import Domain, Drug, InjectionSite
from vitals.services import alerts_service, glp1_service
from vitals.services.conflict_engine import ConflictBlocked
from vitals.utils.timeutils import today_local
from web.deps import get_session, require_auth
from web.templating import templates

router = APIRouter(prefix="/glp1", tags=["glp1"])


def _redirect(request: Request) -> RedirectResponse:
    response = RedirectResponse(url="/glp1", status_code=status.HTTP_303_SEE_OTHER)
    if "hx-request" in request.headers:
        response.headers["HX-Redirect"] = "/glp1"
    return response


@router.get("", response_class=HTMLResponse)
async def glp1_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    """GLP-1 dashboard: current dose, body-map rotation, injections, side effects."""
    await glp1_service.refresh_plateau_alert(db)
    await db.commit()

    injections = await glp1_service.list_injections(db)
    phases = await glp1_service.list_dose_phases(db)
    side_effects = await glp1_service.list_side_effects(db)
    alerts = await alerts_service.list_active(db, domain=Domain.GLP1.value)

    active_phase = await glp1_service.active_dose_phase(db)
    last_inj = await glp1_service.last_injection(db)

    return templates.TemplateResponse(
        request,
        "glp1/index.html",
        {
            "username": username,
            "injections": injections,
            "phases": sorted(phases, key=lambda p: p.start_date, reverse=True),
            "side_effects": side_effects,
            "alerts": alerts,
            "active_phase": active_phase,
            "last_injection": last_inj,
            "drugs": [d.value for d in Drug],
            "sites": [s.value for s in InjectionSite],
            "today": today_local().isoformat(),
            "today_date": today_local(),
        },
    )


@router.post("/injection")
async def add_injection(
    request: Request,
    id: Optional[int] = Form(None),
    date: str = Form(...),
    drug: str = Form(...),
    dose_mg: float = Form(...),
    site: Optional[str] = Form(None),
    note: Optional[str] = Form(None),
    override: bool = Form(False),
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    on_date = date_type.fromisoformat(date)
    try:
        if id is not None:
            await glp1_service.update_injection(
                db, id, on_date=on_date, drug=drug, dose_mg=dose_mg,
                site=site, note=note, override=override,
            )
        else:
            await glp1_service.log_injection(
                db,
                on_date=on_date,
                drug=drug,
                dose_mg=dose_mg,
                site=site,
                note=note,
                override=override,
            )
        await db.commit()
    except ConflictBlocked as e:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"violations": [v.to_dict() for v in e.violations]},
        )
    return _redirect(request)


@router.post("/phase")
async def add_phase(
    request: Request,
    start_date: str = Form(...),
    end_date: Optional[str] = Form(None),
    drug: str = Form(...),
    dose_mg: float = Form(...),
    note: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    start = date_type.fromisoformat(start_date)
    end = date_type.fromisoformat(end_date) if end_date else None
    await glp1_service.add_dose_phase(
        db, start_date=start, end_date=end, drug=drug, dose_mg=dose_mg, note=note
    )
    await db.commit()
    return _redirect(request)


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
    await glp1_service.log_side_effect(
        db, on_date=on_date, effect_type=effect_type, severity=severity, note=note
    )
    await db.commit()
    return _redirect(request)


@router.post("/injection/{id}/delete")
async def delete_injection(
    request: Request,
    id: int,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    await glp1_service.delete_injection(db, id)
    await db.commit()
    return _redirect(request)


@router.post("/phase/{id}/delete")
async def delete_phase(
    request: Request,
    id: int,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    await glp1_service.delete_dose_phase(db, id)
    await db.commit()
    return _redirect(request)


@router.post("/side-effect/{id}/delete")
async def delete_side_effect(
    request: Request,
    id: int,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    await glp1_service.delete_side_effect(db, id)
    await db.commit()
    return _redirect(request)
