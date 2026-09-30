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
    SERIES_BODY_BATTERY,
    SERIES_HEART_RATE,
    SERIES_SLEEP_BB,
    SERIES_SLEEP_HR,
    SERIES_SLEEP_HRV,
    SERIES_SLEEP_SPO2,
    SERIES_SLEEP_STRESS,
    SERIES_STRESS,
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
        "headline", "activity", "intraday", "advice",
        "night", "norms", "norms_days", "norms_min_days", "bars", "days",
    }  # fmt: skip
    assert data["intraday"] == {"stress": [], "body_battery": [], "heart_rate": []}
    assert data["advice"] is None
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


async def test_a_health_auto_export_file_is_imported(auth_client, db_session):
    """The real service, not a stand-in: an uploaded file ends up as daily rows and
    the answer says how many days it wrote."""
    import json

    from sqlalchemy import select

    export = {
        "data": {
            "metrics": [
                {"name": "step_count", "data": [
                    {"date": "2026-03-14 00:00:00 +0000", "qty": 9100},
                    {"date": "2026-03-15 00:00:00 +0000", "qty": 7400},
                ]},
                {"name": "resting_heart_rate", "data": [{"date": "2026-03-14 00:00:00 +0000", "qty": 52}]},
            ]
        }
    }

    r = await auth_client.post(
        f"{RECOVERY}/import",
        files=[("file", ("export.json", json.dumps(export).encode(), "application/json"))],
    )

    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["imported_days"] == 2
    rows = (await db_session.execute(select(GarminDaily).order_by(GarminDaily.date))).scalars().all()
    assert [(row.date, row.steps) for row in rows] == [(dt.date(2026, 3, 14), 9100), (dt.date(2026, 3, 15), 7400)]


async def test_a_file_that_is_not_json_is_a_400(auth_client):
    r = await auth_client.post(
        f"{RECOVERY}/import", files=[("file", ("export.json", b"not json", "application/json"))]
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid"


# ── Personal corridors ────────────────────────────────────────────────────────


def _daily(day: dt.date, **values):
    return GarminDaily(date=day, domain=GARMIN_DOMAIN, source=Source.GARMIN_API.value, **values)


def test_norms_are_mean_plus_minus_one_deviation_of_the_days_before_today():
    from types import SimpleNamespace

    from vitals.services import garmin_service

    today = dt.date(2026, 9, 30)
    # 20 earlier days alternating 50 / 60 (mean 55, deviation 5), and an outlier today
    # that must not move its own yardstick.
    rows = [
        SimpleNamespace(date=today - dt.timedelta(days=i), hrv_avg=50 if i % 2 else 60, resting_hr=None)
        for i in range(1, 21)
    ]
    rows.append(SimpleNamespace(date=today, hrv_avg=5, resting_hr=None))

    norms = garmin_service.norms_from(rows, today)

    assert norms["hrv"] == {"lo": 50.0, "hi": 60.0, "better": 1, "days": 20}
    assert "rhr" not in norms  # nothing recorded — no corridor, not a default one


def test_norms_need_enough_history_and_ignore_days_outside_the_window():
    from types import SimpleNamespace

    from vitals.services import garmin_service

    today = dt.date(2026, 9, 30)
    few = [SimpleNamespace(date=today - dt.timedelta(days=i), hrv_avg=50) for i in range(1, 14)]
    assert garmin_service.norms_from(few, today) == {}

    old = [SimpleNamespace(date=today - dt.timedelta(days=i), hrv_avg=50) for i in range(61, 100)]
    assert garmin_service.norms_from(old, today) == {}


async def test_recovery_without_history_shows_values_without_a_corridor(auth_client, db_session):
    from vitals.utils.timeutils import today_local

    db_session.add(_daily(today_local(), hrv_avg=52.0, resting_hr=51, sleep_score=80))
    await db_session.commit()

    body = (await auth_client.get(RECOVERY)).json()

    assert body["norms"] == {}
    assert body["norms_days"] == 0
    assert body["norms_min_days"] == 14
    hrv = next(b for b in body["bars"] if b["key"] == "hrv")
    assert hrv["value"] == 52.0 and hrv["lo"] is None and hrv["hi"] is None and hrv["unit"] == "ms"
    assert body["headline"]["rhr_note"] == ""


async def test_recovery_corridor_comes_from_his_own_days(auth_client, db_session):
    from vitals.utils.timeutils import today_local

    today = today_local()
    for i in range(1, 21):
        db_session.add(_daily(today - dt.timedelta(days=i), hrv_avg=80.0 if i % 2 else 90.0, resting_hr=44 if i % 2 else 46))
    db_session.add(_daily(today, hrv_avg=70.0, resting_hr=50))
    await db_session.commit()

    body = (await auth_client.get(RECOVERY)).json()

    # Far from the old fixed 45–65 / 48–58 ranges: these are his numbers.
    assert body["norms"]["hrv"] == {"lo": 80.0, "hi": 90.0, "better": 1, "unit": "ms"}
    assert body["norms"]["rhr"] == {"lo": 44.0, "hi": 46.0, "better": -1, "unit": "bpm"}
    assert body["norms_days"] == 20
    assert body["headline"]["rhr_note"] == "above"
    assert body["headline"]["hrv_nights_below"] == 1
    hrv = next(b for b in body["bars"] if b["key"] == "hrv")
    assert hrv["tone"] == "bad" and hrv["max"] >= 90.0


async def test_recovery_overview_day_details(auth_client, db_session, redis):
    """The day strip, the recovery observation, the day's curves and the last sync time."""
    today = today_local()
    db_session.add(
        GarminDaily(
            date=today,
            domain=GARMIN_DOMAIN,
            source=Source.GARMIN_API.value,
            sleep_score=40,
            steps=8000,
            avg_stress=31,
            intensity_minutes_moderate=20,
            intensity_minutes_vigorous=15,
            active_calories=640,
            awake_count=3,
        )
    )
    # A night sample on the same date stays on the sleep screen.
    for series, hour, value in [
        (SERIES_STRESS, 9, 25.0),
        (SERIES_BODY_BATTERY, 9, 70.0),
        (SERIES_HEART_RATE, 10, 64.0),
        (SERIES_SLEEP_HR, 2, 50.0),
    ]:
        db_session.add(
            GarminIntraday(
                date=today,
                domain=GARMIN_DOMAIN,
                source=Source.GARMIN_API.value,
                series_type=series,
                ts=dt.datetime.combine(today, dt.time(hour, 0)),
                value=value,
            )
        )
    await db_session.commit()
    await redis.set("sync:last_success:garmin", "1790000000")

    data = (await auth_client.get(RECOVERY)).json()
    assert data["activity"] == {
        "steps": 8000,
        "stress": 31,
        "intensity_moderate": 20,
        "intensity_vigorous": 15,
        "active_calories": 640,
    }
    assert [p["value"] for p in data["intraday"]["stress"]] == [25.0]
    assert data["intraday"]["stress"][0]["ts"].startswith(today.isoformat())
    assert [p["value"] for p in data["intraday"]["body_battery"]] == [70.0]
    assert [p["value"] for p in data["intraday"]["heart_rate"]] == [64.0]
    assert data["advice"]  # a sleep score of 40 is worth a word
    assert data["days"][0]["awake_count"] == 3
    # An ISO timestamp the screen formats, not a pre-formatted string.
    assert dt.datetime.fromisoformat(data["last_sync"])


async def test_sleep_night_need_breathing_and_recovery_curves(auth_client, db_session):
    day = dt.date(2026, 4, 2)
    db_session.add(
        GarminDaily(
            date=day,
            domain=GARMIN_DOMAIN,
            source=Source.GARMIN_API.value,
            sleep_score=70,
            sleep_seconds=7 * 3600,
            sleep_need_actual=480,
            breathing_disruption="MODERATE",
        )
    )
    for series, value in [(SERIES_SLEEP_SPO2, 93.0), (SERIES_SLEEP_STRESS, 12.0), (SERIES_SLEEP_BB, 55.0)]:
        db_session.add(
            GarminIntraday(
                date=day,
                domain=GARMIN_DOMAIN,
                source=Source.GARMIN_API.value,
                series_type=series,
                ts=dt.datetime(2026, 4, 1, 23, 45),
                value=value,
            )
        )
    await db_session.commit()

    data = (await auth_client.get(f"{RECOVERY}/sleep/{day.isoformat()}")).json()
    assert data["sleep_need_minutes"] == 480
    assert data["breathing_disrupted"] is True
    assert [p["value"] for p in data["spo2"]] == [93.0]
    assert [p["value"] for p in data["stress"]] == [12.0]
    assert [p["value"] for p in data["body_battery"]] == [55.0]
    assert data["body_battery"][0]["ts"] == "2026-04-01T23:45:00"


async def test_nights_list_carries_times_awakenings_and_battery(auth_client, db_session):
    day = dt.date(2026, 4, 3)
    db_session.add(
        GarminDaily(
            date=day,
            domain=GARMIN_DOMAIN,
            source=Source.GARMIN_API.value,
            sleep_score=77,
            sleep_seconds=7 * 3600,
            sleep_start=dt.datetime(2026, 4, 2, 23, 10),
            sleep_end=dt.datetime(2026, 4, 3, 6, 40),
            awake_count=2,
            body_battery_change=48,
        )
    )
    await db_session.commit()

    night = (await auth_client.get(f"{RECOVERY}/nights")).json()["nights"][0]
    assert night["start_time"] == "23:10"
    assert night["end_time"] == "06:40"
    assert night["awake_count"] == 2
    assert night["bb_change"] == 48


async def test_activities_carry_the_detail(auth_client, db_session):
    db_session.add_all(
        [
            GarminActivity(
                external_id="run-1",
                date=dt.date(2026, 4, 3),
                domain=GARMIN_DOMAIN,
                source=Source.GARMIN_API.value,
                activity_type="running",
                name="Morning run",
                start_time=dt.datetime(2026, 4, 3, 7, 0),
                duration_seconds=1800,
                training_effect_aerobic=3.2,
                training_effect_anaerobic=1.1,
                elevation_gain_m=42.0,
                avg_power=250,
                hr_zone_seconds=[{"zone": 1, "secs": 120.0, "low_hr": None}, {"zone": 2, "secs": 900.0, "low_hr": None}],
                splits=[
                    {"index": 1, "distance_m": 1000.0, "duration_s": 300.0, "avg_hr": 140},
                    {"index": 2, "distance_m": 1000.0, "duration_s": 290.0, "avg_hr": 150},
                ],
            ),
            GarminActivity(
                external_id="lift-1",
                date=dt.date(2026, 4, 2),
                domain=GARMIN_DOMAIN,
                source=Source.GARMIN_API.value,
                activity_type="strength_training",
                start_time=dt.datetime(2026, 4, 2, 18, 0),
                duration_seconds=3600,
                splits=[{"index": 1, "distance_m": None, "duration_s": 3600.0, "avg_hr": 110}],
            ),
        ]
    )
    await db_session.commit()

    items = {a["id"]: a for a in (await auth_client.get(f"{RECOVERY}/activities")).json()["activities"]}
    run = items["run-1"]
    assert run["training_effect_aerobic"] == 3.2
    assert run["training_effect_anaerobic"] == 1.1
    assert run["elevation_gain_meters"] == 42.0
    assert run["avg_power"] == 250
    assert run["hr_zones"] == [{"zone": 1, "seconds": 120.0}, {"zone": 2, "seconds": 900.0}]
    assert [s["avg_hr"] for s in run["splits"]] == [140, 150]
    assert run["splits"][0] == {"index": 1, "distance_meters": 1000.0, "duration_seconds": 300.0, "avg_hr": 140}
    # One lap is the activity itself: no splits table.
    assert items["lift-1"]["splits"] == []
    assert items["lift-1"]["hr_zones"] == []
