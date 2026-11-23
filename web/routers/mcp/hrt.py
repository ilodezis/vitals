"""HRT/TRT doses, cycles and side effects."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from vitals.models import (
    HrtDose,
)
from vitals.services.conflict_engine import ConflictBlocked
from vitals.utils.timeutils import today_local
from web.routers.mcp._core import (
    READ, WRITE, _conflict_payload, _merged, _parse_date, gated, get_session_factory, dispatch, serialize_row, serialize_written, tool,
)

# ── HRT / TRT tools ─────────────────────────────────────────────────────────

async def get_hrt_logs(
    start_date: Optional[str] = None, end_date: Optional[str] = None, limit: int = 100
) -> dict:
    """Retrieves HRT/TRT dose administrations, side effects, and the active cycle
    with its per-compound plan. Doses/side effects default to the most recent 100.
    READ tool."""
    from vitals.models.hrt import HrtDose, HrtSideEffect
    from vitals.services import hrt_cycle_service

    session_factory = get_session_factory()
    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")

    async with session_factory() as session:
        d_stmt = select(HrtDose)
        if start:
            d_stmt = d_stmt.where(HrtDose.date >= start)
        if end:
            d_stmt = d_stmt.where(HrtDose.date <= end)
        d_stmt = d_stmt.order_by(HrtDose.date.desc()).limit(limit)
        doses = (await session.execute(d_stmt)).scalars().all()

        s_stmt = select(HrtSideEffect).order_by(HrtSideEffect.date.desc()).limit(limit)
        effects = (await session.execute(s_stmt)).scalars().all()

        active = await hrt_cycle_service.active_cycle(session)
        active_cycle = None
        if active is not None:
            active_cycle = serialize_row(active)
            active_cycle["items"] = [serialize_row(it) for it in active.items]

        return {
            "doses": [serialize_row(d) for d in doses],
            "side_effects": [serialize_row(e) for e in effects],
            "active_cycle": active_cycle,
        }


@gated("hrt")
async def log_hrt_dose(
    compound_key: str,
    dose: Optional[float] = None,
    unit: Optional[str] = None,
    volume_ml: Optional[float] = None,
    concentration_mg_ml: Optional[float] = None,
    on_date: Optional[str] = None,
    brand: Optional[str] = None,
    lab: Optional[str] = None,
    batch: Optional[str] = None,
    site: Optional[str] = None,
    note: Optional[str] = None,
    override: bool = False,
) -> dict:
    """Records an HRT/TRT administration. ``compound_key`` is a catalog slug (e.g.
    'testosterone_enanthate'). Give either ``dose`` (in ``unit`` — mg/iu/mcg) or a
    ``volume_ml`` with ``concentration_mg_ml`` (or the catalog concentration) to
    compute mg. Grey-market ``brand``/``lab``/``batch`` are optional. WRITE tool —
    on a hard block returns ``{"blocked": true, ...}``; retry with
    ``override=True``."""
    from vitals.services import hrt_service

    session_factory = get_session_factory()
    parsed_date = _parse_date(on_date, today_local(), field="on_date")

    async with session_factory() as session:
        try:
            row = await hrt_service.log_dose(
                session, compound_key=compound_key, on_date=parsed_date, dose=dose,
                unit=unit, volume_ml=volume_ml, concentration_mg_ml=concentration_mg_ml,
                brand=brand, lab=lab, batch=batch, site=site, note=note, override=override,
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
        except ValueError as e:
            return {"error": str(e)}
        await session.commit()
        return await serialize_written(session, row)


@gated("hrt")
async def add_hrt_cycle(
    kind: str,
    start_date: Optional[str] = None,
    name: Optional[str] = None,
    end_date: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    """Starts an HRT cycle (``kind``: course | pct — put nuance like TRT/blast/
    cruise in ``name``). An open-ended cycle closes the previous open one. WRITE
    tool. Add compounds with ``add_hrt_cycle_item``."""
    from vitals.services import hrt_cycle_service

    session_factory = get_session_factory()
    start = _parse_date(start_date, today_local(), field="start_date")
    end = _parse_date(end_date, field="end_date")

    async with session_factory() as session:
        try:
            cycle = await hrt_cycle_service.add_cycle(
                session, kind=kind, start_date=start, name=name, end_date=end, note=note,
            )
        except ValueError as e:
            return {"error": str(e)}
        await session.commit()
        return await serialize_written(session, cycle)


@gated("hrt")
async def add_hrt_cycle_item(
    cycle_id: int,
    compound_key: str,
    schedule: Optional[list] = None,
    dose: Optional[float] = None,
    interval_days: Optional[float] = None,
    duration_days: Optional[int] = None,
    start_offset_days: Optional[int] = None,
    unit: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    """Adds a compound plan to a cycle. Pass a full ``schedule`` (a list of
    segments — flat ``{dose, interval_days, duration_days}`` or a linear ramp
    ``{dose_start, dose_end, step, step_every_days, interval_days, duration_days}``)
    for titration/ramps, or the simple ``dose``+``interval_days`` for one flat
    segment. ``start_offset_days`` delays the compound's grid relative to the
    cycle start (week 5 → 28) for staggered courses. WRITE tool."""
    from vitals.services import hrt_cycle_service

    if not schedule:
        if dose is None or interval_days is None:
            return {"error": "provide schedule, or both dose and interval_days"}
        segment: dict = {"dose": dose, "interval_days": interval_days}
        if duration_days:
            segment["duration_days"] = int(duration_days)
        schedule = [segment]

    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            item = await hrt_cycle_service.add_cycle_item(
                session, cycle_id, compound_key=compound_key, schedule=schedule,
                unit=unit, start_offset_days=int(start_offset_days or 0), note=note,
            )
        except ValueError as e:
            return {"error": str(e)}
        if item is None:
            return {"error": f"cycle {cycle_id} not found"}
        await session.commit()
        return await serialize_written(session, item)


@gated("hrt")
async def update_hrt_dose(
    dose_id: int,
    compound_key: Optional[str] = None,
    dose: Optional[float] = None,
    unit: Optional[str] = None,
    volume_ml: Optional[float] = None,
    concentration_mg_ml: Optional[float] = None,
    on_date: Optional[str] = None,
    brand: Optional[str] = None,
    lab: Optional[str] = None,
    batch: Optional[str] = None,
    site: Optional[str] = None,
    note: Optional[str] = None,
    override: bool = False,
) -> dict:
    """Updates a recorded HRT/TRT administration by ID. Only the fields you pass are
    changed; everything left out keeps its stored value, including the dose's own
    date. A new ``volume_ml`` or ``concentration_mg_ml`` without a ``dose`` recomputes
    the mg. WRITE tool — on a hard block returns ``{"blocked": true, ...}``; retry
    with ``override=True``."""
    from vitals.services import hrt_service

    session_factory = get_session_factory()
    parsed_date = _parse_date(on_date, field="on_date")

    async with session_factory() as session:
        merged = await _merged(
            session,
            HrtDose,
            dose_id,
            compound_key=compound_key,
            date=parsed_date,
            dose=dose,
            unit=unit,
            volume_ml=volume_ml,
            concentration_mg_ml=concentration_mg_ml,
            brand=brand,
            lab=lab,
            batch=batch,
            site=site,
            note=note,
        )
        if merged is None:
            return {"error": f"HRT dose {dose_id} not found"}
        # A new volume or concentration is a request to recompute the mg, and an
        # explicit dose wins over both — so carrying the stored one forward here
        # would silently ignore what the call actually changed.
        if dose is None and (volume_ml is not None or concentration_mg_ml is not None):
            merged["dose"] = None
        try:
            row = await hrt_service.update_dose(
                session, dose_id, on_date=merged.pop("date"), override=override, **merged
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
        except ValueError as e:
            return {"error": str(e)}
        await session.commit()
        return await serialize_written(session, row)


@gated("hrt")
async def log_hrt_side_effect(
    effect_type: str,
    severity: int,
    on_date: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    """Records an HRT/TRT side effect (e.g. "акне", "отёки") with a severity 1–5 for
    a date (default today). Distinct from ``log_side_effect``, which belongs to
    GLP-1. WRITE tool — saved immediately."""
    from vitals.services import hrt_service

    session_factory = get_session_factory()
    parsed_date = _parse_date(on_date, today_local(), field="on_date")

    async with session_factory() as session:
        try:
            row = await hrt_service.log_side_effect(
                session, on_date=parsed_date, effect_type=effect_type,
                severity=severity, note=note,
            )
        except ValueError as e:
            return {"error": str(e)}
        await session.commit()
        return await serialize_written(session, row)


@gated("hrt")
async def close_hrt_cycle(cycle_id: int, end_date: Optional[str] = None) -> dict:
    """Closes an HRT cycle by giving it an end date (default today). WRITE tool."""
    from vitals.services import hrt_cycle_service

    session_factory = get_session_factory()
    end = _parse_date(end_date, today_local(), field="end_date")

    async with session_factory() as session:
        try:
            cycle = await hrt_cycle_service.close_cycle(session, cycle_id, end_date=end)
        except ValueError as e:
            return {"error": str(e)}
        if cycle is None:
            return {"error": f"cycle {cycle_id} not found"}
        await session.commit()
        return await serialize_written(session, cycle)


async def get_hrt_cycles() -> dict:
    """Lists all HRT cycles (newest first) with their per-compound plans. READ tool."""
    from vitals.services import hrt_cycle_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        cycles = await hrt_cycle_service.list_cycles(session)
        out = []
        for c in cycles:
            row = serialize_row(c)
            row["items"] = [serialize_row(it) for it in c.items]
            out.append(row)
        return {"cycles": out}


# ── Consolidated tools ───────────────────────────────────────────────────────
_HRT_VIEWS = {
    ("logs", False): (get_hrt_logs, None),
    ("cycles", False): (get_hrt_cycles, None),
}


@tool(READ, module="hrt")
async def get_hrt(
    view: str = "logs",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: Optional[int] = None,
) -> dict:
    """HRT/TRT history. ``view="logs"`` (default): dose administrations and side
    effects for a date range (YYYY-MM-DD, newest first, ``limit`` default 100) plus
    the active cycle with its per-compound plan. ``view="cycles"``: every cycle,
    newest first, with its plans (takes no other argument)."""
    args = dict(start_date=start_date, end_date=end_date, limit=limit)
    return await dispatch("get_hrt", "view", view, _HRT_VIEWS, args)


_HRT_ENTRIES = {
    ("dose", False): (log_hrt_dose, None),
    ("dose", True): (update_hrt_dose, "dose_id"),
    ("side_effect", False): (log_hrt_side_effect, None),
    ("cycle", False): (add_hrt_cycle, None),
    ("cycle_item", False): (add_hrt_cycle_item, None),
    ("close_cycle", False): (close_hrt_cycle, None),
}


@tool(WRITE, module="hrt")
@gated("hrt")
async def save_hrt(
    entry: str = "dose",
    record_id: Optional[int] = None,
    compound_key: Optional[str] = None,
    dose: Optional[float] = None,
    unit: Optional[str] = None,
    volume_ml: Optional[float] = None,
    concentration_mg_ml: Optional[float] = None,
    on_date: Optional[str] = None,
    brand: Optional[str] = None,
    lab: Optional[str] = None,
    batch: Optional[str] = None,
    site: Optional[str] = None,
    effect_type: Optional[str] = None,
    severity: Optional[int] = None,
    kind: Optional[str] = None,
    name: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    cycle_id: Optional[int] = None,
    schedule: Optional[list] = None,
    interval_days: Optional[float] = None,
    duration_days: Optional[int] = None,
    start_offset_days: Optional[int] = None,
    note: Optional[str] = None,
    override: Optional[bool] = None,
) -> dict:
    """Records or corrects HRT/TRT data (ids from ``get_hrt``).

    ``entry``:
      * ``dose`` — an administration of ``compound_key`` (catalog slug, e.g.
        "testosterone_enanthate"): either ``dose`` in ``unit`` (mg/iu/mcg) or
        ``volume_ml`` + ``concentration_mg_ml``; ``on_date``, ``site``, ``brand``,
        ``lab``, ``batch``, ``note``. With ``record_id``: edits only the fields
        passed.
      * ``side_effect`` — ``effect_type`` ("acne", "edema"), ``severity`` 1–5,
        ``on_date``. GLP-1 side effects go to ``save_glp1`` instead.
      * ``cycle`` — starts a cycle: ``kind`` course | pct (nuance like TRT/blast/
        cruise goes in ``name``), ``start_date``, optional ``end_date``. An
        open-ended cycle closes the previous open one.
      * ``cycle_item`` — adds a compound plan to ``cycle_id``: a full ``schedule``
        (segments ``{dose, interval_days, duration_days}`` or a linear ramp
        ``{dose_start, dose_end, ...}``) or the flat ``dose`` + ``interval_days``
        [+ ``duration_days``]; ``start_offset_days`` staggers it from the cycle
        start.
      * ``close_cycle`` — gives ``cycle_id`` an ``end_date`` (default today).

    A hard conflict block returns ``{"blocked": true, ...}``; repeat with
    ``override=true`` only if the owner insists."""
    args = dict(
        compound_key=compound_key, dose=dose, unit=unit, volume_ml=volume_ml,
        concentration_mg_ml=concentration_mg_ml, on_date=on_date, brand=brand, lab=lab,
        batch=batch, site=site, effect_type=effect_type, severity=severity, kind=kind,
        name=name, start_date=start_date, end_date=end_date, cycle_id=cycle_id,
        schedule=schedule, interval_days=interval_days, duration_days=duration_days,
        start_offset_days=start_offset_days, note=note, override=override,
    )
    return await dispatch("save_hrt", "entry", entry, _HRT_ENTRIES, args, record_id)
