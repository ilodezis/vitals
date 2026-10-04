"""Chart series and the night / day summaries."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from env_support import add_samples, at, sample

from vitals.services.environment import queries
from vitals.services.environment import settings as env_settings
from vitals.services.environment.stats import percentile

NOW = at("2026-10-05T12:00:00")
# 2026-10-05 in Chisinau (UTC+3, summer time until 25 October).
NIGHT_START = at("2026-10-04T21:00:00")  # 00:00 local
NIGHT_END = at("2026-10-05T09:00:00")    # 12:00 local
D = date(2026, 10, 5)


# ── Windows ───────────────────────────────────────────────────────────────────
def test_the_default_night_is_midnight_to_noon_local():
    assert queries.night_window(D, env_settings.sanitize(None)) == (NIGHT_START, NIGHT_END)


def test_a_night_window_that_wraps_midnight_starts_the_evening_before():
    cfg = env_settings.sanitize({"night_window": {"start": "22:00", "end": "07:00"}})
    assert queries.night_window(D, cfg) == (at("2026-10-04T19:00:00"), at("2026-10-05T04:00:00"))


def test_a_day_is_local_midnight_to_midnight():
    assert queries.day_window(D) == (NIGHT_START, at("2026-10-05T21:00:00"))


def test_the_day_the_clocks_go_back_is_twenty_five_hours():
    start, end = queries.day_window(date(2026, 10, 25))
    assert (end - start) == timedelta(hours=25)


@pytest.mark.parametrize(
    "hours, requested, effective",
    [(1, "raw", "raw"), (3, "raw", "raw"), (4, "raw", "minute"), (24, "minute", "minute"),
     (48, "minute", "minute"), (49, "minute", "hour"), (72, "raw", "hour"), (168, "minute", "hour"),
     (1, "hour", "hour"), (6, "hour", "hour")],
)
def test_the_resolution_a_range_can_be_served_at(hours, requested, effective):
    assert queries.effective_resolution(NOW - timedelta(hours=hours), NOW, requested) == effective


# ── Summaries ─────────────────────────────────────────────────────────────────
async def test_an_empty_night_is_empty_not_zero(db_session):
    s = await queries.night_summary(db_session, D, now=NOW)
    assert (s.date, s.samples, s.coverage_pct) == (D, 0, 0.0)
    assert (s.window.start, s.window.end) == (NIGHT_START, NIGHT_END)
    assert s.co2.median is None and s.co2.max is None
    assert s.co2.minutes_above_warn == 0.0
    assert s.temperature.min is None and s.humidity.mean is None


async def test_a_full_night_is_summarised(db_session):
    # 12 h at 30 s: CO2 climbs from 600 to 1400 over the night.
    n = 12 * 120
    await add_samples(db_session, NIGHT_START, count=n, step_s=30,
                      co2=lambda i: 600 + round(800 * i / (n - 1)),
                      temp=lambda i: 20.0 + 2.0 * i / (n - 1),
                      rh=lambda i: 50.0 - 10.0 * i / (n - 1))
    s = await queries.night_summary(db_session, D, now=NOW + timedelta(hours=6))

    assert s.samples == n and s.coverage_pct == 100.0
    assert s.co2.max == 1400 and s.co2.median == pytest.approx(1000, abs=1)
    assert s.co2.p90 == pytest.approx(percentile([600 + round(800 * i / (n - 1)) for i in range(n)], 90), abs=0.1)
    assert (s.temperature.min, s.temperature.max) == (20.0, 22.0) and s.temperature.mean == 21.0
    assert (s.humidity.min, s.humidity.max) == (40.0, 50.0)


async def test_minutes_above_a_threshold_are_real_minutes(db_session):
    # 2 h at 1100 (warn, not bad), then 2 h at 1500 (bad), 30 s apart.
    await add_samples(db_session, NIGHT_START, count=240, step_s=30, co2=1100)
    await add_samples(db_session, NIGHT_START + timedelta(hours=2), count=240, step_s=30, co2=1500, first_seq=1000)
    s = await queries.night_summary(db_session, D, now=NOW)
    # 1100 and 1500 are both >= 1000; only the 1500 stretch is >= 1400. (The very
    # last snapshot of a series stands for one 10 s interval, hence the half minute.)
    assert s.co2.minutes_above_warn == pytest.approx(240.0, abs=0.5)
    assert s.co2.minutes_above_bad == pytest.approx(120.0, abs=0.5)


async def test_a_silent_station_is_not_counted_as_high(db_session):
    # Five minutes of 1500, then twenty minutes of nothing, then normal air.
    await add_samples(db_session, NIGHT_START, count=10, step_s=30, co2=1500)
    await add_samples(db_session, NIGHT_START + timedelta(minutes=25), count=10, step_s=30, co2=500, first_seq=100)
    s = await queries.night_summary(db_session, D, now=NOW)
    # 9 intervals of 30 s + the last reading's capped 60 s — not the 20 silent minutes.
    assert s.co2.minutes_above_bad == 5.5
    assert s.coverage_pct < 5  # the silence is not coverage either


async def test_coverage_is_the_share_of_the_window_reported(db_session):
    await add_samples(db_session, NIGHT_START, count=6 * 120, step_s=30)  # the first 6 of 12 hours
    s = await queries.night_summary(db_session, D, now=NOW)
    assert s.coverage_pct == pytest.approx(50.0, abs=0.1)


async def test_a_night_still_running_is_measured_against_what_has_elapsed(db_session):
    await add_samples(db_session, NIGHT_START, count=3 * 120, step_s=30)  # 3 h of data...
    # ...and it is 03:00 local, so 3 h of the window have elapsed.
    s = await queries.night_summary(db_session, D, now=NIGHT_START + timedelta(hours=3))
    assert s.coverage_pct == pytest.approx(100.0, abs=0.5)
    # A night that has not started has no coverage rather than a division by zero.
    assert (await queries.night_summary(db_session, D, now=NIGHT_START - timedelta(hours=1))).coverage_pct == 0.0


async def test_the_night_window_is_start_inclusive_and_end_exclusive(db_session):
    # 10 minutes of samples straddling the start, 10 straddling the end; the window
    # keeps exactly the ones from NIGHT_START on and before NIGHT_END.
    await add_samples(db_session, NIGHT_START - timedelta(minutes=5), count=20, step_s=30, co2=2000)
    await add_samples(db_session, NIGHT_END - timedelta(minutes=5), count=20, step_s=30, co2=1800, first_seq=100)
    s = await queries.night_summary(db_session, D, now=NOW)
    assert s.samples == 20  # 10 after the start + 10 before the end
    assert s.co2.max == 2000


async def test_another_station_is_not_mixed_in(db_session):
    await add_samples(db_session, NIGHT_START, count=20, step_s=30, co2=900)
    await add_samples(db_session, NIGHT_START, count=20, step_s=30, co2=3000, station="other", first_seq=500)
    s = await queries.night_summary(db_session, D, now=NOW)
    assert s.co2.max == 900 and s.samples == 20


async def test_missing_readings_do_not_count_as_zero(db_session):
    await add_samples(db_session, NIGHT_START, count=10, step_s=30,
                      co2=lambda i: None if i % 2 else 800, temp=None, rh=lambda i: 40.0)
    s = await queries.night_summary(db_session, D, now=NOW)
    assert s.co2.median == 800.0 and s.temperature.min is None and s.humidity.mean == 40.0


async def test_a_day_summary_covers_the_calendar_day(db_session):
    await add_samples(db_session, NIGHT_START, count=24 * 120, step_s=30, co2=700)
    s = await queries.day_summary(db_session, D, now=at("2026-10-06T00:00:00"))
    assert s.samples == 24 * 120 and s.coverage_pct == 100.0
    assert (s.window.start, s.window.end) == (NIGHT_START, at("2026-10-05T21:00:00"))


async def test_the_summary_reads_the_saved_thresholds(db_session):
    await add_samples(db_session, NIGHT_START, count=120, step_s=30, co2=900)  # one hour
    assert (await queries.night_summary(db_session, D, now=NOW)).co2.minutes_above_warn == 0.0
    await env_settings.set_settings(db_session, {"co2_warn": 800})
    assert (await queries.night_summary(db_session, D, now=NOW)).co2.minutes_above_warn == pytest.approx(60.0, abs=0.5)


# ── Series ────────────────────────────────────────────────────────────────────
async def test_raw_points_are_the_samples(db_session):
    await add_samples(db_session, NOW - timedelta(minutes=10), count=6, co2=lambda i: 700 + i, rh=None)
    pts = await queries.series(db_session, NOW - timedelta(hours=1), NOW, resolution="raw")
    assert [p.co2_ppm for p in pts] == [700, 701, 702, 703, 704, 705]
    assert pts[0].ts == NOW - timedelta(minutes=10) and pts[0].humidity_pct is None


async def test_minute_points_average_the_minute(db_session):
    # 6 samples a minute for 3 minutes; the third minute has a missing reading.
    await add_samples(db_session, NOW - timedelta(minutes=3), count=18,
                      co2=lambda i: 600 + 6 * (i // 6) + (0 if i % 6 < 3 else 6),
                      temp=lambda i: None if i >= 12 and i % 2 else 21.0)
    pts = await queries.series(db_session, NOW - timedelta(hours=5), NOW, resolution="minute")
    assert [p.ts for p in pts] == [NOW - timedelta(minutes=3) + timedelta(minutes=k) for k in range(3)]
    assert [p.co2_ppm for p in pts] == [603.0, 609.0, 615.0]
    assert pts[2].temperature_c == 21.0  # the missing readings are left out of the mean, not zeroed
    assert pts[0].co2_max is None  # minute points carry no extremes


async def test_a_series_is_bounded_to_its_window_and_station(db_session):
    await add_samples(db_session, NOW - timedelta(hours=2), count=6)
    await add_samples(db_session, NOW - timedelta(minutes=5), count=6, first_seq=50)
    await add_samples(db_session, NOW - timedelta(minutes=5), count=6, station="other", first_seq=90)
    pts = await queries.series(db_session, NOW - timedelta(hours=1), NOW, resolution="raw")
    assert len(pts) == 6


async def test_an_empty_range_is_an_empty_series(db_session):
    assert await queries.series(db_session, NOW - timedelta(hours=1), NOW, resolution="minute") == []


async def test_long_ranges_fall_back_to_hours_even_without_a_rollup(db_session):
    await add_samples(db_session, NOW - timedelta(hours=60), count=60 * 6, step_s=600,
                      co2=lambda i: 500 + 100 * (i // 6 % 3))  # six samples an hour
    pts = await queries.series(db_session, NOW - timedelta(hours=60), NOW, resolution="minute")
    assert len(pts) == 60 and pts[0].co2_max is not None and pts[0].co2_min is not None
    assert pts[0].ts == NOW - timedelta(hours=60)


async def test_coverage_of_a_series_window(db_session):
    await add_samples(db_session, NOW - timedelta(hours=1), count=360)  # the last of 2 hours
    assert await queries.coverage_pct(db_session, NOW - timedelta(hours=2), NOW) == pytest.approx(50.0, abs=0.2)
    assert await queries.coverage_pct(db_session, NOW, NOW) == 0.0


async def test_the_station_default_is_the_configured_one(db_session, monkeypatch):
    monkeypatch.setenv("VITALS_ENV_STATION_ID", "study")
    await add_samples(db_session, NOW - timedelta(minutes=1), count=6, station="study", co2=999)
    await add_samples(db_session, NOW - timedelta(minutes=1), count=6, co2=111, first_seq=100)
    pts = await queries.series(db_session, NOW - timedelta(hours=1), NOW, resolution="raw")
    assert {p.co2_ppm for p in pts} == {999}
