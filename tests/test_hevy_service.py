"""Hevy service tests — sync/normalise, idempotency, re-normalisation on change,
working-weight history, progression verdicts, and the raw-payload safety net."""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from vitals.models.hevy import HevyExercise, HevySet, HevyWorkout
from vitals.models.raw_payload import RawPayload
from vitals.services import hevy_service
from vitals.services.analytics.progression import ADVANCE, DELOAD

pytestmark = pytest.mark.asyncio


class FakeHevyClient:
    """Duck-typed stand-in for HevyClient — returns canned workouts, no network."""

    def __init__(self, workouts):
        self._workouts = workouts
        self.is_configured = True

    async def fetch_workouts(self, *, max_pages: int = 50):
        return list(self._workouts)


def _set(index, weight, reps, type_="normal"):
    return {
        "index": index,
        "type": type_,
        "weight_kg": weight,
        "reps": reps,
        "distance_meters": None,
        "duration_seconds": None,
        "rpe": None,
    }


def _workout(wid, *, start, updated, title="Day A — Push", sets=None, template="BENCH"):
    return {
        "id": wid,
        "title": title,
        "description": "morning session",
        "start_time": start,
        "end_time": start.replace("T10", "T11"),
        "updated_at": updated,
        "exercises": [
            {
                "index": 0,
                "title": "Bench Press (Barbell)",
                "exercise_template_id": template,
                "notes": "elbows tucked",
                "superset_id": None,
                "sets": sets or [_set(0, 80.0, 10), _set(1, 80.0, 9)],
            }
        ],
    }


async def test_sync_creates_workout_tree(db_session):
    client = FakeHevyClient(
        [_workout("w1", start="2026-06-10T10:00:00Z", updated="2026-06-10T11:00:00Z")]
    )
    summary = await hevy_service.sync(db_session, client)
    await db_session.commit()

    assert summary == {"fetched": 1, "created": 1, "updated": 0, "skipped": 0}

    workouts = await hevy_service.list_workouts(db_session)
    assert len(workouts) == 1
    w = workouts[0]
    assert w.external_id == "w1"
    assert w.program == "A"  # "Day A" → A
    assert w.title == "Bench Press (Barbell)" or w.title == "Day A — Push"
    assert len(w.exercises) == 1
    assert w.exercises[0].exercise_template_id == "BENCH"
    assert len(w.exercises[0].sets) == 2

    # Raw payload preserved + linked + marked processed.
    raw = (await db_session.execute(select(RawPayload))).scalars().all()
    assert len(raw) == 1
    assert raw[0].external_id == "w1"
    assert raw[0].processed_at is not None
    assert w.raw_payload_id == raw[0].id


async def test_sync_idempotent_skips_unchanged(db_session):
    wk = _workout("w1", start="2026-06-10T10:00:00Z", updated="2026-06-10T11:00:00Z")
    client = FakeHevyClient([wk])

    await hevy_service.sync(db_session, client)
    await db_session.commit()
    summary2 = await hevy_service.sync(db_session, client)
    await db_session.commit()

    assert summary2["skipped"] == 1
    assert summary2["created"] == 0
    assert await hevy_service.workout_count(db_session) == 1


async def test_sync_renormalises_changed_workout_without_orphans(db_session):
    wk = _workout(
        "w1", start="2026-06-10T10:00:00Z", updated="2026-06-10T11:00:00Z",
        sets=[_set(0, 80.0, 10), _set(1, 80.0, 10)],
    )
    await hevy_service.sync(db_session, FakeHevyClient([wk]), )
    await db_session.commit()

    # Same id, newer updated_at, different sets → re-normalised in place.
    wk2 = _workout(
        "w1", start="2026-06-10T10:00:00Z", updated="2026-06-10T12:30:00Z",
        sets=[_set(0, 82.5, 8)],
    )
    summary = await hevy_service.sync(db_session, FakeHevyClient([wk2]))
    await db_session.commit()

    assert summary["updated"] == 1
    assert await hevy_service.workout_count(db_session) == 1
    # No orphaned exercises/sets — exactly one exercise + one set remain.
    n_ex = (await db_session.execute(select(func.count()).select_from(HevyExercise))).scalar()
    n_set = (await db_session.execute(select(func.count()).select_from(HevySet))).scalar()
    assert n_ex == 1
    assert n_set == 1
    # One raw payload, refreshed in place (not duplicated).
    n_raw = (await db_session.execute(select(func.count()).select_from(RawPayload))).scalar()
    assert n_raw == 1


async def test_working_weight_series_and_catalog(db_session):
    client = FakeHevyClient(
        [
            _workout("w1", start="2026-06-01T10:00:00Z", updated="2026-06-01T11:00:00Z",
                     sets=[_set(0, 80.0, 10)]),
            _workout("w2", start="2026-06-08T10:00:00Z", updated="2026-06-08T11:00:00Z",
                     sets=[_set(0, 82.5, 8)]),
        ]
    )
    await hevy_service.sync(db_session, client)
    await db_session.commit()

    series = await hevy_service.working_weight_series(db_session, "BENCH")
    assert [p["weight_kg"] for p in series] == [80.0, 82.5]
    assert series[0]["date"] == "2026-06-01"

    catalog = await hevy_service.exercise_catalog(db_session)
    assert len(catalog) == 1
    assert catalog[0]["exercise_template_id"] == "BENCH"
    assert catalog[0]["sessions"] == 2


async def test_progression_advance_when_top_of_range_hit(db_session):
    from vitals.services.analytics.progression import ProgressionConfig

    client = FakeHevyClient(
        [
            _workout("w1", start="2026-06-08T10:00:00Z", updated="2026-06-08T11:00:00Z",
                     sets=[_set(0, 80.0, 12), _set(1, 80.0, 12), _set(2, 80.0, 12)]),
        ]
    )
    await hevy_service.sync(db_session, client)
    await db_session.commit()

    verdict = await hevy_service.progression_for_exercise(
        db_session, "BENCH", ProgressionConfig(rep_min=8, rep_max=12, increment_kg=2.5)
    )
    assert verdict is not None
    assert verdict.status == ADVANCE
    assert verdict.suggested_weight_kg == 82.5


async def test_workout_without_id_is_skipped(db_session):
    client = FakeHevyClient([{"id": "", "exercises": []}])
    summary = await hevy_service.sync(db_session, client)
    await db_session.commit()
    assert summary["skipped"] == 1
    assert await hevy_service.workout_count(db_session) == 0
