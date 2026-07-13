"""Endpoints for the Labs module: dashboard, manual entry, document upload
(LLM extraction), per-marker history, defer-retest, delete."""
from __future__ import annotations

import logging
import os
import uuid
from datetime import date as date_type
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from typing import List
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.config import load_config
from vitals.enums import Domain
from vitals.integrations.llm_client import LLMClient, LLMNotConfigured
from vitals.services import alerts_service, labs_service
from web.deps import get_session, require_auth
from web.templating import STATIC_DIR, templates
from web.uploads import DOC_EXTS, file_ext, read_capped, validate_extension

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/labs", tags=["labs"])


@router.get("", response_class=HTMLResponse)
async def labs_dashboard(
    request: Request,
    marker: Optional[str] = None,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    """Labs dashboard: latest value per marker, the selected marker's history, the
    marker catalog (with retest/defer), and out-of-range alerts."""
    await labs_service.refresh_alerts(db)
    await db.commit()

    latest = await labs_service.latest_per_marker(db)
    # Sort latest: out-of-range first (newest to oldest), then normal (newest to oldest)
    latest = sorted(
        latest,
        key=lambda r: (labs_service.is_out_of_range(r.flag), r.date),
        reverse=True
    )
    markers = await labs_service.list_markers(db)
    alerts = await alerts_service.list_active(db, domain=Domain.LABS.value)

    selected = marker or (latest[0].marker if latest else None)
    history = await labs_service.marker_history(db, selected) if selected else []

    out_of_range = sum(1 for r in latest if labs_service.is_out_of_range(r.flag))

    from vitals.utils.timeutils import today_local

    return templates.TemplateResponse(
        request,
        "labs/index.html",
        {
            "username": username,
            "latest": latest,
            "markers": markers,
            "alerts": alerts,
            "selected": selected,
            "series": {"points": history},
            "out_of_range": out_of_range,
            "llm_configured": bool(load_config().openrouter_api_key),
            "today": today_local().isoformat(),
            "upload": request.query_params.get("upload"),
            "added": request.query_params.get("added"),
            "failed": request.query_params.get("failed"),
        },
    )


@router.post("/result")
async def add_result(
    request: Request,
    date: str = Form(...),
    marker: str = Form(...),
    value: float = Form(...),
    unit: Optional[str] = Form(None),
    ref_low: Optional[float] = Form(None),
    ref_high: Optional[float] = Form(None),
    lab_name: Optional[str] = Form(None),
    note: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    await labs_service.add_result(
        db,
        on_date=date_type.fromisoformat(date),
        marker=marker.strip(),
        value=value,
        unit=unit,
        ref_low=ref_low,
        ref_high=ref_high,
        lab_name=lab_name,
        note=note,
    )
    await db.commit()
    return _redirect(request, f"?marker={marker.strip()}&added=1")


@router.post("/upload")
async def upload_document(
    request: Request,
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    """Extract lab markers from one or more uploaded PDF/image files via the
    OpenRouter vision model, then ingest them. Each file is processed in sequence;
    totals are accumulated. The original files are kept under static/uploads."""
    uploads_dir = os.path.join(STATIC_DIR, "uploads", "labs")
    os.makedirs(uploads_dir, exist_ok=True)

    total_created = 0
    failed_count = 0
    any_success = False
    not_configured = False

    try:
        llm = LLMClient()
    except LLMNotConfigured:
        return _redirect(request, "?upload=not_configured")

    for file in files:
        # Reject (and skip) unsupported types and oversized files per-file, so one
        # bad file doesn't fail the whole batch and an .html/.svg can't be stored.
        try:
            validate_extension(file.filename, DOC_EXTS)
            contents = await read_capped(file)
        except HTTPException:
            logger.warning("Lab upload rejected (type/size): %s", file.filename)
            failed_count += 1
            continue

        # Persist the original document for reference.
        ext = file_ext(file.filename) or ".bin"
        file_key = f"labs/{uuid.uuid4().hex}{ext}"
        with open(os.path.join(STATIC_DIR, "uploads", file_key), "wb") as fh:
            fh.write(contents)

        try:
            extracted = await labs_service.extract_from_file(
                contents,
                llm=llm,
                content_type=file.content_type or "image/jpeg",
                filename=file.filename,
            )
        except LLMNotConfigured:
            not_configured = True
            failed_count += 1
            continue
        except Exception as e:  # noqa: BLE001 — surface parse failures softly
            logger.warning("Lab extraction failed for %s: %s", file.filename, e)
            failed_count += 1
            continue

        summary = await labs_service.ingest_extracted(db, extracted, file_key=file_key)
        total_created += summary["created"]
        any_success = True

    await db.commit()

    if not_configured and not any_success:
        return _redirect(request, "?upload=not_configured")
    if not any_success:
        return _redirect(request, "?upload=error")
    return _redirect(request, f"?upload=ok&added={total_created}&failed={failed_count}")


@router.post("/marker/{name}/defer")
async def defer_marker(
    request: Request,
    name: str,
    until: str = Form(...),
    note: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    await labs_service.defer_retest(
        db, name, until=date_type.fromisoformat(until), note=note
    )
    await db.commit()
    return _redirect(request, f"?marker={name}")


@router.post("/result/{result_id}/delete")
async def delete_result(
    request: Request,
    result_id: int,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    await labs_service.delete_result(db, result_id)
    await db.commit()
    return _redirect(request)


def _redirect(request: Request, suffix: str = "") -> RedirectResponse:
    url = f"/labs{suffix}"
    response = RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)
    if "hx-request" in request.headers:
        response.headers["HX-Redirect"] = url
    return response
