"""The live state: zone, liveness and trend."""
from __future__ import annotations

import json
from datetime import timedelta

import pytest
from env_support import add_samples, at, sample

from vitals.services.environment import live
from vitals.services.environment import settings as env_settings
from vitals.services.environment.settings import sanitize
from vitals.services.environment.live import co2_zone, get_live, station_status
from vitals.services.environment.types import LiveState

NOW = at("2026-10-05T12:00:00")


async def test_a_station_that_never_reported_has_no_live_state(db_session, redis):
    assert await get_live(db_session, redis, now=NOW) is None
    assert await get_live(db_session, None, now=NOW) is None


@pytest.mark.parametrize(
    "co2, zone",
    [(None, "none"), (0, "good"), (799, "good"), (800, "ok"), (999, "ok"),
     (1000, "warn"), (1399, "warn"), (1400, "bad"), (5000, "bad")],
)
def test_zones_at_the_default_thresholds(co2, zone):
    assert co2_zone(co2, sanitize(None)) == zone


def test_zones_follow_the_owners_thresholds():
    cfg = sanitize({"co2_ok_max": 600, "co2_warn": 700, "co2_bad": 900})
    assert [co2_zone(v, cfg) for v in (599, 600, 699, 700, 899, 900)] == [
        "good", "ok", "ok", "warn", "warn", "bad",
    ]


@pytest.mark.parametrize(
    "age, poll, status",
    [(0, 10, "online"), (30, 10, "online"), (31, 10, "stale"), (300, 10, "stale"),
     (301, 10, "offline"), (3600, 10, "offline"),
     # Polling every 5 s still only finds a new snapshot every 10 s.
     (30, 5, "online"), (31, 5, "stale"),
     (180, 60, "online"), (181, 60, "stale")],
)
def test_station_status_from_the_age_of_the_last_snapshot(age, poll, status):
    assert station_status(age, poll) == status


async def test_the_latest_reading_comes_from_the_database(db_session):
    await add_samples(db_session, NOW - timedelta(seconds=40), count=3, co2=lambda i: 700 + i * 10,
                      temp=21.5, rh=44.0)
    state = await get_live(db_session, None, now=NOW)

    assert isinstance(state, LiveState)
    assert state.now.co2_ppm == 720 and state.now.temperature_c == 21.5 and state.now.humidity_pct == 44.0
    assert state.now.co2_zone == "good"
    assert state.station.status == "online"
    assert state.station.age_s == 20  # the newest sample is 20 s old
    assert state.station.last_seen_at == NOW - timedelta(seconds=20)


async def test_the_rssi_and_firmware_come_from_the_sample(db_session):
    row = sample(NOW - timedelta(seconds=5), 1, extra={"rssi": -61, "fw": "env-1.1.0"})
    db_session.add(row)
    await db_session.flush()
    state = await get_live(db_session, None, now=NOW)
    assert (state.station.rssi, state.station.fw) == (-61, "env-1.1.0")


async def test_the_cache_is_preferred_and_the_database_is_the_fallback(db_session, redis):
    await add_samples(db_session, NOW - timedelta(seconds=30), count=1, co2=500)
    await redis.set(
        live.live_key("bedroom"),
        json.dumps({
            "ts": (NOW - timedelta(seconds=4)).isoformat(),
            "received_at": (NOW - timedelta(seconds=4)).isoformat(),
            "boot": "b1", "seq": 9, "co2_ppm": 1450, "temperature_c": 23.0,
            "humidity_pct": 38.0, "lux": None, "rssi": -70, "fw": "x",
        }),
    )
    cached = await get_live(db_session, redis, now=NOW)
    assert cached.now.co2_ppm == 1450 and cached.now.co2_zone == "bad" and cached.station.age_s == 4

    await redis.delete(live.live_key("bedroom"))
    assert (await get_live(db_session, redis, now=NOW)).now.co2_ppm == 500


async def test_an_unreadable_cache_falls_back_to_the_database(db_session, redis):
    await add_samples(db_session, NOW - timedelta(seconds=10), count=1, co2=640)
    await redis.set(live.live_key("bedroom"), "{not json")
    assert (await get_live(db_session, redis, now=NOW)).now.co2_ppm == 640


async def test_a_quiet_station_ages_into_stale_and_offline(db_session):
    await add_samples(db_session, NOW - timedelta(minutes=2), count=1)
    assert (await get_live(db_session, None, now=NOW)).station.status == "stale"
    assert (await get_live(db_session, None, now=NOW + timedelta(minutes=10))).station.status == "offline"


async def test_the_zone_uses_the_saved_thresholds(db_session):
    await add_samples(db_session, NOW - timedelta(seconds=10), count=1, co2=850)
    assert (await get_live(db_session, None, now=NOW)).now.co2_zone == "ok"
    await env_settings.set_settings(db_session, {"co2_ok_max": 700, "co2_warn": 800, "co2_bad": 900})
    assert (await get_live(db_session, None, now=NOW)).now.co2_zone == "warn"


# ── The trend ─────────────────────────────────────────────────────────────────
async def test_a_steady_rise_reads_as_its_rate_per_hour(db_session):
    # +1 ppm every 10 s = +360 ppm/h, 90 samples = 15 minutes.
    await add_samples(db_session, NOW - timedelta(minutes=15), count=90, co2=lambda i: 600 + i)
    assert (await get_live(db_session, None, now=NOW)).now.co2_trend_ppm_per_h == pytest.approx(360.0, abs=0.1)


async def test_a_fall_is_negative_and_flat_is_zero(db_session):
    await add_samples(db_session, NOW - timedelta(minutes=15), count=90, co2=lambda i: 1200 - 2 * i)
    assert (await get_live(db_session, None, now=NOW)).now.co2_trend_ppm_per_h == pytest.approx(-720.0, abs=0.1)


async def test_flat_air_has_a_zero_trend(db_session):
    await add_samples(db_session, NOW - timedelta(minutes=10), count=60, co2=700)
    assert (await get_live(db_session, None, now=NOW)).now.co2_trend_ppm_per_h == 0.0


async def test_the_trend_needs_six_readings(db_session):
    await add_samples(db_session, NOW - timedelta(seconds=50), count=5, co2=lambda i: 600 + i)
    assert (await get_live(db_session, None, now=NOW)).now.co2_trend_ppm_per_h is None
    await add_samples(db_session, NOW - timedelta(seconds=0), count=1, co2=700, first_seq=100)
    assert (await get_live(db_session, None, now=NOW)).now.co2_trend_ppm_per_h is not None


async def test_the_trend_only_looks_at_the_last_fifteen_minutes(db_session):
    # A steep rise an hour ago, then flat: the trend is about now, so it is flat.
    await add_samples(db_session, NOW - timedelta(minutes=80), count=60, co2=lambda i: 400 + 10 * i)
    await add_samples(db_session, NOW - timedelta(minutes=10), count=60, co2=900, first_seq=1000)
    assert (await get_live(db_session, None, now=NOW)).now.co2_trend_ppm_per_h == 0.0


async def test_no_trend_from_a_stale_series(db_session):
    await add_samples(db_session, NOW - timedelta(minutes=14), count=60, co2=lambda i: 600 + i)  # newest 4 min old
    assert (await get_live(db_session, None, now=NOW)).now.co2_trend_ppm_per_h is None


async def test_missing_co2_readings_are_skipped_in_the_trend(db_session):
    await add_samples(db_session, NOW - timedelta(minutes=10), count=60,
                      co2=lambda i: None if i % 2 else 600 + i)
    trend = (await get_live(db_session, None, now=NOW)).now.co2_trend_ppm_per_h
    assert trend == pytest.approx(360.0, abs=0.5)
