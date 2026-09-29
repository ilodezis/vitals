"""``GET /api/v1/today`` — the whole Today screen in one request.

The old page phrases everything on the server; this endpoint sends the values
(``today_service.collect``) and the React screen phrases them, so the tests here
pin *what is sent*: numbers as numbers, dates as ISO strings, and a block of the
screen that belongs to a module that is off simply absent.
"""
from datetime import timedelta

import pytest

from vitals.enums import Domain, Source
from vitals.models.garmin import GarminDaily
from vitals.services import modules_service, nutrition_service, weight_service
from vitals.utils.timeutils import today_local

TODAY = "/api/v1/today"


async def _switch_off(db_session, redis, key: str):
    state = await modules_service.set_module_enabled(db_session, key=key, enabled=False)
    await db_session.commit()
    await modules_service.prime_cache(redis, state)


def _garmin(days_ago: int, **fields):
    return GarminDaily(
        date=today_local() - timedelta(days=days_ago),
        domain=Domain.GARMIN.value,
        source=Source.GARMIN_API.value,
        **fields,
    )


async def test_today_is_guarded(client):
    r = await client.get(TODAY)
    assert r.status_code == 401
    assert r.json() == {"error": "unauthenticated"}


async def test_today_has_the_agreed_shape(auth_client):
    r = await auth_client.get(TODAY)
    assert r.status_code == 200
    assert set(r.json()) == {
        "date", "narrative", "narrative_source", "sync", "figures", "changes",
        "feed", "attention", "goal", "latest_weight",
    }  # fmt: skip


async def test_an_empty_lake_is_still_a_whole_screen(auth_client):
    body = (await auth_client.get(TODAY)).json()

    assert body["date"] == today_local().isoformat()
    assert body["narrative"]
    assert body["narrative_source"] == "computed"
    # The figures row is the skeleton of the screen: it is there, empty, so the
    # screen does not change shape when the first number arrives.
    assert [f["key"] for f in body["figures"]] == [
        "weight", "sleep_score", "hrv_avg", "body_battery_high", "calories",
    ]  # fmt: skip
    assert all(f["value"] is None for f in body["figures"][:4])
    assert body["changes"] == [] and body["feed"] == []
    assert body["goal"] is None and body["latest_weight"] is None


async def test_the_figures_are_numbers(auth_client, db_session):
    for offset, kg in ((14, 95.0), (7, 93.5), (0, 92.0)):
        await weight_service.log_weight(
            db_session, on_date=today_local() - timedelta(days=offset), weight_kg=kg
        )
    db_session.add(
        _garmin(0, sleep_score=82, sleep_seconds=27240, hrv_avg=46.0,
                body_battery_high=94, body_battery_change=58)
    )
    await db_session.commit()

    body = (await auth_client.get(TODAY)).json()

    figures = {f["key"]: f for f in body["figures"]}
    assert figures["weight"]["value"] == 92.0
    assert isinstance(figures["weight"]["trend"], float)
    assert figures["sleep_score"]["sleep_seconds"] == 27240
    assert figures["body_battery_high"]["gained"] == 58
    assert body["latest_weight"] == {"kg": 92.0, "date": today_local().isoformat()}
    assert body["sync"] == [{"source": "Garmin", "date": today_local().isoformat()}]


async def test_nutrition_switched_off_leaves_no_calories_and_no_meals(auth_client, db_session, redis):
    await nutrition_service.log_meal(
        db_session, on_date=today_local(), name="Обед", calories=520
    )
    await db_session.commit()
    on = (await auth_client.get(TODAY)).json()
    assert [row["kind"] for row in on["feed"]] == ["meal"]

    await _switch_off(db_session, redis, "nutrition")
    off = (await auth_client.get(TODAY)).json()

    assert "calories" not in [f["key"] for f in off["figures"]]
    assert off["feed"] == []


async def test_a_weigh_in_is_in_the_days_feed(auth_client, db_session):
    """The screen shows a saved weight in the feed at once; the refetch that
    follows must not take it away."""
    await weight_service.log_weight(db_session, on_date=today_local(), weight_kg=86.1)
    await db_session.commit()

    body = (await auth_client.get(TODAY)).json()

    assert body["feed"] == [
        {"time": "", "kind": "weight", "dot": "good", "text": "", "detail": "", "value": 86.1}
    ]


async def test_the_spa_can_read_dates_back(auth_client, db_session):
    """Every date the screen parses is a plain ISO string."""
    await weight_service.log_weight(db_session, on_date=today_local(), weight_kg=86.1)
    await db_session.commit()

    body = (await auth_client.get(TODAY)).json()

    for value in (body["date"], body["latest_weight"]["date"]):
        assert isinstance(value, str) and len(value) == 10
        assert value.count("-") == 2


@pytest.mark.parametrize("path", ["/api/v1/today/", "/api/v1/today/x"])
async def test_nothing_else_lives_under_today(auth_client, path):
    r = await auth_client.get(path)
    assert r.status_code in (307, 404)
