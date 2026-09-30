"""The August 2026 nav handoff: the /more screen and the rail's status card.

Both surfaces read the same two services (modules_service for what to list,
nav_status_service for today's numbers), so these cover the pieces the static
template contracts in test_ui_static_contracts.py can't see.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from vitals.enums import Source
from vitals.i18n import current_lang
from vitals.models.garmin import DOMAIN as GARMIN_DOMAIN, GarminDaily
from vitals.models.weight import DOMAIN as WEIGHT_DOMAIN, WeightLog
from vitals.services import nav_status_service
from vitals.utils.timeutils import today_local


# ── /more ────────────────────────────────────────────────────────────────────

async def test_more_screen_lists_every_visible_section(auth_client):
    """Not only the rubrics without a bottom-bar column. The bar's three slots
    reach their siblings through the masthead chips, which is a fine way to
    switch and a terrible way to find — half the app looked missing on a phone.
    """
    from vitals.services.modules_service import nav_modules

    response = await auth_client.get("/more", headers={"Accept": "text/html"})
    assert response.status_code == 200
    enabled = {"labs": True, "weight": True, "garmin": True, "reports": True, "charts": True}
    for spec in nav_modules(enabled):
        assert f'href="{spec.route}"' in response.text, spec.key
    assert 'href="/settings"' in response.text
    # It is a page, not an overlay — nothing to close, and Back leaves it.
    assert "mobileMenuOpen" not in response.text


async def test_journal_pages_live_on_the_more_screen(auth_client):
    """Timeline, reports and charts are views over every domain, not Health
    sections: they form their own rubric, which never gets a bottom-bar column,
    so on a phone they are reached through /more and light up its cell."""
    from vitals.services.modules_service import bottom_slots, more_rubrics

    enabled = {"timeline": True}
    assert "journal" not in {s.key for s in bottom_slots(enabled)}
    assert "journal" in more_rubrics(enabled)

    more = await auth_client.get("/more", headers={"Accept": "text/html"})
    assert "Журнал" in more.text

    # /share is an account row on the same screen, so it counts as "inside" too.
    for path in ("/reports", "/charts", "/share"):
        page = await auth_client.get(path, headers={"Accept": "text/html"})
        assert page.status_code == 200, path
        assert '<a href="/more" class="v-bnav-link is-active"' in page.text, path


async def test_more_screen_has_one_account_row_not_a_second_settings_link(auth_client):
    """The "Modules" row pointed at the same page as "Settings"; its count moved
    onto the Settings row instead of standing as a second destination."""
    response = await auth_client.get("/more", headers={"Accept": "text/html"})
    # Scoped to the screen itself — the rail (hidden on a phone, still rendered)
    # carries its own Settings link.
    screen = response.text.split('class="v-page v-page-more')[1].split("</form>")[0]
    assert screen.count('href="/settings"') == 1


async def test_more_screen_reports_how_many_modules_are_on(auth_client):
    from vitals.services.modules_service import MODULE_REGISTRY

    response = await auth_client.get("/more", headers={"Accept": "text/html"})
    assert f"из {len(MODULE_REGISTRY)}" in response.text


# ── The rail's status card ───────────────────────────────────────────────────

async def test_status_card_reports_todays_weight_and_the_weeks_direction(db_session):
    """The card exists to say where he is, not how the plumbing is doing — the
    first version reported "labs · 99 days ago" every single day."""
    for days_ago, kg in ((9, 87.0), (0, 86.1)):
        db_session.add(
            WeightLog(
                date=today_local() - timedelta(days=days_ago),
                domain=WEIGHT_DOMAIN,
                source=Source.MANUAL.value,
                weight_kg=kg,
            )
        )
    await db_session.flush()

    rows = {r.key: r for r in await nav_status_service.rail_stats(db_session)}
    assert rows["weight"].value.startswith("86.1")
    assert rows["weight"].sub == "−0.7"
    assert rows["weight"].tone == "good"


async def test_a_source_that_went_quiet_says_so_instead_of_a_number(db_session):
    db_session.add(
        GarminDaily(
            date=today_local() - timedelta(days=6),
            domain=GARMIN_DOMAIN,
            source=Source.GARMIN_API.value,
            sleep_seconds=7 * 3600,
        )
    )
    await db_session.flush()

    rows = {r.key: r for r in await nav_status_service.rail_stats(db_session)}
    assert rows["recovery"].tone == "warn"
    assert "6" in rows["recovery"].value


async def test_last_nights_sleep_reads_as_hours_and_minutes(db_session):
    db_session.add(
        GarminDaily(
            date=today_local(),
            domain=GARMIN_DOMAIN,
            source=Source.GARMIN_API.value,
            sleep_seconds=7 * 3600 + 20 * 60,
            training_readiness=62,
        )
    )
    await db_session.flush()

    rows = {r.key: r for r in await nav_status_service.rail_stats(db_session)}
    assert rows["recovery"].value == "7:20"
    assert "62" in rows["recovery"].sub


async def test_a_domain_with_nothing_logged_yet_gets_no_row(db_session):
    assert await nav_status_service.rail_stats(db_session) == []


async def test_a_disabled_module_gets_no_row(db_session):
    db_session.add(
        GarminDaily(
            date=today_local(),
            domain=GARMIN_DOMAIN,
            source=Source.GARMIN_API.value,
            sleep_seconds=7 * 3600,
        )
    )
    await db_session.flush()

    enabled = {"garmin": False, "weight": True}
    assert await nav_status_service.rail_stats(db_session, enabled) == []


async def test_status_rows_never_raise_on_a_broken_session():
    """The rail is chrome: an unreadable domain must lose its row, not 500 the
    page it is drawn on."""

    class Boom:
        async def execute(self, *a, **kw):
            raise RuntimeError("db is down")

    assert await nav_status_service.rail_stats(Boom()) == []


# ── The card has to survive a boosted navigation ─────────────────────────────

async def test_status_card_survives_a_boosted_navigation(auth_client, db_session):
    """The regression: hx-boost sends no Accept header at all, so a guard that
    required "text/html" skipped the reads on exactly the requests that
    re-render the whole rail — the card vanished on every click and came back on
    every reload."""
    db_session.add(
        GarminDaily(
            date=today_local(),
            domain=GARMIN_DOMAIN,
            source=Source.GARMIN_API.value,
            sleep_seconds=7 * 3600,
        )
    )
    await db_session.commit()

    full = await auth_client.get("/weight", headers={"Accept": "text/html"})
    # What hx-boost actually puts on the wire: HX-Request, and XHR's default
    # Accept — which htmx never touches, so it is either absent or "*/*".
    absent = await auth_client.get("/weight", headers={"HX-Request": "true", "Accept": ""})
    wildcard = await auth_client.get("/weight", headers={"HX-Request": "true", "Accept": "*/*"})
    for name, response in (("full", full), ("absent", absent), ("wildcard", wildcard)):
        assert 'class="mh-rail-stats"' in response.text, name


async def test_a_json_client_still_pays_nothing_for_the_card(auth_client):
    """The guard exists to keep MCP and API reads off these four queries."""
    from web.deps import load_nav_status

    class Req:
        method = "GET"
        headers = {"accept": "application/json"}
        state = type("S", (), {})()

    req = Req()
    await load_nav_status(req, db=None)
    assert req.state.nav_status == []


# ── The same card, as numbers ────────────────────────────────────────────────
# ``rail_stats`` hands Jinja finished phrases ("86.1 kg", "7:20"); the JSON API
# hands the React app the raw values and lets the client do the formatting.


async def test_the_raw_rail_carries_numbers_not_phrases(db_session):
    for days_ago, kg in ((9, 87.0), (0, 86.1)):
        db_session.add(
            WeightLog(
                date=today_local() - timedelta(days=days_ago),
                domain=WEIGHT_DOMAIN,
                source=Source.MANUAL.value,
                weight_kg=kg,
            )
        )
    await db_session.flush()

    rows = {r.key: r for r in await nav_status_service.rail_stats_raw(db_session)}
    weight = rows["weight"]
    assert weight.weight_kg == pytest.approx(86.1)
    assert weight.delta_kg == pytest.approx(-0.7)
    assert weight.tone == "good"


async def test_the_raw_rail_has_no_delta_before_a_week_of_history(db_session):
    db_session.add(
        WeightLog(
            date=today_local(),
            domain=WEIGHT_DOMAIN,
            source=Source.MANUAL.value,
            weight_kg=86.1,
        )
    )
    await db_session.flush()

    rows = {r.key: r for r in await nav_status_service.rail_stats_raw(db_session)}
    assert rows["weight"].delta_kg is None
    assert rows["weight"].tone == ""


async def test_the_raw_rail_reports_sleep_in_seconds(db_session):
    db_session.add(
        GarminDaily(
            date=today_local(),
            domain=GARMIN_DOMAIN,
            source=Source.GARMIN_API.value,
            sleep_seconds=7 * 3600 + 20 * 60,
            training_readiness=62,
        )
    )
    await db_session.flush()

    rows = {r.key: r for r in await nav_status_service.rail_stats_raw(db_session)}
    assert rows["recovery"].sleep_seconds == 26400
    assert rows["recovery"].readiness == 62
    assert rows["recovery"].days_since is None


async def test_the_raw_rail_reports_a_quiet_source_as_a_day_count(db_session):
    db_session.add(
        GarminDaily(
            date=today_local() - timedelta(days=6),
            domain=GARMIN_DOMAIN,
            source=Source.GARMIN_API.value,
            sleep_seconds=7 * 3600,
        )
    )
    await db_session.flush()

    rows = {r.key: r for r in await nav_status_service.rail_stats_raw(db_session)}
    assert rows["recovery"].days_since == 6
    assert rows["recovery"].sleep_seconds is None
    assert rows["recovery"].tone == "warn"


# Nutrition and Hevy are optional modules: their rows only exist when switched on.
OPTIONALS_ON = {"weight": True, "garmin": True, "nutrition": True, "hevy": True}


@pytest.fixture
def intake_and_last_session(monkeypatch):
    """Today's intake over its ceiling and a session a week ago, without the
    meal and workout tables the two rows read."""
    from vitals.services import hevy_service, nutrition_service

    async def daily_summary(session, on_date, cfg):
        return {
            "meal_count": 3,
            "totals": {"calories": 2340.4, "protein_g": 151.6},
            "goals": {"calories_max": 2200.0},
        }

    async def latest_workout_date(session):
        return today_local() - timedelta(days=7)

    monkeypatch.setattr(nutrition_service, "daily_summary", daily_summary)
    monkeypatch.setattr(hevy_service, "latest_workout_date", latest_workout_date)


async def test_the_raw_rail_carries_intake_and_the_last_session(
    db_session, intake_and_last_session
):
    rows = {
        r.key: r
        for r in await nav_status_service.rail_stats_raw(db_session, OPTIONALS_ON)
    }
    nutrition, workouts = rows["nutrition"], rows["workouts"]
    assert nutrition.calories == pytest.approx(2340.4)
    assert nutrition.calories_max == pytest.approx(2200.0)
    assert nutrition.protein_g == pytest.approx(151.6)
    assert nutrition.tone == "bad"
    assert workouts.days_since == 7
    assert workouts.tone == "warn"


async def test_the_phrased_rail_reads_the_same_as_before(
    db_session, intake_and_last_session
):
    """Jinja still renders these strings, so building them on top of the raw
    values must not move a character."""
    current_lang.set("en")
    rows = {
        r.key: r for r in await nav_status_service.rail_stats(db_session, OPTIONALS_ON)
    }
    assert rows["nutrition"].value == "2340 / 2200 kcal"
    assert rows["nutrition"].sub == "protein 152 g"
    assert rows["nutrition"].tone == "bad"
    assert rows["workouts"].value == "7 days ago"
    assert rows["workouts"].tone == "warn"
