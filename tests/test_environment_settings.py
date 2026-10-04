"""Thresholds and alert switches of the environment module."""
from __future__ import annotations

import pytest

from vitals.models.app_settings import AppSetting
from vitals.services.environment import settings as env_settings


def test_defaults_are_the_documented_numbers():
    d = env_settings.sanitize(None)
    assert (d.co2_ok_max, d.co2_warn, d.co2_bad) == (800, 1000, 1400)
    assert (d.temp_day_min, d.temp_day_max) == (18.0, 26.0)
    assert (d.temp_sleep_min, d.temp_sleep_max) == (17.0, 20.0)
    assert (d.rh_min, d.rh_max, d.rh_alert_low, d.rh_alert_high) == (35.0, 60.0, 30.0, 70.0)
    assert d.night_times() == (
        env_settings.time_type.fromisoformat("00:00"),
        env_settings.time_type.fromisoformat("12:00"),
    )
    assert d.alerts_enabled and d.alert_telegram


@pytest.mark.parametrize("junk", [None, "nope", 42, [], {"co2_warn": "abc"}, {"co2_warn": float("nan")}])
def test_nonsense_degrades_to_defaults(junk):
    assert env_settings.sanitize(junk).co2_warn == 1000


def test_numbers_are_clamped_into_their_bounds():
    s = env_settings.sanitize({"co2_warn": 99999, "co2_ok_max": -5, "rh_min": -10, "temp_day_max": 500})
    assert s.co2_ok_max == env_settings.CO2_RANGE[0]
    assert s.co2_warn == env_settings.CO2_RANGE[1]
    assert s.rh_min == 0.0
    assert s.temp_day_max == env_settings.TEMP_RANGE[1]


def test_zones_stay_ordered_whatever_is_stored():
    s = env_settings.sanitize({"co2_ok_max": 1500, "co2_warn": 900, "co2_bad": 800})
    assert s.co2_ok_max < s.co2_warn < s.co2_bad


def test_a_band_never_collapses():
    s = env_settings.sanitize({"temp_day_min": 30, "temp_day_max": 20, "rh_min": 50, "rh_max": 50})
    assert s.temp_day_min < s.temp_day_max
    assert s.rh_min < s.rh_max


def test_bad_night_window_falls_back_and_an_empty_one_too():
    assert env_settings.sanitize({"night_window": {"start": "25:99", "end": "x"}}).night_start == "00:00"
    s = env_settings.sanitize({"night_window": {"start": "06:00", "end": "06:00"}})
    assert (s.night_start, s.night_end) == ("00:00", "12:00")
    s = env_settings.sanitize({"night_window": {"start": "22:30", "end": "07:00"}})
    assert (s.night_start, s.night_end) == ("22:30", "07:00")


def test_switches_only_accept_booleans():
    assert env_settings.sanitize({"alerts_enabled": "false"}).alerts_enabled is True
    assert env_settings.sanitize({"alerts_enabled": False}).alerts_enabled is False


async def test_set_settings_merges_a_partial_patch(db_session):
    await env_settings.set_settings(db_session, {"co2_warn": 1100})
    saved = await env_settings.set_settings(
        db_session, {"night_window": {"start": "22:00"}, "alert_telegram": False, "unknown": 1}
    )
    assert saved.co2_warn == 1100                       # the earlier patch survives
    assert (saved.night_start, saved.night_end) == ("22:00", "12:00")  # partial window
    assert saved.alert_telegram is False
    assert (await env_settings.get_settings(db_session)) == saved
    row = await db_session.get(AppSetting, env_settings.SETTINGS_KEY)
    assert row.value["night_window"] == {"start": "22:00", "end": "12:00"}
    assert "unknown" not in row.value


async def test_get_settings_survives_a_corrupt_row(db_session):
    db_session.add(AppSetting(key=env_settings.SETTINGS_KEY, value="garbage"))
    await db_session.flush()
    assert (await env_settings.get_settings(db_session)).co2_bad == 1400
