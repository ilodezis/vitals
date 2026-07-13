"""Endpoints for the Labs module: dashboard, manual entry, document upload
(LLM extraction) with an edit-before-save preview, per-marker history,
defer-retest, delete."""
from __future__ import annotations

import logging
import os
import uuid
from datetime import date as date_type
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.config import load_config
from vitals.enums import Domain, Source
from vitals.i18n import t
from vitals.integrations.llm_client import LLMClient, LLMNotConfigured
from vitals.services import alerts_service, labs_service, raw_payload_service
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


class LabMarkerIn(BaseModel):
    marker: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    ref_low: Optional[float] = None
    ref_high: Optional[float] = None


class LabConfirm(BaseModel):
    date: str
    lab_name: Optional[str] = None
    file_key: Optional[str] = None
    raw_payload_id: Optional[int] = None
    markers: list[LabMarkerIn] = []


@router.post("/upload")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    """Step 1: a photo/PDF of a lab report -> vision extraction -> editable
    preview. The original file + verbatim vision payload are stored now
    (data-lake); the normalized ``LabResult`` rows are only written on confirm,
    with the owner's edits. Returns JSON the client renders as an editable
    table — a multi-file selection is queued and uploaded one file at a time by
    the client, each getting its own preview."""
    from vitals.utils.timeutils import today_local

    # 415/413 surface as HTTP errors (handled by the client's error branch).
    validate_extension(file.filename, DOC_EXTS)
    contents = await read_capped(file)

    try:
        llm = LLMClient()
    except LLMNotConfigured:
        return JSONResponse({"ok": False, "reason": "not_configured", "message": t("labs.upload_not_configured")})

    # Persist the original document for reference (served at /static/uploads/...).
    ext = file_ext(file.filename) or ".bin"
    file_key = f"labs/{uuid.uuid4().hex}{ext}"
    os.makedirs(os.path.join(STATIC_DIR, "uploads", "labs"), exist_ok=True)
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
        return JSONResponse({"ok": False, "reason": "not_configured", "message": t("labs.upload_not_configured")})
    except Exception as e:  # noqa: BLE001 — surface parse failures softly
        logger.warning("Lab extraction failed for %s: %s", file.filename, e)
        return JSONResponse({"ok": False, "reason": "error", "message": t("labs.upload_error")})

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

    return JSONResponse({
        "ok": True,
        "lab": {
            "date": lab_date,
            "lab_name": extracted.get("lab_name"),
            "file_key": file_key,
            "raw_payload_id": raw_row.id,
            "markers": rows,
        },
    })


@router.post("/confirm")
async def labs_confirm(
    request: Request,
    payload: LabConfirm,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    """Step 2: persist the owner-edited marker rows from the upload preview."""
    try:
        on_date = date_type.fromisoformat(payload.date)
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date")

    created = await labs_service.confirm_extracted(
        db,
        on_date=on_date,
        markers=[m.model_dump() for m in payload.markers],
        lab_name=payload.lab_name,
        raw_payload_id=payload.raw_payload_id,
    )
    await labs_service.refresh_alerts(db)
    await db.commit()
    return JSONResponse({"ok": True, "created": len(created)})


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
