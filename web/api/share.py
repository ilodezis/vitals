"""``/api/v1/share`` — Doctor reports endpoints."""
from __future__ import annotations

from datetime import date as date_type
from typing import Optional

from fastapi import Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.services import share_service
from web.api.errors import ApiRouter, not_found
from web.api.schemas.share import CreatedShareResponse, CreateShareRequest, ShareView
from web.deps import get_session, require_auth

router = ApiRouter(prefix="/share", dependencies=[Depends(require_auth)])


@router.get("", response_model=ShareView)
async def read_share(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> ShareView:
    """The doctor reports management dashboard."""
    enabled = getattr(request.state, "enabled_modules", None) or {}
    data = await share_service.collect(db, enabled)
    return ShareView.model_validate(data)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=CreatedShareResponse,
)
async def create_share_report(
    body: CreateShareRequest,
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> CreatedShareResponse:
    """Create a frozen report for a doctor and generate a secure password."""
    if not body.title or not body.title.strip():
        raise ValueError("title is required")

    enabled = getattr(request.state, "enabled_modules", None) or {}
    chosen = share_service.resolve_domains(body.domains, enabled)
    if not chosen:
        raise ValueError("at least one valid domain must be selected")

    if body.period == "custom":
        if not body.period_start or not body.period_end:
            raise ValueError("custom period requires period_start and period_end")
        start = date_type.fromisoformat(body.period_start)
        end = date_type.fromisoformat(body.period_end)
        if end < start:
            raise ValueError("period_end cannot be before period_start")
    elif body.period == "all":
        _, end = share_service.window_for(1)
        start = await share_service.earliest_data_date(db) or end
    else:
        try:
            days = int(body.period)
        except ValueError:
            days = 90
        start, end = share_service.window_for(days)

    row, password = await share_service.create_report(
        db,
        title=body.title.strip(),
        domains=chosen,
        period_start=start,
        period_end=end,
        expires_days=body.expires_days,
        note=body.note,
        labs_flagged_only=body.labs_flagged_only,
        preset=body.preset or None,
        enabled=enabled,
    )
    await db.commit()

    return CreatedShareResponse(
        id=row.id,
        token=row.token,
        password=password,
        url=f"/r/{row.token}",
        expires_at=row.expires_at.isoformat(),
    )


@router.post("/{report_id}/revoke")
async def revoke_share_report(
    report_id: int,
    db: AsyncSession = Depends(get_session),
):
    """Revoke an active doctor report link."""
    if not await share_service.revoke(db, report_id):
        return not_found()
    await db.commit()
    return {"ok": True, "id": report_id}


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_share_report(
    report_id: int,
    db: AsyncSession = Depends(get_session),
):
    """Delete a doctor report record completely."""
    if not await share_service.delete_report(db, report_id):
        return not_found()
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
