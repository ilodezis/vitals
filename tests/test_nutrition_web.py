"""Web routes for the Nutrition module — day-nav (?date=) view, calorie ring
and macro bars in the Masthead interface (I2)."""
from __future__ import annotations

from datetime import timedelta

import pytest

from vitals.services import nutrition_service
from vitals.utils.timeutils import today_local

pytestmark = pytest.mark.asyncio


async def test_nutrition_dashboard_defaults_to_today(auth_client):
    r = await auth_client.get("/nutrition", headers={"Accept": "text/html"})
    assert r.status_code == 200


async def test_nutrition_dashboard_by_date_shows_that_days_meals_only(auth_client, db_session):
    day_with_food = today_local() - timedelta(days=30)
    empty_day = today_local() - timedelta(days=31)
    await nutrition_service.log_meal(
        db_session, on_date=day_with_food, name="Овсянка с бананом",
        calories=420, protein_g=15, fat_g=8, carbs_g=70,
    )
    await db_session.commit()

    r = await auth_client.get(f"/nutrition?date={day_with_food.isoformat()}", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert "Овсянка с бананом" in r.text
    assert "420" in r.text

    r_empty = await auth_client.get(f"/nutrition?date={empty_day.isoformat()}", headers={"Accept": "text/html"})
    assert r_empty.status_code == 200
    # The day-specific table is empty (the meal only shows up in the unfiltered
    # "full history" list further down the page, which stays unaffected by ?date=).
    assert "Сегодня приёмов пока нет." in r_empty.text


async def test_nutrition_dashboard_invalid_date_rejected(auth_client):
    r = await auth_client.get("/nutrition?date=not-a-date", headers={"Accept": "text/html"})
    assert r.status_code == 422


async def test_nutrition_dashboard_masthead_day_nav_and_empty_state(auth_client, db_session):
    """Masthead-only surface: prev/next day links, the ring/bars card, and the
    date-aware empty state (distinct from classic's always-"today" copy)."""
    await auth_client.post("/settings/ui-version", data={"ui_version": "masthead"})

    day_with_food = today_local() - timedelta(days=30)
    prev_day = day_with_food - timedelta(days=1)
    next_day = day_with_food + timedelta(days=1)
    empty_day = today_local() - timedelta(days=31)

    await nutrition_service.log_meal(
        db_session, on_date=day_with_food, name="Гречка с курицей",
        calories=520, protein_g=40, fat_g=12, carbs_g=55,
    )
    await db_session.commit()

    r = await auth_client.get(f"/nutrition?date={day_with_food.isoformat()}", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert "Гречка с курицей" in r.text
    assert f'/nutrition?date={prev_day.isoformat()}"' in r.text
    assert f'/nutrition?date={next_day.isoformat()}"' in r.text
    assert ">Сегодня<" in r.text  # jump-to-today link, only rendered when viewing a non-today date

    r_empty = await auth_client.get(f"/nutrition?date={empty_day.isoformat()}", headers={"Accept": "text/html"})
    assert r_empty.status_code == 200
    assert "В этот день приёмов нет." in r_empty.text
