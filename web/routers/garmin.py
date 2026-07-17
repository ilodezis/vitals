"""Endpoints for the Garmin module: dashboard, the per-night sleep detail page,
manual sync, and the Health Auto Export backup-channel upload."""
from __future__ import annotations

import json
import logging
from datetime import date as date_type
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import Domain
from vitals.integrations.garmin_client import GarminClient
from vitals.models.garmin import SERIES_BODY_BATTERY, SERIES_STRESS, SLEEP_SERIES_TYPES
from vitals.services import alerts_service, garmin_service
from web.deps import get_redis, get_session, require_auth
from web.templating import templates
from web.uploads import JSON_EXTS, read_capped, validate_extension

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/garmin", tags=["garmin"])


@router.get("", response_class=HTMLResponse)
async def garmin_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_session),
    redis = Depends(get_redis),
    username: str = Depends(require_auth),
):
    """Recovery + activity dashboard: latest day's metrics, recovery advice, recent
    history, and recorded activities."""
    latest = await garmin_service.latest_daily(db)
    history = await garmin_service.list_daily(db, limit=30)
    activities = await garmin_service.list_activities(db, limit=20)
    # The latest day's stress / Body Battery curves (empty dict on a day that has
    # only day-level scalars — the template then hides the chart card). Asked for
    # by name: the same date also holds the night's ~2k samples, which belong to
    # the sleep page and would otherwise ride along into this page for nothing.
    intraday = (
        await garmin_service.intraday_series_map(
            db, latest.date, series_types=(SERIES_STRESS, SERIES_BODY_BATTERY)
        )
        if latest
        else {}
    )
    count = await garmin_service.daily_count(db)
    advice = garmin_service.recovery_advice(latest)
    alerts = await alerts_service.list_active(db, domain=Domain.GARMIN.value)

    client = GarminClient.from_config()

    last_sync = None
    last_sync_raw = await redis.get("sync:last_success:garmin")
    if last_sync_raw:
        try:
            from datetime import datetime, timezone
            from vitals.utils.timeutils import to_local_naive
            dt = datetime.fromtimestamp(int(last_sync_raw), timezone.utc)
            local_dt = to_local_naive(dt)
            if local_dt:
                last_sync = local_dt.strftime("%d-%m-%Y %H:%M")
        except Exception:
            pass

    return templates.TemplateResponse(
        request,
        "garmin/index.html",
        {
            "username": username,
            "latest": latest,
            "history": history,
            "activities": activities,
            "intraday": intraday,
            "count": count,
            "advice": advice,
            "alerts": alerts,
            "is_configured": client.is_configured,
            "last_sync": last_sync,
            "sync": request.query_params.get("sync"),
            "synced": request.query_params.get("synced"),
        },
    )


@router.get("/sleep", response_class=HTMLResponse)
async def sleep_list(
    request: Request,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    """The Sleep tab: recent nights (days with a recorded sleep session), newest
    first, and the latest one singled out for a highlighted summary."""
    nights = await garmin_service.list_nights(db, limit=60)
    return templates.TemplateResponse(
        request,
        "garmin/sleep_list.html",
        {
            "username": username,
            "latest_night": nights[0] if nights else None,
            "nights": nights,
            "night_count": len(nights),
        },
    )


@router.get("/sleep/{on_date}", response_class=HTMLResponse)
async def sleep_night(
    request: Request,
    on_date: date_type,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    """One night in detail: the hypnogram plus the minute-level curves recorded
    while asleep. Its own page rather than another card on the dashboard because
    it's a different scale of data — a night is ~2k samples across seven series,
    against the dashboard's day-level scalars.

    ``on_date`` is the date of the daily row, i.e. the morning you woke up; the
    samples themselves start the previous evening."""
    daily = await garmin_service.get_daily(db, on_date)
    if daily is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such day")

    series = await garmin_service.intraday_series_map(
        db, on_date, series_types=SLEEP_SERIES_TYPES
    )
    prev_date, next_date = await garmin_service.adjacent_night_dates(db, on_date)
    return templates.TemplateResponse(
        request,
        "garmin/sleep.html",
        {
            "username": username,
            "daily": daily,
            "series": series,
            "stages": daily.sleep_stages or [],
            "prev_date": prev_date,
            "next_date": next_date,
        },
    )


@router.get("/activities", response_class=HTMLResponse)
async def activities_list(
    request: Request,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    """The Workouts tab: recorded sport activities, full width."""
    activities = await garmin_service.list_activities(db, limit=20)
    return templates.TemplateResponse(
        request,
        "garmin/activities.html",
        {
            "username": username,
            "activities": activities,
        },
    )


@router.post("/sync")
async def sync_now(
    request: Request,
    db: AsyncSession = Depends(get_session),
    redis=Depends(get_redis),
    username: str = Depends(require_auth),
):
    """Pull the last week of Garmin metrics on demand. Auth/MFA failures are turned
    into a passive alert inside the service, so this never hard-errors."""
    client = GarminClient.from_config(redis=redis)
    if not client.is_configured:
        return _redirect(request, "?sync=not_configured")

    summary = await garmin_service.sync(db, client)
    await db.commit()

    if summary.get("error"):
        return _redirect(request, f"?sync={summary['error']}")
    
    import time
    await redis.set("sync:last_success:garmin", str(int(time.time())))
    return _redirect(request, f"?sync=ok&synced={summary['days']}")


@router.post("/import")
async def import_health_auto_export(
    request: Request,
    file: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    """Backup channel: ingest a Health Auto Export JSON dump (uploaded file or a
    raw JSON request body) into the daily metrics. Returns JSON for programmatic
    callers, redirects for the dashboard form."""
    try:
        if file is not None:
            validate_extension(file.filename, JSON_EXTS)
            payload = json.loads((await read_capped(file)).decode("utf-8"))
        else:
            payload = await request.json()
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "invalid JSON"},
        )

    result = await garmin_service.ingest_health_auto_export(db, payload)
    await db.commit()

    if "application/json" in request.headers.get("accept", "") and file is None:
        return JSONResponse(content={"status": "ok", **result})
    return _redirect(request, f"?sync=imported&synced={result['dates']}")


def _redirect(request: Request, suffix: str = "") -> RedirectResponse:
    url = f"/garmin{suffix}"
    response = RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)
    if "hx-request" in request.headers:
        response.headers["HX-Redirect"] = url
    return response
