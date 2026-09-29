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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.config import load_config
from vitals.enums import Domain, Source
from vitals.integrations.llm_client import LLMClient, LLMNotConfigured
from vitals.services import alerts_service, body_scan_service, raw_payload_service, weight_service
from vitals.services.analytics import body_metrics
from vitals.services import garmin_weight_service
from vitals.utils.timeutils import today_local
from web.api.errors import MUTATION_ERRORS, ApiRouter, not_found
from web.api.schemas.weight import (
    BodyMeasurementCreate,
    BodyMeasurementItem,
    BodyMeasurementRef,
    BodyScanConfirm,
    BodyScanConfirmResponse,
    BodyScanDetailItem,
    BodyScanMetricIn,
    BodyScanMetricItem,
    BodyScanPreview,
    BodyScanUploadResponse,
    DosePhase,
    GarminExportResponse,
    LastScanRow,
    LastScanSummary,
    NoiseMarkerCreate,
    NoiseMarkerItem,
    NoiseMarkerRef,
    ProgressPhotoItem,
    WeightHistoryItem,
    WeightLogCreate,
    WeightLogCreated,
    WeightLogPatch,
    WeightLogRef,
    WeightMeasuresView,
    WeightPace,
    WeightPaceDose,
    WeightPaceGoal,
    WeightPoint,
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
    body_comp_enabled = bool(em.get("body_comp"))
    timeline_enabled = bool(em.get("timeline"))
    glp1_enabled = bool(em.get("glp1"))
    lang = getattr(request.state, "lang", "ru")

    # Refresh alerts
    await weight_service.refresh_noise_alert(db)
    if body_comp_enabled:
        await body_scan_service.refresh_alerts(db)
    await db.commit()

    # Load data
    weights = await weight_service.list_active_weights(db)
    measurements = await weight_service.list_body_measurements(db)
    series = await weight_service.chart_series(
        db, include_bia=body_comp_enabled, include_timeline=timeline_enabled, include_glp1=glp1_enabled
    )

    from vitals.models.weight import WeightLog

    all_weights_result = await db.execute(
        select(WeightLog).order_by(WeightLog.date.desc(), WeightLog.id.desc())
    )
    all_weights = all_weights_result.scalars().all()

    # Scans
    bc_scans = await body_scan_service.list_scans(db) if body_comp_enabled else []
    bc_latest = bc_scans[0] if bc_scans else None

    # Latest body fat & source
    body_fat_pct = None
    body_fat_source = None
    if bc_latest:
        bf_val = body_metrics.body_fat_pct_from_scan(bc_latest.metrics)
        if bf_val is not None:
            body_fat_pct = bf_val
            body_fat_source = bc_latest.device or "InBody"

    if body_fat_pct is None:
        for m in measurements:
            if m.body_fat_pct is not None:
                body_fat_pct = m.body_fat_pct
                body_fat_source = "Navy"
                break

    latest_kg = weights[0].weight_kg if weights else None
    latest_date = weights[0].date if weights else None
    average7 = series["trend_ma"][-1]["weight_kg"] if series.get("trend_ma") else None
    week_delta = series.get("weekly_delta")

    # Drug name if glp1 is on
    drug_name = "GLP-1"
    if glp1_enabled:
        try:
            from vitals.models.glp1 import DOMAIN as GLP1_DOMAIN, Glp1Medication
            med_res = await db.execute(select(Glp1Medication).where(Glp1Medication.domain == GLP1_DOMAIN))
            med = med_res.scalars().first()
            if med and med.name:
                drug_name = med.name
        except Exception:
            pass

    # Weighings and trend series
    weighings = [
        WeightPoint(date=dt.date.fromisoformat(p["date"]), kg=p["weight_kg"])
        for p in series.get("raw", [])
    ]
    trend = [
        WeightPoint(date=dt.date.fromisoformat(p["date"]), kg=p["weight_kg"])
        for p in series.get("trend_ma", [])
    ]
    dose_phases = [
        DosePhase(
            from_date=dt.date.fromisoformat(p["start"]),
            to_date=dt.date.fromisoformat(p["end"]) if p.get("end") else None,
            label=p.get("label") or "",
        )
        for p in series.get("phases", [])
    ]

    def _norm_source(src: str) -> str:
        if src in ("garmin_api", "garmin"):
            return "garmin"
        if src in ("body_scan", "bia"):
            return "bia"
        return "manual"

    history = [
        WeightHistoryItem(
            id=w.id,
            date=w.date,
            time="",
            weight_kg=w.weight_kg,
            source=_norm_source(w.source),
            superseded=bool(w.superseded),
            note=w.note,
        )
        for w in all_weights
    ]

    # Pace
    trend_info = series.get("trend")
    per_week_kg = trend_info.get("slope_per_week") if trend_info else None

    # Dose pace
    dose_pace = None
    if glp1_enabled and dose_phases:
        active_phase = dose_phases[-1]
        today = today_local()
        days_on_dose = max(0, (today - active_phase.from_date).days)
        # Find weight at dose start and now
        weights_on_dose = [w for w in weights if w.date >= active_phase.from_date]
        if weights_on_dose and len(weights_on_dose) >= 2:
            delta_kg = round(weights_on_dose[0].weight_kg - weights_on_dose[-1].weight_kg, 1)
        else:
            delta_kg = 0.0
        dose_pace = WeightPaceDose(
            label=active_phase.label or "0,5 мг",
            since_date=active_phase.from_date,
            days=days_on_dose,
            delta_kg=delta_kg,
        )

    # Goal pace
    goal_pace = None
    projection = series.get("projection")
    if projection and projection.get("target_kg"):
        target_kg = projection["target_kg"]
        weeks = None
        if projection.get("date"):
            try:
                proj_date = dt.date.fromisoformat(projection["date"])
                weeks = max(0, (proj_date - today_local()).days // 7)
            except Exception:
                pass
        goal_pace = WeightPaceGoal(target_kg=target_kg, weeks=weeks)

    pace = WeightPace(per_week_kg=per_week_kg, dose=dose_pace, goal=goal_pace)

    # Last scan summary
    last_scan = None
    if bc_latest:
        by_key = {m.metric_key: m for m in bc_latest.metrics if m.metric_key}
        scan_rows = []
        for key in body_metrics.HEADLINE_KEYS:
            m = by_key.get(key)
            if m is not None:
                scan_rows.append(
                    LastScanRow(
                        label=body_metrics.display_name(key, lang) or m.label,
                        value=m.value,
                        unit=body_metrics.METRIC_REGISTRY[key].unit or "",
                    )
                )
        last_scan = LastScanSummary(device=bc_latest.device, date=bc_latest.date, rows=scan_rows)

    return WeightView(
        latest_kg=latest_kg,
        latest_date=latest_date,
        average7=average7,
        week_delta_kg=week_delta,
        body_fat_pct=body_fat_pct,
        body_fat_source=body_fat_source,
        drug=drug_name,
        weighings=weighings,
        trend=trend,
        dose_phases=dose_phases,
        history=history,
        pace=pace,
        last_scan=last_scan,
    )


# ── GET /api/v1/weight/measures ───────────────────────────────────────────────


@router.get("/measures", response_model=WeightMeasuresView)
async def read_weight_measures(
    request: Request, db: AsyncSession = Depends(get_session)
) -> WeightMeasuresView:
    """The Measurements desk: circumferences, Navy fat, scans, noise markers, photos."""
    em = getattr(request.state, "enabled_modules", None) or {}
    body_comp_enabled = bool(em.get("body_comp"))
    timeline_enabled = bool(em.get("timeline"))
    lang = getattr(request.state, "lang", "ru")
    cfg = load_config()

    weights = await weight_service.list_active_weights(db)
    measurements = await weight_service.list_body_measurements(db)
    noise_markers = await weight_service.list_noise_markers(db)
    photos = await weight_service.list_progress_photos(db)
    series = await weight_service.chart_series(
        db, include_bia=body_comp_enabled, include_timeline=timeline_enabled
    )

    bc_scans = await body_scan_service.list_scans(db) if body_comp_enabled else []
    bc_latest = bc_scans[0] if bc_scans else None

    # Unified measurements
    unified: list[BodyMeasurementItem] = []
    for m in measurements:
        unified.append(
            BodyMeasurementItem(
                id=m.id,
                date=m.date,
                neck_cm=m.neck_cm,
                waist_cm=m.waist_cm,
                hips_cm=m.hips_cm,
                body_fat_pct=m.body_fat_pct,
                lbm_kg=m.lbm_kg,
                source="navy",
                source_label="Navy",
                note=m.note,
            )
        )
    if body_comp_enabled:
        for s in bc_scans:
            bf_val = body_metrics.body_fat_pct_from_scan(s.metrics)
            lbm_val = body_metrics.lbm_from_scan(s.metrics)
            if bf_val is not None or lbm_val is not None:
                unified.append(
                    BodyMeasurementItem(
                        id=s.id,
                        date=s.date,
                        neck_cm=None,
                        waist_cm=None,
                        hips_cm=None,
                        body_fat_pct=bf_val,
                        lbm_kg=lbm_val,
                        source="scan",
                        source_label=s.device or "InBody",
                        note=s.note,
                    )
                )
    sorted_unified = sorted(unified, key=lambda x: x.date, reverse=True)

    # Latest body fat & source
    with_bf = [m for m in sorted_unified if m.body_fat_pct is not None]
    latest_bf_row = next((m for m in with_bf if m.source == "scan"), next(iter(with_bf), None))
    latest_bf = latest_bf_row.body_fat_pct if latest_bf_row else None
    latest_bf_source = latest_bf_row.source_label if latest_bf_row else None

    headline_metrics: list[LastScanRow] = []
    if bc_latest:
        by_key = {m.metric_key: m for m in bc_latest.metrics if m.metric_key}
        for key in body_metrics.HEADLINE_KEYS:
            m = by_key.get(key)
            if m is not None:
                headline_metrics.append(
                    LastScanRow(
                        label=body_metrics.display_name(key, lang) or m.label,
                        value=m.value,
                        unit=body_metrics.METRIC_REGISTRY[key].unit or "",
                    )
                )

    scans_out = [
        BodyScanDetailItem(
            id=s.id,
            date=s.date,
            device=s.device,
            file_key=s.file_key,
            note=s.note,
            metrics_count=len(s.metrics),
            metrics=[
                BodyScanMetricItem(
                    id=m.id,
                    metric_key=m.metric_key,
                    label=m.label,
                    value=m.value,
                    unit=m.unit,
                    ref_low=m.ref_low,
                    ref_high=m.ref_high,
                    segment=m.segment,
                    category=m.category,
                )
                for m in s.metrics
            ],
        )
        for s in bc_scans
    ]

    photos_out = [
        ProgressPhotoItem(
            id=p.id,
            date=p.date,
            file_key=p.file_key,
            url=f"/static/{p.file_key}",
            note=p.note,
        )
        for p in photos
    ]

    noise_out = [
        NoiseMarkerItem(
            id=n.id,
            start_date=n.start_date,
            end_date=n.end_date,
            reason=n.reason,
            direction=n.direction,
        )
        for n in noise_markers
    ]

    latest_kg = weights[0].weight_kg if weights else None
    average7 = series["trend_ma"][-1]["weight_kg"] if series.get("trend_ma") else None

    return WeightMeasuresView(
        latest_kg=latest_kg,
        average7=average7,
        body_fat_pct=latest_bf,
        body_fat_source=latest_bf_source,
        week_delta_kg=series.get("weekly_delta"),
        height_cm=cfg.height_cm,
        sex=cfg.sex,
        body_comp_enabled=body_comp_enabled,
        llm_configured=bool(cfg.openrouter_api_key),
        headline_metrics=headline_metrics,
        measurements=sorted_unified,
        scans=scans_out,
        photos=photos_out,
        noise_markers=noise_out,
    )


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
