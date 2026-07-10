"""Tests for the read-only external JSON API (web/routers/external_api.py).

Covers the Bearer-token guard (off / wrong / right) and the /external/summary
shape, including the graceful empty-database case.
"""
from datetime import timedelta

import pytest

from vitals.enums import Domain, MilestoneStatus
from vitals.models.garmin import GarminDaily
from vitals.models.milestones import Milestone
from vitals.models.nutrition import MealLog
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
    # A Garmin daily with recovery signals.
    db_session.add(
        GarminDaily(date=today, domain=Domain.GARMIN.value, sleep_score=82, body_battery_high=78, training_readiness=65, resting_hr=52, hrv_avg=68.0)
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
    assert rec["body_battery_high"] == 78
    assert rec["training_readiness"] == 65

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
    assert body["nutrition_today"]["meal_count"] == 0
    assert body["activity"]["weight_days"] == []
