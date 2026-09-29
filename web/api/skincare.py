"""``/api/v1/skincare`` — Skincare checklist, observations, and products endpoints."""
from __future__ import annotations

from datetime import date as date_type

from fastapi import Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.services import skincare_service
from web.api.errors import MUTATION_ERRORS, ApiRouter, not_found
from web.api.schemas.skincare import (
    SkincareLogCreate,
    SkincareLogItem,
    SkincareObservationCreate,
    SkincareObservationCreated,
    SkincareProductCreate,
    SkincareProductCreated,
    SkincareProductItem,
    SkincareProductUpdate,
    SkincareView,
)
from web.deps import get_session, require_auth

router = ApiRouter(prefix="/skincare", dependencies=[Depends(require_auth)])


@router.get("", response_model=SkincareView)
async def read_skincare(db: AsyncSession = Depends(get_session)) -> SkincareView:
    """The entire skincare dashboard: schedule, products, diary, observations, rules."""
    data = await skincare_service.collect(db)
    return SkincareView.model_validate(data)


@router.post(
    "/logs",
    response_model=SkincareLogItem,
    responses=MUTATION_ERRORS,
)
async def upsert_skincare_log(
    body: SkincareLogCreate, db: AsyncSession = Depends(get_session)
) -> SkincareLogItem:
    """Save or update skincare daily checklist log."""
    on_date = date_type.fromisoformat(body.date)
    row = await skincare_service.upsert_log(
        db,
        on_date=on_date,
        retinoid=body.retinoid,
        azelaic=body.azelaic,
        peel=body.peel,
        niacinamide_spf=body.niacinamide_spf,
        moisturizer=body.moisturizer,
        vitamin_c=body.vitamin_c,
        benzoyl_peroxide=body.benzoyl_peroxide,
        note=body.note,
        override=body.override,
    )
    await db.commit()
    return SkincareLogItem(
        id=row.id,
        date=row.date.isoformat(),
        retinoid=row.retinoid,
        azelaic=row.azelaic,
        peel=row.peel,
        niacinamide_spf=row.niacinamide_spf,
        moisturizer=row.moisturizer,
        vitamin_c=row.vitamin_c,
        benzoyl_peroxide=row.benzoyl_peroxide,
        note=row.note,
    )


@router.delete("/logs/{log_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skincare_log(
    log_id: int, db: AsyncSession = Depends(get_session)
):
    """Delete a skincare diary log entry."""
    if not await skincare_service.delete_log(db, log_id):
        return not_found()
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/observations",
    status_code=status.HTTP_201_CREATED,
    response_model=SkincareObservationCreated,
    responses=MUTATION_ERRORS,
)
async def create_skincare_observation(
    body: SkincareObservationCreate, db: AsyncSession = Depends(get_session)
) -> SkincareObservationCreated:
    """Record a skincare observation."""
    on_date = date_type.fromisoformat(body.date)
    row = await skincare_service.add_observation(
        db,
        on_date=on_date,
        inflammation=body.inflammation,
        pih=body.pih,
        zone=body.zone,
        note=body.note,
    )
    await db.commit()
    return SkincareObservationCreated(id=row.id)


@router.delete("/observations/{obs_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skincare_observation(
    obs_id: int, db: AsyncSession = Depends(get_session)
):
    """Delete a skincare observation entry."""
    if not await skincare_service.delete_observation(db, obs_id):
        return not_found()
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/products",
    status_code=status.HTTP_201_CREATED,
    response_model=SkincareProductCreated,
    responses=MUTATION_ERRORS,
)
async def create_skincare_product(
    body: SkincareProductCreate, db: AsyncSession = Depends(get_session)
) -> SkincareProductCreated:
    """Add a skincare product."""
    if not body.name or not body.name.strip():
        raise ValueError("name is required")
    if not body.type or not body.type.strip():
        raise ValueError("type is required")

    row = await skincare_service.add_product(
        db,
        name=body.name.strip(),
        type=body.type.strip(),
        active_ingredient=body.active_ingredient,
        description=body.description,
        usage_instructions=body.usage_instructions,
        default_time=body.default_time,
        schedule_days=body.schedule_days,
        active=body.active,
    )
    await db.commit()
    return SkincareProductCreated(id=row.id)


@router.patch(
    "/products/{product_id}",
    response_model=SkincareProductItem,
    responses=MUTATION_ERRORS,
)
async def update_skincare_product(
    product_id: int,
    body: SkincareProductUpdate,
    db: AsyncSession = Depends(get_session),
) -> SkincareProductItem:
    """Update a skincare product."""
    existing = await db.get(skincare_service.SkincareProduct, product_id)
    if existing is None:
        return not_found()

    name = body.name.strip() if body.name is not None else existing.name
    type_val = body.type.strip() if body.type is not None else existing.type
    if not name:
        raise ValueError("name cannot be empty")
    if not type_val:
        raise ValueError("type cannot be empty")

    row = await skincare_service.update_product(
        db,
        product_id,
        name=name,
        type=type_val,
        active_ingredient=body.active_ingredient if body.active_ingredient is not None else existing.active_ingredient,
        description=body.description if body.description is not None else existing.description,
        usage_instructions=body.usage_instructions if body.usage_instructions is not None else existing.usage_instructions,
        default_time=body.default_time if body.default_time is not None else existing.default_time,
        schedule_days=body.schedule_days if body.schedule_days is not None else (existing.schedule_days or []),
        active=body.active if body.active is not None else existing.active,
    )
    await db.commit()
    return SkincareProductItem(
        id=row.id,
        name=row.name,
        type=row.type,
        active_ingredient=row.active_ingredient,
        ing=row.active_ingredient,
        description=row.description,
        desc=row.description,
        usage_instructions=row.usage_instructions,
        use=row.usage_instructions,
        default_time=row.default_time,
        time=row.default_time,
        schedule_days=row.schedule_days or [],
        days=row.schedule_days or [],
        active=row.active,
        on=row.active,
    )


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skincare_product(
    product_id: int, db: AsyncSession = Depends(get_session)
):
    """Delete a skincare product."""
    if not await skincare_service.delete_product(db, product_id):
        return not_found()
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
