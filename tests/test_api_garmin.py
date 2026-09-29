"""Tests for ``/api/v1/recovery`` — Garmin recovery overview, sleep detail,
nights list, activities, sync, and data import.
"""
from __future__ import annotations

import datetime as dt
from unittest.mock import AsyncMock, patch

import pytest

from vitals.enums import Domain, Source
from vitals.models.garmin import (
    DOMAIN as GARMIN_DOMAIN,
    GarminActivity,
    GarminDaily,
    GarminIntraday,
    SERIES_SLEEP_HR,
    SERIES_SLEEP_HRV,
)
from vitals.utils.timeutils import today_local

RECOVERY = "/api/v1/recovery"


async def test_recovery_routes_guarded(client):
    today = today_local().isoformat()
    for method, path in [
        ("GET", RECOVERY),
        ("GET", f"{RECOVERY}/sleep/{today}"),
        ("GET", f"{RECOVERY}/nights"),
        ("GET", f"{RECOVERY}/activities"),
        ("POST", f"{RECOVERY}/sync"),
        ("POST", f"{RECOVERY}/import"),
    ]:
        r = await client.request(method, path)
        assert r.status_code == 401
        assert r.json() == {"error": "unauthenticated"}


async def test_recovery_empty_overview(auth_client):
    r = await auth_client.get(RECOVERY)
    assert r.status_code == 200
    data = r.json()
    assert set(data) == {
        "date", "today_date", "is_today", "is_configured", "last_sync",
        "headline", "night", "norms", "bars", "days",
    }  # fmt: skip
    assert data["headline"]["sleep_score"] is None
    assert data["night"] is None
    assert data["days"] == []
    assert len(data["bars"]) == 4


async def test_recovery_overview_with_data(auth_client, db_session):
    today = today_local()
    daily = GarminDaily(
        date=today,
        domain=GARMIN_DOMAIN,
        source=Source.GARMIN_API.value,
        sleep_score=85,
        sleep_seconds=7 * 3600,
        hrv_avg=55.0,
        resting_hr=52,
        body_battery_low=25,
        body_battery_high=90,
        avg_stress=22,
        steps=10500,
        awake_seconds=30 * 60,
        rem_sleep_seconds=90 * 60,
        light_sleep_seconds=210 * 60,
        deep_sleep_seconds=90 * 60,
        sleep_start=dt.datetime.combine(today, dt.time(23, 0)),
        sleep_end=dt.datetime.combine(today, dt.time(6, 30)),
    )
    db_session.add(daily)
    await db_session.commit()

    r = await auth_client.get(RECOVERY)
    assert r.status_code == 200
    data = r.json()
    assert data["headline"]["sleep_score"] == 85
    assert data["headline"]["sleep_minutes"] == 420
    assert data["headline"]["hrv"] == 55.0
    assert data["headline"]["rhr"] == 52
    assert data["headline"]["body_battery_from"] == 25
    assert data["headline"]["body_battery_to"] == 90
    assert data["night"] is not None
    assert data["night"]["start"] == "23:00"
    assert data["night"]["end"] == "06:30"
    assert len(data["days"]) == 1
    assert data["days"][0]["sleep"] == 85


async def test_sleep_night_detail_not_found(auth_client):
    r = await auth_client.get(f"{RECOVERY}/sleep/2020-01-01")
    assert r.status_code == 404
    assert r.json() == {"error": "not_found"}


async def test_sleep_night_detail_with_curves(auth_client, db_session):
    day = dt.date(2026, 3, 15)
    start_dt = dt.datetime(2026, 3, 14, 23, 0)
    end_dt = dt.datetime(2026, 3, 15, 7, 0)

    daily = GarminDaily(
        date=day,
        domain=GARMIN_DOMAIN,
        source=Source.GARMIN_API.value,
        sleep_score=80,
        sleep_seconds=8 * 3600,
        resting_hr=50,
        sleep_start=start_dt,
        sleep_end=end_dt,
        deep_sleep_seconds=120 * 60,
        light_sleep_seconds=240 * 60,
        rem_sleep_seconds=100 * 60,
        awake_seconds=20 * 60,
        sleep_stages=[
            {"stage": "light", "start": "2026-03-14T23:00:00Z", "end": "2026-03-15T01:00:00Z"},
            {"stage": "deep", "start": "2026-03-15T01:00:00Z", "end": "2026-03-15T03:00:00Z"},
        ],
    )
    hr_pt = GarminIntraday(
        date=day,
        domain=GARMIN_DOMAIN,
        source=Source.GARMIN_API.value,
        series_type=SERIES_SLEEP_HR,
        ts=dt.datetime(2026, 3, 14, 23, 30),
        value=52.0,
    )
    hrv_pt = GarminIntraday(
        date=day,
        domain=GARMIN_DOMAIN,
        source=Source.GARMIN_API.value,
        series_type=SERIES_SLEEP_HRV,
        ts=dt.datetime(2026, 3, 14, 23, 30),
        value=58.0,
    )
    db_session.add_all([daily, hr_pt, hrv_pt])
    await db_session.commit()

    r = await auth_client.get(f"{RECOVERY}/sleep/{day.isoformat()}")
    assert r.status_code == 200
    body = r.json()
    assert body["score"] == 80
    assert body["stages_minutes"]["deep"] == 120
    assert body["stages_minutes"]["light"] == 240
    assert len(body["stages_series"]) == 2
    assert len(body["heart_rate"]) >= 1
    assert body["heart_rate"][0]["value"] == 52.0
    assert len(body["hrv"]) >= 1
    assert body["hrv"][0]["value"] == 58.0


async def test_nights_list(auth_client, db_session):
    d1 = GarminDaily(
        date=dt.date(2026, 3, 10),
        domain=GARMIN_DOMAIN,
        source=Source.GARMIN_API.value,
        sleep_score=75,
        sleep_seconds=7 * 3600,
    )
    d2 = GarminDaily(
        date=dt.date(2026, 3, 11),
        domain=GARMIN_DOMAIN,
        source=Source.GARMIN_API.value,
        sleep_score=82,
        sleep_seconds=8 * 3600,
    )
    db_session.add_all([d1, d2])
    await db_session.commit()

    r = await auth_client.get(f"{RECOVERY}/nights")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    scores = [n["score"] for n in body["nights"]]
    assert 82 in scores
    assert 75 in scores


async def test_activities_list(auth_client, db_session):
    act = GarminActivity(
        external_id="12345678",
        date=dt.date(2026, 3, 12),
        domain=GARMIN_DOMAIN,
        source=Source.GARMIN_API.value,
        name="Morning Run",
        activity_type="running",
        start_time=dt.datetime(2026, 3, 12, 7, 30),
        duration_seconds=1800,
        calories=350,
        distance_m=5000.0,
        avg_hr=145,
        max_hr=168,
    )
    db_session.add(act)
    await db_session.commit()

    r = await auth_client.get(f"{RECOVERY}/activities")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["activities"][0]["name"] == "Morning Run"
    assert body["activities"][0]["activity_type"] == "running"
    assert body["activities"][0]["calories"] == 350


async def test_sync_unconfigured_or_mocked(auth_client):
    # Unconfigured client
    with patch("web.api.garmin.GarminClient.from_config") as mock_client:
        mock_instance = AsyncMock()
        mock_instance.is_configured = False
        mock_client.return_value = mock_instance

        r = await auth_client.post(f"{RECOVERY}/sync")
        assert r.status_code == 200
        assert r.json() == {"ok": False, "synced_days": 0, "error": "not_configured"}

    # Mocked successful sync
    with patch("web.api.garmin.GarminClient.from_config") as mock_client, \
         patch("web.api.garmin.garmin_service.sync", new_callable=AsyncMock) as mock_sync:
        mock_instance = AsyncMock()
        mock_instance.is_configured = True
        mock_client.return_value = mock_instance
        mock_sync.return_value = {"days": 3}

        r = await auth_client.post(f"{RECOVERY}/sync")
        assert r.status_code == 200
        assert r.json() == {"ok": True, "synced_days": 3, "error": None}


async def test_import_garmin_json(auth_client):
    with patch("web.api.garmin.garmin_service.ingest_health_auto_export", new_callable=AsyncMock) as mock_ingest:
        mock_ingest.return_value = {"dates": [dt.date(2026, 3, 14), dt.date(2026, 3, 15)]}

        # JSON body import
        r = await auth_client.post(f"{RECOVERY}/import", json={"data": {"metrics": []}})
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert len(r.json()["imported_dates"]) == 2
