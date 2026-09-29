"""``/api/v1/reports`` — Reports, milestones, digests, and briefs endpoints."""
from __future__ import annotations

from datetime import date as date_type
from typing import Optional

from fastapi import Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.services import milestones_service, reports_service
from web.api.errors import ApiRouter, not_found
from web.api.schemas.reports import (
    DigestGenerateRequest,
    DigestItem,
    MilestoneCreate,
    MilestoneCreated,
    MilestoneStatusUpdate,
    ReportsView,
)
from web.deps import get_session, require_auth
from web.routers.telegram import get_notifier

router = ApiRouter(prefix="/reports", dependencies=[Depends(require_auth)])


@router.get("", response_model=ReportsView)
async def read_reports(db: AsyncSession = Depends(get_session)) -> ReportsView:
    """The reports dashboard: active goals, archive, weekly digest, morning brief."""
    data = await reports_service.collect(db)
    return ReportsView.model_validate(data)


@router.post(
    "/milestones",
    status_code=status.HTTP_201_CREATED,
    response_model=MilestoneCreated,
)
async def create_milestone(
    body: MilestoneCreate, db: AsyncSession = Depends(get_session)
) -> MilestoneCreated:
    """Create a health goal / milestone card."""
    if not body.name or not body.name.strip():
        raise ValueError("name is required")

    deadline = date_type.fromisoformat(body.deadline) if body.deadline else None
    row = await milestones_service.create_milestone(
        db,
        name=body.name.strip(),
        domain=body.domain,
        target_value=body.target_value,
        target_unit=body.target_unit,
        deadline=deadline,
        note=body.note,
    )
    await db.commit()
    return MilestoneCreated(id=row.id)


@router.patch("/milestones/{milestone_id}/status")
async def update_milestone_status(
    milestone_id: int,
    body: MilestoneStatusUpdate,
    db: AsyncSession = Depends(get_session),
):
    """Change milestone status (e.g. active, achieved, abandoned)."""
    row = await milestones_service.set_status(db, milestone_id, body.status)
    if row is None:
        return not_found()
    await db.commit()
    return {"ok": True, "id": row.id, "status": row.status}


@router.delete("/milestones/{milestone_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_milestone(
    milestone_id: int, db: AsyncSession = Depends(get_session)
):
    """Delete a goal milestone card."""
    if not await milestones_service.delete_milestone(db, milestone_id):
        return not_found()
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/digests", response_model=Optional[DigestItem])
async def generate_digest(
    body: Optional[DigestGenerateRequest] = None,
    db: AsyncSession = Depends(get_session),
) -> Optional[DigestItem]:
    """Generate a weekly digest on demand."""
    period_days = body.period_days if body else 7
    result = await reports_service.generate_digest(db, period_days=period_days)
    return DigestItem.model_validate(result) if result else None


@router.post("/briefs/build", response_model=Optional[DigestItem])
async def build_brief(
    db: AsyncSession = Depends(get_session),
) -> Optional[DigestItem]:
    """Assemble today's brief without sending."""
    result = await reports_service.build_brief(db)
    return DigestItem.model_validate(result) if result else None


@router.post("/briefs/test")
async def send_test_brief(
    db: AsyncSession = Depends(get_session),
    notifier=Depends(get_notifier),
):
    """Generate and send today's brief via Telegram."""
    res = await reports_service.send_test_brief(db, notifier)
    return {"ok": True, "result": res}
