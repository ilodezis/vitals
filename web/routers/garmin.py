"""Endpoints for the Garmin module: dashboard, manual sync, and the Health Auto
Export backup-channel upload."""
from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import Domain
from vitals.integrations.garmin_client import GarminClient
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
            "count": count,
            "advice": advice,
            "alerts": alerts,
            "is_configured": client.is_configured,
            "last_sync": last_sync,
            "sync": request.query_params.get("sync"),
            "synced": request.query_params.get("synced"),
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
