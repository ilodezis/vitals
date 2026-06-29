"""Nutrition service tests — meal logging, daily summary, period summary."""
from __future__ import annotations

from datetime import date, time

import pytest

from vitals.services import nutrition_service

pytestmark = pytest.mark.asyncio


def _make_cfg(**overrides):
    from vitals.config import Config
    defaults = dict(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://localhost:6379/0",
        nutrition_protein_target_g=150.0,
        nutrition_calories_min=1300,
        nutrition_calories_max=1700,
    )
    defaults.update(overrides)
    return Config(**defaults)


async def test_log_meal_creates_row(db_session):
    m = await nutrition_service.log_meal(
        db_session,
        on_date=date(2026, 6, 1),
        name="2 eggs, toast",
        eaten_at=time(8, 30),
        calories=350.0,
        protein_g=20.0,
        fat_g=12.0,
        carbs_g=30.0,
    )
    await db_session.commit()
    assert m.id is not None
    assert m.name == "2 eggs, toast"
    assert m.calories == 350.0
    assert m.domain == "nutrition"
    assert m.source == "manual"


async def test_multiple_meals_same_day(db_session):
    d = date(2026, 6, 2)
    await nutrition_service.log_meal(db_session, on_date=d, name="breakfast", calories=300)
    await nutrition_service.log_meal(db_session, on_date=d, name="lunch", calories=500)
    await nutrition_service.log_meal(db_session, on_date=d, name="dinner", calories=600)
    await db_session.commit()

    meals = await nutrition_service.list_meals_for_date(db_session, d)
    assert len(meals) == 3


async def test_update_meal(db_session):
    m = await nutrition_service.log_meal(
        db_session, on_date=date(2026, 6, 3), name="original", calories=100
    )
    await db_session.commit()

    updated = await nutrition_service.update_meal(
        db_session, m.id, on_date=date(2026, 6, 3), name="updated", calories=200
    )
    await db_session.commit()
    assert updated is not None
    assert updated.name == "updated"
    assert updated.calories == 200


async def test_delete_meal(db_session):
    m = await nutrition_service.log_meal(
        db_session, on_date=date(2026, 6, 4), name="to delete"
    )
    await db_session.commit()

    result = await nutrition_service.delete_meal(db_session, m.id)
    await db_session.commit()
    assert result is True

    meals = await nutrition_service.list_meals_for_date(db_session, date(2026, 6, 4))
    assert len(meals) == 0


async def test_delete_nonexistent_returns_false(db_session):
    result = await nutrition_service.delete_meal(db_session, 9999)
    assert result is False


async def test_daily_summary_totals_and_on_track(db_session):
    d = date(2026, 6, 5)
    await nutrition_service.log_meal(db_session, on_date=d, name="meal1", calories=600, protein_g=50)
    await nutrition_service.log_meal(db_session, on_date=d, name="meal2", calories=700, protein_g=60)
    await nutrition_service.log_meal(db_session, on_date=d, name="meal3", calories=300, protein_g=50)
    await db_session.commit()

    cfg = _make_cfg()
    summary = await nutrition_service.daily_summary(db_session, d, cfg)

    assert summary["meal_count"] == 3
    assert summary["totals"]["calories"] == 1600
    assert summary["totals"]["protein_g"] == 160
    assert summary["on_track"]["calories"] is True   # 1300 <= 1600 <= 1700
    assert summary["on_track"]["protein"] is True    # 160 >= 150


async def test_daily_summary_under_target(db_session):
    d = date(2026, 6, 6)
    await nutrition_service.log_meal(db_session, on_date=d, name="snack", calories=500, protein_g=20)
    await db_session.commit()

    cfg = _make_cfg()
    summary = await nutrition_service.daily_summary(db_session, d, cfg)

    assert summary["on_track"]["calories"] is False   # 500 < 1300
    assert summary["on_track"]["protein"] is False    # 20 < 150


async def test_daily_summary_over_target(db_session):
    d = date(2026, 6, 7)
    await nutrition_service.log_meal(db_session, on_date=d, name="feast", calories=2000, protein_g=200)
    await db_session.commit()

    cfg = _make_cfg()
    summary = await nutrition_service.daily_summary(db_session, d, cfg)

    assert summary["on_track"]["calories"] is False   # 2000 > 1700
    assert summary["on_track"]["protein"] is True     # 200 >= 150


async def test_nutrition_summary_period(db_session):
    d1, d2 = date(2026, 6, 10), date(2026, 6, 11)
    await nutrition_service.log_meal(db_session, on_date=d1, name="day1-meal", calories=1500, protein_g=100)
    await nutrition_service.log_meal(db_session, on_date=d2, name="day2-meal", calories=1400, protein_g=120)
    await db_session.commit()

    cfg = _make_cfg()
    summary = await nutrition_service.nutrition_summary(db_session, d1, d2, cfg)

    assert summary["meal_count"] == 2
    assert summary["days_with_logs"] == 2
    assert summary["totals"]["calories"] == 2900
    assert summary["totals"]["protein_g"] == 220
    assert len(summary["per_day"]) == 2
    assert summary["per_day"][0]["date"] == "2026-06-10"
    assert summary["per_day"][0]["calories"] == 1500


async def test_goals_from_config(db_session):
    cfg = _make_cfg(nutrition_protein_target_g=180.0, nutrition_calories_min=1500, nutrition_calories_max=2000)
    goals = nutrition_service.get_goals(cfg)

    assert goals["protein_target_g"] == 180.0
    assert goals["calories_min"] == 1500
    assert goals["calories_max"] == 2000


async def test_eaten_at_defaults_to_now(db_session):
    m = await nutrition_service.log_meal(
        db_session, on_date=date(2026, 6, 8), name="no time given"
    )
    await db_session.commit()
    assert m.eaten_at is not None


async def test_list_meals_date_range(db_session):
    await nutrition_service.log_meal(db_session, on_date=date(2026, 6, 1), name="a")
    await nutrition_service.log_meal(db_session, on_date=date(2026, 6, 5), name="b")
    await nutrition_service.log_meal(db_session, on_date=date(2026, 6, 10), name="c")
    await db_session.commit()

    meals = await nutrition_service.list_meals(db_session, start=date(2026, 6, 3), end=date(2026, 6, 7))
    assert len(meals) == 1
    assert meals[0].name == "b"
