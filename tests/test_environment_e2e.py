"""The whole path on simulated hardware: the station simulator → the real client and
``poll_once`` → ``environment_samples`` → the rollup → the real reads → the MCP tools.

Everything above the sensor is real; only the HTTP hop is a mock transport. It is the
test that notices when the simulator and the poller stop agreeing on the snapshot
contract, or when a tool and the storage layer's reads drift apart.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

mcp_router = pytest.importorskip("web.routers.mcp")

from fixtures.environment import FakeStation, poll_many  # noqa: E402
from vitals.models.environment import EnvironmentSample  # noqa: E402
from vitals.services.environment import rollup  # noqa: E402
from vitals.utils.timeutils import local_naive_to_utc  # noqa: E402

NIGHT = date(2026, 9, 30)


def night_start_epoch() -> float:
    """The moment the simulated night begins: 00:00 local on NIGHT."""
    return local_naive_to_utc(datetime(NIGHT.year, NIGHT.month, NIGHT.day)).timestamp()


@pytest.fixture(autouse=True)
async def _tools_on(session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(mcp_router, "get_redis_client", lambda: None)
    await mcp_router.set_module("environment", True)


async def _count(session) -> int:
    return (await session.execute(select(func.count()).select_from(EnvironmentSample))).scalar_one()


async def test_a_simulated_co2_climb_shows_up_as_a_night_summary(db_session):
    """A tenth-speed hour of the room clock fills the first hour of the night window."""
    station = FakeStation("co2_rising", start=night_start_epoch(), speed=10, seed=3)

    outcomes = await poll_many(db_session, station, count=360)  # one hour of snapshots, 10 s apart
    await db_session.commit()

    assert outcomes.count("inserted") == 360
    night = await mcp_router.get_environment_night(on_date=NIGHT.isoformat())

    assert night["samples"] == 360
    assert 1590 <= night["co2"]["max"] <= 1700
    assert night["co2"]["minutes_above_bad"] > 0.5
    assert night["co2"]["minutes_above_warn"] >= night["co2"]["minutes_above_bad"]
    # one hour of a twelve-hour window: the rest is a gap, and the summary says so
    assert 7.5 <= night["coverage_pct"] <= 9.0
    assert night["window"] == {"start": "2026-09-30T00:00", "end": "2026-09-30T12:00"}


async def test_the_rolled_up_hours_follow_the_scenario(db_session):
    station = FakeStation("co2_rising", start=night_start_epoch(), speed=10, seed=3)
    await poll_many(db_session, station, count=360)
    start_hour = datetime.fromtimestamp(night_start_epoch(), tz=timezone.utc)
    await rollup.rollup_range(db_session, "bedroom", start_hour, start_hour + timedelta(hours=2))
    await db_session.commit()

    out = await mcp_router.get_environment(start_date=NIGHT.isoformat(), end_date=NIGHT.isoformat(), granularity="hour")

    assert out["columns"][:2] == ["ts", "co2_ppm"]
    first = dict(zip(out["columns"], out["rows"][0]))
    assert first["ts"] == "2026-09-30T00:00"
    assert first["co2_max"] >= 1590 and first["co2_min"] < 800
    assert first["co2_ppm"] > first["co2_min"]
    assert 0 < out["coverage_pct"] <= 100


async def test_a_reboot_keeps_every_snapshot_because_boot_and_seq_travel_together(db_session):
    station = FakeStation("reboot", start=night_start_epoch(), after=300)

    outcomes = await poll_many(db_session, station, count=60)  # 10 minutes; reboots at 5
    await db_session.commit()

    assert set(outcomes) == {"inserted"}
    boots = (await db_session.execute(select(EnvironmentSample.boot_id).distinct())).scalars().all()
    assert len(boots) == 2 and await _count(db_session) == 60


async def test_polling_the_same_snapshot_twice_stores_it_once(db_session):
    station = FakeStation("normal", start=night_start_epoch())

    outcomes = await poll_many(db_session, station, count=5, step=0)  # the clock never moves

    assert outcomes == ["inserted", "duplicate", "duplicate", "duplicate", "duplicate"]
    assert await _count(db_session) == 1


async def test_a_station_without_a_clock_is_stored_by_arrival_time(db_session):
    station = FakeStation("normal", start=night_start_epoch(), unsynced=True)

    await poll_many(db_session, station, count=3)
    await db_session.commit()

    rows = (await db_session.execute(select(EnvironmentSample))).scalars().all()
    assert {r.time_basis for r in rows} == {"received"}
    assert all(r.quality & 8 for r in rows)


async def test_a_cold_start_snapshot_is_stored_with_missing_readings_flagged(db_session):
    station = FakeStation("normal", start=night_start_epoch(), cold_start=True)

    await poll_many(db_session, station, count=2)
    await db_session.commit()

    first, second = (
        await db_session.execute(select(EnvironmentSample).order_by(EnvironmentSample.seq))
    ).scalars().all()
    assert first.co2_ppm is None and first.quality & 1
    assert second.co2_ppm is not None and not second.quality & 1


async def test_a_dropped_connection_is_an_error_outcome_not_a_crash(db_session):
    station = FakeStation("offline", start=night_start_epoch(), after=0)

    assert await poll_many(db_session, station, count=2) == ["error", "error"]
    assert await _count(db_session) == 0


async def test_the_live_tool_reads_what_the_poller_just_stored(db_session):
    """Unlike the night, "now" is the real clock: poll at this instant."""
    from datetime import datetime as dt

    now = dt.now(timezone.utc)
    station = FakeStation("normal", start=now.timestamp(), seed=1)

    await poll_many(db_session, station, count=1, real_now=True)
    await db_session.commit()
    live = await mcp_router.get_environment_live()

    assert live["station"]["status"] == "online"
    assert 450 <= live["now"]["co2_ppm"] < 800 and live["now"]["co2_zone"] == "good"
