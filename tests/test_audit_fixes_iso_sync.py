import re
from datetime import date, datetime, timezone
import pytest

from vitals.models.garmin import GarminDaily
from vitals.models.hevy import HevyWorkout
from vitals.models.weight import WeightLog
from vitals.services import today_service
from vitals.utils.timeutils import DEFAULT_TIMEZONE, format_iso, now_local, set_timezone, today_local
from web.routers import mcp as mcp_router

_ISO_OFFSET_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$")


def test_format_iso_offsets_and_no_microseconds(monkeypatch):
    prev_tz = DEFAULT_TIMEZONE
    try:
        set_timezone("Europe/Moscow")
        dt = datetime(2026, 10, 28, 14, 9, 55, 123456)
        formatted = format_iso(dt)
        assert formatted == "2026-10-28T14:09:55+03:00"
        assert _ISO_OFFSET_PATTERN.match(formatted)

        utc_dt = datetime(2026, 10, 28, 11, 0, 16, 359075, tzinfo=timezone.utc)
        formatted_utc_to_local = format_iso(utc_dt)
        assert formatted_utc_to_local == "2026-10-28T14:00:16+03:00"

        formatted_utc = format_iso(utc_dt, to_local=False)
        assert formatted_utc == "2026-10-28T11:00:16+00:00"

        assert format_iso(None) is None
    finally:
        set_timezone(prev_tz)


async def test_get_today_now_has_offset(session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    data = await mcp_router.get_today()
    now_str = data["now"]
    assert _ISO_OFFSET_PATTERN.match(now_str)


async def test_get_today_sync_separates_data_date_and_sync_time(db_session, session_factory, monkeypatch):
    from vitals.services import modules_service
    await modules_service.set_module_enabled(db_session, key="hevy", enabled=True)
    await db_session.commit()

    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    today = today_local()

    # Add a Hevy workout from August
    w = HevyWorkout(
        external_id="test_hw_sync",
        domain="workouts",
        source="hevy",
        date=date(2026, 8, 4),
        title="Leg Day",
        start_time=datetime(2026, 8, 4, 16, 33, 10),
    )
    db_session.add(w)
    await db_session.commit()

    class FakeRedis:
        async def get(self, key):
            if key == "sync:last_success:hevy":
                # Synced today at 14:00 UTC
                dt = datetime(2026, 10, 29, 14, 0, 0, tzinfo=timezone.utc)
                return str(int(dt.timestamp()))
            return None

    monkeypatch.setattr(mcp_router, "get_redis_client", lambda: FakeRedis())

    data = await mcp_router.get_today()
    sync_entries = {s["source"]: s for s in data["sync"]}
    assert "Hevy" in sync_entries
    hevy_sync = sync_entries["Hevy"]
    assert hevy_sync["last_data_date"] == "2026-08-04"
    assert _ISO_OFFSET_PATTERN.match(hevy_sync["last_sync_at"])
    assert "2026-10-29T" in hevy_sync["last_sync_at"]


async def test_get_data_overview_last_updated_has_iso_offset(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    wl = WeightLog(
        domain="weight",
        source="manual",
        date=today_local(),
        weight_kg=98.5,
    )
    db_session.add(wl)
    await db_session.commit()

    overview = await mcp_router.get_data_overview()
    weight_overview = overview["weight"]
    assert weight_overview["last_updated"] is not None
    assert _ISO_OFFSET_PATTERN.match(weight_overview["last_updated"])


async def test_get_hevy_workouts_start_time_has_iso_offset(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    w = HevyWorkout(
        external_id="test_hw_dt",
        domain="workouts",
        source="hevy",
        date=date(2026, 8, 4),
        title="Pull Day",
        start_time=datetime(2026, 8, 4, 16, 33, 10),
    )
    db_session.add(w)
    await db_session.commit()

    workouts = await mcp_router.get_hevy_workouts(limit=5)
    matched = [item for item in workouts if item["external_id"] == "test_hw_dt"]
    assert len(matched) == 1
    assert _ISO_OFFSET_PATTERN.match(matched[0]["start_time"])
