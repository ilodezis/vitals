"""The hourly rollup: its numbers, idempotency, and the chart reads that use it."""
from __future__ import annotations

from datetime import timedelta

import pytest
from env_support import STATION_URL, add_samples, at, sample
from freezegun import freeze_time
from sqlalchemy import func, select

from vitals.models.environment import EnvironmentHourly
from vitals.services import modules_service
from vitals.services.environment import queries, rollup
from vitals.services.environment.rollup import SampleRow, aggregate_hours
from vitals.utils.timeutils import as_utc

H0 = at("2026-10-05T10:00:00")
STATION = "bedroom"


def _row(ts, co2=800, temp=21.0, rh=45.0, lux=None, lux_max=None):
    return SampleRow(ts, co2, temp, rh, lux, lux_max)


async def _hourly(session):
    return list(
        (await session.execute(select(EnvironmentHourly).order_by(EnvironmentHourly.hour_start))).scalars()
    )


# ── The numbers of an hour ────────────────────────────────────────────────────
def test_an_hour_of_ten_second_samples_is_fully_covered():
    rows = [_row(H0 + timedelta(seconds=10 * i), co2=500 + i) for i in range(360)]
    (hs,) = aggregate_hours(rows).values()
    assert (hs.hour_start, hs.sample_count, hs.coverage_pct) == (H0, 360, 100.0)
    assert (hs.co2_min, hs.co2_max) == (500, 859)
    assert hs.co2_mean == pytest.approx(679.5, abs=0.05)
    assert hs.co2_p90 == pytest.approx(500 + 0.9 * 359, abs=0.05)
    assert (hs.temp_mean, hs.temp_min, hs.temp_max) == (21.0, 21.0, 21.0)
    assert (hs.rh_mean, hs.rh_min, hs.rh_max) == (45.0, 45.0, 45.0)
    assert hs.lux_mean is None and hs.lux_max is None


def test_coverage_counts_only_the_time_reported():
    # Half an hour of samples, a 20 minute silence, then ten minutes more.
    rows = [_row(H0 + timedelta(seconds=10 * i)) for i in range(180)]
    rows += [_row(H0 + timedelta(minutes=50) + timedelta(seconds=10 * i)) for i in range(60)]
    (hs,) = aggregate_hours(rows).values()
    # 179 intervals of 10 s and the last of them capped at 60 s, then 59 of 10 s and
    # the final snapshot's 10 s: 2450 s of the 3600 — the 20 silent minutes are not.
    assert hs.coverage_pct == pytest.approx(2450 / 3600 * 100, abs=0.05)


def test_a_gap_across_the_hour_boundary_is_split_not_double_counted():
    rows = [_row(H0 + timedelta(minutes=59, seconds=40)), _row(H0 + timedelta(hours=1, seconds=20))]
    hours = aggregate_hours(rows)
    assert hours[H0].coverage_pct == pytest.approx(20 / 3600 * 100, abs=0.1)         # 20 s of the 60 s cap
    assert hours[H0 + timedelta(hours=1)].coverage_pct == pytest.approx(30 / 3600 * 100, abs=0.1)


def test_missing_readings_are_left_out_of_the_hour():
    rows = [_row(H0, co2=None, temp=20.0), _row(H0 + timedelta(seconds=10), co2=900, temp=None)]
    (hs,) = aggregate_hours(rows).values()
    assert (hs.co2_mean, hs.co2_min, hs.co2_max) == (900.0, 900, 900)
    assert hs.temp_mean == 20.0


def test_an_hour_with_no_values_for_a_quantity_leaves_it_null():
    (hs,) = aggregate_hours([_row(H0, co2=None, temp=None, rh=None)]).values()
    assert hs.sample_count == 1
    assert (hs.co2_mean, hs.co2_min, hs.temp_mean, hs.rh_mean) == (None, None, None, None)


def test_light_peaks_prefer_the_explicit_maximum():
    (hs,) = aggregate_hours([_row(H0, lux=2.0, lux_max=9.0), _row(H0 + timedelta(seconds=10), lux=4.0, lux_max=5.0)]).values()
    assert (hs.lux_mean, hs.lux_max) == (3.0, 9.0)
    (hs,) = aggregate_hours([_row(H0, lux=2.0), _row(H0 + timedelta(seconds=10), lux=4.0)]).values()
    assert hs.lux_max == 4.0


# ── Writing them ──────────────────────────────────────────────────────────────
async def test_rollup_range_writes_one_row_per_hour_with_data(db_session):
    await add_samples(db_session, H0, count=360 * 2, co2=lambda i: 600 if i < 360 else 1200)
    assert await rollup.rollup_range(db_session, STATION, H0, H0 + timedelta(hours=4)) == 2

    first, second = await _hourly(db_session)
    assert (as_utc(first.hour_start), first.co2_mean, second.co2_mean) == (H0, 600.0, 1200.0)
    assert (first.domain, first.source, first.station_id) == ("environment", "esphome", STATION)
    assert first.date.isoformat() == "2026-10-05"  # local date of the hour (13:00 local)
    assert first.coverage_pct == 100.0 and first.sample_count == 360


async def test_rolling_up_twice_changes_nothing(db_session):
    await add_samples(db_session, H0, count=360)
    await rollup.rollup_range(db_session, STATION, H0, H0 + timedelta(hours=1))
    await db_session.commit()
    before = [(h.id, h.sample_count, h.co2_mean, h.updated_at) for h in await _hourly(db_session)]

    await rollup.rollup_range(db_session, STATION, H0, H0 + timedelta(hours=1))
    await db_session.commit()
    assert [(h.id, h.sample_count, h.co2_mean, h.updated_at) for h in await _hourly(db_session)] == before
    assert (await db_session.execute(select(func.count()).select_from(EnvironmentHourly))).scalar() == 1


async def test_a_late_sample_updates_the_hour_it_belongs_to(db_session):
    await add_samples(db_session, H0, count=100, co2=700)
    await rollup.rollup_range(db_session, STATION, H0, H0 + timedelta(hours=1))
    db_session.add(sample(H0 + timedelta(minutes=50), 9999, co2=1700))
    await db_session.flush()
    await rollup.rollup_range(db_session, STATION, H0, H0 + timedelta(hours=1))

    (hour,) = await _hourly(db_session)
    assert hour.sample_count == 101 and hour.co2_max == 1700


async def test_the_gap_to_the_next_chunk_is_measured_not_assumed(db_session):
    # Samples every 40 s straight across the boundary: the last one before it must
    # stand for 40 s, not the 10 s of a series' final snapshot.
    await add_samples(db_session, H0 + timedelta(minutes=50), count=30, step_s=40)
    await rollup.rollup_range(db_session, STATION, H0, H0 + timedelta(hours=1))
    (hour,) = await _hourly(db_session)
    assert hour.coverage_pct == pytest.approx(10 * 60 / 3600 * 100, abs=0.2)


# ── The job ───────────────────────────────────────────────────────────────────
@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("VITALS_ENV_STATION_URL", STATION_URL)
    monkeypatch.setenv("VITALS_ENV_STATION_ID", STATION)


async def _module(db_session, redis, on=True):
    state = await modules_service.set_module_enabled(db_session, key="environment", enabled=on)
    await db_session.commit()
    await modules_service.prime_cache(redis, state)


@freeze_time("2026-10-05T14:30:00")
async def test_the_first_run_backfills_everything_and_is_then_stable(db_session, session_factory, redis, configured):
    await _module(db_session, redis)
    await add_samples(db_session, at("2026-10-05T09:15:00"), count=6 * 60 * 5, step_s=10)  # 5 h
    await db_session.commit()

    await rollup.environment_rollup_job(session_factory, redis)
    hours = [as_utc(h.hour_start) for h in await _hourly(db_session)]
    assert hours == [at(f"2026-10-05T{h:02d}:00:00") for h in (9, 10, 11, 12, 13, 14)]

    snapshot = [(h.id, h.sample_count, h.coverage_pct) for h in await _hourly(db_session)]
    await rollup.environment_rollup_job(session_factory, redis)
    assert [(h.id, h.sample_count, h.coverage_pct) for h in await _hourly(db_session)] == snapshot


@freeze_time("2026-10-05T14:30:00")
async def test_a_later_run_picks_up_new_data_and_the_previous_hour(db_session, session_factory, redis, configured):
    await _module(db_session, redis)
    await add_samples(db_session, at("2026-10-05T13:00:00"), count=6 * 60, step_s=10)
    await db_session.commit()
    await rollup.environment_rollup_job(session_factory, redis)

    await add_samples(db_session, at("2026-10-05T14:00:00"), count=6 * 30, step_s=10, first_seq=10_000)
    db_session.add(sample(at("2026-10-05T13:59:55"), 20_000, co2=2500))  # a late one for 13:00
    await db_session.commit()
    await rollup.environment_rollup_job(session_factory, redis)

    by_hour = {as_utc(h.hour_start): h for h in await _hourly(db_session)}
    assert by_hour[at("2026-10-05T13:00:00")].co2_max == 2500
    assert by_hour[at("2026-10-05T14:00:00")].sample_count == 180


async def test_the_job_does_nothing_without_a_station_or_with_the_module_off(db_session, session_factory, redis, monkeypatch):
    await _module(db_session, redis)
    await add_samples(db_session, H0, count=100)
    await db_session.commit()

    monkeypatch.delenv("VITALS_ENV_STATION_URL", raising=False)
    await rollup.environment_rollup_job(session_factory, redis)
    assert await _hourly(db_session) == []

    monkeypatch.setenv("VITALS_ENV_STATION_URL", STATION_URL)
    await _module(db_session, redis, on=False)
    await rollup.environment_rollup_job(session_factory, redis)
    assert await _hourly(db_session) == []


async def test_the_job_with_no_samples_is_a_no_op(db_session, session_factory, redis, configured):
    await _module(db_session, redis)
    await rollup.environment_rollup_job(session_factory, redis)
    assert await _hourly(db_session) == []


# ── Chart reads over the rollup ───────────────────────────────────────────────
async def test_hour_points_come_from_the_table_and_the_live_tail_agree(db_session):
    now = at("2026-10-05T14:30:00")
    await add_samples(db_session, at("2026-10-05T08:00:00"), count=6 * 60 * 6 + 6 * 30, step_s=10,
                      co2=lambda i: 500 + (i // 360) * 100)  # 08:00-14:30, +100 ppm per hour
    await rollup.rollup_range(db_session, STATION, at("2026-10-05T08:00:00"), at("2026-10-05T15:00:00"))
    await db_session.commit()

    # Corrupt a stored old hour: the read must prefer the table for old hours...
    stored = (await db_session.execute(select(EnvironmentHourly).where(
        EnvironmentHourly.hour_start == at("2026-10-05T09:00:00")))).scalar_one()
    stored.co2_mean = 12345.0
    # ...and recompute the newest two hours from the samples, whatever the table says.
    newest = (await db_session.execute(select(EnvironmentHourly).where(
        EnvironmentHourly.hour_start == at("2026-10-05T14:00:00")))).scalar_one()
    newest.co2_mean = 54321.0
    await db_session.commit()

    pts = await queries.series(db_session, now - timedelta(hours=7), now, resolution="hour")
    by_ts = {p.ts: p for p in pts}
    assert by_ts[at("2026-10-05T09:00:00")].co2_ppm == 12345.0
    assert by_ts[at("2026-10-05T14:00:00")].co2_ppm == 1100.0  # recomputed, not 54321
    assert by_ts[at("2026-10-05T14:00:00")].co2_max == 1100
    assert [p.ts.hour for p in pts] == [8, 9, 10, 11, 12, 13, 14]


async def test_long_coverage_is_read_from_the_hourly_rows(db_session):
    now = at("2026-10-05T14:00:00")
    await add_samples(db_session, now - timedelta(hours=72), count=6 * 60 * 36, step_s=10)  # the first 36 of 72 h
    await rollup.rollup_range(db_session, STATION, now - timedelta(hours=72), now)
    await db_session.commit()
    assert await queries.coverage_pct(db_session, now - timedelta(hours=72), now) == pytest.approx(50.0, abs=0.5)
