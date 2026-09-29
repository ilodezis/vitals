"""Tests for ``/api/v1/workouts`` — Hevy workouts dashboard, exercise catalog,
and synchronization.
"""
from __future__ import annotations

import datetime as dt
from unittest.mock import AsyncMock, patch

import pytest

from vitals.enums import Domain, Source
from vitals.models.hevy import DOMAIN as HEVY_DOMAIN, HevyExercise, HevySet, HevyWorkout
from vitals.services import modules_service
from vitals.utils.timeutils import today_local

WORKOUTS = "/api/v1/workouts"


async def _set_module(db_session, redis, key: str, enabled: bool):
    state = await modules_service.set_module_enabled(db_session, key=key, enabled=enabled)
    await db_session.commit()
    await modules_service.prime_cache(redis, state)


async def test_workouts_guarded(client):
    r = await client.get(WORKOUTS)
    assert r.status_code == 401
    assert r.json() == {"error": "unauthenticated"}

    r_sync = await client.post(f"{WORKOUTS}/sync")
    assert r_sync.status_code == 401
    assert r_sync.json() == {"error": "unauthenticated"}


async def test_workouts_disabled_module_gives_404(auth_client, db_session, redis):
    await _set_module(db_session, redis, "hevy", False)
    r = await auth_client.get(WORKOUTS)
    assert r.status_code == 404
    assert r.json() == {"error": "module_disabled"}


async def test_workouts_empty_view(auth_client, db_session, redis):
    await _set_module(db_session, redis, "hevy", True)
    r = await auth_client.get(WORKOUTS)
    assert r.status_code == 200
    data = r.json()
    assert set(data) == {
        "workout_count", "last_workout_date", "exercise_count",
        "is_configured", "last_sync", "workouts", "catalog",
    }  # fmt: skip
    assert data["workout_count"] == 0
    assert data["workouts"] == []
    assert data["catalog"] == []


async def test_workouts_with_exercises_and_sets(auth_client, db_session, redis):
    await _set_module(db_session, redis, "hevy", True)
    today = today_local()

    workout = HevyWorkout(
        date=today,
        domain=HEVY_DOMAIN,
        source=Source.HEVY_API.value,
        external_id="hevy_12345",
        title="Push Day A",
        program="A",
        duration_seconds=3600,
        start_time=dt.datetime.combine(today, dt.time(18, 0)),
        end_time=dt.datetime.combine(today, dt.time(19, 0)),
    )
    exercise = HevyExercise(
        workout=workout,
        exercise_index=0,
        title="Bench Press",
        exercise_template_id="template_bench_press",
        notes="Felt good, solid form",
    )
    s1 = HevySet(
        exercise=exercise,
        set_index=0,
        set_type="warmup",
        weight_kg=60.0,
        reps=10,
        rpe=6.0,
    )
    s2 = HevySet(
        exercise=exercise,
        set_index=1,
        set_type="normal",
        weight_kg=90.0,
        reps=8,
        rpe=8.5,
    )
    db_session.add(workout)
    await db_session.commit()

    r = await auth_client.get(WORKOUTS)
    assert r.status_code == 200
    data = r.json()
    assert data["workout_count"] == 1
    assert data["last_workout_date"] == today.isoformat()
    assert len(data["workouts"]) == 1

    w = data["workouts"][0]
    assert w["id"] == "hevy_12345"
    assert w["title"] == "Push Day A"
    assert w["program"] == "A"
    assert w["duration_min"] == 60
    assert len(w["exercises"]) == 1

    ex = w["exercises"][0]
    assert ex["title"] == "Bench Press"
    assert ex["exercise_template_id"] == "template_bench_press"
    assert len(ex["sets"]) == 2
    assert ex["sets"][0]["set_type"] == "warmup"
    assert ex["sets"][1]["weight_kg"] == 90.0

    # Catalog
    assert len(data["catalog"]) == 1
    cat = data["catalog"][0]
    assert cat["title"] == "Bench Press"
    assert cat["sessions_count"] == 1
    assert len(cat["working_weight_series"]) == 1
    assert cat["working_weight_series"][0]["weight_kg"] == 90.0


async def test_hevy_sync_unconfigured_and_success(auth_client, db_session, redis):
    await _set_module(db_session, redis, "hevy", True)

    with patch("web.api.hevy.HevyClient.from_config") as mock_client:
        inst = AsyncMock()
        inst.is_configured = False
        mock_client.return_value = inst

        r = await auth_client.post(f"{WORKOUTS}/sync")
        assert r.status_code == 200
        assert r.json() == {"ok": False, "synced": 0, "error": "not_configured"}

    with patch("web.api.hevy.HevyClient.from_config") as mock_client, \
         patch("web.api.hevy.hevy_service.sync", new_callable=AsyncMock) as mock_sync:
        inst = AsyncMock()
        inst.is_configured = True
        mock_client.return_value = inst
        mock_sync.return_value = {"created": 2, "updated": 1}

        r = await auth_client.post(f"{WORKOUTS}/sync")
        assert r.status_code == 200
        assert r.json() == {"ok": True, "synced": 3, "error": None}
