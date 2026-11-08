"""Tests for the read-only external JSON API (web/routers/external_api.py).

Covers the Bearer-token guard (off / wrong / right) and the /external/summary
shape, including the graceful empty-database case.
"""
from datetime import datetime, time, timedelta

import pytest

from vitals.enums import Domain, MilestoneStatus
from vitals.models.garmin import GarminDaily
from vitals.models.hevy import HevyExercise, HevySet, HevyWorkout
from vitals.models.milestones import Milestone
from vitals.models.nutrition import MealLog
from vitals.models.skincare import SkincareCheck, SkincareProduct
from vitals.models.weight import WeightLog
from vitals.utils.timeutils import today_local

TOKEN = "external-secret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def _token(monkeypatch):
    monkeypatch.setenv("VITALS_EXTERNAL_API_TOKEN", TOKEN)


async def _seed(db_session):
    today = today_local()
    # 10 consecutive daily weights, gently trending down (so the MA7 sparkline has
    # points and the slope is a real number).
    for i in range(10):
        day = today - timedelta(days=9 - i)
        db_session.add(WeightLog(date=day, domain=Domain.WEIGHT.value, weight_kg=90.0 - i * 0.3, superseded=False))
    # An active weight goal below current weight → chart_series returns a projection.
    db_session.add(
        Milestone(
            domain=Domain.WEIGHT.value,
            name="Reach 85",
            target_value=85.0,
            target_unit="кг",
            deadline=today + timedelta(days=120),
            status=MilestoneStatus.ACTIVE.value,
        )
    )
    # Today's meals (macros card).
    db_session.add(MealLog(date=today, domain=Domain.NUTRITION.value, name="Oats", calories=400, protein_g=20))
    db_session.add(MealLog(date=today, domain=Domain.NUTRITION.value, name="Chicken", calories=600, protein_g=50))
    # A Garmin daily with recovery and activity signals.
    db_session.add(
        GarminDaily(
            date=today,
            domain=Domain.GARMIN.value,
            sleep_score=82,
            sleep_seconds=28800,
            deep_sleep_seconds=5400,
            rem_sleep_seconds=7200,
            light_sleep_seconds=14400,
            awake_seconds=1800,
            awake_count=2,
            body_battery_high=78,
            training_readiness=65,
            resting_hr=52,
            hrv_avg=68.0,
            hrv_status="balanced",
            avg_stress=25,
            max_stress=65,
            avg_sleep_stress=12,
            steps=8500,
            active_calories=420,
            intensity_minutes_moderate=30,
            intensity_minutes_vigorous=15,
        )
    )
    # Hevy workout with exercise and set
    workout = HevyWorkout(
        date=today,
        domain=Domain.WORKOUTS.value,
        external_id="hevy-ext-1",
        title="Upper Body A",
        start_time=datetime.combine(today, time(18, 0)),
        end_time=datetime.combine(today, time(18, 55)),
        duration_seconds=3300,
    )
    db_session.add(workout)
    await db_session.flush()

    ex = HevyExercise(
        workout_id=workout.id,
        exercise_index=0,
        title="Bench Press (Barbell)",
    )
    db_session.add(ex)
    await db_session.flush()

    db_session.add(
        HevySet(
            exercise_id=ex.id,
            set_index=0,
            set_type="normal",
            weight_kg=80.0,
            reps=8,
        )
    )

    # Skincare products
    prod_morning = SkincareProduct(
        name="Cleanser",
        type="Очищение",
        active=True,
        default_time="morning",
        schedule_days=[0, 1, 2, 3, 4, 5, 6],
    )
    prod_evening = SkincareProduct(
        name="Retinol 0.2%",
        type="Ретиноид",
        active=True,
        default_time="evening",
        schedule_days=[0, 1, 2, 3, 4, 5, 6],
    )
    db_session.add(prod_morning)
    db_session.add(prod_evening)
    await db_session.flush()

    # Check for evening product done
    db_session.add(
        SkincareCheck(
            product_id=prod_evening.id,
            product_name=prod_evening.name,
            date=today,
            domain=Domain.SKINCARE.value,
            slot="evening",
            done_at=datetime.combine(today, time(22, 0)),
        )
    )

    await db_session.commit()


@pytest.mark.asyncio
async def test_summary_disabled_without_server_token(client, monkeypatch):
    monkeypatch.delenv("VITALS_EXTERNAL_API_TOKEN", raising=False)
    r = await client.get("/external/summary", headers=AUTH)
    assert r.status_code == 503
    assert r.json()["detail"] == "external_api_disabled"


@pytest.mark.asyncio
async def test_summary_rejects_bad_token(client, _token):
    assert (await client.get("/external/summary")).status_code == 401
    assert (await client.get("/external/summary", headers={"Authorization": "Bearer wrong"})).status_code == 401
    assert (await client.get("/external/summary", headers={"Authorization": TOKEN})).status_code == 401  # no scheme


@pytest.mark.asyncio
async def test_summary_returns_all_cards(client, db_session, _token):
    await _seed(db_session)
    r = await client.get("/external/summary", headers=AUTH)
    assert r.status_code == 200
    body = r.json()

    w = body["weight"]
    assert w["latest_kg"] == pytest.approx(90.0 - 9 * 0.3)
    assert w["latest_date"] == today_local().isoformat()
    assert len(w["sparkline"]) > 0
    assert isinstance(w["slope_kg_per_week"], (int, float))
    assert w["goal"]["target_kg"] == 85.0
    assert "eta_date" in w["goal"]
    assert w["goal"]["days_left"] == 120

    n = body["nutrition_today"]
    assert n["totals"]["calories"] == 1000
    assert n["totals"]["protein_g"] == 70
    assert n["meal_count"] == 2
    assert "goals" in n and "on_track" in n

    rec = body["recovery"]
    assert rec["sleep_score"] == 82
    assert rec["sleep_seconds"] == 28800
    assert rec["deep_sleep_seconds"] == 5400
    assert rec["rem_sleep_seconds"] == 7200
    assert rec["light_sleep_seconds"] == 14400
    assert rec["awake_seconds"] == 1800
    assert rec["awake_count"] == 2
    assert rec["body_battery_high"] == 78
    assert rec["training_readiness"] == 65
    assert rec["resting_hr"] == 52
    assert rec["hrv_avg"] == 68.0
    assert rec["hrv_status"] == "balanced"
    assert rec["avg_stress"] == 25
    assert rec["max_stress"] == 65
    assert rec["avg_sleep_stress"] == 12

    act_today = body["activity_today"]
    assert act_today["steps"] == 8500
    assert act_today["active_calories"] == 420
    assert act_today["intensity_minutes"] == 45

    workout = body["latest_workout"]
    assert workout is not None
    assert workout["title"] == "Upper Body A"
    assert workout["date"] == today_local().isoformat()
    assert workout["duration_minutes"] == 55
    assert workout["volume_kg"] == 640.0
    assert len(workout["exercises"]) == 1
    assert workout["exercises"][0]["name"] == "Bench Press (Barbell)"
    assert workout["exercises"][0]["max_weight_kg"] == 80.0
    assert workout["exercises"][0]["reps"] == 8

    skincare = body["skincare_today"]
    assert len(skincare["morning"]) == 1
    assert skincare["morning"][0]["name"] == "Cleanser"
    assert skincare["morning"][0]["type"] == "Очищение"
    assert skincare["morning"][0]["done"] is False
    assert len(skincare["evening"]) == 1
    assert skincare["evening"][0]["name"] == "Retinol 0.2%"
    assert skincare["evening"][0]["type"] == "Ретиноид"
    assert skincare["evening"][0]["done"] is True

    act = body["activity"]
    assert today_local().isoformat() in act["nutrition_days"]
    assert today_local().isoformat() in act["recovery_days"]
    assert len(act["weight_days"]) == 10


@pytest.mark.asyncio
async def test_summary_empty_db_is_graceful(client, _token):
    r = await client.get("/external/summary", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["weight"]["latest_kg"] is None
    assert body["weight"]["goal"] is None
    assert body["weight"]["sparkline"] == []
    assert body["recovery"] is None
    assert body["activity_today"] is None
    assert body["latest_workout"] is None
    assert body["skincare_today"]["morning"] == []
    assert body["skincare_today"]["evening"] == []
    assert body["nutrition_today"]["meal_count"] == 0
    assert body["activity"]["weight_days"] == []
