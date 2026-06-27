"""Endpoints for the Hevy workouts module: dashboard, manual sync, per-exercise
history + progression."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import Domain, Severity
from vitals.integrations.hevy_client import HevyAPIError, HevyClient, HevyNotConfigured
from vitals.services import alerts_service, hevy_service
from web.deps import get_redis, get_session, require_auth
from web.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/hevy", tags=["hevy"])

SYNC_ALERT_KEY = "hevy.sync_failed"


@router.get("", response_class=HTMLResponse)
async def hevy_dashboard(
    request: Request,
    ex: Optional[str] = None,
    db: AsyncSession = Depends(get_session),
    redis = Depends(get_redis),
    username: str = Depends(require_auth),
):
    """Workouts dashboard: recent sessions, exercise catalog, and — when an
    exercise is selected (``?ex=<template_id>``) — its working-weight history +
    progression verdict."""
    workouts = await hevy_service.list_workouts(db, limit=30)
    catalog = await hevy_service.exercise_catalog(db)
    count = await hevy_service.workout_count(db)
    last_date = await hevy_service.latest_workout_date(db)
    alerts = await alerts_service.list_active(db, domain=Domain.WORKOUTS.value)

    # Default the selected exercise to the most recently trained one.
    selected = ex or (catalog[0]["exercise_template_id"] if catalog else None)
    series: list = []
    verdict = None
    notes = None
    selected_title = None
    if selected:
        series = await hevy_service.working_weight_series(db, selected)
        verdict = await hevy_service.progression_for_exercise(db, selected)
        notes = await hevy_service.latest_notes(db, selected)
        selected_title = next(
            (c["title"] for c in catalog if c["exercise_template_id"] == selected), selected
        )

    client = HevyClient.from_config()

    last_sync = None
    last_sync_raw = await redis.get("sync:last_success:hevy")
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
        "hevy/index.html",
        {
            "username": username,
            "workouts": workouts,
            "catalog": catalog,
            "count": count,
            "last_date": last_date.isoformat() if last_date else None,
            "alerts": alerts,
            "selected": selected,
            "selected_title": selected_title,
            "series": {"points": series},
            "verdict": verdict,
            "notes": notes,
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
    redis = Depends(get_redis),
    username: str = Depends(require_auth),
):
    """Pull the latest workouts from Hevy on demand. Failures surface as a passive
    ``warn`` alert (never a hard error) so the page still renders."""
    client = HevyClient.from_config()
    if not client.is_configured:
        return _redirect(request, "?sync=not_configured")

    try:
        summary = await hevy_service.sync(db, client)
        await alerts_service.resolve_by_key(db, alert_key=SYNC_ALERT_KEY)
        await db.commit()
        
        import time
        await redis.set("sync:last_success:hevy", str(int(time.time())))
    except (HevyNotConfigured, HevyAPIError) as e:
        logger.warning("Hevy sync failed: %s", e)
        await alerts_service.raise_alert(
            db,
            domain=Domain.WORKOUTS.value,
            severity=Severity.WARN.value,
            message=f"Не удалось синхронизировать Hevy: {e}",
            alert_key=SYNC_ALERT_KEY,
        )
        await db.commit()
        return _redirect(request, "?sync=error")

    created = summary["created"] + summary["updated"]
    return _redirect(request, f"?sync=ok&synced={created}")


def _redirect(request: Request, suffix: str = "") -> RedirectResponse:
    url = f"/hevy{suffix}"
    response = RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)
    if "hx-request" in request.headers:
        response.headers["HX-Redirect"] = url
    return response
