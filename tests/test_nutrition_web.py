"""Web routes for the Nutrition module — day-nav (?date=) view, calorie ring
and macro bars in the Masthead interface (I2)."""
from __future__ import annotations

from datetime import timedelta


from vitals.services import nutrition_service
from vitals.utils.timeutils import today_local



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
    # empty_day isn't today, so the empty-state copy is the date-aware variant,
    # not "no meals today" — in either UI shell (the classic one has day-nav too).
    assert "В этот день приёмов нет." in r_empty.text


async def test_history_is_one_row_per_day_that_opens_the_day(auth_client, db_session):
    """The history used to render every meal ever logged as its own table row,
    each with its own delete form — ~300 rows and about a megabyte of HTML on a
    phone. It is one row per logged day of the last 30, and the row opens that
    day in the day view above, which is where a meal is edited or deleted."""
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

    r = await auth_client.get("/nutrition", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert f'href="/nutrition?date={day.isoformat()}"' in r.text
    assert ">550<" in r.text                      # the day's total, not its meals
    assert "Яичница" not in r.text                # another day's meals stay in that day
    assert f"?date={old.isoformat()}" not in r.text
    assert "Старый суп" not in r.text


async def test_nutrition_dashboard_invalid_date_rejected(auth_client):
    r = await auth_client.get("/nutrition?date=not-a-date", headers={"Accept": "text/html"})
    assert r.status_code == 422


async def test_nutrition_dashboard_masthead_day_nav_and_empty_state(auth_client, db_session):
    """Masthead layout: prev/next day links, the ring/bars card, and the
    date-aware empty state."""
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


async def test_intake_uses_the_shared_meter_not_a_bespoke_ring(auth_client, db_session):
    """One progress language. Calories used to be an SVG donut and protein an
    inline bar right beside it — the same fact drawn as two different kinds of
    thing. Both are now .v-meter, and the ring is gone from the codebase."""
    await nutrition_service.log_meal(
        db_session, on_date=today_local(), name="Овсянка",
        calories=400, protein_g=20, fat_g=10, carbs_g=50,
    )
    await db_session.commit()

    r = await auth_client.get("/nutrition", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert r.text.count('class="v-meter"') == 2      # calories + protein
    assert "v-meter-fill" in r.text
    assert "mh-ring" not in r.text
    assert "mh-protein-bar" not in r.text
    # A composition bar is not progress — it survives the unification.
    assert "mh-macro-bar" in r.text


def test_meter_is_the_only_progress_component_and_the_ring_is_deleted():
    from pathlib import Path

    static = Path(__file__).resolve().parents[1] / "web/static"
    tokens = (static / "vitals.css").read_text(encoding="utf-8")
    masthead = (static / "vitals-masthead.css").read_text(encoding="utf-8")

    assert ".v-meter {" in tokens and ".v-meter-fill {" in tokens
    for modifier in ("is-good", "is-warn", "is-bad"):
        assert f".v-meter-fill.{modifier}" in tokens
    assert "mh-ring" not in masthead
    assert "mh-protein" not in masthead
    # …and it is shared, not a nutrition-local class: at least two domain pages.
    templates = Path(__file__).resolve().parents[1] / "web/templates"
    users = {p.parent.name for p in templates.rglob("*.html") if "v-meter" in p.read_text(encoding="utf-8")}
    assert len(users) >= 2, users
