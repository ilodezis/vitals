"""``/api/v1/timeline`` — Cross-domain timeline feed & manual chart annotations endpoints."""
from __future__ import annotations

from datetime import date as date_type
from typing import Optional

from fastapi import Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.services import timeline_service
from web.api.errors import ApiRouter, not_found
from web.api.schemas.timeline import (
    AnnotationCreate,
    AnnotationCreated,
    AnnotationUpdate,
    TimelineEventItem,
    TimelineView,
)
from web.deps import get_session, require_auth

router = ApiRouter(prefix="/timeline", dependencies=[Depends(require_auth)])


@router.get("", response_model=TimelineView)
async def read_timeline(
    domain: Optional[str] = None,
    limit: int = 200,
    db: AsyncSession = Depends(get_session),
) -> TimelineView:
    """The unified timeline feed: manual annotations + derived events."""
    data = await timeline_service.collect(db, domain=domain, limit=limit)
    return TimelineView.model_validate(data)


@router.post(
    "/annotations",
    status_code=status.HTTP_201_CREATED,
    response_model=AnnotationCreated,
)
async def create_annotation(
    body: AnnotationCreate, db: AsyncSession = Depends(get_session)
) -> AnnotationCreated:
    """Create a manual annotation."""
    if not body.title or not body.title.strip():
        raise ValueError("title is required")

    on_date = date_type.fromisoformat(body.date)
    end = date_type.fromisoformat(body.end_date) if body.end_date else None

    row = await timeline_service.create_annotation(
        db,
        title=body.title.strip(),
        on_date=on_date,
        end_date=end,
        kind=body.kind,
        domain=body.domain,
        note=body.note,
    )
    await db.commit()
    return AnnotationCreated(id=row.id)


@router.patch(
    "/annotations/{annotation_id}",
    response_model=TimelineEventItem,
)
async def update_annotation(
    annotation_id: int,
    body: AnnotationUpdate,
    db: AsyncSession = Depends(get_session),
) -> TimelineEventItem:
    """Update a manual annotation."""
    existing = await timeline_service.get_annotation(db, annotation_id)
    if existing is None:
        return not_found()

    title = body.title.strip() if body.title is not None else existing.title
    if not title:
        raise ValueError("title cannot be empty")

    on_date = date_type.fromisoformat(body.date) if body.date is not None else existing.date
    end = date_type.fromisoformat(body.end_date) if body.end_date is not None else existing.end_date

    row = await timeline_service.update_annotation(
        db,
        annotation_id,
        title=title,
        on_date=on_date,
        end_date=end,
        kind=body.kind if body.kind is not None else existing.kind,
        domain=body.domain if body.domain is not None else existing.domain,
        note=body.note if body.note is not None else existing.note,
    )
    await db.commit()
    return TimelineEventItem(
        id=row.id,
        date=row.date.isoformat(),
        end_date=row.end_date.isoformat() if row.end_date else None,
        domain=row.domain,
        dom=row.domain,
        kind=row.kind,
        title=row.title,
        detail=row.note,
        tone=timeline_service._TONE_BY_KIND.get(row.kind, ""),
        source="manual",
        manual=True,
        ref=f"annotation:{row.id}",
    )


@router.delete("/annotations/{annotation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_annotation(
    annotation_id: int, db: AsyncSession = Depends(get_session)
):
    """Delete a manual annotation."""
    if not await timeline_service.delete_annotation(db, annotation_id):
        return not_found()
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
