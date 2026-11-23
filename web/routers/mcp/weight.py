"""Weight, body measurements and noise markers."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from vitals.enums import Source
from vitals.models import (
    BodyMeasurement, NoiseMarker,
)
from vitals.services.conflict_engine import ConflictBlocked
from vitals.utils.timeutils import today_local
from web.routers.mcp._core import (
    READ, WRITE, _conflict_payload, _parse_date, get_session_factory, dispatch, serialize_row, serialize_written, tool,
)

@tool(READ)
async def get_weight_logs(
    start_date: Optional[str] = None, end_date: Optional[str] = None, limit: int = 100
) -> dict:
    """Retrieves active weight logs, body measurements, and noise markers for a
    date range (YYYY-MM-DD). Weights/measurements default to the most recent 100."""
    from vitals.services import weight_service

    session_factory = get_session_factory()
    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")

    async with session_factory() as session:
        # Weight logs — the "active weight" invariant (superseded filter, source
        # priority) lives in weight_service; call it instead of re-encoding the
        # rule here, then apply this tool's newest-first, most-recent-`limit`
        # contract on top (the service returns all matching rows, ascending).
        weights = await weight_service.list_active_weights(session, start=start, end=end)
        weights = sorted(weights, key=lambda w: w.date, reverse=True)[:limit]

        # Body measurements
        m_stmt = select(BodyMeasurement)
        if start:
            m_stmt = m_stmt.where(BodyMeasurement.date >= start)
        if end:
            m_stmt = m_stmt.where(BodyMeasurement.date <= end)
        m_stmt = m_stmt.order_by(BodyMeasurement.date.desc()).limit(limit)
        measurements = (await session.execute(m_stmt)).scalars().all()

        # Noise markers
        n_stmt = select(NoiseMarker).order_by(NoiseMarker.start_date.desc())
        noise = (await session.execute(n_stmt)).scalars().all()

        return {
            "weights": [serialize_row(w) for w in weights],
            "measurements": [serialize_row(m) for m in measurements],
            "noise_markers": [serialize_row(n) for n in noise],
        }


# ── Weight tools ────────────────────────────────────────────────────────────

async def log_weight(
    weight_kg: float,
    on_date: Optional[str] = None,
    note: Optional[str] = None,
    override: bool = False,
) -> dict:
    """Records a manual weight entry (kg). One active weight per date — manual
    entries override Garmin imports. WRITE tool — saved immediately. If a hard
    conflict rule blocks the save, returns ``{"blocked": true, ...}``; call again
    with ``override=True`` to save anyway."""
    from vitals.services import weight_service

    session_factory = get_session_factory()
    parsed_date = _parse_date(on_date, today_local(), field="on_date")

    async with session_factory() as session:
        try:
            row = await weight_service.log_weight(
                session, on_date=parsed_date, weight_kg=weight_kg, note=note,
                source=Source.MCP.value, override=override,
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
        except ValueError as e:
            return {"error": str(e)}
        await session.commit()
        return await serialize_written(session, row)


async def update_weight(
    log_id: int,
    weight_kg: Optional[float] = None,
    on_date: Optional[str] = None,
    note: Optional[str] = None,
    clear_note: bool = False,
    override: bool = False,
) -> dict:
    """Corrects a weight entry by ID (from ``get_weight_logs``) — a mistyped
    value, the wrong day, a note. Only what you pass changes; ``clear_note=True``
    empties the note. Moving it to another date re-ranks both days (the entry
    can outrank a Garmin import there, and the old day's next entry becomes
    active again). Runs the same conflict check as ``log_weight`` — a hard block
    returns ``{"blocked": true, ...}``; retry with ``override=True``. WRITE tool."""
    from vitals.services import weight_service

    parsed_date = _parse_date(on_date, field="on_date")
    session_factory = get_session_factory()
    async with session_factory() as session:
        row = await weight_service.get_weight_log(session, log_id)
        if row is None:
            return {"error": f"Weight log {log_id} not found"}
        try:
            updated = await weight_service.update_weight_log(
                session, log_id,
                on_date=parsed_date or row.date,
                weight_kg=weight_kg if weight_kg is not None else row.weight_kg,
                note=None if clear_note else (note if note is not None else row.note),
                override=override,
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
        except ValueError as e:
            return {"error": str(e)}
        await session.commit()
        return await serialize_written(session, updated)


# ── Body measurement tools ──────────────────────────────────────────────────

async def log_measurement(
    on_date: Optional[str] = None,
    neck_cm: Optional[float] = None,
    waist_cm: Optional[float] = None,
    hips_cm: Optional[float] = None,
    note: Optional[str] = None,
    override: bool = False,
) -> dict:
    """Records body circumference measurements (neck, waist, hips in cm). Upserts
    per date. Auto-computes Navy body-fat % and LBM if weight exists for the date.
    WRITE tool — saved immediately. If a hard conflict rule blocks the save,
    returns ``{"blocked": true, ...}``; call again with ``override=True``."""
    from vitals.services import weight_service

    session_factory = get_session_factory()
    parsed_date = _parse_date(on_date, today_local(), field="on_date")

    async with session_factory() as session:
        try:
            row = await weight_service.upsert_body_measurement(
                session, on_date=parsed_date, neck_cm=neck_cm, waist_cm=waist_cm,
                hips_cm=hips_cm, note=note, override=override,
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
        except ValueError as e:
            return {"error": str(e)}
        await session.commit()
        return await serialize_written(session, row)


async def get_measurements(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    """Retrieves body measurements (neck, waist, hips, body-fat %, LBM) for a date
    range. Defaults to the most recent 100 rows."""
    session_factory = get_session_factory()
    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")

    async with session_factory() as session:
        stmt = select(BodyMeasurement)
        if start:
            stmt = stmt.where(BodyMeasurement.date >= start)
        if end:
            stmt = stmt.where(BodyMeasurement.date <= end)
        stmt = stmt.order_by(BodyMeasurement.date.desc()).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        return [serialize_row(r) for r in rows]


# ── Body measurement edit/delete + noise markers ──────────────────────────────
async def update_measurement(
    measurement_id: int,
    on_date: Optional[str] = None,
    neck_cm: Optional[float] = None,
    waist_cm: Optional[float] = None,
    hips_cm: Optional[float] = None,
    note: Optional[str] = None,
    override: bool = False,
) -> dict:
    """Edits a body-measurement row by ID (recomputes Navy body-fat % / LBM).
    Only the fields you pass change; ``on_date`` left out keeps the row's own
    date. On a hard block returns ``{"blocked": true, ...}``; retry with
    ``override=True``. WRITE tool."""
    from vitals.services import weight_service

    session_factory = get_session_factory()
    parsed_date = _parse_date(on_date, field="on_date")
    async with session_factory() as session:
        if parsed_date is None:
            existing = await session.get(BodyMeasurement, measurement_id)
            if existing is None:
                return {"error": f"Measurement {measurement_id} not found"}
            parsed_date = existing.date
        try:
            row = await weight_service.update_body_measurement(
                session, measurement_id, on_date=parsed_date, neck_cm=neck_cm,
                waist_cm=waist_cm, hips_cm=hips_cm, note=note, override=override,
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
        except ValueError as e:
            return {"error": str(e)}
        if row is None:
            return {"error": f"Measurement {measurement_id} not found"}
        await session.commit()
        return await serialize_written(session, row)


async def add_noise_marker(
    start_date: str,
    reason: str,
    end_date: Optional[str] = None,
    direction: Optional[str] = None,
) -> dict:
    """Marks a date range as noisy so it's excluded from the weight moving average
    and trend (e.g. "sick week", "creatine loading"). ``direction`` is up (scale
    inflated), down (scale deflated), or neutral. Omit ``end_date`` for a single
    day. WRITE tool — the weight trend recomputes without this range."""
    from vitals.services import weight_service

    session_factory = get_session_factory()
    parsed_start = _parse_date(start_date, field="start_date")
    parsed_end = _parse_date(end_date, field="end_date")
    async with session_factory() as session:
        row = await weight_service.add_noise_marker(
            session, start_date=parsed_start, end_date=parsed_end,
            reason=reason, direction=direction,
        )
        await session.commit()
        return await serialize_written(session, row)


# ── Consolidated write tool ──────────────────────────────────────────────────
_WEIGHT_ENTRIES = {
    ("weight", False): (log_weight, None),
    ("weight", True): (update_weight, "log_id"),
    ("measurement", False): (log_measurement, None),
    ("measurement", True): (update_measurement, "measurement_id"),
    ("noise_marker", False): (add_noise_marker, None),
}


@tool(WRITE)
async def save_weight(
    entry: str = "weight",
    record_id: Optional[int] = None,
    weight_kg: Optional[float] = None,
    on_date: Optional[str] = None,
    neck_cm: Optional[float] = None,
    waist_cm: Optional[float] = None,
    hips_cm: Optional[float] = None,
    note: Optional[str] = None,
    clear_note: Optional[bool] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    reason: Optional[str] = None,
    direction: Optional[str] = None,
    override: Optional[bool] = None,
) -> dict:
    """Records or corrects weight-domain data. Without ``record_id`` it creates;
    with one (an ``id`` from ``get_weight_logs``) it edits only the fields passed.

    ``entry``:
      * ``weight`` — ``weight_kg`` for ``on_date`` (default today), ``note``. One
        active weight per date; manual entries outrank Garmin imports. Editing:
        ``clear_note=true`` empties the note.
      * ``measurement`` — ``neck_cm`` / ``waist_cm`` / ``hips_cm`` (cm) for
        ``on_date``; upserts per date and recomputes Navy body-fat % and LBM.
      * ``noise_marker`` — ``start_date`` [+ ``end_date``] excluded from the weight
        moving average and trend, with a ``reason`` ("sick week", "creatine
        loading") and an optional ``direction``: up (scale inflated) or down.

    A hard conflict block returns ``{"blocked": true, ...}``; repeat with
    ``override=true`` only if the owner insists."""
    args = dict(
        weight_kg=weight_kg, on_date=on_date, neck_cm=neck_cm, waist_cm=waist_cm,
        hips_cm=hips_cm, note=note, clear_note=clear_note, start_date=start_date,
        end_date=end_date, reason=reason, direction=direction, override=override,
    )
    return await dispatch("save_weight", "entry", entry, _WEIGHT_ENTRIES, args, record_id)
