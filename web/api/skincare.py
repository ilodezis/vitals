"""``/api/v1/skincare`` — Skincare checklist, observations, products, the day's
done-ticks, and the face photo diary."""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import date as date_type
from typing import Optional

from fastapi import Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.services import photo_derivatives, skincare_service
from vitals.services.proactive import channels
from vitals.services.proactive import skincare as skincare_reminders
from web.api.errors import MUTATION_ERRORS, ApiRouter, not_found
from web.api.schemas.skincare import (
    SkincareCheckUpdate,
    SkincareDayPlan,
    SkincareLogCreate,
    SkincareLogItem,
    SkincareObservationCreate,
    SkincareObservationCreated,
    SkincarePhotoItem,
    SkincareProductCreate,
    SkincareProductCreated,
    SkincareProductItem,
    SkincareProductUpdate,
    SkincareView,
)
from web.deps import get_session, require_auth
from web.templating import STATIC_DIR
from web.uploads import IMAGE_EXTS, read_capped, validate_extension, write_upload

logger = logging.getLogger(__name__)

router = ApiRouter(prefix="/skincare", dependencies=[Depends(require_auth)])

# Same cap as the weight's progress photos: one shot from a few angles, not an album.
MAX_PHOTOS_PER_UPLOAD = 5


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
        active_flag=body.active_flag,
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
        active_flag=(
            body.active_flag if "active_flag" in body.model_fields_set else existing.active_flag
        ),
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
        active_flag=row.active_flag,
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


# ── The day's ticks ──────────────────────────────────────────────────────────
@router.post("/checks", response_model=SkincareDayPlan, responses=MUTATION_ERRORS)
async def set_skincare_check(
    body: SkincareCheckUpdate, db: AsyncSession = Depends(get_session)
) -> SkincareDayPlan:
    """Tick or untick one product in a slot (or, with no product, tick the whole
    slot). Returns that day's plan as it now stands. A blocking conflict rule
    answers 409 unless ``override``."""
    on_date = date_type.fromisoformat(body.date)
    if body.slot not in skincare_service.SLOTS:
        raise ValueError(f"unknown slot: {body.slot}")
    if body.product_id is None:
        if not body.done:
            raise ValueError("a whole slot can only be ticked, not unticked")
        await skincare_service.complete_slot(
            db, on_date=on_date, slot=body.slot, override=body.override
        )
    else:
        try:
            await skincare_service.set_check(
                db,
                on_date=on_date,
                product_id=body.product_id,
                slot=body.slot,
                done=body.done,
                override=body.override,
            )
        except LookupError:
            return not_found()
    await db.commit()

    # The reminder already sitting in Telegram shows the same ticks. Best-effort:
    # the tick is committed, and a slow or refused edit must not fail it.
    try:
        await skincare_reminders.sync_sent(db, channels.build_notifier(), on_date, body.slot)
    except Exception:  # noqa: BLE001
        logger.warning("could not sync the skincare reminder", exc_info=True)

    return SkincareDayPlan.model_validate(await skincare_service.plan_for(db, on_date))


# ── Face photo diary ─────────────────────────────────────────────────────────
@router.post(
    "/photos",
    status_code=status.HTTP_201_CREATED,
    response_model=list[SkincarePhotoItem],
    responses=MUTATION_ERRORS,
)
async def upload_skincare_photos(
    date: str = Form(...),
    note: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    files: Optional[list[UploadFile]] = File(None),
    db: AsyncSession = Depends(get_session),
) -> list[SkincarePhotoItem]:
    """Upload up to five face photos for a date."""
    on_date = date_type.fromisoformat(date)
    uploaded = [f for f in ([file] if file is not None else []) + list(files or []) if f.filename]
    if not uploaded:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No files uploaded")
    if len(uploaded) > MAX_PHOTOS_PER_UPLOAD:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Too many files (max {MAX_PHOTOS_PER_UPLOAD})",
        )

    note = note.strip() if note else None
    uploads_dir = os.path.join(STATIC_DIR, "uploads")
    saved: list[SkincarePhotoItem] = []
    for f in uploaded:
        ext = validate_extension(f.filename, IMAGE_EXTS)
        contents = await read_capped(f)
        unique_name = f"{uuid.uuid4().hex}{ext}"
        await write_upload(os.path.join(uploads_dir, unique_name), contents)
        file_key = f"uploads/{unique_name}"
        # The tile and screen copies. A photo the decoder cannot read is still saved:
        # the screens show the original in their place.
        await asyncio.to_thread(photo_derivatives.make_derivatives, STATIC_DIR, file_key)
        photo = await skincare_service.add_photo(
            db, on_date=on_date, file_key=file_key, note=note or None
        )
        saved.append(
            SkincarePhotoItem(
                id=photo.id, date=photo.date.isoformat(), note=photo.note, **photo_derivatives.photo_urls(file_key)
            )
        )
    await db.commit()
    return saved


@router.delete("/photos/{photo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skincare_photo(photo_id: int, db: AsyncSession = Depends(get_session)):
    """Delete a face photo, and its file once the row is gone."""
    file_key = await skincare_service.delete_photo(db, photo_id)
    if not file_key:
        return not_found()
    await db.commit()

    file_path = os.path.join(STATIC_DIR, file_key)
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except OSError:
            pass
    photo_derivatives.remove_derivatives(STATIC_DIR, file_key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
