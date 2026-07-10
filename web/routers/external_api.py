"""Read-only JSON API for an external personal dashboard (glance cards).

A separate single-user app — same owner — shows a few calm health *glance*
cards: weight trend, today's macros, Garmin recovery, and simple logging
streaks. It reaches this API server-to-server with a static Bearer token
(``VITALS_EXTERNAL_API_TOKEN``); that app's own frontend never talks to Vitals
directly.

Design rules for this module:
  * **Read-only.** Nothing here writes, and it only ever *reads through the
    existing domain services* — no business logic (weight MA/slope, macro goals,
    recovery thresholds) is re-implemented. If a number needs computing, the
    service that owns it computes it.
  * **Locale-agnostic.** It returns raw numbers/codes only, never rendered text
    (e.g. no ``recovery_advice`` string): the caller applies its own i18n.
  * **Fails closed.** A missing/blank server token disables the endpoint (503);
    a wrong/absent Bearer is 401. The token is constant-time compared.

Auth deliberately bypasses the session/OAuth stack: the caller holds one
long-lived token in its own env and presents ``Authorization: Bearer <token>``.
"""
from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.config import load_config
from vitals.enums import Domain, MilestoneStatus
from vitals.utils.timeutils import today_local
from web.config import get_web_config
from web.deps import get_session

router = APIRouter(prefix="/external", tags=["external"])

# How far back the streak/activity date lists reach. 60 days is plenty for a
# "current consecutive-day" streak while keeping the payload tiny.
_ACTIVITY_WINDOW_DAYS = 60


async def require_external_token(request: Request) -> None:
    """Guard: a valid static Bearer token, constant-time compared.

    503 (not 401) when the server token is unset so the caller can tell
    "feature is switched off here" apart from "my token is wrong"."""
    expected = get_web_config().external_api_token
    if not expected:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="external_api_disabled")
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_token")


async def _weight_block(session: AsyncSession) -> dict[str, Any]:
    """Latest weight, a noise-excluded MA7 sparkline, the trend slope, and — if an
    active weight goal exists — the projected date to reach it (all from
    ``weight_service``; nothing recomputed here)."""
    from vitals.services import milestones_service, weight_service

    weights = await weight_service.list_active_weights(session)
    latest = weights[-1] if weights else None

    # An active weight goal (soonest deadline first, per list_milestones' order)
    # feeds chart_series so it returns a projection date for the goal.
    active = await milestones_service.list_milestones(session, status=MilestoneStatus.ACTIVE.value)
    goal_ms = next(
        (m for m in active if m.domain == Domain.WEIGHT.value and m.target_value is not None),
        None,
    )
    goal_kg = goal_ms.target_value if goal_ms else None

    series = await weight_service.chart_series(session, goal_kg=goal_kg)
    sparkline = [{"date": p["date"], "kg": p["weight_kg"]} for p in series["trend_ma"]]
    slope = series["trend"]["slope_per_week"] if series.get("trend") else None
    projection = series.get("projection")

    goal = None
    if goal_ms is not None:
        today = today_local()
        goal = {
            "target_kg": goal_ms.target_value,
            "eta_date": projection["date"] if projection else None,
            "deadline": goal_ms.deadline.isoformat() if goal_ms.deadline else None,
            "days_left": (goal_ms.deadline - today).days if goal_ms.deadline else None,
        }

    return {
        "latest_kg": latest.weight_kg if latest else None,
        "latest_date": latest.date.isoformat() if latest else None,
        "sparkline": sparkline,
        "slope_kg_per_week": slope,
        "goal": goal,
    }


async def _recovery_block(session: AsyncSession) -> Optional[dict[str, Any]]:
    """The most recent Garmin daily row's recovery numbers — raw values only, so
    the caller renders its own advice/labels from thresholds it owns."""
    from vitals.services import garmin_service

    g = await garmin_service.latest_daily(session)
    if g is None:
        return None
    return {
        "date": g.date.isoformat(),
        "sleep_score": g.sleep_score,
        "body_battery_high": g.body_battery_high,
        "training_readiness": g.training_readiness,
        "resting_hr": g.resting_hr,
        "hrv_avg": g.hrv_avg,
    }


async def _activity_block(session: AsyncSession) -> dict[str, list[str]]:
    """Recent per-domain log dates (last ``_ACTIVITY_WINDOW_DAYS`` days), newest
    first. The caller derives "current streak" from these — a presentation
    concept the caller owns, not a Vitals metric, so only the raw dates cross
    the wire."""
    from vitals.services import garmin_service, nutrition_service, weight_service

    today = today_local()
    since = today - timedelta(days=_ACTIVITY_WINDOW_DAYS - 1)

    weights = await weight_service.list_active_weights(session, start=since, end=today)
    meals = await nutrition_service.list_meals(session, start=since, end=today)
    daily = await garmin_service.list_daily(session, limit=_ACTIVITY_WINDOW_DAYS)

    def _dates(rows) -> list[str]:
        seen = {r.date for r in rows}
        return [d.isoformat() for d in sorted(seen, reverse=True)]

    return {
        "weight_days": _dates(weights),
        "nutrition_days": _dates(meals),
        # Garmin rows always carry a real date; keep only days with a recovery signal
        # so an empty ghost sync row doesn't inflate the streak.
        "recovery_days": _dates([g for g in daily if g.sleep_score is not None or g.body_battery_high is not None]),
    }


@router.get("/summary", dependencies=[Depends(require_external_token)])
async def external_summary(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """One compact payload for the caller's four health glance cards."""
    from vitals.services import nutrition_service

    cfg = load_config()
    nutrition_today = await nutrition_service.daily_summary(session, today_local(), cfg)

    return {
        "weight": await _weight_block(session),
        "nutrition_today": nutrition_today,
        "recovery": await _recovery_block(session),
        "activity": await _activity_block(session),
    }
