"""Body-composition (BIA) scans."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from vitals.enums import Source
from vitals.models import (
    BodyScan,
)
from vitals.services.conflict_engine import ConflictBlocked
from vitals.utils.timeutils import today_local
from web.routers.mcp._core import (
    READ, WRITE, _conflict_payload, _parse_date, gated, get_session_factory, route, serialize_row, tool,
)

# ── Body composition tools (InBody / МедАсс — optional module) ────────────────
def _serialize_scan(scan: BodyScan) -> dict:
    """A scan plus its metrics nested (relationship must be loaded already)."""
    d = serialize_row(scan)
    d["metrics"] = [serialize_row(m) for m in scan.metrics]
    return d


async def get_body_scans(
    start_date: Optional[str] = None, end_date: Optional[str] = None, limit: int = 100
) -> list[dict]:
    """Retrieves body-composition scans (InBody / МедАсс) with every parsed metric
    (skeletal muscle, body water, visceral fat, segmental analysis, phase angle…).
    Defaults to the most recent 100 scans."""
    session_factory = get_session_factory()
    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")

    async with session_factory() as session:
        stmt = select(BodyScan).options(selectinload(BodyScan.metrics))
        if start:
            stmt = stmt.where(BodyScan.date >= start)
        if end:
            stmt = stmt.where(BodyScan.date <= end)
        stmt = stmt.order_by(BodyScan.date.desc(), BodyScan.id.desc()).limit(limit)
        scans = (await session.execute(stmt)).scalars().all()
        return [_serialize_scan(s) for s in scans]


async def get_body_scan(scan_id: int) -> dict:
    """Retrieves a single body-composition scan with its full metric sheet."""
    from vitals.services import body_scan_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        scan = await body_scan_service.get_scan(session, scan_id)
        if scan is None:
            return {"error": f"Body scan {scan_id} not found"}
        return _serialize_scan(scan)


async def get_body_metric_history(
    metric_key: str,
    segment: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> list[dict]:
    """Time series for one body-composition metric (e.g. ``skeletal_muscle_mass``,
    ``phase_angle``, ``visceral_fat_area``), optionally for a single body segment."""
    from vitals.services import body_scan_service

    session_factory = get_session_factory()
    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")
    async with session_factory() as session:
        return await body_scan_service.metric_history(
            session, metric_key, segment=segment, start=start, end=end
        )


@tool(WRITE, module='body_comp')
@gated("body_comp")
async def log_body_scan(
    metrics: list[dict],
    on_date: Optional[str] = None,
    device: Optional[str] = None,
    note: Optional[str] = None,
    override: bool = False,
) -> dict:
    """Records a body-composition scan from structured metrics (no photo needed).

    Each metric is ``{"label" or "metric_key": str, "value": number, "unit": str?,
    "ref_low": number?, "ref_high": number?, "segment": str?}``. The scan's weight /
    body-fat% / LBM are bridged into the weight domain. WRITE tool — saved
    immediately. No-op with an error if the body_comp module is disabled. If a hard
    conflict rule blocks the save, returns ``{"blocked": true, ...}``; call again
    with ``override=True``."""
    from vitals.services import body_scan_service

    session_factory = get_session_factory()
    parsed_date = _parse_date(on_date, today_local(), field="on_date")

    async with session_factory() as session:
        try:
            scan = await body_scan_service.save_scan(
                session,
                on_date=parsed_date,
                device=device,
                metrics=metrics,
                note=note,
                source=Source.BODY_SCAN.value,
                override=override,
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
        except ValueError as e:
            return {"error": str(e)}
        await body_scan_service.refresh_alerts(session)
        await session.commit()
        full = await body_scan_service.get_scan(session, scan.id)
        return _serialize_scan(full) if full else {"scan_id": scan.id}


# ── Consolidated read tool ───────────────────────────────────────────────────
@tool(READ, module="body_comp")
async def get_body_comp(
    scan_id: Optional[int] = None,
    metric_key: Optional[str] = None,
    segment: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: Optional[int] = None,
) -> dict:
    """Body-composition scans (InBody / MedAss), dates YYYY-MM-DD.

    By default ``{"scans": [...]}``: every scan in the range, newest first
    (``limit`` default 100), each with all its parsed metrics (skeletal muscle,
    body water, visceral fat, segmental analysis, phase angle…). ``scan_id``:
    that one scan with its full metric sheet. ``metric_key`` (e.g.
    ``skeletal_muscle_mass``, ``phase_angle``, ``visceral_fat_area``) [+
    ``segment``]: ``{"history": [...]}``, the time series of that metric."""
    if scan_id is not None:
        return await route(
            get_body_scan, "get_body_comp(scan_id)",
            dict(scan_id=scan_id, metric_key=metric_key, segment=segment,
                 start_date=start_date, end_date=end_date, limit=limit),
        )
    if metric_key is not None:
        rows = await route(
            get_body_metric_history, "get_body_comp(metric_key)",
            dict(metric_key=metric_key, segment=segment, start_date=start_date,
                 end_date=end_date, limit=limit),
        )
        return rows if isinstance(rows, dict) else {"history": rows}
    rows = await route(
        get_body_scans, "get_body_comp",
        dict(segment=segment, start_date=start_date, end_date=end_date, limit=limit),
    )
    return rows if isinstance(rows, dict) else {"scans": rows}
