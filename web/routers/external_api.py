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
from web.deps import get_redis, get_session

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
        "sleep_seconds": g.sleep_seconds,
        "deep_sleep_seconds": g.deep_sleep_seconds,
        "rem_sleep_seconds": g.rem_sleep_seconds,
        "light_sleep_seconds": g.light_sleep_seconds,
        "awake_seconds": g.awake_seconds,
        "awake_count": g.awake_count,
        "body_battery_high": g.body_battery_high,
        "training_readiness": g.training_readiness,
        "resting_hr": g.resting_hr,
        "hrv_avg": g.hrv_avg,
        "hrv_status": g.hrv_status,
        "avg_stress": g.avg_stress,
        "max_stress": g.max_stress,
        "avg_sleep_stress": g.avg_sleep_stress,
    }


async def _activity_today_block(session: AsyncSession) -> Optional[dict[str, Any]]:
    """Today's activity snapshot from GarminDaily (or latest available)."""
    from vitals.services import garmin_service

    g = await garmin_service.get_daily(session, today_local())
    if g is None:
        g = await garmin_service.latest_daily(session)
    if g is None:
        return None
    moderate = g.intensity_minutes_moderate or 0
    vigorous = g.intensity_minutes_vigorous or 0
    return {
        "date": g.date.isoformat(),
        "steps": g.steps,
        "active_calories": g.active_calories,
        "intensity_minutes": moderate + vigorous,
    }


async def _latest_workout_block(session: AsyncSession) -> Optional[dict[str, Any]]:
    """Query the most recent HevyWorkout from vitals.models.hevy."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from vitals.models.hevy import HevyExercise, HevyWorkout

    stmt = (
        select(HevyWorkout)
        .options(selectinload(HevyWorkout.exercises).selectinload(HevyExercise.sets))
        .order_by(HevyWorkout.start_time.desc().nullslast(), HevyWorkout.date.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    workout = result.scalars().first()
    if workout is None:
        return None

    date_str = (
        workout.start_time.date().isoformat()
        if workout.start_time
        else (workout.date.isoformat() if workout.date else None)
    )

    duration_minutes = None
    if workout.end_time and workout.start_time:
        duration_minutes = int((workout.end_time - workout.start_time).total_seconds() / 60)
    elif workout.duration_seconds:
        duration_minutes = int(workout.duration_seconds / 60)

    total_vol = 0.0
    exercises_data = []
    for ex in workout.exercises:
        weights = [s.weight_kg for s in ex.sets if s.weight_kg is not None]
        max_w = max(weights) if weights else None
        top_set = (
            next((s for s in ex.sets if s.weight_kg == max_w), None)
            if max_w is not None
            else (ex.sets[0] if ex.sets else None)
        )
        reps = top_set.reps if top_set and top_set.reps is not None else None
        vol = sum((s.weight_kg or 0.0) * (s.reps or 0) for s in ex.sets)
        total_vol += vol
        exercises_data.append(
            {
                "name": ex.title,
                "max_weight_kg": max_w,
                "reps": reps,
                "_vol": vol,
            }
        )

    # Top exercises by volume (or max weight)
    exercises_data.sort(key=lambda x: (x["_vol"], x["max_weight_kg"] or 0), reverse=True)
    exercises = [
        {"name": e["name"], "max_weight_kg": e["max_weight_kg"], "reps": e["reps"]}
        for e in exercises_data[:5]
    ]

    volume_kg = getattr(workout, "volume_kg", None)
    if volume_kg is None and total_vol > 0:
        volume_kg = round(total_vol, 1)

    return {
        "id": str(workout.id),
        "title": workout.title,
        "date": date_str,
        "duration_minutes": duration_minutes,
        "volume_kg": volume_kg,
        "exercises": exercises,
    }


async def _skincare_today_block(session: AsyncSession) -> dict[str, list[dict[str, Any]]]:
    """Today's skincare routine from skincare_service."""
    from vitals.services import skincare_service

    plan = await skincare_service.plan_for(session, today_local())
    morning = [
        {"name": item["name"], "type": item.get("type"), "done": item.get("done", False)}
        for item in plan.get("morning", [])
    ]
    evening = [
        {"name": item["name"], "type": item.get("type"), "done": item.get("done", False)}
        for item in plan.get("evening", [])
    ]
    return {
        "morning": morning,
        "evening": evening,
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


async def _environment_block(
    session: AsyncSession, redis: Optional[Any] = None
) -> Optional[dict[str, Any]]:
    """Latest indoor environment readings from the air station."""
    from vitals.services.environment import live as env_live
    from vitals.services.environment.types import STATUS_NEVER

    try:
        state = await env_live.get_live(session, redis)
    except Exception:
        return None

    if state is None or state.station.status == STATUS_NEVER:
        return None

    now = state.now
    if now.co2_ppm is None and now.temperature_c is None and now.humidity_pct is None:
        return None

    return {
        "status": state.station.status,
        "co2_ppm": now.co2_ppm,
        "co2_zone": now.co2_zone,
        "co2_trend_ppm_per_h": now.co2_trend_ppm_per_h,
        "temperature_c": now.temperature_c,
        "humidity_pct": now.humidity_pct,
        "lux": now.lux,
    }


@router.get("/summary", dependencies=[Depends(require_external_token)])
async def external_summary(
    session: AsyncSession = Depends(get_session),
    redis: Optional[Any] = Depends(get_redis),
) -> dict[str, Any]:
    """One compact payload for the caller's health glance cards."""
    from vitals.services import nutrition_service

    cfg = load_config()
    nutrition_today = await nutrition_service.daily_summary(session, today_local(), cfg)

    return {
        "weight": await _weight_block(session),
        "nutrition_today": nutrition_today,
        "recovery": await _recovery_block(session),
        "activity_today": await _activity_today_block(session),
        "latest_workout": await _latest_workout_block(session),
        "skincare_today": await _skincare_today_block(session),
        "environment": await _environment_block(session, redis),
        "activity": await _activity_block(session),
    }
