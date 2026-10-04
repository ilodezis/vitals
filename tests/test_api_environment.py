"""The environment API (``/api/v1/environment``): the gate, the empty state and
the settings round-trip. The data endpoints are covered next to their services."""
from __future__ import annotations

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
