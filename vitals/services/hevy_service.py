"""Hevy workouts service (module 5).

Owns the workouts domain:

  * **Sync** — pull workouts from the Hevy API, keep each full payload in
    ``raw_payloads``, and normalise the exercise→set tree into
    ``hevy_workouts`` / ``hevy_exercises`` / ``hevy_sets``. Re-sync is idempotent:
    a workout whose Hevy ``updated_at`` is unchanged is skipped; a changed one is
    re-normalised in place (children rebuilt). The upsert key is the Hevy id.
  * **Program mapping** — tag a workout with the training program it matches
    (title heuristic; overridable as routines/templates land).
  * **Progression** — per exercise, reduce the session history to the engine's
    ``SessionResult`` shape and ask ``analytics.progression`` what to do next
    (🟢 advance / 🟡 hold / 🔴 deload).
  * **Working-weight history** — per-exercise series for the dashboard charts.

The service is handed a client (tests pass a fake), never constructing one for
the network itself, keeping it unit-testable without Hevy.
"""
from __future__ import annotations

from datetime import date as date_type, datetime
from typing import Any, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from vitals.enums import Source
from vitals.models.hevy import DOMAIN, HevyExercise, HevySet, HevyWorkout
from vitals.models.raw_payload import RawPayload
from vitals.services import raw_payload_service
from vitals.services.analytics.progression import (
    ProgressionConfig,
    ProgressionVerdict,
    SessionResult,
    evaluate_progression,
)
from vitals.utils.timeutils import now_local, to_local_naive

# Only these set types are "working sets" that drive progression / top-weight.
_WORKING_SET_TYPES = {"normal", "failure"}


# ── Parsing helpers ───────────────────────────────────────────────────────────
def _parse_dt(value: Any) -> Optional[datetime]:
    """Parse a Hevy ISO-8601 timestamp into a naive **local** datetime."""
    if not value:
        return None
    if isinstance(value, datetime):
        return to_local_naive(value)
    try:
        text = str(value).replace("Z", "+00:00")
        return to_local_naive(datetime.fromisoformat(text))
    except (ValueError, TypeError):
        return None


def _int_or_none(v: Any) -> Optional[int]:
    try:
        return int(v) if v is not None else None
    except (ValueError, TypeError):
        return None


def _float_or_none(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (ValueError, TypeError):
        return None


def _map_program(raw_workout: dict) -> Optional[str]:
    """Best-effort training-program tag from the workout title.

    A title like "Day A — Push" → "A". Deliberately light; richer template/routine
    matching can replace this without touching the schema (the column stays).
    """
    title = (raw_workout.get("title") or "").lower()
    for token, label in (("program a", "A"), ("program b", "B"), ("day a", "A"), ("day b", "B")):
        if token in title:
            return label
    return None


# ── Sync ──────────────────────────────────────────────────────────────────────
async def sync(
    session: AsyncSession,
    client: Any,
    *,
    max_pages: int = 50,
    force: bool = False,
) -> dict:
    """Fetch workouts and normalise them. Returns a summary dict
    (``fetched`` / ``created`` / ``updated`` / ``skipped``). Does not commit."""
    raw_workouts = await client.fetch_workouts(max_pages=max_pages)
    summary = {"fetched": len(raw_workouts), "created": 0, "updated": 0, "skipped": 0}

    for raw in raw_workouts:
        external_id = str(raw.get("id") or "").strip()
        if not external_id:
            summary["skipped"] += 1
            continue

        existing = await _get_workout_by_external(session, external_id)
        hevy_updated = _parse_dt(raw.get("updated_at"))
        if existing is not None and not force and existing.hevy_updated_at == hevy_updated:
            summary["skipped"] += 1
            continue

        raw_row = await raw_payload_service.upsert_raw_payload(
            session,
            domain=DOMAIN,
            source=Source.HEVY_API.value,
            external_id=external_id,
            payload=raw,
        )
        created = await _upsert_workout(session, raw, raw_payload_id=raw_row.id)
        raw_row.processed_at = now_local()
        summary["created" if created else "updated"] += 1

    await session.flush()
    return summary


async def _get_workout_by_external(
    session: AsyncSession, external_id: str
) -> Optional[HevyWorkout]:
    result = await session.execute(
        select(HevyWorkout).where(HevyWorkout.external_id == external_id)
    )
    return result.scalars().first()


async def _upsert_workout(
    session: AsyncSession, raw: dict, *, raw_payload_id: int
) -> bool:
    """Create or refresh a workout + its exercise/set children. Returns True when a
    new workout row was created (False = updated in place)."""
    external_id = str(raw["id"])
    start = _parse_dt(raw.get("start_time"))
    end = _parse_dt(raw.get("end_time"))
    duration = None
    if start and end:
        duration = int((end - start).total_seconds())
    on_date = (start or end or now_local()).date()

    workout = await _get_workout_by_external(session, external_id)
    created = workout is None
    if workout is None:
        workout = HevyWorkout(external_id=external_id, domain=DOMAIN)
        session.add(workout)

    workout.date = on_date
    workout.source = Source.HEVY_API.value
    workout.raw_payload_id = raw_payload_id
    workout.title = raw.get("title")
    workout.description = raw.get("description")
    workout.start_time = start
    workout.end_time = end
    workout.duration_seconds = duration
    workout.hevy_updated_at = _parse_dt(raw.get("updated_at"))
    workout.program = _map_program(raw)
    await session.flush()

    # Rebuild children so a changed workout never leaves orphaned rows. Delete
    # sets then exercises explicitly (not relying on FK ON DELETE CASCADE, which
    # SQLite doesn't enforce by default) so the rebuild is DB-agnostic.
    if not created:
        ex_ids = (
            select(HevyExercise.id)
            .where(HevyExercise.workout_id == workout.id)
            .scalar_subquery()
        )
        await session.execute(HevySet.__table__.delete().where(HevySet.exercise_id.in_(ex_ids)))
        await session.execute(
            HevyExercise.__table__.delete().where(HevyExercise.workout_id == workout.id)
        )
        await session.flush()

    for ex_raw in raw.get("exercises") or []:
        exercise = HevyExercise(
            workout_id=workout.id,
            exercise_index=_int_or_none(ex_raw.get("index")) or 0,
            title=ex_raw.get("title") or "—",
            exercise_template_id=ex_raw.get("exercise_template_id"),
            notes=ex_raw.get("notes"),
            superset_id=_int_or_none(ex_raw.get("superset_id")),
        )
        session.add(exercise)
        await session.flush()
        for set_raw in ex_raw.get("sets") or []:
            session.add(
                HevySet(
                    exercise_id=exercise.id,
                    set_index=_int_or_none(set_raw.get("index")) or 0,
                    set_type=(set_raw.get("type") or "normal"),
                    weight_kg=_float_or_none(set_raw.get("weight_kg")),
                    reps=_int_or_none(set_raw.get("reps")),
                    rpe=_float_or_none(set_raw.get("rpe")),
                    distance_m=_float_or_none(set_raw.get("distance_meters")),
                    duration_seconds=_int_or_none(set_raw.get("duration_seconds")),
                )
            )
    await session.flush()
    return created


async def reparse_from_raw(session: AsyncSession, raw_row: RawPayload) -> None:
    """Re-derive a Hevy workout straight from its stored raw payload. Unlike a
    normal sync this skips re-upserting the raw row itself, so ``fetched_at``
    stays put — this is a re-derive, not a fresh pull. Used by
    :func:`reparse_pending` (the nightly sweep — raw_payload_service.
    sweep_pending_job)."""
    raw = raw_row.payload if isinstance(raw_row.payload, dict) else {}
    await _upsert_workout(session, raw, raw_payload_id=raw_row.id)


async def reparse_pending(
    session: AsyncSession,
    *,
    limit: int = raw_payload_service.REPARSE_BATCH,
    since_days: int = raw_payload_service.REPARSE_WINDOW_DAYS,
) -> int:
    """Sweep Hevy raw payloads still pending a normalized workout row. Does not
    commit."""
    has_normalized = (
        select(HevyWorkout.id).where(HevyWorkout.raw_payload_id == RawPayload.id).exists()
    )
    return await raw_payload_service.sweep_domain(
        session,
        domain=DOMAIN,
        reparse=reparse_from_raw,
        has_normalized=has_normalized,
        limit=limit,
        since_days=since_days,
    )


# ── Reads ─────────────────────────────────────────────────────────────────────
async def list_workouts(
    session: AsyncSession, *, limit: int = 50
) -> Sequence[HevyWorkout]:
    result = await session.execute(
        select(HevyWorkout)
        .options(selectinload(HevyWorkout.exercises).selectinload(HevyExercise.sets))
        .order_by(HevyWorkout.date.desc(), HevyWorkout.start_time.desc())
        .limit(limit)
    )
    return result.scalars().all()


def workout_summary(workout: HevyWorkout) -> dict:
    """One session the way a reader needs it: when, what, how much work.

    Tonnage counts working sets only — warm-ups add kilograms without adding
    training, which is the same line the progression engine already draws.
    """
    volume = 0.0
    working_sets = 0
    exercise_details = []
    for exercise in workout.exercises:
        exercise_volume = 0.0
        exercise_sets = 0
        weights: list[float] = []
        reps: list[int] = []
        rpes: list[float] = []
        for s in exercise.sets:
            if s.set_type not in _WORKING_SET_TYPES:
                continue
            working_sets += 1
            exercise_sets += 1
            if s.weight_kg and s.reps:
                set_volume = s.weight_kg * s.reps
                volume += set_volume
                exercise_volume += set_volume
            if s.weight_kg is not None:
                weights.append(s.weight_kg)
            if s.reps is not None:
                reps.append(s.reps)
            if s.rpe is not None:
                rpes.append(s.rpe)
        exercise_details.append(
            {
                "title": exercise.title,
                "working_sets": exercise_sets,
                "volume_kg": round(exercise_volume) or None,
                "top_weight_kg": max(weights) if weights else None,
                "total_reps": sum(reps) if reps else None,
                "mean_rpe": round(sum(rpes) / len(rpes), 1) if rpes else None,
            }
        )
    return {
        "date": workout.date.isoformat(),
        "title": workout.title,
        "program": workout.program,
        "start_time": workout.start_time.isoformat() if workout.start_time else None,
        "duration_min": (
            round(workout.duration_seconds / 60) if workout.duration_seconds else None
        ),
        "working_sets": working_sets,
        "volume_kg": round(volume) or None,
        "exercises": [e.title for e in workout.exercises],
        "exercise_details": exercise_details,
    }


async def workout_count(
    session: AsyncSession, *, since: Optional[date_type] = None
) -> int:
    stmt = select(func.count()).select_from(HevyWorkout)
    if since is not None:
        stmt = stmt.where(HevyWorkout.date >= since)
    result = await session.execute(stmt)
    return int(result.scalar() or 0)


async def latest_workout_date(session: AsyncSession) -> Optional[date_type]:
    result = await session.execute(select(func.max(HevyWorkout.date)))
    return result.scalar()


async def exercise_catalog(session: AsyncSession) -> list[dict]:
    """Distinct exercises seen across all workouts, with the most recent working
    weight + date — the picklist for the per-exercise history/progression view."""
    result = await session.execute(
        select(
            HevyExercise.exercise_template_id,
            HevyExercise.title,
            func.count(func.distinct(HevyExercise.workout_id)).label("sessions"),
            func.max(HevyWorkout.date).label("last_date"),
        )
        .join(HevyWorkout, HevyExercise.workout_id == HevyWorkout.id)
        .where(HevyExercise.exercise_template_id.is_not(None))
        .group_by(HevyExercise.exercise_template_id, HevyExercise.title)
        .order_by(func.max(HevyWorkout.date).desc())
    )
    return [
        {
            "exercise_template_id": tid,
            "title": title,
            "sessions": int(sessions),
            "last_date": last_date.isoformat() if last_date else None,
        }
        for (tid, title, sessions, last_date) in result.all()
    ]


ExerciseSessions = list[tuple[date_type, list[HevySet], Optional[str]]]


async def exercise_sessions_by_template(
    session: AsyncSession, exercise_template_ids: Optional[Sequence[str]] = None
) -> dict[str, ExerciseSessions]:
    """Per-session (date, working sets, notes) for each exercise, oldest first. A
    session = one workout containing the exercise. ``None`` reads every exercise.

    Two queries whatever the number of exercises or sessions: one for the
    exercise rows, one for all of their sets."""
    if exercise_template_ids is not None and not exercise_template_ids:
        return {}
    scope = (
        HevyExercise.exercise_template_id.is_not(None)
        if exercise_template_ids is None
        else HevyExercise.exercise_template_id.in_(list(exercise_template_ids))
    )
    rows = (
        await session.execute(
            select(HevyExercise.exercise_template_id, HevyWorkout.date, HevyExercise.id, HevyExercise.notes)
            .join(HevyExercise, HevyExercise.workout_id == HevyWorkout.id)
            .where(scope)
            .order_by(HevyWorkout.date, HevyExercise.id)
        )
    ).all()
    sets_by_exercise: dict[int, list[HevySet]] = {}
    set_rows = await session.execute(
        select(HevySet)
        .join(HevyExercise, HevySet.exercise_id == HevyExercise.id)
        .where(scope, HevySet.set_type.in_(_WORKING_SET_TYPES))
        .order_by(HevySet.exercise_id, HevySet.set_index)
    )
    for s in set_rows.scalars():
        sets_by_exercise.setdefault(s.exercise_id, []).append(s)

    out: dict[str, ExerciseSessions] = {}
    for tid, on_date, ex_id, notes in rows:
        sets = sets_by_exercise.get(ex_id)
        if sets:
            out.setdefault(tid, []).append((on_date, sets, notes))
    return out


async def _exercise_sessions(session: AsyncSession, exercise_template_id: str) -> ExerciseSessions:
    """``exercise_sessions_by_template`` for one exercise."""
    by_template = await exercise_sessions_by_template(session, [exercise_template_id])
    return by_template.get(exercise_template_id, [])


def _top_weight_session(on_date: date_type, sets: list[HevySet]) -> Optional[SessionResult]:
    """Reduce a session's working sets to the engine shape: the heaviest weight
    used and the reps of every set at that weight."""
    weighted = [s for s in sets if s.weight_kg is not None and s.reps is not None]
    if not weighted:
        return None
    top = max(s.weight_kg for s in weighted)
    reps = [s.reps for s in weighted if s.weight_kg == top]
    return SessionResult(on_date=on_date, weight_kg=top, reps=reps)


def series_from_sessions(sessions: ExerciseSessions) -> list[dict]:
    """Top working weight per session over time — the working-weight history chart."""
    series: list[dict] = []
    for on_date, sets, _notes in sessions:
        sr = _top_weight_session(on_date, sets)
        if sr is not None:
            series.append(
                {
                    "date": on_date.isoformat(),
                    "weight_kg": sr.weight_kg,
                    "top_reps": max(sr.reps) if sr.reps else None,
                    "sets": len(sr.reps),
                }
            )
    return series


def progression_from_sessions(
    sessions: ExerciseSessions, config: Optional[ProgressionConfig] = None
) -> Optional[ProgressionVerdict]:
    """The progression verdict (🟢/🟡/🔴) for one exercise from its history."""
    results = [
        sr
        for (on_date, sets, _notes) in sessions
        if (sr := _top_weight_session(on_date, sets)) is not None
    ]
    return evaluate_progression(results, config or ProgressionConfig())


def notes_from_sessions(sessions: ExerciseSessions) -> Optional[str]:
    """Most recent technique note recorded for an exercise (from Hevy)."""
    for _date, _sets, notes in reversed(sessions):
        if notes:
            return notes
    return None


async def working_weight_series(
    session: AsyncSession, exercise_template_id: str
) -> list[dict]:
    """Top working weight per session over time — the working-weight history chart."""
    return series_from_sessions(await _exercise_sessions(session, exercise_template_id))


async def progression_for_exercise(
    session: AsyncSession,
    exercise_template_id: str,
    config: Optional[ProgressionConfig] = None,
) -> Optional[ProgressionVerdict]:
    """The progression verdict (🟢/🟡/🔴) for one exercise from its history."""
    return progression_from_sessions(await _exercise_sessions(session, exercise_template_id), config)


async def latest_notes(session: AsyncSession, exercise_template_id: str) -> Optional[str]:
    """Most recent technique note recorded for an exercise (from Hevy)."""
    return notes_from_sessions(await _exercise_sessions(session, exercise_template_id))


# ── Scheduler job ─────────────────────────────────────────────────────────────
async def sync_job(session_factory, redis=None) -> Optional[dict]:
    """Every-6h Hevy sync (registered in vitals/scheduler/jobs.py). No-ops cleanly
    when Hevy isn't configured so the scheduler never logs spurious failures —
    returns None in that case, else the sync summary (the MCP ``sync_hevy`` tool
    reports it back to the model)."""
    from vitals.integrations.hevy_client import HevyClient

    client = HevyClient.from_config()
    if not client.is_configured:
        return None
    async with session_factory() as session:
        summary = await sync(session, client)
        await session.commit()
        if redis is not None:
            import time
            await redis.set("sync:last_success:hevy", str(int(time.time())))
        return summary
