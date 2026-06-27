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


async def _exercise_sessions(
    session: AsyncSession, exercise_template_id: str
) -> list[tuple[date_type, list[HevySet], Optional[str]]]:
    """Per-session (date, working sets, latest notes) for one exercise, oldest
    first. A session = one workout containing the exercise."""
    result = await session.execute(
        select(HevyWorkout.date, HevyExercise.id, HevyExercise.notes)
        .join(HevyExercise, HevyExercise.workout_id == HevyWorkout.id)
        .where(HevyExercise.exercise_template_id == exercise_template_id)
        .order_by(HevyWorkout.date)
    )
    rows = result.all()
    sessions: list[tuple[date_type, list[HevySet], Optional[str]]] = []
    for on_date, ex_id, notes in rows:
        set_result = await session.execute(
            select(HevySet).where(HevySet.exercise_id == ex_id).order_by(HevySet.set_index)
        )
        sets = [s for s in set_result.scalars().all() if s.set_type in _WORKING_SET_TYPES]
        if sets:
            sessions.append((on_date, sets, notes))
    return sessions


def _top_weight_session(on_date: date_type, sets: list[HevySet]) -> Optional[SessionResult]:
    """Reduce a session's working sets to the engine shape: the heaviest weight
    used and the reps of every set at that weight."""
    weighted = [s for s in sets if s.weight_kg is not None and s.reps is not None]
    if not weighted:
        return None
    top = max(s.weight_kg for s in weighted)
    reps = [s.reps for s in weighted if s.weight_kg == top]
    return SessionResult(on_date=on_date, weight_kg=top, reps=reps)


async def working_weight_series(
    session: AsyncSession, exercise_template_id: str
) -> list[dict]:
    """Top working weight per session over time — the working-weight history chart."""
    sessions = await _exercise_sessions(session, exercise_template_id)
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


async def progression_for_exercise(
    session: AsyncSession,
    exercise_template_id: str,
    config: Optional[ProgressionConfig] = None,
) -> Optional[ProgressionVerdict]:
    """The progression verdict (🟢/🟡/🔴) for one exercise from its history."""
    sessions = await _exercise_sessions(session, exercise_template_id)
    results = [
        sr
        for (on_date, sets, _notes) in sessions
        if (sr := _top_weight_session(on_date, sets)) is not None
    ]
    return evaluate_progression(results, config or ProgressionConfig())


async def latest_notes(session: AsyncSession, exercise_template_id: str) -> Optional[str]:
    """Most recent technique note recorded for an exercise (from Hevy)."""
    sessions = await _exercise_sessions(session, exercise_template_id)
    for _date, _sets, notes in reversed(sessions):
        if notes:
            return notes
    return None


# ── Scheduler job ─────────────────────────────────────────────────────────────
async def sync_job(session_factory, redis=None) -> None:
    """Every-6h Hevy sync (registered in vitals/scheduler/jobs.py). No-ops cleanly
    when Hevy isn't configured so the scheduler never logs spurious failures."""
    from vitals.integrations.hevy_client import HevyClient

    client = HevyClient.from_config()
    if not client.is_configured:
        return
    async with session_factory() as session:
        await sync(session, client)
        await session.commit()
        if redis is not None:
            import time
            await redis.set("sync:last_success:hevy", str(int(time.time())))
