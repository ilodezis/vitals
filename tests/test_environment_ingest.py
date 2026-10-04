"""Polling the station into ``environment_samples``."""
from __future__ import annotations

import json
from datetime import timedelta

import pytest
from env_support import STATION_URL, FakeStation, at, esphome_body, sample, snapshot
from sqlalchemy import func, select

from vitals.integrations import esphome_client as ec
from vitals.integrations.esphome_client import StationClient
from vitals.models.environment import (
    Q_CLOCK_UNSYNCED,
    Q_MISSING,
    Q_OUT_OF_RANGE,
    Q_STALE,
    EnvironmentSample,
)
from vitals.services import modules_service
from vitals.services.environment import ingest, live
from vitals.services.environment.ingest import PollOutcome, build_row, poll_once
from vitals.utils.timeutils import as_utc

NOW = at("2026-10-05T12:00:30")
T = int(at("2026-10-05T12:00:25").timestamp())  # the station's clock, 5 s before NOW


async def _rows(session) -> list[EnvironmentSample]:
    return list((await session.execute(select(EnvironmentSample).order_by(EnvironmentSample.id))).scalars())


def _snap(**kw):
    kw.setdefault("t", T)
    return ec.parse_snapshot(esphome_body(snapshot(**kw)))


# ── Turning a snapshot into a row ─────────────────────────────────────────────
def test_a_clean_snapshot_becomes_a_clean_row():
    row = build_row(_snap(lux_max=4.0), station_id="bedroom", received_at=NOW)
    assert row["ts"] == at("2026-10-05T12:00:25") and row["received_at"] == NOW
    assert row["time_basis"] == "device" and row["quality"] == 0
    assert (row["co2_ppm"], row["temperature_c"], row["humidity_pct"]) == (812, 21.4, 41.2)
    assert row["lux_max"] == 4.0 and "lux_max" not in row["extra"]
    assert row["extra"]["rssi"] == -61 and row["extra"]["fw"] == "env-1.1.0"
    assert (row["domain"], row["source"]) == ("environment", "esphome")
    # ``date`` is the *local* calendar date of ts (Chisinau, UTC+3 in October).
    assert row["date"].isoformat() == "2026-10-05"


def test_the_local_date_follows_the_zone_not_utc():
    late = at("2026-10-05T22:30:00")  # 01:30 the next day, local
    row = build_row(_snap(t=int(late.timestamp())), station_id="bedroom", received_at=late)
    assert row["date"].isoformat() == "2026-10-06"


@pytest.mark.parametrize("t", [0, None, 86400, int(at("2025-12-31T00:00:00").timestamp())])
def test_a_station_without_real_time_is_filed_under_the_receipt_time(t):
    row = build_row(_snap(t=t), station_id="bedroom", received_at=NOW)
    assert row["ts"] == NOW and row["time_basis"] == "received"
    assert row["quality"] & Q_CLOCK_UNSYNCED


def test_a_clock_far_from_ours_is_not_trusted_but_not_lost():
    far = int(at("2026-10-05T09:00:00").timestamp())  # 3 h behind the receipt
    row = build_row(_snap(t=far), station_id="bedroom", received_at=NOW)
    assert row["ts"] == NOW and row["time_basis"] == "received"
    assert row["extra"]["t"] == far


def test_impossible_values_are_nulled_and_kept():
    row = build_row(_snap(co2=20000, temp=99.0, rh=130.0), station_id="bedroom", received_at=NOW)
    assert (row["co2_ppm"], row["temperature_c"], row["humidity_pct"]) == (None, None, None)
    assert row["quality"] & Q_OUT_OF_RANGE
    assert row["extra"]["out_of_range"] == {"co2": 20000, "temp": 99.0, "rh": 130.0}


def test_range_edges_are_valid():
    row = build_row(_snap(co2=0, temp=-20.0, rh=100.0), station_id="bedroom", received_at=NOW)
    assert (row["co2_ppm"], row["temperature_c"], row["humidity_pct"]) == (0, -20.0, 100.0)
    assert not row["quality"] & Q_OUT_OF_RANGE


def test_a_missing_sensor_is_flagged_and_stays_null():
    row = build_row(_snap(co2=None), station_id="bedroom", received_at=NOW)
    assert row["co2_ppm"] is None and row["temperature_c"] == 21.4
    assert row["quality"] & Q_MISSING and not row["quality"] & Q_OUT_OF_RANGE


# ── poll_once ─────────────────────────────────────────────────────────────────
async def test_a_poll_stores_one_row(db_session):
    station = FakeStation(snapshot(seq=10, t=T))
    outcome = await poll_once(db_session, station.client(), now=NOW, station_id="bedroom")
    assert outcome is PollOutcome.INSERTED

    (row,) = await _rows(db_session)
    assert (row.station_id, row.boot_id, row.seq) == ("bedroom", "9f3a1c2e", 10)
    assert as_utc(row.ts) == at("2026-10-05T12:00:25")
    assert row.co2_ppm == 812 and row.domain == "environment" and row.source == "esphome"


async def test_asking_twice_for_the_same_snapshot_changes_nothing(db_session):
    station = FakeStation(snapshot(seq=10, t=T))
    client = station.client()
    assert await poll_once(db_session, client, now=NOW) is PollOutcome.INSERTED
    assert await poll_once(db_session, client, now=NOW + timedelta(seconds=10)) is PollOutcome.DUPLICATE
    assert len(await _rows(db_session)) == 1


async def test_a_new_seq_is_a_new_row_and_a_reboot_never_collides(db_session):
    station = FakeStation()
    client = station.client()
    for boot, seq in (("aaaa", 1), ("aaaa", 2), ("bbbb", 1), ("bbbb", 2)):
        station.current = snapshot(boot=boot, seq=seq, t=T)
        assert await poll_once(db_session, client, now=NOW) is PollOutcome.INSERTED
    assert len(await _rows(db_session)) == 4
    # The pair identifies the snapshot: seq 1 of the first boot is still one row.
    station.current = snapshot(boot="aaaa", seq=1, t=T)
    assert await poll_once(db_session, client, now=NOW) is PollOutcome.DUPLICATE


async def test_a_failed_poll_writes_nothing_and_reports_the_error(db_session, redis):
    station = FakeStation()
    station.status = 500
    outcome = await poll_once(db_session, station.client(), redis=redis, now=NOW, station_id="bedroom")
    assert outcome is PollOutcome.ERROR
    assert await _rows(db_session) == []
    state = await redis.hgetall(live.station_key("bedroom"))
    assert state["last_error"] == ec.BAD_STATUS and state["fail_count"] == "1"


async def test_failures_back_off_up_to_five_minutes_and_a_success_resets(db_session, redis):
    station = FakeStation()
    station.status = 500
    client = station.client()
    pauses = []
    for _ in range(8):
        await poll_once(db_session, client, redis=redis, now=NOW, station_id="bedroom")
        state = await redis.hgetall(live.station_key("bedroom"))
        pauses.append(round(float(state["retry_at"]) - NOW.timestamp()))
    assert pauses[:4] == [10, 20, 40, 80]
    assert max(pauses) == ingest.MAX_BACKOFF_S == 300
    assert pauses == sorted(pauses)

    station.status = 200
    station.current = snapshot(seq=1, t=T)
    assert await poll_once(db_session, client, redis=redis, now=NOW, station_id="bedroom") is PollOutcome.INSERTED
    state = await redis.hgetall(live.station_key("bedroom"))
    assert state["fail_count"] == "0" and state["retry_at"] == "" and state["last_error"] == ""
    assert state["boot"] == "9f3a1c2e" and state["seq_head"] == "1" and state["last_ok_at"]


async def test_a_poll_publishes_the_live_reading(db_session, redis):
    station = FakeStation(snapshot(seq=3, t=T, co2=905))
    await poll_once(db_session, station.client(), redis=redis, now=NOW, station_id="bedroom")
    cached = json.loads(await redis.get(live.live_key("bedroom")))
    assert cached["co2_ppm"] == 905 and cached["seq"] == 3 and cached["rssi"] == -61
    assert 0 < await redis.ttl(live.live_key("bedroom")) <= live.LIVE_TTL_S


async def test_an_older_snapshot_does_not_roll_the_live_reading_back(db_session, redis):
    station = FakeStation()
    client = station.client()
    station.current = snapshot(seq=20, t=T, co2=1000)
    await poll_once(db_session, client, redis=redis, now=NOW, station_id="bedroom")
    station.current = snapshot(boot="old", seq=2, t=T - 300, co2=500)  # replayed from before
    await poll_once(db_session, client, redis=redis, now=NOW, station_id="bedroom")

    assert len(await _rows(db_session)) == 2  # the history keeps both
    assert json.loads(await redis.get(live.live_key("bedroom")))["co2_ppm"] == 1000


async def test_a_frozen_sensor_is_flagged_after_half_an_hour(db_session, redis):
    station = FakeStation()
    client = station.client()
    start = at("2026-10-05T12:00:00")
    for i in range(0, 32 * 60, 60):  # a snapshot a minute, the same three readings
        now = start + timedelta(seconds=i)
        station.current = snapshot(seq=i // 60 + 1, t=int(now.timestamp()), co2=700, temp=22.0, rh=40.0)
        await poll_once(db_session, client, redis=redis, now=now, station_id="bedroom")
    rows = await _rows(db_session)
    flagged = [r.seq for r in rows if r.quality & Q_STALE]
    assert flagged and min(flagged) == 31  # the first snapshot past 30 minutes
    assert not any(r.quality & Q_STALE for r in rows[:30])


async def test_a_moving_sensor_is_never_flagged(db_session, redis):
    station = FakeStation()
    client = station.client()
    start = at("2026-10-05T12:00:00")
    for i in range(40):
        now = start + timedelta(minutes=i)
        station.current = snapshot(seq=i + 1, t=int(now.timestamp()), co2=700 + i)
        await poll_once(db_session, client, redis=redis, now=now, station_id="bedroom")
    assert not any(r.quality & Q_STALE for r in await _rows(db_session))


# ── The scheduled job ─────────────────────────────────────────────────────────
@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("VITALS_ENV_STATION_URL", STATION_URL)
    monkeypatch.setenv("VITALS_ENV_STATION_ID", "bedroom")
    station = FakeStation(snapshot(seq=1, t=int(ingest.now_utc().timestamp())))
    monkeypatch.setattr(
        ingest,
        "client_from_config",
        lambda: StationClient(STATION_URL, "u", "p", transport=station.transport),
    )
    return station


async def _module(db_session, redis, on: bool) -> None:
    state = await modules_service.set_module_enabled(db_session, key="environment", enabled=on)
    await db_session.commit()
    await modules_service.prime_cache(redis, state)


async def test_the_job_polls_and_commits(db_session, session_factory, redis, configured):
    await _module(db_session, redis, True)
    await ingest.environment_poll_job(session_factory, redis)
    assert len(configured.requests) == 1
    assert len(await _rows(db_session)) == 1


async def test_the_job_makes_no_request_without_a_station(db_session, session_factory, redis, monkeypatch):
    await _module(db_session, redis, True)
    monkeypatch.delenv("VITALS_ENV_STATION_URL", raising=False)
    built = []
    monkeypatch.setattr(ingest, "client_from_config", lambda: built.append(1))
    await ingest.environment_poll_job(session_factory, redis)
    assert built == [] and await _rows(db_session) == []


async def test_the_job_makes_no_request_while_the_module_is_off(db_session, session_factory, redis, configured):
    await _module(db_session, redis, False)
    await ingest.environment_poll_job(session_factory, redis)
    assert configured.requests == [] and await _rows(db_session) == []


async def test_the_job_sits_out_a_backoff_pause(db_session, session_factory, redis, configured):
    await _module(db_session, redis, True)
    configured.status = 500
    await ingest.environment_poll_job(session_factory, redis)  # fails, sets a pause
    await ingest.environment_poll_job(session_factory, redis)  # inside the pause: no request
    assert len(configured.requests) == 1


# ── The "check the connection" button ─────────────────────────────────────────
async def test_check_reports_success_even_inside_a_pause(db_session, redis, configured):
    configured.status = 500
    first = await ingest.check_station(db_session, redis)
    assert first == {"ok": False, "status": "never", "error": ec.BAD_STATUS}

    configured.status = 200
    configured.current = snapshot(seq=2, t=int(ingest.now_utc().timestamp()))
    second = await ingest.check_station(db_session, redis)  # not held back by the pause
    assert second == {"ok": True, "status": "online", "error": None}


async def test_check_without_a_station_says_so(db_session, redis, monkeypatch):
    monkeypatch.delenv("VITALS_ENV_STATION_URL", raising=False)
    result = await ingest.check_station(db_session, redis)
    assert result == {"ok": False, "status": "never", "error": ec.NOT_CONFIGURED}


async def test_the_unique_snapshot_key_holds_in_the_database(db_session):
    """On Postgres this is the real constraint; on SQLite the same one."""
    from sqlalchemy.exc import IntegrityError

    db_session.add(sample(NOW, 1))
    await db_session.flush()
    db_session.add(sample(NOW, 1))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
    assert (await db_session.execute(select(func.count()).select_from(EnvironmentSample))).scalar() == 0
