"""Endpoints for managing weight logs, measurements, noise markers, photos, and
body-composition scans (InBody / МедАсс — the optional ``body_comp`` module)."""
from __future__ import annotations

from datetime import date as date_type
import logging
import os
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.config import load_config
from vitals.enums import Domain, Source
from vitals.i18n import t
from vitals.integrations.llm_client import LLMClient, LLMNotConfigured
from vitals.services import alerts_service, body_scan_service, raw_payload_service, weight_service
from vitals.services.analytics import body_metrics
from vitals.services.conflict_engine import ConflictBlocked
from web.deps import get_session, require_auth, require_module
from web.templating import STATIC_DIR, templates
from web.uploads import DOC_EXTS, IMAGE_EXTS, file_ext, read_capped, validate_extension

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/weight", tags=["weight"])

# Render order of metric categories in the body-composition detail view.
BODY_CAT_ORDER = ["composition", "water", "segmental", "score", "derived", "other"]


@router.get("", response_class=HTMLResponse)
async def weight_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    """Renders the weight OS dashboard, refreshing alerts and passing active metrics."""
    # Is the optional body-composition module on? Gates the tab, the BIA chart
    # overlay, and the scan section — disabled behaves as if it isn't there.
    em = getattr(request.state, "enabled_modules", None) or {}
    body_comp_enabled = bool(em.get("body_comp"))

    # Refresh noise alerts for today (+ body-scan alerts when the module is on)
    await weight_service.refresh_noise_alert(db)
    if body_comp_enabled:
        await body_scan_service.refresh_alerts(db)
    await db.commit()

    # Load data
    weights = await weight_service.list_active_weights(db)
    measurements = await weight_service.list_body_measurements(db)
    noise_markers = await weight_service.list_noise_markers(db)
    photos = await weight_service.list_progress_photos(db)
    alerts = await alerts_service.list_active(db, domain=Domain.WEIGHT.value)
    series = await weight_service.chart_series(db, include_bia=body_comp_enabled)

    # Body-composition scans + the compact summary chips for the latest one.
    bc_scans = await body_scan_service.list_scans(db) if body_comp_enabled else []
    bc_latest = bc_scans[0] if bc_scans else None
    lang = getattr(request.state, "lang", "ru")
    bc_headline = []
    if bc_latest is not None:
        by_key: dict = {}
        for m in bc_latest.metrics:
            by_key.setdefault(m.metric_key, m)
        for key in body_metrics.HEADLINE_KEYS:
            m = by_key.get(key)
            if m is not None:
                bc_headline.append({
                    "key": key,
                    "name": body_metrics.display_name(key, lang) or m.label,
                    "value": m.value,
                    "unit": body_metrics.METRIC_REGISTRY[key].unit or "",
                })

    # Reverse logs list for table view (newest first)
    sorted_weights = sorted(weights, key=lambda w: w.date, reverse=True)
    sorted_measurements = sorted(measurements, key=lambda m: m.date, reverse=True)

    # Top "body fat %" card must reflect the most recent measurement that
    # actually carries a Navy body-fat value (neck+waist were entered), not just
    # the newest measurement row — which may only hold a partial entry.
    latest_bf = next(
        (m.body_fat_pct for m in sorted_measurements if m.body_fat_pct is not None),
        None,
    )
    latest_lbm = next(
        (m.lbm_kg for m in sorted_measurements if m.lbm_kg is not None),
        None,
    )

    # Default today's date for forms
    from vitals.utils.timeutils import today_local
    today_str = today_local().isoformat()

    return templates.TemplateResponse(
        request,
        "weight/index.html",
        {
            "username": username,
            "weights": sorted_weights,
            "measurements": sorted_measurements,
            "latest_bf": latest_bf,
            "latest_lbm": latest_lbm,
            "noise_markers": noise_markers,
            "photos": photos,
            "alerts": alerts,
            "series": series,
            "today": today_str,
            "sex": load_config().sex,
            # Body composition (optional module)
            "body_comp_enabled": body_comp_enabled,
            "bc_scans": bc_scans,
            "bc_latest": bc_latest,
            "bc_headline": bc_headline,
            "bc_cat_order": BODY_CAT_ORDER,
            "llm_configured": bool(load_config().openrouter_api_key),
        },
    )


@router.post("/log")
async def log_weight_entry(
    request: Request,
    id: Optional[int] = Form(None),
    weight_kg: float = Form(...),
    date: str = Form(...),
    note: Optional[str] = Form(None),
    override: bool = Form(False),
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    """Logs or edits a weight, returning 409 JSON on rule violation for override confirmation."""
    on_date = date_type.fromisoformat(date)
    try:
        if id is not None:
            await weight_service.update_weight_log(
                db,
                log_id=id,
                on_date=on_date,
                weight_kg=weight_kg,
                note=note,
                override=override,
            )
        else:
            await weight_service.log_weight(
                db,
                on_date=on_date,
                weight_kg=weight_kg,
                note=note,
                override=override,
            )
        await db.commit()
    except ConflictBlocked as e:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"violations": [v.to_dict() for v in e.violations]},
        )

    if "hx-request" in request.headers:
        response = RedirectResponse(url="/weight", status_code=status.HTTP_303_SEE_OTHER)
        response.headers["HX-Redirect"] = "/weight"
        return response

    return RedirectResponse(url="/weight", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/measurement")
async def log_measurement_entry(
    request: Request,
    id: Optional[int] = Form(None),
    date: str = Form(...),
    neck_cm: Optional[float] = Form(None),
    waist_cm: Optional[float] = Form(None),
    hips_cm: Optional[float] = Form(None),
    note: Optional[str] = Form(None),
    override: bool = Form(False),
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    """Upserts or edits a body measurement log, returning 409 JSON on rule violation."""
    on_date = date_type.fromisoformat(date)
    try:
        if id is not None:
            await weight_service.update_body_measurement(
                db,
                measurement_id=id,
                on_date=on_date,
                neck_cm=neck_cm,
                waist_cm=waist_cm,
                hips_cm=hips_cm,
                note=note,
                override=override,
              )
        else:
            await weight_service.upsert_body_measurement(
                db,
                on_date=on_date,
                neck_cm=neck_cm,
                waist_cm=waist_cm,
                hips_cm=hips_cm,
                note=note,
                override=override,
            )
        await db.commit()
    except ConflictBlocked as e:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"violations": [v.to_dict() for v in e.violations]},
        )

    if "hx-request" in request.headers:
        response = RedirectResponse(url="/weight", status_code=status.HTTP_303_SEE_OTHER)
        response.headers["HX-Redirect"] = "/weight"
        return response

    return RedirectResponse(url="/weight", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/noise")
async def add_noise_entry(
    request: Request,
    start_date: str = Form(...),
    end_date: Optional[str] = Form(None),
    reason: str = Form(...),
    direction: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    """Exclude a period from calculations to filter out creatine or salt spikes."""
    start = date_type.fromisoformat(start_date)
    end = date_type.fromisoformat(end_date) if end_date else None
    # Normalise: empty string → None
    dir_value = direction.strip() if direction and direction.strip() else None

    await weight_service.add_noise_marker(
        db, start_date=start, end_date=end, reason=reason, direction=dir_value
    )
    await db.commit()

    if "hx-request" in request.headers:
        response = RedirectResponse(url="/weight", status_code=status.HTTP_303_SEE_OTHER)
        response.headers["HX-Redirect"] = "/weight"
        return response

    return RedirectResponse(url="/weight", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/photo")
async def add_photo_entry(
    request: Request,
    date: str = Form(...),
    note: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    files: Optional[list[UploadFile]] = File(None),
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    """Saves up to 5 daily progress photos to static/uploads/ and references them in the DB."""
    on_date = date_type.fromisoformat(date)

    # Gather all uploaded files from both "file" (single-field tests) and "files" (multiple files input)
    uploaded_files: list[UploadFile] = []
    if file is not None and file.filename:
        uploaded_files.append(file)
    if files is not None:
        for f in files:
            if f.filename:
                uploaded_files.append(f)

    if not uploaded_files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=t("weight.error.no_files")
        )

    if len(uploaded_files) > 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=t("weight.error.too_many_files")
        )

    # Save to static/uploads
    uploads_dir = os.path.join(STATIC_DIR, "uploads")
    os.makedirs(uploads_dir, exist_ok=True)

    for f in uploaded_files:
        file_extension = validate_extension(f.filename, IMAGE_EXTS)
        contents = await read_capped(f)
        unique_filename = f"{uuid.uuid4().hex}{file_extension}"
        file_path = os.path.join(uploads_dir, unique_filename)

        with open(file_path, "wb") as buffer:
            buffer.write(contents)

        # Save reference key (relative path inside static directory)
        file_key = f"uploads/{unique_filename}"
        await weight_service.add_progress_photo(db, on_date=on_date, file_key=file_key, note=note)

    await db.commit()

    if "hx-request" in request.headers:
        response = RedirectResponse(url="/weight", status_code=status.HTTP_303_SEE_OTHER)
        response.headers["HX-Redirect"] = "/weight"
        return response

    return RedirectResponse(url="/weight", status_code=status.HTTP_303_SEE_OTHER)


# ── Body composition (InBody / МедАсс) — optional module ──────────────────────
class BodyScanMetricIn(BaseModel):
    metric_key: Optional[str] = None
    label: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    ref_low: Optional[float] = None
    ref_high: Optional[float] = None
    segment: Optional[str] = None
    category: Optional[str] = None


class BodyScanConfirm(BaseModel):
    date: str
    device: Optional[str] = None
    file_key: Optional[str] = None
    raw_payload_id: Optional[int] = None
    note: Optional[str] = None
    override: bool = False
    metrics: list[BodyScanMetricIn] = []


@router.post("/body-scan/upload")
async def body_scan_upload(
    request: Request,
    file: UploadFile = File(...),
    date: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
    _gate: None = Depends(require_module("body_comp")),
):
    """Step 1: a photo/PDF of a scan sheet → vision extraction → editable preview.

    The original file + verbatim vision payload are stored now (data-lake); the
    normalized ``BodyScan`` rows are only written on confirm, with the owner's
    edits. Returns JSON the client renders as an editable table."""
    from vitals.utils.timeutils import today_local

    # 415/413 surface as HTTP errors (handled by the client's error branch).
    validate_extension(file.filename, DOC_EXTS)
    contents = await read_capped(file)

    try:
        llm = LLMClient()
    except LLMNotConfigured:
        return JSONResponse({"ok": False, "reason": "not_configured", "message": t("body.not_configured")})

    # Persist the original sheet image for reference (served at /static/uploads/...).
    ext = file_ext(file.filename) or ".bin"
    file_key = f"body/{uuid.uuid4().hex}{ext}"
    os.makedirs(os.path.join(STATIC_DIR, "uploads", "body"), exist_ok=True)
    with open(os.path.join(STATIC_DIR, "uploads", file_key), "wb") as fh:
        fh.write(contents)

    try:
        extracted = await body_scan_service.extract_from_file(
            contents,
            llm=llm,
            content_type=file.content_type or "image/jpeg",
            filename=file.filename,
        )
    except LLMNotConfigured:
        return JSONResponse({"ok": False, "reason": "not_configured", "message": t("body.not_configured")})
    except Exception as e:  # noqa: BLE001 — surface parse failures softly
        logger.warning("Body-scan extraction failed for %s: %s", file.filename, e)
        return JSONResponse({"ok": False, "reason": "error", "message": t("body.upload.error")})

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
        scan_date = date_type.fromisoformat(str(raw_date)[:10]).isoformat()
    except (ValueError, TypeError):
        scan_date = today_local().isoformat()

    return JSONResponse({
        "ok": True,
        "scan": {
            "date": scan_date,
            "device": extracted.get("device"),
            "file_key": file_key,
            "raw_payload_id": raw_row.id,
            "metrics": rows,
        },
    })


@router.post("/body-scan/confirm")
async def body_scan_confirm(
    request: Request,
    payload: BodyScanConfirm,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
    _gate: None = Depends(require_module("body_comp")),
):
    """Step 2: persist the owner-edited scan rows. 409 + violations on a block."""
    try:
        on_date = date_type.fromisoformat(payload.date)
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date")

    try:
        await body_scan_service.save_scan(
            db,
            on_date=on_date,
            device=payload.device,
            file_key=payload.file_key,
            raw_payload_id=payload.raw_payload_id,
            metrics=[m.model_dump() for m in payload.metrics],
            note=payload.note,
            override=payload.override,
        )
        await body_scan_service.refresh_alerts(db)
        await db.commit()
    except ConflictBlocked as e:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"violations": [v.to_dict() for v in e.violations]},
        )
    return JSONResponse({"ok": True, "redirect": "/weight"})


@router.post("/body-scan/{scan_id}/delete")
async def delete_body_scan_entry(
    request: Request,
    scan_id: int,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
    _gate: None = Depends(require_module("body_comp")),
):
    scan = await body_scan_service.get_scan(db, scan_id)
    file_key = scan.file_key if scan is not None else None
    await body_scan_service.delete_scan(db, scan_id)
    await db.commit()

    if file_key:
        file_path = os.path.join(STATIC_DIR, "uploads", file_key)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError as e:
                logger.warning("Could not remove scan file %s: %s", file_path, e)

    if "hx-request" in request.headers:
        response = RedirectResponse(url="/weight", status_code=status.HTTP_303_SEE_OTHER)
        response.headers["HX-Redirect"] = "/weight"
        return response
    return RedirectResponse(url="/weight", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/log/{id}/delete")
async def delete_weight_entry(
    request: Request,
    id: int,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    await weight_service.delete_weight_log(db, id)
    await db.commit()

    if "hx-request" in request.headers:
        response = RedirectResponse(url="/weight", status_code=status.HTTP_303_SEE_OTHER)
        response.headers["HX-Redirect"] = "/weight"
        return response

    return RedirectResponse(url="/weight", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/measurement/{id}/delete")
async def delete_measurement_entry(
    request: Request,
    id: int,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    await weight_service.delete_body_measurement(db, id)
    await db.commit()

    if "hx-request" in request.headers:
        response = RedirectResponse(url="/weight", status_code=status.HTTP_303_SEE_OTHER)
        response.headers["HX-Redirect"] = "/weight"
        return response

    return RedirectResponse(url="/weight", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/noise/{id}/delete")
async def delete_noise_marker_entry(
    request: Request,
    id: int,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    await weight_service.delete_noise_marker(db, id)
    await db.commit()

    if "hx-request" in request.headers:
        response = RedirectResponse(url="/weight", status_code=status.HTTP_303_SEE_OTHER)
        response.headers["HX-Redirect"] = "/weight"
        return response

    return RedirectResponse(url="/weight", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/photo/delete")
async def delete_photo_entry(
    request: Request,
    id: int = Form(...),
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    file_key = await weight_service.delete_progress_photo(db, id)
    await db.commit()

    if file_key:
        file_path = os.path.join(STATIC_DIR, file_key)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"Error removing file {file_path}: {e}")

    if "hx-request" in request.headers:
        response = RedirectResponse(url="/weight", status_code=status.HTTP_303_SEE_OTHER)
        response.headers["HX-Redirect"] = "/weight"
        return response

    return RedirectResponse(url="/weight", status_code=status.HTTP_303_SEE_OTHER)

