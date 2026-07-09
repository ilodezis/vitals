"""Milestones (goal cards) service — module 10.

Goal cards are simple config rows (name, related domain, optional numeric target +
deadline, status). For a weight-domain goal with a numeric target we compute live
progress against the latest active weight; other domains just carry status. The
product is a navigator, so nothing here is enforced — a goal is context for the
weekly digest and a dashboard card.
"""
from __future__ import annotations

from datetime import date as date_type
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import Domain, MilestoneStatus
from vitals.models.milestones import Milestone
from vitals.utils.timeutils import today_local


async def create_milestone(
    session: AsyncSession,
    *,
    name: str,
    domain: str = Domain.WEIGHT.value,
    target_value: Optional[float] = None,
    target_unit: Optional[str] = None,
    deadline: Optional[date_type] = None,
    note: Optional[str] = None,
) -> Milestone:
    row = Milestone(
        name=name,
        domain=domain,
        target_value=target_value,
        target_unit=target_unit,
        deadline=deadline,
        status=MilestoneStatus.ACTIVE.value,
        note=note,
    )
    session.add(row)
    await session.flush()
    return row


async def list_milestones(
    session: AsyncSession, *, status: Optional[str] = None
) -> Sequence[Milestone]:
    stmt = select(Milestone)
    if status is not None:
        stmt = stmt.where(Milestone.status == status)
    stmt = stmt.order_by(Milestone.deadline.is_(None), Milestone.deadline, Milestone.id)
    result = await session.execute(stmt)
    return result.scalars().all()


async def set_status(session: AsyncSession, milestone_id: int, status: str) -> Optional[Milestone]:
    row = await session.get(Milestone, milestone_id)
    if row is None:
        return None
    row.status = status
    await session.flush()
    return row


# Sentinel so a caller can patch a single field to ``None`` (e.g. clear a
# deadline) without every other field being wiped — only args that differ from
# ``_UNSET`` are applied.
_UNSET: object = object()


async def update_milestone(
    session: AsyncSession,
    milestone_id: int,
    *,
    name: object = _UNSET,
    domain: object = _UNSET,
    target_value: object = _UNSET,
    target_unit: object = _UNSET,
    deadline: object = _UNSET,
    status: object = _UNSET,
    note: object = _UNSET,
) -> Optional[Milestone]:
    """Partial-update a goal card. Only fields explicitly passed are changed;
    the rest keep their current value (pass ``None`` to clear an optional field)."""
    row = await session.get(Milestone, milestone_id)
    if row is None:
        return None
    for attr, value in (
        ("name", name),
        ("domain", domain),
        ("target_value", target_value),
        ("target_unit", target_unit),
        ("deadline", deadline),
        ("status", status),
        ("note", note),
    ):
        if value is not _UNSET:
            setattr(row, attr, value)
    await session.flush()
    return row


async def delete_milestone(session: AsyncSession, milestone_id: int) -> bool:
    row = await session.get(Milestone, milestone_id)
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


async def _current_weight(session: AsyncSession) -> Optional[float]:
    """Latest active weight, imported lazily to avoid a hard module dependency."""
    from vitals.services import weight_service

    weights = await weight_service.list_active_weights(session)
    return weights[-1].weight_kg if weights else None


async def _current_body_fat(session: AsyncSession) -> Optional[float]:
    """Latest active body fat percentage, either Navy or InBody (BIA) based on preference."""
    from vitals.config import load_config
    from vitals.services import weight_service
    from vitals.services.modules_service import get_enabled_modules

    config = load_config()
    source_pref = config.body_fat_source or "latest"

    enabled = await get_enabled_modules(session)
    body_comp_enabled = enabled.get("body_comp", False)

    # 1. Fetch Navy measurements if not pinned to bia
    navy_val = None
    navy_date = None
    if source_pref in ("latest", "navy"):
        measurements = await weight_service.list_body_measurements(session)
        # Find the latest measurement with body_fat_pct
        for m in reversed(measurements):
            if m.body_fat_pct is not None:
                navy_val = m.body_fat_pct
                navy_date = m.date
                break

    # 2. Fetch BIA scans if body_comp is enabled and not pinned to navy
    bia_val = None
    bia_date = None
    if body_comp_enabled and source_pref in ("latest", "bia"):
        from vitals.services import body_scan_service
        from vitals.services.analytics import body_metrics

        scans = await body_scan_service.list_scans(session)
        for s in scans:
            bf_val = body_metrics.body_fat_pct_from_scan(s.metrics)
            if bf_val is not None:
                bia_val = bf_val
                bia_date = s.date
                break

    # 3. Resolve based on preference
    if source_pref == "navy":
        return navy_val
    if source_pref == "bia":
        return bia_val

    # "latest" or fallback: choose whichever is newer
    if navy_date is not None and bia_date is not None:
        if bia_date >= navy_date:
            return bia_val
        return navy_val
    if navy_date is not None:
        return navy_val
    return bia_val


async def progress(session: AsyncSession, milestone: Milestone) -> dict:
    """Live progress for a goal. Weight goals get current/remaining/pct vs target;
    others just echo status + days-to-deadline."""
    today = today_local()
    days_left = (milestone.deadline - today).days if milestone.deadline else None
    out: dict = {
        "id": milestone.id,
        "name": milestone.name,
        "domain": milestone.domain,
        "status": milestone.status,
        "target_value": milestone.target_value,
        "target_unit": milestone.target_unit,
        "deadline": milestone.deadline.isoformat() if milestone.deadline else None,
        "days_left": days_left,
        "current": None,
        "remaining": None,
        "pct": None,
    }

    if milestone.domain == Domain.WEIGHT.value and milestone.target_value is not None:
        current = await _current_weight(session)
        if current is not None:
            out["current"] = round(current, 2)
            out["remaining"] = round(current - milestone.target_value, 2)
    elif milestone.domain == Domain.BODY_COMPOSITION.value and milestone.target_value is not None:
        current = await _current_body_fat(session)
        if current is not None:
            out["current"] = round(current, 2)
            out["remaining"] = round(current - milestone.target_value, 2)
    return out


async def dashboard_cards(session: AsyncSession) -> list[dict]:
    """All goals with progress computed — the dashboard widget / reports list."""
    rows = await list_milestones(session)
    return [await progress(session, m) for m in rows]
