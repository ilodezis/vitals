"""GLP-1 injections, dose phases and side effects."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from vitals.models import (
    DosePhase, Injection, SideEffect,
)
from vitals.services.conflict_engine import ConflictBlocked
from vitals.utils.timeutils import today_local
from web.routers.mcp._core import (
    READ, WRITE, _conflict_payload, _merged, _parse_date, gated, get_session_factory, dispatch, serialize_row, serialize_written, tool,
)

@tool(READ, module="glp1")
async def get_glp1_logs(
    start_date: Optional[str] = None, end_date: Optional[str] = None, limit: int = 100
) -> dict:
    """Retrieves GLP-1 injection logs, active dosage phases, and recorded side
    effects. Injections/side effects default to the most recent 100."""
    session_factory = get_session_factory()
    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")

    async with session_factory() as session:
        # Injections
        i_stmt = select(Injection)
        if start:
            i_stmt = i_stmt.where(Injection.date >= start)
        if end:
            i_stmt = i_stmt.where(Injection.date <= end)
        i_stmt = i_stmt.order_by(Injection.date.desc()).limit(limit)
        injections = (await session.execute(i_stmt)).scalars().all()

        # Dose phases
        p_stmt = select(DosePhase).order_by(DosePhase.start_date.desc())
        phases = (await session.execute(p_stmt)).scalars().all()

        # Side effects
        s_stmt = select(SideEffect)
        if start:
            s_stmt = s_stmt.where(SideEffect.date >= start)
        if end:
            s_stmt = s_stmt.where(SideEffect.date <= end)
        s_stmt = s_stmt.order_by(SideEffect.date.desc()).limit(limit)
        effects = (await session.execute(s_stmt)).scalars().all()

        return {
            "injections": [serialize_row(i) for i in injections],
            "dose_phases": [serialize_row(p) for p in phases],
            "side_effects": [serialize_row(s) for s in effects],
        }


# ── GLP-1 tools ─────────────────────────────────────────────────────────────

@gated("glp1")
async def log_glp1(
    drug: str,
    dose_mg: float,
    on_date: Optional[str] = None,
    site: Optional[str] = None,
    note: Optional[str] = None,
    override: bool = False,
) -> dict:
    """Records a GLP-1 injection (drug name, dose in mg, optional injection site).
    WRITE tool — saved immediately. If a hard conflict rule blocks the save,
    returns ``{"blocked": true, ...}``; call again with ``override=True`` to save
    anyway."""
    from vitals.services import glp1_service
    from vitals.utils.timeutils import today_local

    session_factory = get_session_factory()
    parsed_date = _parse_date(on_date, today_local(), field="on_date")

    async with session_factory() as session:
        try:
            row = await glp1_service.log_injection(
                session, on_date=parsed_date, drug=drug, dose_mg=dose_mg,
                site=site, note=note, override=override,
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
        except ValueError as e:
            # An LLM bypasses the HTML form, so bad input (dose_mg<=0, garbage site)
            # comes back as a clean error instead of an opaque DB failure.
            return {"error": str(e)}
        await session.commit()
        return await serialize_written(session, row)


# ── GLP-1 write completeness (edit/delete injection, side effects, phases) ────
@gated("glp1")
async def update_glp1(
    injection_id: int,
    drug: Optional[str] = None,
    dose_mg: Optional[float] = None,
    on_date: Optional[str] = None,
    site: Optional[str] = None,
    note: Optional[str] = None,
    override: bool = False,
) -> dict:
    """Edits an existing GLP-1 injection by ID. Only the fields you pass are
    changed; ``on_date`` left out keeps the injection's own date. Runs the same
    conflict gate as a fresh log — on a hard block returns ``{"blocked": true,
    ...}``; retry with ``override=True``. WRITE tool."""
    from vitals.services import glp1_service

    session_factory = get_session_factory()
    parsed_date = _parse_date(on_date, field="on_date")
    async with session_factory() as session:
        merged = await _merged(
            session, Injection, injection_id,
            date=parsed_date, drug=drug, dose_mg=dose_mg, site=site, note=note,
        )
        if merged is None:
            return {"error": f"Injection {injection_id} not found"}
        try:
            row = await glp1_service.update_injection(
                session, injection_id, on_date=merged.pop("date"),
                override=override, **merged,
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
        except ValueError as e:
            return {"error": str(e)}
        await session.commit()
        return await serialize_written(session, row)


@gated("glp1")
async def log_side_effect(
    effect_type: str,
    severity: int,
    on_date: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    """Records a GLP-1 side effect (e.g. "nausea") with a severity 1–5 for a date
    (default today). WRITE tool — saved immediately."""
    from vitals.services import glp1_service
    from vitals.utils.timeutils import today_local

    session_factory = get_session_factory()
    parsed_date = _parse_date(on_date, today_local(), field="on_date")
    async with session_factory() as session:
        row = await glp1_service.log_side_effect(
            session, on_date=parsed_date, effect_type=effect_type,
            severity=severity, note=note,
        )
        await session.commit()
        return await serialize_written(session, row)


@gated("glp1")
async def add_dose_phase(
    start_date: str,
    drug: str,
    dose_mg: float,
    end_date: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    """Adds a GLP-1 dose phase (a period on a given drug + dose, overlaid on the
    weight chart). An open-ended phase (no ``end_date``) auto-closes any other
    still-open phase the day before it starts. WRITE tool."""
    from vitals.services import glp1_service

    if not (drug or "").strip():
        return {"error": "drug is required"}
    if dose_mg is None or dose_mg <= 0:
        return {"error": "dose_mg must be a positive number"}
    session_factory = get_session_factory()
    parsed_start = _parse_date(start_date, field="start_date")
    parsed_end = _parse_date(end_date, field="end_date")
    async with session_factory() as session:
        row = await glp1_service.add_dose_phase(
            session, start_date=parsed_start, drug=drug, dose_mg=dose_mg,
            end_date=parsed_end, note=note,
        )
        await session.commit()
        return await serialize_written(session, row)


@gated("glp1")
async def close_dose_phase(
    phase_id: Optional[int] = None, end_date: Optional[str] = None
) -> dict:
    """Ends a GLP-1 dose phase — the "close" action on the GLP-1 screen: the
    phase gets ``end_date`` (default today) and stops being the current dose.
    Without ``phase_id`` it closes the phase covering today. Starting a new
    open-ended phase with ``add_dose_phase`` already closes the previous one, so
    this is for stopping (a pause, the end of the course). WRITE tool."""
    from vitals.services import glp1_service

    parsed_end = _parse_date(end_date, today_local(), field="end_date")
    session_factory = get_session_factory()
    async with session_factory() as session:
        if phase_id is not None:
            phase = await session.get(DosePhase, phase_id)
        else:
            phase = await glp1_service.active_dose_phase(session)
        if phase is None:
            return {"error": "No such dose phase" if phase_id else "No dose phase covers today"}
        if parsed_end < phase.start_date:
            return {"error": f"end_date is before the phase's start ({phase.start_date.isoformat()})"}
        phase.end_date = parsed_end
        await session.flush()
        await session.commit()
        return await serialize_written(session, phase)


# ── Consolidated write tool ──────────────────────────────────────────────────
_GLP1_ENTRIES = {
    ("injection", False): (log_glp1, None),
    ("injection", True): (update_glp1, "injection_id"),
    ("side_effect", False): (log_side_effect, None),
    ("dose_phase", False): (add_dose_phase, None),
    ("close_phase", False): (close_dose_phase, None),
    ("close_phase", True): (close_dose_phase, "phase_id"),
}


@tool(WRITE, module="glp1")
@gated("glp1")
async def save_glp1(
    entry: str = "injection",
    record_id: Optional[int] = None,
    drug: Optional[str] = None,
    dose_mg: Optional[float] = None,
    on_date: Optional[str] = None,
    site: Optional[str] = None,
    effect_type: Optional[str] = None,
    severity: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    note: Optional[str] = None,
    override: Optional[bool] = None,
) -> dict:
    """Records or corrects GLP-1 protocol data (ids from ``get_glp1_logs``).

    ``entry``:
      * ``injection`` — ``drug``, ``dose_mg``, ``on_date`` (default today),
        optional ``site``, ``note``. With ``record_id``: edits only the fields
        passed (a left-out ``on_date`` keeps the injection's own date).
      * ``side_effect`` — ``effect_type`` ("nausea"), ``severity`` 1–5, ``on_date``.
      * ``dose_phase`` — a period on ``drug`` + ``dose_mg`` from ``start_date``
        [to ``end_date``], overlaid on the weight chart; an open-ended phase
        closes the previous open one.
      * ``close_phase`` — ends a phase at ``end_date`` (default today); without
        ``record_id`` the phase covering today. Only for stopping or pausing.

    A hard conflict block returns ``{"blocked": true, ...}``; repeat with
    ``override=true`` only if the owner insists."""
    args = dict(
        drug=drug, dose_mg=dose_mg, on_date=on_date, site=site, effect_type=effect_type,
        severity=severity, start_date=start_date, end_date=end_date, note=note,
        override=override,
    )
    return await dispatch("save_glp1", "entry", entry, _GLP1_ENTRIES, args, record_id)
