"""The four environment tools: what the connector sees of the bedroom's air.

The module gate (off → refuses and is not listed) lives with the other gated tools in
``test_mcp_module_gate``. Here: with the module on, each tool answers from the shaping
layer, parses its arguments like every other tool, and says when a window was cut.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

mcp_router = pytest.importorskip("web.routers.mcp")

from fixtures.environment import insert_samples, sample_row  # noqa: E402
from vitals.models import SystemAlert  # noqa: E402
from vitals.services.environment import live as env_live  # noqa: E402
from vitals.services.environment import queries  # noqa: E402
from vitals.services.environment.types import (  # noqa: E402
    Co2Stats,
    LiveNow,
    LiveState,
    LiveStation,
    NightSummary,
    Point,
    RangeStats,
    Window,
)
from vitals.utils.timeutils import local_naive_to_utc, today_local  # noqa: E402


@pytest.fixture(autouse=True)
def _use_test_factory(session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)


@pytest.fixture(autouse=True)
async def _module_on(_use_test_factory):
    await mcp_router.set_module("environment", True)


def _local(d: date, hour: int = 0):
    return local_naive_to_utc(datetime(d.year, d.month, d.day, hour))


async def test_live_answers_with_the_reading_and_the_thresholds(monkeypatch):
    seen = {}

    async def fake(session, redis=None, *, now=None):
        seen["redis"] = redis
        return LiveState(
            station=LiveStation(status="online", age_s=3),
            now=LiveNow(co2_ppm=780, co2_zone="good", temperature_c=21.2, humidity_pct=44.0),
        )

    sentinel = object()
    monkeypatch.setattr(env_live, "get_live", fake)
    monkeypatch.setattr(mcp_router, "get_redis_client", lambda: sentinel)

    out = await mcp_router.get_environment_live()

    assert out["station"]["status"] == "online"
    assert out["now"]["co2_ppm"] == 780 and out["now"]["co2_zone"] == "good"
    assert out["thresholds"]["co2_bad"] == 1400
    assert seen["redis"] is sentinel


async def test_live_still_answers_when_no_redis_client_can_be_built(monkeypatch):
    async def fake(session, redis=None, *, now=None):
        return None

    def broken():
        raise RuntimeError("no redis configured")

    monkeypatch.setattr(env_live, "get_live", fake)
    monkeypatch.setattr(mcp_router, "get_redis_client", broken)

    assert (await mcp_router.get_environment_live())["station"] == {"status": "never"}


async def test_history_parses_dates_and_returns_columnar_hours(monkeypatch):
    async def series(session, start, end, *, resolution, station_id="bedroom"):
        return [Point(ts=_local(date(2026, 10, 4), 23), co2_ppm=640.0, temperature_c=20.5, humidity_pct=48.0)]

    async def coverage(session, start, end, *, station_id="bedroom"):
        return 91.0

    monkeypatch.setattr(queries, "series", series)
    monkeypatch.setattr(queries, "coverage_pct", coverage)

    out = await mcp_router.get_environment(start_date="2026-10-04", end_date="2026-10-05")

    assert out["granularity"] == "hour"
    assert out["columns"][:2] == ["ts", "co2_ppm"]
    assert out["rows"] == [["2026-10-04T23:00", 640, 20.5, 48.0]]
    assert out["window"] == {"start": "2026-10-04", "end": "2026-10-05"}


async def test_history_defaults_to_the_last_week_of_hours(monkeypatch):
    calls = []

    async def series(session, start, end, *, resolution, station_id="bedroom"):
        calls.append(resolution)
        return []

    async def coverage(session, start, end, *, station_id="bedroom"):
        return 0.0

    monkeypatch.setattr(queries, "series", series)
    monkeypatch.setattr(queries, "coverage_pct", coverage)

    out = await mcp_router.get_environment()

    assert calls == ["hour"] and out["rows"] == [] and out["count"] == 0
    assert out["window"]["end"] == today_local().isoformat()


async def test_history_says_when_the_window_was_cut(monkeypatch):
    async def series(session, start, end, *, resolution, station_id="bedroom"):
        return []

    async def coverage(session, start, end, *, station_id="bedroom"):
        return 0.0

    monkeypatch.setattr(queries, "series", series)
    monkeypatch.setattr(queries, "coverage_pct", coverage)

    out = await mcp_router.get_environment(start_date="2026-01-01", end_date="2026-10-05", granularity="hour")

    assert out["truncated"] is True and "start_date" in out["hint"]


async def test_history_refuses_raw_granularity():
    out = await mcp_router.get_environment(granularity="sample")

    assert "granularity" in out["error"]


async def test_bad_dates_raise_like_every_other_tool():
    with pytest.raises(ValueError, match="start_date must be a YYYY-MM-DD date"):
        await mcp_router.get_environment(start_date="05.10.2026")
    with pytest.raises(ValueError, match="on_date must be a YYYY-MM-DD date"):
        await mcp_router.get_environment_night(on_date="last night")


async def test_night_defaults_to_today_which_is_last_night(monkeypatch):
    asked = []

    async def fake(session, on_date, *, station_id="bedroom"):
        asked.append(on_date)
        return NightSummary(
            date=on_date, window=Window(start=_local(on_date), end=_local(on_date, 12)),
            samples=100, coverage_pct=90.0,
            co2=Co2Stats(median=700.0, p90=900.0, max=1100.0, minutes_above_warn=30.0),
            temperature=RangeStats(min=19.0, mean=20.0, max=21.0),
            humidity=RangeStats(min=40.0, mean=45.0, max=50.0),
        )

    monkeypatch.setattr(queries, "night_summary", fake)

    out = await mcp_router.get_environment_night()

    assert asked == [today_local()]
    assert out["co2"]["max"] == 1100 and out["thresholds"]["temp_sleep_max"] == 20


async def test_night_without_readings_is_a_note_not_zeros(monkeypatch):
    async def fake(session, on_date, *, station_id="bedroom"):
        return NightSummary(date=on_date, window=Window(start=_local(on_date), end=_local(on_date, 12)))

    monkeypatch.setattr(queries, "night_summary", fake)

    out = await mcp_router.get_environment_night(on_date="2026-09-30")

    assert out["samples"] == 0 and "note" in out and "co2" not in out


async def test_alerts_report_an_episode_with_its_peak(db_session):
    started = datetime(2026, 10, 5, 3, 10)
    db_session.add(SystemAlert(
        domain="environment", severity="warn", message="Душно", alert_key="env_co2_bad",
        entity_ref="e1", created_at=started, resolved_at=datetime(2026, 10, 5, 3, 40),
    ))
    await db_session.commit()
    await insert_samples(db_session, [sample_row(_local(date(2026, 10, 5), 3).replace(minute=20), co2=1610)])

    out = await mcp_router.get_environment_alerts(hours=24 * 7)

    (row,) = out["alerts"]
    assert row["key"] == "env_co2_bad" and row["peak"]["value"] == 1610 and row["ongoing"] is False


async def test_alerts_with_nothing_fired_is_an_empty_list():
    out = await mcp_router.get_environment_alerts()

    assert out["alerts"] == [] and out["hours"] == 24


async def test_the_overview_counts_the_samples_and_the_hours(db_session):
    from vitals.models.environment import EnvironmentHourly

    await insert_samples(db_session, [
        sample_row(datetime(2026, 10, 4, 21, 0, tzinfo=timezone.utc), co2=700, seq=1),
        sample_row(datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc), co2=800, seq=2),
    ])
    db_session.add(EnvironmentHourly(
        station_id="bedroom", hour_start=datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc),
        date=date(2026, 10, 5), domain="environment", source="esphome", sample_count=360, coverage_pct=100.0,
    ))
    await db_session.commit()

    overview = await mcp_router.get_data_overview()

    assert overview["environment_samples"]["count"] == 2
    assert overview["environment_samples"]["earliest"] == "2026-10-05"  # 00:00 local on the 5th
    assert overview["environment_samples"]["latest"] == "2026-10-05"
    assert overview["environment_hourly"]["count"] == 1
