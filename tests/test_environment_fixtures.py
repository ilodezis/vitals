"""The helpers other environment tests build on: a fake station behind
``httpx.MockTransport``, row builders, and a bulk insert into ``environment_samples``.

They are test infrastructure, but a wrong helper fails *other* tests in confusing
ways, so the behaviour the others rely on is pinned here.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from zoneinfo import ZoneInfo

from fixtures.environment import (
    STATION_URL,
    FakeStation,
    flat_rows,
    insert_samples,
    night_rows,
    ramp_rows,
    sample_row,
)

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


async def _fetch(station: FakeStation) -> dict:
    async with httpx.AsyncClient(transport=station.transport, base_url=station.url) as client:
        resp = await client.get("/text_sensor/env_snapshot", auth=station.credentials)
        resp.raise_for_status()
        return json.loads(resp.json()["value"])


def test_the_station_address_is_the_reserved_test_host():
    assert STATION_URL == "http://station.test"


async def test_a_fake_station_answers_through_the_mock_transport():
    station = FakeStation("normal")

    snap = await _fetch(station)

    assert snap["v"] == 1 and snap["seq"] == 1 and 400 < snap["co2"] < 1000


async def test_advancing_the_clock_produces_new_snapshots():
    station = FakeStation("normal", interval=10)
    first = await _fetch(station)
    station.advance(10)
    second = await _fetch(station)
    station.advance(3)
    repeat = await _fetch(station)

    assert (second["boot"], second["seq"]) == (first["boot"], 2)
    assert repeat == second


async def test_wrong_credentials_are_a_401_like_the_device():
    station = FakeStation("normal")
    async with httpx.AsyncClient(transport=station.transport, base_url=station.url) as client:
        resp = await client.get("/text_sensor/env_snapshot", auth=("station-user", "wrong"))

    assert resp.status_code == 401


async def test_an_offline_station_is_a_transport_error_not_a_response():
    station = FakeStation("offline", after=0)

    with pytest.raises(httpx.TransportError):
        await _fetch(station)


async def test_reboot_through_the_fake_station_changes_boot():
    station = FakeStation("reboot", after=60)
    before = await _fetch(station)
    station.advance(60)
    after = await _fetch(station)

    assert after["boot"] != before["boot"] and after["seq"] == 1


def test_sample_row_has_every_column_and_utc_time():
    row = sample_row(NOW, co2=900, temp=22.5, rh=48.0, seq=7)

    assert row["co2_ppm"] == 900 and row["temperature_c"] == 22.5 and row["seq"] == 7
    assert row["ts"] == NOW and row["received_at"] >= NOW
    assert row["domain"] == "environment" and row["source"] == "esphome"
    assert isinstance(row["date"], date)


def test_flat_rows_end_at_now_with_constant_values():
    rows = flat_rows(NOW, minutes=15, co2=1500, interval_s=10)

    assert len(rows) == 15 * 6
    assert rows[-1]["ts"] == NOW - timedelta(seconds=10)
    assert {r["co2_ppm"] for r in rows} == {1500}
    assert len({(r["boot_id"], r["seq"]) for r in rows}) == len(rows)


def test_ramp_rows_climb_linearly():
    rows = ramp_rows(NOW, minutes=10, co2_from=800, co2_to=1400, interval_s=60)
    co2 = [r["co2_ppm"] for r in rows]

    assert co2[0] == 800 and co2[-1] > 1300 and co2 == sorted(co2)


def test_night_rows_cover_the_midnight_to_noon_window_in_local_time():
    rows = night_rows(date(2026, 9, 30), "stuffy", interval_s=60)

    assert len(rows) == 12 * 60
    stamps = [r["ts"] for r in rows]
    assert stamps == sorted(stamps) and stamps[0].astimezone(ZoneInfo("Europe/Chisinau")).hour == 0
    assert max(r["co2_ppm"] for r in rows) >= 1400
    assert {r["date"] for r in rows} == {date(2026, 9, 30)}


async def test_insert_samples_writes_rows_a_reader_can_see(db_session):
    models = pytest.importorskip("vitals.models.environment")
    from sqlalchemy import func, select

    rows = flat_rows(NOW, minutes=5, co2=900, interval_s=30)
    await insert_samples(db_session, rows)

    count = (await db_session.execute(select(func.count()).select_from(models.EnvironmentSample))).scalar_one()
    assert count == len(rows)
