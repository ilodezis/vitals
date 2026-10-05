"""The environment API (``/api/v1/environment``): the gate, the empty state and
the settings round-trip. The data endpoints are covered next to their services."""
from __future__ import annotations

import pytest

from vitals.services import modules_service

URL = "/api/v1/environment"


async def test_environment_is_not_reachable_anonymously(client):
    for path in ("/live", "/series", "/settings", "/day/2026-10-05", "/night/2026-10-05"):
        assert (await client.get(URL + path)).status_code == 401
    assert (await client.post(URL + "/station/check")).status_code == 401


async def test_environment_module_is_gated(auth_client, db_session, redis):
    state = await modules_service.set_module_enabled(db_session, key="environment", enabled=False)
    await db_session.commit()
    await modules_service.prime_cache(redis, state)

    for path in ("/live", "/series", "/settings"):
        r = await auth_client.get(URL + path)
        assert r.status_code == 404, path
        assert r.json() == {"error": "module_disabled"}
    assert (await auth_client.post(URL + "/station/check")).status_code == 404


async def test_the_module_is_optional_in_the_health_rubric():
    spec = modules_service.MODULE_REGISTRY["environment"]
    assert (spec.category, spec.route, spec.rubric) == ("optional", "/environment", "health")
    assert modules_service.DEFAULT_STATE["environment"] is False  # off until the owner has hardware


async def test_live_without_a_station_is_the_empty_state(auth_client, monkeypatch):
    monkeypatch.delenv("VITALS_ENV_STATION_URL", raising=False)
    body = (await auth_client.get(URL + "/live")).json()
    assert body["configured"] is False
    assert body["station"]["status"] == "never"
    assert body["now"]["co2_zone"] == "none"
    assert body["now"]["co2_ppm"] is None
    assert body["thresholds"]["co2_warn"] == 1000


async def test_settings_round_trip(auth_client):
    got = (await auth_client.get(URL + "/settings")).json()
    assert got["co2_bad"] == 1400 and got["night_window"] == {"start": "00:00", "end": "12:00"}

    r = await auth_client.put(
        URL + "/settings",
        json={"co2_warn": 1100, "night_window": {"start": "23:00", "end": "09:00"}, "alert_telegram": False},
    )
    assert r.status_code == 200
    saved = r.json()
    assert saved["co2_warn"] == 1100 and saved["alert_telegram"] is False
    assert saved["night_window"] == {"start": "23:00", "end": "09:00"}
    assert saved["co2_bad"] == 1400  # untouched fields keep their value

    assert (await auth_client.get(URL + "/settings")).json() == saved


async def test_settings_clamp_instead_of_rejecting(auth_client):
    saved = (await auth_client.put(URL + "/settings", json={"co2_warn": 99999})).json()
    assert saved["co2_warn"] == 5000
    assert (await auth_client.put(URL + "/settings", json={"co2_warn": "x"})).status_code == 422


# ── With data ─────────────────────────────────────────────────────────────────
import datetime as dt  # noqa: E402

from env_support import STATION_URL, FakeStation, add_samples, at, snapshot  # noqa: E402
from freezegun import freeze_time  # noqa: E402

from vitals.integrations.esphome_client import StationClient  # noqa: E402
from vitals.services.environment import ingest  # noqa: E402

NOW = at("2026-10-05T12:00:00")


@freeze_time("2026-10-05T12:00:00")
async def test_live_shows_the_latest_reading(auth_client, db_session, monkeypatch):
    monkeypatch.setenv("VITALS_ENV_STATION_URL", STATION_URL)
    await add_samples(db_session, NOW - dt.timedelta(minutes=15), count=90, co2=lambda i: 900 + i * 2,
                      temp=22.5, rh=41.0)
    await db_session.commit()

    from web.auth import create_session
    from web.config import SESSION_COOKIE

    auth_client.cookies.set(SESSION_COOKIE, create_session("tester"))
    resp = await auth_client.get(URL + "/live")
    body = resp.json()
    assert body["configured"] is True
    assert body["station"]["status"] == "online"
    assert body["now"]["co2_ppm"] == 1078 and body["now"]["co2_zone"] == "warn"
    assert body["now"]["temperature_c"] == 22.5 and body["now"]["humidity_pct"] == 41.0
    assert body["now"]["co2_trend_ppm_per_h"] == pytest.approx(720.0, abs=0.5)
    assert body["thresholds"]["co2_bad"] == 1400


@freeze_time("2026-10-05T12:00:00")
async def test_series_serves_the_resolution_the_range_allows(auth_client, db_session):
    await add_samples(db_session, NOW - dt.timedelta(hours=60), count=60 * 6, step_s=600, co2=700)
    await db_session.commit()

    from web.auth import create_session
    from web.config import SESSION_COOKIE

    auth_client.cookies.set(SESSION_COOKIE, create_session("tester"))
    day = (await auth_client.get(URL + "/series", params={"hours": 24})).json()
    assert day["resolution"] == "minute" and day["window"]["end"].startswith("2026-10-05T12:00:00")
    assert day["thresholds"]["co2_warn"] == 1000 and 0 < day["coverage_pct"] <= 100

    long = (await auth_client.get(URL + "/series", params={"hours": 72, "resolution": "minute"})).json()
    assert long["resolution"] == "hour"
    assert long["points"] and long["points"][0]["co2_max"] == 700

    short = (await auth_client.get(URL + "/series", params={"hours": 1, "resolution": "raw"})).json()
    assert short["resolution"] == "raw"


@pytest.mark.parametrize("params", [{"hours": 0}, {"hours": 169}, {"resolution": "second"}])
async def test_series_validates_its_parameters(auth_client, params):
    assert (await auth_client.get(URL + "/series", params=params)).status_code == 422


async def test_the_night_endpoint_carries_the_summary_and_the_minute_curve(auth_client, db_session):
    start = at("2026-10-04T21:00:00")  # 00:00 local on the 5th
    await add_samples(db_session, start, count=6 * 120, step_s=30, co2=lambda i: 700 + i)  # 6 h
    await db_session.commit()

    body = (await auth_client.get(URL + "/night/2026-10-05")).json()
    summary = body["summary"]
    assert summary["date"] == "2026-10-05" and summary["samples"] == 720
    assert summary["window"]["start"].startswith("2026-10-04T21:00:00")
    assert summary["window"]["end"].startswith("2026-10-05T09:00:00")
    assert summary["co2"]["max"] == 1419 and summary["co2"]["minutes_above_bad"] > 0
    assert len(body["series"]) == 6 * 60 and body["series"][0]["ts"].startswith("2026-10-04T21:00:00")
    assert body["thresholds"]["co2_ok_max"] == 800


async def test_the_day_endpoint_and_a_bad_date(auth_client, db_session):
    await add_samples(db_session, at("2026-10-05T06:00:00"), count=360, co2=650)
    await db_session.commit()
    body = (await auth_client.get(URL + "/day/2026-10-05")).json()
    assert body["summary"]["samples"] == 360 and body["summary"]["co2"]["median"] == 650.0
    assert (await auth_client.get(URL + "/day/not-a-date")).status_code == 422


async def test_the_night_follows_the_saved_window(auth_client, db_session):
    await auth_client.put(URL + "/settings", json={"night_window": {"start": "22:00", "end": "07:00"}})
    body = (await auth_client.get(URL + "/night/2026-10-05")).json()
    assert body["summary"]["window"]["start"].startswith("2026-10-04T19:00:00")  # 22:00 local the evening before
    assert body["summary"]["window"]["end"].startswith("2026-10-05T04:00:00")


async def test_station_check_polls_now(auth_client, monkeypatch):
    station = FakeStation(snapshot(seq=3, t=int(dt.datetime.now(dt.timezone.utc).timestamp())))
    monkeypatch.setenv("VITALS_ENV_STATION_URL", STATION_URL)
    monkeypatch.setattr(
        ingest, "client_from_config", lambda: StationClient(STATION_URL, "u", "p", transport=station.transport)
    )
    ok = (await auth_client.post(URL + "/station/check")).json()
    assert ok == {"ok": True, "status": "online", "error": None}

    station.status = 401
    bad = (await auth_client.post(URL + "/station/check")).json()
    assert bad["ok"] is False and bad["error"] == "unauthorized"
    # The error never carries the address.
    assert "station.test" not in str(bad)


async def test_station_check_without_an_address(auth_client, monkeypatch):
    monkeypatch.delenv("VITALS_ENV_STATION_URL", raising=False)
    assert (await auth_client.post(URL + "/station/check")).json() == {
        "ok": False, "status": "never", "error": "not_configured",
    }
