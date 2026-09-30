"""``/api/v1/weight`` — weight dashboard, measurements, noise markers, photos,
body-composition scans, and Garmin export.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import uuid
from typing import Optional

from fastapi import Depends, File, Form, HTTPException, Request, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import Domain, Source
from vitals.integrations.llm_client import LLMClient, LLMNotConfigured
from vitals.services import body_scan_service, garmin_weight_service, raw_payload_service, weight_service
from vitals.utils.timeutils import today_local
from web.api.errors import MUTATION_ERRORS, ApiRouter, not_found
from web.api.schemas.weight import (
    BodyMeasurementCreate,
    BodyMeasurementPatch,
    BodyMeasurementRef,
    BodyScanConfirm,
    BodyScanConfirmResponse,
    BodyScanMetricItem,
    BodyScanPreview,
    BodyScanUploadResponse,
    GarminExportResponse,
    NoiseMarkerCreate,
    NoiseMarkerRef,
    ProgressPhotoItem,
    WeightLogCreate,
    WeightLogCreated,
    WeightLogPatch,
    WeightLogRef,
    WeightMeasuresView,
    WeightView,
)
from web.deps import get_redis, get_session, require_auth, require_module
from web.templating import STATIC_DIR
from web.uploads import DOC_EXTS, IMAGE_EXTS, file_ext, read_capped, validate_extension

logger = logging.getLogger(__name__)

router = ApiRouter(prefix="/weight", dependencies=[Depends(require_auth)])


# ── GET /api/v1/weight ────────────────────────────────────────────────────────


@router.get("", response_model=WeightView)
async def read_weight_dashboard(
    request: Request, db: AsyncSession = Depends(get_session)
) -> WeightView:
    """The Weight screen: latest weight, MA-7, week change, body fat, trend chart series,
    history with superseded flags, pace and latest scan summary."""
    em = getattr(request.state, "enabled_modules", None) or {}
    data = await weight_service.collect(
        db,
        include_bia=bool(em.get("body_comp")),
        include_timeline=bool(em.get("timeline")),
        include_glp1=bool(em.get("glp1")),
        lang=getattr(request.state, "lang", "ru"),
    )
    return WeightView.model_validate(data)


# ── GET /api/v1/weight/measures ───────────────────────────────────────────────


@router.get("/measures", response_model=WeightMeasuresView)
async def read_weight_measures(
    request: Request, db: AsyncSession = Depends(get_session)
) -> WeightMeasuresView:
    """The Measurements desk: circumferences, Navy fat, scans, noise markers, photos."""
    em = getattr(request.state, "enabled_modules", None) or {}
    data = await weight_service.collect_measures(
        db,
        include_bia=bool(em.get("body_comp")),
        include_timeline=bool(em.get("timeline")),
        lang=getattr(request.state, "lang", "ru"),
    )
    return WeightMeasuresView.model_validate(data)


# ── Measurements Mutations ───────────────────────────────────────────────────


@router.post(
    "/measures",
    status_code=status.HTTP_201_CREATED,
    response_model=BodyMeasurementRef,
    responses=MUTATION_ERRORS,
)
async def create_body_measurement(
    body: BodyMeasurementCreate, db: AsyncSession = Depends(get_session)
) -> BodyMeasurementRef:
    """Log or update body circumference measurements."""
    row = await weight_service.upsert_body_measurement(
        db,
        on_date=body.date,
        neck_cm=body.neck_cm,
        waist_cm=body.waist_cm,
        hips_cm=body.hips_cm,
        note=body.note,
        override=body.override,
    )
    await db.commit()
    return BodyMeasurementRef(id=row.id, body_fat_pct=row.body_fat_pct, lbm_kg=row.lbm_kg)


@router.patch(
    "/measures/{measurement_id}",
    response_model=BodyMeasurementRef,
    responses=MUTATION_ERRORS,
)
async def update_body_measurement(
    measurement_id: int, body: BodyMeasurementPatch, db: AsyncSession = Depends(get_session)
):
    """Correct a tape measurement. The body is the whole row: a circumference or the
    note it leaves out is cleared. Moving it to another day answers with the id of
    the row it became."""
    row = await weight_service.update_body_measurement(
        db,
        measurement_id,
        on_date=body.date,
        neck_cm=body.neck_cm,
        waist_cm=body.waist_cm,
        hips_cm=body.hips_cm,
        note=body.note,
        override=body.override,
        partial=False,
    )
    if row is None:
        return not_found()
    await db.commit()
    return BodyMeasurementRef(id=row.id, body_fat_pct=row.body_fat_pct, lbm_kg=row.lbm_kg)


@router.delete("/measures/{measurement_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_body_measurement(
    measurement_id: int, db: AsyncSession = Depends(get_session)
):
    """Delete a body measurement entry."""
    if not await weight_service.delete_body_measurement(db, measurement_id):
        return not_found()
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Noise Markers ─────────────────────────────────────────────────────────────


@router.post(
    "/noise-markers",
    status_code=status.HTTP_201_CREATED,
    response_model=NoiseMarkerRef,
    responses=MUTATION_ERRORS,
)
async def create_noise_marker(
    body: NoiseMarkerCreate, db: AsyncSession = Depends(get_session)
) -> NoiseMarkerRef:
    """Exclude a period from calculations to filter out noise."""
    dir_val = body.direction.strip() if body.direction and body.direction.strip() else None
    row = await weight_service.add_noise_marker(
        db,
        start_date=body.start_date,
        end_date=body.end_date,
        reason=body.reason,
        direction=dir_val,
    )
    await db.commit()
    return NoiseMarkerRef(id=row.id)


@router.delete("/noise-markers/{marker_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_noise_marker(marker_id: int, db: AsyncSession = Depends(get_session)):
    """Delete an excluded period marker."""
    if not await weight_service.delete_noise_marker(db, marker_id):
        return not_found()
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Photos ───────────────────────────────────────────────────────────────────


@router.post(
    "/photos",
    status_code=status.HTTP_201_CREATED,
    response_model=list[ProgressPhotoItem],
    responses=MUTATION_ERRORS,
)
async def upload_progress_photos(
    date: str = Form(...),
    note: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    files: Optional[list[UploadFile]] = File(None),
    db: AsyncSession = Depends(get_session),
) -> list[ProgressPhotoItem]:
    """Upload up to 5 daily progress photos."""
    on_date = dt.date.fromisoformat(date)
    uploaded_files: list[UploadFile] = []
    if file is not None and file.filename:
        uploaded_files.append(file)
    if files is not None:
        for f in files:
            if f.filename:
                uploaded_files.append(f)

    if not uploaded_files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No files uploaded")
    if len(uploaded_files) > 5:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Too many files (max 5)")

    uploads_dir = os.path.join(STATIC_DIR, "uploads")
    os.makedirs(uploads_dir, exist_ok=True)

    saved_items: list[ProgressPhotoItem] = []
    for f in uploaded_files:
        ext = validate_extension(f.filename, IMAGE_EXTS)
        contents = await read_capped(f)
        unique_name = f"{uuid.uuid4().hex}{ext}"
        file_path = os.path.join(uploads_dir, unique_name)
        with open(file_path, "wb") as fh:
            fh.write(contents)

        file_key = f"uploads/{unique_name}"
        photo = await weight_service.add_progress_photo(
            db, on_date=on_date, file_key=file_key, note=note
        )
        saved_items.append(
            ProgressPhotoItem(
                id=photo.id,
                date=photo.date,
                file_key=file_key,
                url=f"/static/{file_key}",
                note=photo.note,
            )
        )

    await db.commit()
    return saved_items


@router.delete("/photos/{photo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_progress_photo(photo_id: int, db: AsyncSession = Depends(get_session)):
    """Delete a progress photo."""
    file_key = await weight_service.delete_progress_photo(db, photo_id)
    if not file_key:
        return not_found()
    await db.commit()

    file_path = os.path.join(STATIC_DIR, file_key)
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except OSError:
            pass

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Body Scans (BIA) ─────────────────────────────────────────────────────────


@router.post(
    "/body-scans/upload",
    response_model=BodyScanUploadResponse,
    dependencies=[Depends(require_module("body_comp"))],
    responses=MUTATION_ERRORS,
)
async def upload_body_scan(
    file: UploadFile = File(...),
    date: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_session),
) -> BodyScanUploadResponse:
    """Step 1: vision extraction from a photo/PDF of a scan sheet."""
    validate_extension(file.filename, DOC_EXTS)
    contents = await read_capped(file)

    try:
        llm = LLMClient()
    except LLMNotConfigured:
        return BodyScanUploadResponse(ok=False, reason="not_configured", message="LLM not configured")

    try:
        extracted = await body_scan_service.extract_from_file(
            contents,
            llm=llm,
            content_type=file.content_type or "image/jpeg",
            filename=file.filename,
        )
    except LLMNotConfigured:
        return BodyScanUploadResponse(ok=False, reason="not_configured", message="LLM not configured")
    except Exception as e:
        logger.warning("Body-scan extraction failed for %s: %s", file.filename, e)
        return BodyScanUploadResponse(ok=False, reason="error", message=str(e))

    ext = file_ext(file.filename) or ".bin"
    file_key = f"body/{uuid.uuid4().hex}{ext}"
    os.makedirs(os.path.join(STATIC_DIR, "uploads", "body"), exist_ok=True)
    with open(os.path.join(STATIC_DIR, "uploads", file_key), "wb") as fh:
        fh.write(contents)

    raw_row = await raw_payload_service.upsert_raw_payload(
        db,
        domain=Domain.BODY_COMPOSITION.value,
        source=Source.BODY_SCAN.value,
        external_id=file_key,
        payload=extracted,
    )
    await db.commit()

    rows = body_scan_service.normalize_extracted(extracted)
    raw_date = date or extracted.get("date")
    try:
        scan_date = dt.date.fromisoformat(str(raw_date)[:10])
    except (ValueError, TypeError):
        scan_date = today_local()

    return BodyScanUploadResponse(
        ok=True,
        scan=BodyScanPreview(
            date=scan_date,
            device=extracted.get("device"),
            file_key=file_key,
            raw_payload_id=raw_row.id,
            metrics=[
                BodyScanMetricItem(
                    label=r["label"],
                    value=r["value"],
                    unit=r.get("unit"),
                    metric_key=r.get("metric_key"),
                    ref_low=r.get("ref_low"),
                    ref_high=r.get("ref_high"),
                    segment=r.get("segment"),
                    category=r.get("category"),
                )
                for r in rows
            ],
        ),
    )


@router.post(
    "/body-scans/confirm",
    response_model=BodyScanConfirmResponse,
    dependencies=[Depends(require_module("body_comp"))],
    responses=MUTATION_ERRORS,
)
async def confirm_body_scan(
    body: BodyScanConfirm, db: AsyncSession = Depends(get_session)
) -> BodyScanConfirmResponse:
    """Step 2: persist the owner-edited scan rows."""
    scan = await body_scan_service.save_scan(
        db,
        on_date=body.date,
        device=body.device,
        file_key=body.file_key,
        raw_payload_id=body.raw_payload_id,
        metrics=[m.model_dump() for m in body.metrics],
        note=body.note,
        override=body.override,
    )
    await body_scan_service.refresh_alerts(db)
    await db.commit()
    return BodyScanConfirmResponse(ok=True, scan_id=scan.id)


@router.delete(
    "/body-scans/{scan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_module("body_comp"))],
)
async def delete_body_scan(scan_id: int, db: AsyncSession = Depends(get_session)):
    """Delete a body scan entry and its stored file."""
    scan = await body_scan_service.get_scan(db, scan_id)
    if scan is None:
        return not_found()
    file_key = scan.file_key
    await body_scan_service.delete_scan(db, scan_id)
    await db.commit()

    if file_key:
        file_path = os.path.join(STATIC_DIR, "uploads", file_key)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Garmin Weight Export ──────────────────────────────────────────────────────


@router.post("/garmin-export", response_model=GarminExportResponse)
async def trigger_garmin_weight_export(
    db: AsyncSession = Depends(get_session),
    redis=Depends(get_redis),
) -> GarminExportResponse:
    """Explicitly trigger Garmin weight export reconciliation."""
    result = await garmin_weight_service.send_now(db, redis=redis)
    await db.commit()
    st = await garmin_weight_service.get_status(db)
    return GarminExportResponse(
        ok=result.get("status") not in ("error", "failed"),
        status=result.get("status", "done"),
        last_error=st.get("last_error"),
        next_attempt_at=st.get("next_attempt_at"),
    )


# ── Existing Weight Logs ──────────────────────────────────────────────────────


@router.post(
    "/logs",
    status_code=status.HTTP_201_CREATED,
    response_model=WeightLogCreated,
    responses=MUTATION_ERRORS,
)
async def create_weight_log(
    body: WeightLogCreate, db: AsyncSession = Depends(get_session)
) -> WeightLogCreated:
    """Log a weight as a manual reading. A reading the day already holds comes back
    with ``created: false``; a block rule answers 409 until ``override`` is set."""
    before = await weight_service.get_active_weight(db, body.date)
    row = await weight_service.log_weight(
        db, on_date=body.date, weight_kg=body.weight_kg, note=body.note, override=body.override
    )
    await db.commit()
    return WeightLogCreated(id=row.id, created=before is None or before.id != row.id)


@router.patch("/logs/{log_id}", response_model=WeightLogRef, responses=MUTATION_ERRORS)
async def update_weight_log(
    log_id: int, body: WeightLogPatch, db: AsyncSession = Depends(get_session)
):
    """Correct a reading; whatever the body leaves out stays as it was."""
    row = await weight_service.get_weight_log(db, log_id)
    if row is None:
        return not_found()
    updated = await weight_service.update_weight_log(
        db,
        log_id,
        on_date=body.date if body.date is not None else row.date,
        weight_kg=body.weight_kg if body.weight_kg is not None else row.weight_kg,
        note=body.note if "note" in body.model_fields_set else row.note,
        override=body.override,
    )
    if updated is None:
        return not_found()
    await db.commit()
    return WeightLogRef(id=updated.id)


@router.delete("/logs/{log_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_weight_log(log_id: int, db: AsyncSession = Depends(get_session)):
    """Take a reading back. If it was the day's active one, the reading it had
    outranked (a Garmin import) becomes active again."""
    if not await weight_service.delete_weight_log(db, log_id):
        return not_found()
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
