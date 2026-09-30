"""``/api/v1/labs`` — Lab results, extraction preview/confirm, and marker catalog."""
from __future__ import annotations

import logging
import os
import uuid
from datetime import date as date_type
from typing import Optional

from fastapi import Depends, File, Response, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import Domain, Source
from vitals.i18n import t
from vitals.integrations.llm_client import LLMClient, LLMNotConfigured
from vitals.models.labs import LabMarker, LabResult
from vitals.services import labs_service, raw_payload_service
from vitals.utils.timeutils import today_local
from web.api.errors import MUTATION_ERRORS, ApiRouter, not_found
from web.api.schemas.labs import (
    LabCatalogEntry,
    LabConfirm,
    LabConfirmResponse,
    LabMarkerDefer,
    LabMarkerDetail,
    LabMarkerPatch,
    LabMarkerResponse,
    LabResultCreate,
    LabResultCreated,
    LabUploadResponse,
    LabsView,
)
from web.deps import get_session, require_auth
from web.ratelimit import rate_limit
from web.templating import STATIC_DIR
from web.uploads import DOC_EXTS, file_ext, read_capped, validate_extension

logger = logging.getLogger(__name__)

router = ApiRouter(prefix="/labs", dependencies=[Depends(require_auth)])


@router.get("", response_model=LabsView)
async def read_labs(db: AsyncSession = Depends(get_session)) -> LabsView:
    """The whole Labs dashboard in one request: latest values with reference
    ranges, category groupings, and collection history."""
    data = await labs_service.collect(db)
    catalog = [
        LabCatalogEntry(
            name=m.name,
            tier=m.tier,
            retest_interval_days=m.retest_interval_days,
            defer_until=m.defer_until.isoformat() if m.defer_until else None,
        )
        for m in await labs_service.list_markers(db)
    ]
    return LabsView.model_validate({**data, "catalog": catalog})


@router.get("/markers/{marker_id_or_name}", response_model=LabMarkerDetail)
async def read_lab_marker(
    marker_id_or_name: str, db: AsyncSession = Depends(get_session)
) -> LabMarkerDetail:
    """Detailed history and reference information for a single biomarker."""
    marker_row = None
    if marker_id_or_name.isdigit():
        marker_row = await db.get(LabMarker, int(marker_id_or_name))
        if marker_row is None:
            # Maybe a result ID was passed from the list
            res = await db.get(LabResult, int(marker_id_or_name))
            if res:
                marker_row = await labs_service.get_marker(db, res.marker)

    if marker_row is None:
        marker_row = await labs_service.get_marker(db, marker_id_or_name)

    if marker_row is None:
        return not_found()

    history = await labs_service.marker_history(db, marker_row.name)
    return LabMarkerDetail(
        id=str(marker_row.id),
        name=marker_row.name,
        unit=marker_row.unit,
        ref_low=marker_row.ref_low,
        ref_high=marker_row.ref_high,
        category=marker_row.category,
        tier=marker_row.tier,
        defer_until=marker_row.defer_until.isoformat() if marker_row.defer_until else None,
        history=history,
    )


@router.post("/upload", response_model=LabUploadResponse)
async def upload_lab_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_session),
    _rl: None = Depends(rate_limit("labs_upload", limit=20, window=60)),
) -> LabUploadResponse:
    """Upload a PDF or image of a lab test report and extract markers with LLM vision."""
    validate_extension(file.filename, DOC_EXTS)
    contents = await read_capped(file)

    try:
        llm = LLMClient()
    except LLMNotConfigured:
        return LabUploadResponse(
            ok=False,
            reason="not_configured",
            message=t("labs.upload_not_configured"),
        )

    try:
        extracted = await labs_service.extract_from_file(
            contents,
            llm=llm,
            content_type=file.content_type or "image/jpeg",
            filename=file.filename,
        )
    except LLMNotConfigured:
        return LabUploadResponse(
            ok=False,
            reason="not_configured",
            message=t("labs.upload_not_configured"),
        )
    except Exception as e:
        logger.warning("Lab extraction failed for %s: %s", file.filename, e)
        return LabUploadResponse(
            ok=False,
            reason="error",
            message=t("labs.upload_error"),
        )

    ext = file_ext(file.filename) or ".bin"
    file_key = f"labs/{uuid.uuid4().hex}{ext}"
    os.makedirs(os.path.join(STATIC_DIR, "uploads", "labs"), exist_ok=True)
    with open(os.path.join(STATIC_DIR, "uploads", file_key), "wb") as fh:
        fh.write(contents)

    raw_row = await raw_payload_service.upsert_raw_payload(
        db,
        domain=Domain.LABS.value,
        source=Source.LAB_PARSER.value,
        external_id=file_key,
        payload=extracted,
    )
    await db.commit()

    rows = labs_service.normalize_extracted(extracted)
    try:
        lab_date = date_type.fromisoformat(str(extracted.get("date"))[:10]).isoformat()
    except (ValueError, TypeError):
        lab_date = today_local().isoformat()

    return LabUploadResponse(
        ok=True,
        lab={
            "date": lab_date,
            "lab_name": extracted.get("lab_name"),
            "file_key": file_key,
            "raw_payload_id": raw_row.id,
            "markers": rows,
        },
    )


@router.post(
    "/confirm",
    response_model=LabConfirmResponse,
    responses=MUTATION_ERRORS,
)
async def confirm_lab_document(
    payload: LabConfirm,
    db: AsyncSession = Depends(get_session),
) -> LabConfirmResponse:
    """Save user-reviewed biomarker results from the extraction preview."""
    try:
        on_date = date_type.fromisoformat(payload.date)
    except (ValueError, TypeError):
        raise ValueError("Invalid date format")

    created = await labs_service.confirm_extracted(
        db,
        on_date=on_date,
        markers=[m.model_dump() for m in payload.markers],
        lab_name=payload.lab_name,
        raw_payload_id=payload.raw_payload_id,
        override=payload.override,
    )
    await labs_service.refresh_alerts(db)
    await db.commit()
    return LabConfirmResponse(ok=True, created=len(created))


@router.post(
    "/results",
    status_code=status.HTTP_201_CREATED,
    response_model=LabResultCreated,
    responses=MUTATION_ERRORS,
)
async def create_lab_result(
    body: LabResultCreate, db: AsyncSession = Depends(get_session)
) -> LabResultCreated:
    """Record a single biomarker measurement manually."""
    row = await labs_service.add_result(
        db,
        on_date=body.date,
        marker=body.marker.strip(),
        value=body.value,
        unit=body.unit,
        ref_low=body.ref_low,
        ref_high=body.ref_high,
        lab_name=body.lab_name,
        note=body.note,
        override=body.override,
    )
    await labs_service.refresh_alerts(db)
    await db.commit()
    return LabResultCreated(id=row.id)


@router.delete("/results/{result_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lab_result(result_id: int, db: AsyncSession = Depends(get_session)):
    """Delete a biomarker result."""
    if not await labs_service.delete_result(db, result_id):
        return not_found()
    await labs_service.refresh_alerts(db)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/markers/{marker_name}/defer",
    response_model=LabMarkerResponse,
    responses=MUTATION_ERRORS,
)
async def defer_lab_marker(
    marker_name: str, body: LabMarkerDefer, db: AsyncSession = Depends(get_session)
) -> LabMarkerResponse:
    """Defer retesting a marker until a future date."""
    row = await labs_service.defer_retest(
        db, marker_name, until=body.until, note=body.note
    )
    if row is None:
        return not_found()
    await labs_service.refresh_alerts(db)
    await db.commit()
    return LabMarkerResponse(id=row.id, name=row.name)


@router.patch(
    "/markers/{marker_id}",
    response_model=LabMarkerResponse,
    responses=MUTATION_ERRORS,
)
async def update_lab_marker(
    marker_id: int, body: LabMarkerPatch, db: AsyncSession = Depends(get_session)
) -> LabMarkerResponse:
    """Update metadata for a catalog marker."""
    row = await db.get(LabMarker, marker_id)
    if row is None:
        return not_found()
    if body.category is not None:
        row.category = body.category
    if body.tier is not None:
        row.tier = body.tier
    if body.retest_interval_days is not None:
        row.retest_interval_days = body.retest_interval_days
    if body.ref_low is not None:
        row.ref_low = body.ref_low
    if body.ref_high is not None:
        row.ref_high = body.ref_high
    if body.note is not None:
        row.note = body.note
    await db.commit()
    return LabMarkerResponse(id=row.id, name=row.name)
