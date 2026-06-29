"""Endpoints for managing weight logs, measurements, noise markers, and photos."""
from __future__ import annotations

from datetime import date as date_type
import os
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.config import load_config
from vitals.enums import Domain
from vitals.i18n import t
from vitals.services import alerts_service, weight_service
from vitals.services.conflict_engine import ConflictBlocked
from web.deps import get_session, require_auth
from web.templating import STATIC_DIR, templates
from web.uploads import IMAGE_EXTS, read_capped, validate_extension

router = APIRouter(prefix="/weight", tags=["weight"])


@router.get("", response_class=HTMLResponse)
async def weight_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    """Renders the weight OS dashboard, refreshing alerts and passing active metrics."""
    # Refresh noise alerts for today
    await weight_service.refresh_noise_alert(db)
    await db.commit()

    # Load data
    weights = await weight_service.list_active_weights(db)
    measurements = await weight_service.list_body_measurements(db)
    noise_markers = await weight_service.list_noise_markers(db)
    photos = await weight_service.list_progress_photos(db)
    alerts = await alerts_service.list_active(db, domain=Domain.WEIGHT.value)
    series = await weight_service.chart_series(db)

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

