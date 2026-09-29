"""``/api/v1/supplements`` — Supplements catalog endpoints."""
from __future__ import annotations

from fastapi import Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.services import supplements_service
from web.api.errors import MUTATION_ERRORS, ApiRouter, not_found
from web.api.schemas.supplements import (
    SupplementCreate,
    SupplementCreated,
    SupplementItem,
    SupplementToggle,
    SupplementUpdate,
    SupplementsView,
)
from web.deps import get_session, require_auth

router = ApiRouter(prefix="/supplements", dependencies=[Depends(require_auth)])


@router.get("", response_model=SupplementsView)
async def read_supplements(db: AsyncSession = Depends(get_session)) -> SupplementsView:
    """The entire supplements catalog grouped by timing slot, plus archive."""
    data = await supplements_service.collect(db)
    return SupplementsView.model_validate(data)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=SupplementCreated,
    responses=MUTATION_ERRORS,
)
async def create_supplement(
    body: SupplementCreate, db: AsyncSession = Depends(get_session)
) -> SupplementCreated:
    """Add a supplement to the catalog."""
    if not body.name or not body.name.strip():
        raise ValueError("name is required")

    row = await supplements_service.add_supplement(
        db,
        name=body.name.strip(),
        key=body.key,
        dose=body.dose,
        timing=body.timing,
        evidence=body.evidence or None,
        active=body.active,
        contraindications=body.contraindications,
        note=body.note,
        override=body.override,
    )
    await db.commit()
    return SupplementCreated(id=row.id)


@router.patch(
    "/{supplement_id}",
    response_model=SupplementItem,
    responses=MUTATION_ERRORS,
)
async def update_supplement(
    supplement_id: int,
    body: SupplementUpdate,
    db: AsyncSession = Depends(get_session),
) -> SupplementItem:
    """Update a supplement."""
    existing = await db.get(supplements_service.Supplement, supplement_id)
    if existing is None:
        return not_found()

    name = body.name.strip() if body.name is not None else existing.name
    if not name:
        raise ValueError("name cannot be empty")

    row = await supplements_service.update_supplement(
        db,
        supplement_id,
        name=name,
        key=body.key or existing.key,
        dose=body.dose if body.dose is not None else existing.dose,
        timing=body.timing if body.timing is not None else existing.timing,
        evidence=body.evidence if body.evidence is not None else existing.evidence,
        active=body.active if body.active is not None else existing.active,
        contraindications=body.contraindications if body.contraindications is not None else existing.contraindications,
        note=body.note if body.note is not None else existing.note,
        override=body.override,
    )
    await db.commit()
    return SupplementItem(
        id=row.id,
        name=row.name,
        key=row.key,
        dose=row.dose,
        timing=row.timing,
        timing_slot=supplements_service._parse_slot(row.timing),
        timing_bucket=supplements_service.timing_bucket(row.timing),
        evidence=row.evidence,
        active=row.active,
        contraindications=row.contraindications,
        contra=row.contraindications,
        note=row.note,
    )


@router.post(
    "/{supplement_id}/toggle",
    response_model=SupplementItem,
    responses=MUTATION_ERRORS,
)
async def toggle_supplement(
    supplement_id: int,
    body: SupplementToggle,
    db: AsyncSession = Depends(get_session),
) -> SupplementItem:
    """Toggle a supplement active/inactive."""
    row = await supplements_service.set_active(
        db, supplement_id, body.active, override=body.override
    )
    if row is None:
        return not_found()
    await db.commit()
    return SupplementItem(
        id=row.id,
        name=row.name,
        key=row.key,
        dose=row.dose,
        timing=row.timing,
        timing_slot=supplements_service._parse_slot(row.timing),
        timing_bucket=supplements_service.timing_bucket(row.timing),
        evidence=row.evidence,
        active=row.active,
        contraindications=row.contraindications,
        contra=row.contraindications,
        note=row.note,
    )


@router.delete("/{supplement_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_supplement(
    supplement_id: int, db: AsyncSession = Depends(get_session)
):
    """Delete a supplement from the catalog."""
    if not await supplements_service.delete_supplement(db, supplement_id):
        return not_found()
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
