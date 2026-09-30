"""Nutrition day view over the JSON API — ``?date=`` selects one day's meals,
day-nav dates, the 30-day per-day history, and date validation."""
from __future__ import annotations

from datetime import timedelta

from vitals.services import modules_service, nutrition_service
from vitals.utils.timeutils import today_local

NUTRITION = "/api/v1/nutrition"


async def _enable_nutrition(db_session, redis):
    state = await modules_service.set_module_enabled(db_session, key="nutrition", enabled=True)
    await db_session.commit()
    await modules_service.prime_cache(redis, state)


async def test_nutrition_defaults_to_today(auth_client, db_session, redis):
    await _enable_nutrition(db_session, redis)
    data = (await auth_client.get(NUTRITION)).json()
    assert data["date"] == today_local().isoformat()
    assert data["is_today"] is True


async def test_nutrition_by_date_shows_that_days_meals_only(auth_client, db_session, redis):
    await _enable_nutrition(db_session, redis)
    day_with_food = today_local() - timedelta(days=30)
    empty_day = today_local() - timedelta(days=31)
    await nutrition_service.log_meal(
        db_session, on_date=day_with_food, name="Овсянка с бананом",
        calories=420, protein_g=15, fat_g=8, carbs_g=70,
    )
    await db_session.commit()

    r = await auth_client.get(f"{NUTRITION}?date={day_with_food.isoformat()}")
    assert r.status_code == 200
    data = r.json()
    assert [m["name"] for m in data["meals"]] == ["Овсянка с бананом"]
    assert data["totals"]["calories"] == 420
    assert data["is_today"] is False
    assert data["prev_date"] == (day_with_food - timedelta(days=1)).isoformat()
    assert data["next_date"] == (day_with_food + timedelta(days=1)).isoformat()

    empty = (await auth_client.get(f"{NUTRITION}?date={empty_day.isoformat()}")).json()
    assert empty["meals"] == []
    assert empty["totals"]["calories"] == 0


async def test_history_is_one_entry_per_day_of_the_last_30(auth_client, db_session, redis):
    """The history is one row per logged day of the last 30 carrying the day's
    total, not one row per meal ever logged."""
    await _enable_nutrition(db_session, redis)
    day = today_local() - timedelta(days=3)
    old = today_local() - timedelta(days=45)
    for name, kcal in (("Яичница", 300), ("Творог", 250)):
        await nutrition_service.log_meal(
            db_session, on_date=day, name=name, calories=kcal, protein_g=20, fat_g=5, carbs_g=5,
        )
    await nutrition_service.log_meal(
        db_session, on_date=old, name="Старый суп", calories=250, protein_g=10, fat_g=5, carbs_g=20,
    )
    await db_session.commit()

    data = (await auth_client.get(NUTRITION)).json()
    logged = [d for d in data["recent_days"] if d["meal_count"]]
    assert len(logged) == 1
    assert logged[0]["date"] == day.isoformat()
    assert logged[0]["calories"] == 550
    assert logged[0]["meal_count"] == 2
    assert all(d["date"] != old.isoformat() for d in data["recent_days"])
    assert data["meals"] == []  # another day's meals stay in that day


async def test_nutrition_invalid_date_rejected(auth_client, db_session, redis):
    await _enable_nutrition(db_session, redis)
    r = await auth_client.get(f"{NUTRITION}?date=not-a-date")
    assert r.status_code == 422
