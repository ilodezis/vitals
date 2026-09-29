"""``GET /api/v1/session`` — who is signed in, in what language, and what the
shell may draw.

The React app hardcodes no section: the navigation comes from here, built by
``modules_service`` from the same registry the server-rendered rail reads, so
switching a module off in Settings removes it from both.
"""
from datetime import timedelta

import pytest

from vitals.enums import Source
from vitals.models.weight import DOMAIN as WEIGHT_DOMAIN, WeightLog
from vitals.services import language_service, modules_service
from vitals.utils.timeutils import today_local

SESSION = "/api/v1/session"


async def test_the_session_is_guarded(client):
    r = await client.get(SESSION)
    assert r.status_code == 401
    assert r.json() == {"error": "unauthenticated"}


async def test_the_session_has_the_agreed_shape(auth_client):
    r = await auth_client.get(SESSION)
    assert r.status_code == 200
    body = r.json()

    assert set(body) == {"username", "lang", "enabled_modules", "nav", "rail"}
    assert body["username"] == "tester"
    # The ``client`` fixture stores Russian as the UI language.
    assert body["lang"] == "ru"
    assert body["enabled_modules"] == {k: True for k in modules_service.MODULE_REGISTRY}
    assert set(body["nav"]) == {"items", "bottom_slots", "more_rubrics", "more_routes"}
    assert body["rail"] == []


async def test_the_nav_is_the_registry_in_rail_order(auth_client):
    nav = (await auth_client.get(SESSION)).json()["nav"]

    assert [i["key"] for i in nav["items"]] == [
        "weight", "garmin", "hevy", "nutrition",
        "glp1", "hrt", "labs", "genetics",
        "supplements", "skincare", "interactions", "signals",
        "timeline", "reports", "charts",
    ]  # fmt: skip
    weight = nav["items"][0]
    assert weight == {"key": "weight", "route": "/weight", "rubric": "health", "eyebrow": ""}
    # A section may override its rubric's masthead eyebrow.
    reports = next(i for i in nav["items"] if i["key"] == "reports")
    assert reports["eyebrow"] == "digest"
    # Body composition is a tab inside Weight, never a nav item of its own.
    assert "body_comp" not in {i["key"] for i in nav["items"]}


async def test_the_phone_bar_and_the_more_screen_split_the_sections(auth_client):
    nav = (await auth_client.get(SESSION)).json()["nav"]

    assert [s["key"] for s in nav["bottom_slots"]] == ["health", "nutrition", "lifestyle"]
    health = nav["bottom_slots"][0]
    assert health["label_key"] == "nav.tab.health"
    assert health["icon"] == "weight"
    assert health["route"] == "/weight"
    assert "/garmin" in health["routes"]

    assert nav["more_rubrics"] == ["markers", "journal"]
    assert nav["more_routes"][:3] == ["/more", "/share", "/settings"]
    assert "/glp1" in nav["more_routes"]


async def test_a_module_switched_off_leaves_the_nav(auth_client, db_session, redis):
    state = await modules_service.set_module_enabled(db_session, key="glp1", enabled=False)
    await db_session.commit()
    await modules_service.prime_cache(redis, state)

    body = (await auth_client.get(SESSION)).json()

    assert body["enabled_modules"]["glp1"] is False
    nav = body["nav"]
    assert "glp1" not in {i["key"] for i in nav["items"]}
    assert "/glp1" not in nav["more_routes"]
    # The rest of the rubric is still there.
    assert "hrt" in {i["key"] for i in nav["items"]}


async def test_the_language_follows_the_setting(auth_client, db_session, redis):
    await language_service.set_language(db_session, "en", redis)
    await db_session.commit()

    assert (await auth_client.get(SESSION)).json()["lang"] == "en"


async def test_the_rail_carries_raw_values(auth_client, db_session):
    for days_ago, kg in ((9, 87.0), (0, 86.1)):
        db_session.add(
            WeightLog(
                date=today_local() - timedelta(days=days_ago),
                domain=WEIGHT_DOMAIN,
                source=Source.MANUAL.value,
                weight_kg=kg,
            )
        )
    await db_session.commit()

    rail = (await auth_client.get(SESSION)).json()["rail"]

    assert [r["key"] for r in rail] == ["weight"]
    weight = rail[0]
    # Numbers, not "86,1 кг" — the client formats them.
    assert weight["weight_kg"] == pytest.approx(86.1)
    assert weight["delta_kg"] == pytest.approx(-0.9)
    assert weight["tone"] == "good"
    assert weight["sleep_seconds"] is None


async def test_the_rail_carries_last_nights_sleep_in_seconds(auth_client, db_session):
    from vitals.models.garmin import DOMAIN as GARMIN_DOMAIN, GarminDaily

    db_session.add(
        GarminDaily(
            date=today_local(),
            domain=GARMIN_DOMAIN,
            source=Source.GARMIN_API.value,
            sleep_seconds=7 * 3600,
        )
    )
    await db_session.commit()

    rail = (await auth_client.get(SESSION)).json()["rail"]
    assert [r["key"] for r in rail] == ["recovery"]
    assert rail[0]["sleep_seconds"] == 7 * 3600


async def test_a_json_read_does_not_pay_for_the_page_chrome(db_session):
    """``load_nav_status`` exists for the server-rendered rail. A fetch sends
    ``Accept: */*``, which counts as a document — the API's own paths must be
    ruled out, or every call would run the four queries twice."""
    from web.deps import load_nav_status

    class Spy:
        calls = 0

        async def execute(self, *a, **kw):
            Spy.calls += 1
            raise AssertionError("the rail must not be read for an API call")

    class Req:
        method = "GET"
        headers = {"accept": "*/*"}
        state = type("S", (), {})()
        url = type("U", (), {"path": SESSION})()

    req = Req()
    await load_nav_status(req, db=Spy())
    assert Spy.calls == 0
    assert req.state.nav_status == []
