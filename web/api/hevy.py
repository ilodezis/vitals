"""``/api/v1/workouts`` — workouts dashboard and sync (Hevy module)."""
from __future__ import annotations

import datetime as dt
import logging
from typing import Optional

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.integrations.hevy_client import HevyAPIError, HevyClient, HevyNotConfigured
from vitals.services import hevy_service
from vitals.utils.timeutils import to_local_naive
from web.api.errors import ApiRouter
from web.api.schemas.hevy import (
    ExerciseCatalogItem,
    HevyExerciseItem,
    HevySetItem,
    HevySyncResponse,
    HevyWorkoutItem,
    WorkingWeightPoint,
    WorkoutsView,
)
from web.deps import get_redis, get_session, require_auth

logger = logging.getLogger(__name__)

router = ApiRouter(prefix="/workouts", dependencies=[Depends(require_auth)])


@router.get("", response_model=WorkoutsView)
async def read_workouts(
    db: AsyncSession = Depends(get_session),
    redis=Depends(get_redis),
) -> WorkoutsView:
    """The Workouts screen: recent sessions expandable to sets, exercise catalog with progression."""
    workouts = await hevy_service.list_workouts(db, limit=50)
    count = await hevy_service.workout_count(db)
    last_date = await hevy_service.latest_workout_date(db)
    catalog = await hevy_service.exercise_catalog(db)

    client = HevyClient.from_config()
    is_configured = client.is_configured

    last_sync = None
    if redis is not None:
        last_sync_raw = await redis.get("sync:last_success:hevy")
        if last_sync_raw:
            try:
                from datetime import datetime, timezone
                dt_sync = datetime.fromtimestamp(int(last_sync_raw), timezone.utc)
                local_dt = to_local_naive(dt_sync)
                if local_dt:
                    last_sync = local_dt.strftime("%d-%m-%Y %H:%M")
            except (ValueError, TypeError, OverflowError):
                logger.debug("Invalid sync:last_success:hevy timestamp: %r", last_sync_raw)

    workout_items: list[HevyWorkoutItem] = []
    for w in workouts:
        summary = hevy_service.workout_summary(w)
        exercises_out = []
        for ex in w.exercises:
            sets_out = [
                HevySetItem(
                    set_index=s.set_index,
                    set_type=s.set_type,
                    weight_kg=s.weight_kg,
                    reps=s.reps,
                    rpe=s.rpe,
                )
                for s in ex.sets
            ]
            exercises_out.append(
                HevyExerciseItem(
                    exercise_index=ex.exercise_index,
                    title=ex.title,
                    exercise_template_id=ex.exercise_template_id,
                    notes=ex.notes,
                    sets=sets_out,
                )
            )

        workout_items.append(
            HevyWorkoutItem(
                id=str(w.external_id or w.id),
                date=w.date,
                title=w.title,
                program=w.program,
                start_time=w.start_time.isoformat() if w.start_time else None,
                duration_min=summary.get("duration_min"),
                working_sets=summary.get("working_sets", 0),
                volume_kg=float(summary["volume_kg"]) if summary.get("volume_kg") else None,
                exercises=exercises_out,
            )
        )

    catalog_items: list[ExerciseCatalogItem] = []
    for c in catalog:
        tid = c["exercise_template_id"]
        series = await hevy_service.working_weight_series(db, tid)
        verdict = await hevy_service.progression_for_exercise(db, tid)
        notes = await hevy_service.latest_notes(db, tid)
        catalog_items.append(
            ExerciseCatalogItem(
                exercise_template_id=tid,
                title=c["title"],
                sessions_count=c["sessions"],
                last_date=dt.date.fromisoformat(c["last_date"]) if c.get("last_date") else None,
                working_weight_series=[
                    WorkingWeightPoint(
                        date=dt.date.fromisoformat(p["date"]),
                        weight_kg=p["weight_kg"],
                        top_reps=p.get("top_reps"),
                        sets=p.get("sets", 0),
                    )
                    for p in series
                ],
                progression_verdict=verdict.status if verdict else None,
                latest_notes=notes,
            )
        )

    return WorkoutsView(
        workout_count=count,
        last_workout_date=last_date,
        exercise_count=len(catalog),
        is_configured=is_configured,
        last_sync=last_sync,
        workouts=workout_items,
        catalog=catalog_items,
    )


@router.post("/sync", response_model=HevySyncResponse)
async def sync_hevy_now(
    db: AsyncSession = Depends(get_session),
    redis=Depends(get_redis),
) -> HevySyncResponse:
    """Pull the latest workouts from Hevy."""
    client = HevyClient.from_config()
    if not client.is_configured:
        return HevySyncResponse(ok=False, synced=0, error="not_configured")

    try:
        summary = await hevy_service.sync(db, client)
        await db.commit()
        if redis is not None:
            import time
            await redis.set("sync:last_success:hevy", str(int(time.time())))
        return HevySyncResponse(ok=True, synced=summary["created"] + summary["updated"])
    except (HevyNotConfigured, HevyAPIError) as e:
        logger.warning("Hevy sync error: %s", e)
        return HevySyncResponse(ok=False, synced=0, error=str(e))
