"""Garmin service tests — daily normalisation/upsert, the weight bridge with
manual-over-Garmin priority, activities, recovery advice, the MFA alert path,
and the Health Auto Export backup channel."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import func, select

from vitals.integrations.garmin_client import GarminMFARequired
from vitals.models.garmin import GarminActivity, GarminDaily
from vitals.models.raw_payload import RawPayload
from vitals.models.weight import WeightLog
from vitals.services import garmin_service, weight_service
from vitals.utils.timeutils import to_local_naive

# asyncio_mode=auto (pytest.ini) runs the async tests; the pure normalisation
# tests below stay synchronous, so no module-level asyncio mark here.

DAY = date(2026, 6, 10)

# GMT epoch ms for the sleep window used below (night of 2026-06-09 -> 06-10).
_SLEEP_START_GMT_MS = int(datetime(2026, 6, 9, 23, 0, tzinfo=timezone.utc).timestamp() * 1000)
_SLEEP_END_GMT_MS = int(datetime(2026, 6, 10, 6, 30, tzinfo=timezone.utc).timestamp() * 1000)

RAW_DAY = {
    "summary": {
        "totalSteps": 8000,
        "totalKilocalories": 2500,
        "activeKilocalories": 600,
        "bmrKilocalories": 1900,
        "restingHeartRate": 52,
        "minHeartRate": 48,
        "maxHeartRate": 150,
        "averageStressLevel": 30,
        "maxStressLevel": 88,
        "bodyBatteryHighestValue": 85,
        "bodyBatteryLowestValue": 25,
        "moderateIntensityMinutes": 20,
        "vigorousIntensityMinutes": 10,
        "floorsAscended": 12,
        "avgWakingRespirationValue": 14.5,
    },
    "sleep": {
        "dailySleepDTO": {
            "sleepTimeSeconds": 27000,
            "deepSleepSeconds": 6000,
            "lightSleepSeconds": 15000,
            "remSleepSeconds": 6000,
            "awakeSleepSeconds": 300,
            "sleepScores": {"overall": {"value": 78}},
            "sleepStartTimestampGMT": _SLEEP_START_GMT_MS,
            "sleepEndTimestampGMT": _SLEEP_END_GMT_MS,
            "awakeCount": 2,
            "restlessMomentsCount": 8,
            "avgSleepStress": 18,
            "avgHeartRate": 54,
            "lowestSpO2Value": 91,
            "lowestRespirationValue": 12.5,
            "highestRespirationValue": 16.0,
            "breathingDisruptionSeverity": "NONE",
            "nextSleepNeed": {"actual": 480},
        },
        "bodyBatteryChange": 55,
    },
    "hrv": {"hrvSummary": {"lastNightAvg": 45, "status": "BALANCED", "weeklyAvg": 47}},
    "training_readiness": [{"score": 72}],
    "max_metrics": [{"generic": {"vo2MaxValue": 48.0}}],
    "training_status": {
        "userId": 147716288,
        "mostRecentVO2Max": {"generic": {"vo2MaxValue": 48.0}},
        "mostRecentTrainingLoadBalance": None,
        "mostRecentTrainingStatus": {
            "latestTrainingStatusData": {
                "3635381933": {
                    "calendarDate": "2026-06-10",
                    "trainingStatus": 6,
                    "trainingStatusFeedbackPhrase": "PRODUCTIVE_1",
                    "acuteTrainingLoadDTO": {
                        "acuteTrainingLoad": 450.5,
                        "acwrPercent": 105.0,
                        "acwrStatus": "OPTIMAL",
                    },
                }
            }
        },
        "heatAltitudeAcclimationDTO": None,
    },
    "body_battery": [{"charged": 60, "drained": 40}],
    "body_composition": {"totalAverage": {"weight": 85000.0}},
}


# Per-activity detail bundles (real shapes from get_activity_hr_zones /
# get_activity_splits), keyed as the client merges them under ``_details``.
HR_ZONES_DETAIL = [
    {"zoneNumber": 1, "secsInZone": 1382.487, "zoneLowBoundary": 101},
    {"zoneNumber": 2, "secsInZone": 1569.401, "zoneLowBoundary": 121},
    {"zoneNumber": 3, "secsInZone": 433, "zoneLowBoundary": 141},
    {"zoneNumber": 4, "secsInZone": 0, "zoneLowBoundary": 162},
    {"zoneNumber": 5, "secsInZone": 0, "zoneLowBoundary": 182},
]
SPLITS_DETAIL = {
    "activityId": 12345,
    "lapDTOs": [
        {"lapIndex": 1, "distance": 1000.0, "duration": 300.0,
         "averageHR": 150, "maxHR": 165, "averageSpeed": 3.33},
        {"lapIndex": 2, "distance": 1000.0, "duration": 310.0,
         "averageHR": 155, "maxHR": 168, "averageSpeed": 3.22},
    ],
}
ACTIVITY_DETAILS = {"hr_zones": HR_ZONES_DETAIL, "splits": SPLITS_DETAIL}


class FakeGarminClient:
    def __init__(self, *, daily=None, activities=None, details=None, raise_exc=None):
        self._daily = daily if daily is not None else {DAY: RAW_DAY}
        self._activities = activities or []
        self._details = details or {}
        self._raise = raise_exc
        self.is_configured = True

    async def fetch_daily(self, on_date):
        if self._raise is not None:
            raise self._raise
        return self._daily.get(on_date, {"summary": {}})

    async def fetch_activities(self, start, end):
        return list(self._activities)

    async def fetch_activity_details(self, activity_id):
        return self._details.get(activity_id, {})


# ── Pure normalisation ────────────────────────────────────────────────────────
def test_normalize_daily_extracts_metrics():
    f = garmin_service._normalize_daily(RAW_DAY)
    assert f["steps"] == 8000
    assert f["sleep_seconds"] == 27000
    assert f["sleep_score"] == 78
    assert f["hrv_avg"] == 45.0
    assert f["hrv_status"] == "BALANCED"
    assert f["resting_hr"] == 52
    assert f["body_battery_high"] == 85
    assert f["body_battery_low"] == 25
    assert f["training_readiness"] == 72
    assert f["vo2max"] == 48.0
    assert f["active_calories"] == 600


def test_normalize_daily_extracts_sleep_detail():
    f = garmin_service._normalize_daily(RAW_DAY)
    assert f["sleep_start"] == to_local_naive(datetime(2026, 6, 9, 23, 0, tzinfo=timezone.utc))
    assert f["sleep_end"] == to_local_naive(datetime(2026, 6, 10, 6, 30, tzinfo=timezone.utc))
    assert f["awake_count"] == 2
    assert f["restless_moments"] == 8
    assert f["avg_sleep_stress"] == 18
    assert f["avg_sleep_hr"] == 54
    assert f["spo2_lowest"] == 91
    assert f["respiration_lowest"] == 12.5
    assert f["respiration_highest"] == 16.0
    assert f["body_battery_change"] == 55
    assert f["breathing_disruption"] == "NONE"
    assert f["sleep_need_actual"] == 480


def test_normalize_daily_extracts_training_status():
    f = garmin_service._normalize_daily(RAW_DAY)
    assert f["training_status"] == "PRODUCTIVE"
    assert f["acute_load"] == 450.5
    assert f["load_ratio"] == 105.0


def test_normalize_daily_sparse_is_all_none():
    f = garmin_service._normalize_daily({"summary": {}})
    assert f["steps"] is None
    assert f["sleep_score"] is None
    assert f["vo2max"] is None
    assert f["sleep_start"] is None
    assert f["spo2_lowest"] is None
    assert f["body_battery_change"] is None
    assert f["breathing_disruption"] is None
    assert f["training_status"] is None
    assert f["acute_load"] is None
    assert f["load_ratio"] is None


# ── Training status feedback-phrase level suffix ──────────────────────────────
def test_strip_level_suffix_variants():
    strip = garmin_service._strip_level_suffix
    assert strip("PRODUCTIVE_1") == "PRODUCTIVE"
    assert strip("NO_STATUS_0") == "NO_STATUS"
    assert strip("PEAKING") == "PEAKING"
    assert strip(None) is None


# ── Per-activity detail parsers (HR zones + splits) ───────────────────────────
def test_normalize_hr_zones_from_detail_keeps_boundaries():
    zones = garmin_service._normalize_hr_zones({"_details": {"hr_zones": HR_ZONES_DETAIL}})
    assert zones is not None
    assert len(zones) == 5
    assert zones[0] == {"zone": 1, "secs": 1382.487, "low_hr": 101}
    assert zones[2] == {"zone": 3, "secs": 433.0, "low_hr": 141}


def test_normalize_hr_zones_falls_back_to_summary_fields():
    raw = {"hrTimeInZone_1": 120.0, "hrTimeInZone_2": 300.0, "hrTimeInZone_3": 60.0}
    zones = garmin_service._normalize_hr_zones(raw)
    assert zones == [
        {"zone": 1, "secs": 120.0, "low_hr": None},
        {"zone": 2, "secs": 300.0, "low_hr": None},
        {"zone": 3, "secs": 60.0, "low_hr": None},
    ]


def test_normalize_hr_zones_absent_is_none():
    assert garmin_service._normalize_hr_zones({}) is None


def test_normalize_splits_from_lap_dtos():
    splits = garmin_service._normalize_splits({"_details": {"splits": SPLITS_DETAIL}})
    assert splits is not None
    assert len(splits) == 2
    assert splits[0] == {
        "index": 1, "distance_m": 1000.0, "duration_s": 300.0,
        "avg_hr": 150, "max_hr": 165, "avg_speed_mps": 3.33,
    }


def test_normalize_splits_absent_is_none():
    assert garmin_service._normalize_splits({}) is None
    assert garmin_service._normalize_splits({"_details": {"splits": {"lapDTOs": []}}}) is None


# ── Sleep boundary parsing (GMT vs Local epoch quirk) ─────────────────────────
def test_parse_sleep_boundary_prefers_gmt():
    dto = {"sleepStartTimestampGMT": _SLEEP_START_GMT_MS, "sleepStartTimestampLocal": 0}
    result = garmin_service._parse_sleep_boundary(dto, "sleepStart")
    assert result == to_local_naive(datetime(2026, 6, 9, 23, 0, tzinfo=timezone.utc))


def test_parse_sleep_boundary_falls_back_to_local_as_is():
    # Garmin's "*Local" epoch already bakes the local offset into the ms count, so
    # decoding it as UTC and stripping tzinfo gives the correct wall-clock time
    # directly -- routing it through to_local_naive() would double-shift it.
    local_ms = int(datetime(2026, 6, 9, 23, 0, tzinfo=timezone.utc).timestamp() * 1000)
    dto = {"sleepStartTimestampLocal": local_ms}
    result = garmin_service._parse_sleep_boundary(dto, "sleepStart")
    assert result == datetime(2026, 6, 9, 23, 0)


def test_parse_sleep_boundary_missing_is_none():
    assert garmin_service._parse_sleep_boundary({}, "sleepStart") is None


# ── Daily upsert + raw payload ────────────────────────────────────────────────
async def test_sync_creates_daily_row_and_raw(db_session):
    client = FakeGarminClient()
    summary = await garmin_service.sync(db_session, client, days=1, on_date=DAY)
    await db_session.commit()

    assert summary["days"] == 1
    assert summary["error"] is None

    row = await garmin_service.get_daily(db_session, DAY)
    assert row is not None
    assert row.steps == 8000
    assert row.sleep_score == 78
    assert row.source == "garmin_api"

    raw = (await db_session.execute(
        select(RawPayload).where(RawPayload.external_id == f"daily:{DAY.isoformat()}")
    )).scalars().first()
    assert raw is not None
    assert raw.processed_at is not None
    assert row.raw_payload_id == raw.id


async def test_sync_is_idempotent_per_date(db_session):
    client = FakeGarminClient()
    await garmin_service.sync(db_session, client, days=1, on_date=DAY)
    await db_session.commit()
    await garmin_service.sync(db_session, client, days=1, on_date=DAY)
    await db_session.commit()

    n = (await db_session.execute(select(func.count()).select_from(GarminDaily))).scalar()
    assert n == 1
    n_raw = (await db_session.execute(
        select(func.count()).select_from(RawPayload).where(
            RawPayload.external_id == f"daily:{DAY.isoformat()}"
        )
    )).scalar()
    assert n_raw == 1


async def test_sync_persists_sleep_detail_columns(db_session):
    client = FakeGarminClient()
    await garmin_service.sync(db_session, client, days=1, on_date=DAY)
    await db_session.commit()

    row = await garmin_service.get_daily(db_session, DAY)
    assert row.sleep_start == to_local_naive(datetime(2026, 6, 9, 23, 0, tzinfo=timezone.utc))
    assert row.sleep_end == to_local_naive(datetime(2026, 6, 10, 6, 30, tzinfo=timezone.utc))
    assert row.awake_count == 2
    assert row.restless_moments == 8
    assert row.avg_sleep_stress == 18
    assert row.avg_sleep_hr == 54
    assert row.spo2_lowest == 91
    assert row.respiration_lowest == 12.5
    assert row.respiration_highest == 16.0
    assert row.body_battery_change == 55
    assert row.breathing_disruption == "NONE"
    assert row.sleep_need_actual == 480


async def test_sync_persists_training_status_columns(db_session):
    client = FakeGarminClient()
    await garmin_service.sync(db_session, client, days=1, on_date=DAY)
    await db_session.commit()

    row = await garmin_service.get_daily(db_session, DAY)
    assert row.training_status == "PRODUCTIVE"
    assert row.acute_load == 450.5
    assert row.load_ratio == 105.0


# ── Weight bridge + manual-over-Garmin priority ───────────────────────────────
async def test_daily_bridges_weigh_in_and_manual_supersedes(db_session):
    await garmin_service.ingest_daily(db_session, DAY, RAW_DAY)
    await db_session.commit()

    active = await weight_service.get_active_weight(db_session, DAY)
    assert active is not None
    assert active.weight_kg == 85.0
    assert active.source == "garmin_api"

    # A manual entry for the same date wins.
    await weight_service.log_weight(db_session, on_date=DAY, weight_kg=84.0)
    await db_session.commit()
    active = await weight_service.get_active_weight(db_session, DAY)
    assert active.weight_kg == 84.0
    assert active.source == "manual"
    # Garmin row kept, just superseded (data lake — never deleted).
    rows = (await db_session.execute(select(WeightLog).where(WeightLog.date == DAY))).scalars().all()
    assert len(rows) == 2


# ── Activities ────────────────────────────────────────────────────────────────
async def test_ingest_activities_upserts_by_id(db_session):
    activity = {
        "activityId": 12345,
        "activityName": "Утренняя пробежка",
        "activityType": {"typeKey": "running"},
        "startTimeGMT": "2026-06-10 06:00:00",
        "duration": 1800.0,
        "distance": 5000.0,
        "calories": 350,
        "averageHR": 140,
        "maxHR": 165,
    }
    client = FakeGarminClient(daily={}, activities=[activity])
    summary = await garmin_service.sync(db_session, client, days=1, on_date=DAY)
    await db_session.commit()
    assert summary["activities"] == 1

    rows = (await db_session.execute(select(GarminActivity))).scalars().all()
    assert len(rows) == 1
    assert rows[0].activity_type == "running"
    assert rows[0].distance_m == 5000.0
    assert rows[0].avg_hr == 140

    # Re-sync → upsert, not duplicate.
    await garmin_service.sync(db_session, client, days=1, on_date=DAY)
    await db_session.commit()
    n = (await db_session.execute(select(func.count()).select_from(GarminActivity))).scalar()
    assert n == 1


async def test_sync_persists_activity_detail_columns(db_session):
    activity = {
        "activityId": 12345,
        "activityName": "Утренняя пробежка",
        "activityType": {"typeKey": "running"},
        "startTimeGMT": "2026-06-10 06:00:00",
        "duration": 1800.0,
        "distance": 5000.0,
        "calories": 350,
        "averageHR": 140,
        "maxHR": 165,
        "elevationGain": 42.0,
        "avgPower": 210,
        "aerobicTrainingEffect": 3.4,
        "anaerobicTrainingEffect": 1.1,
    }
    client = FakeGarminClient(
        daily={}, activities=[activity], details={12345: ACTIVITY_DETAILS}
    )
    await garmin_service.sync(db_session, client, days=1, on_date=DAY)
    await db_session.commit()

    row = (await db_session.execute(select(GarminActivity))).scalars().first()
    assert row.elevation_gain_m == 42.0
    assert row.avg_power == 210
    assert row.training_effect_aerobic == 3.4
    assert row.training_effect_anaerobic == 1.1
    # HR zones from the detail call (with boundaries).
    assert row.hr_zone_seconds[0] == {"zone": 1, "secs": 1382.487, "low_hr": 101}
    assert len(row.hr_zone_seconds) == 5
    # Per-lap splits from the detail call.
    assert len(row.splits) == 2
    assert row.splits[0]["distance_m"] == 1000.0
    assert row.splits[1]["avg_hr"] == 155
    # Full detail bundle also captured in the raw payload.
    raw = (await db_session.execute(
        select(RawPayload).where(RawPayload.external_id == "activity:12345")
    )).scalars().first()
    assert raw.payload["_details"]["hr_zones"][0]["zoneNumber"] == 1


# ── MFA / auth alert path ─────────────────────────────────────────────────────
async def test_sync_mfa_raises_warn_alert(db_session):
    from vitals.services import alerts_service

    client = FakeGarminClient(raise_exc=GarminMFARequired("mfa needed"))
    summary = await garmin_service.sync(db_session, client, days=1, on_date=DAY)
    await db_session.commit()

    assert summary["error"] == "mfa"
    active = await alerts_service.list_active(db_session, domain="garmin")
    assert any(a.alert_key == garmin_service.AUTH_ALERT_KEY for a in active)
    assert all(a.severity == "warn" for a in active)


# ── Recovery advice ───────────────────────────────────────────────────────────
async def test_recovery_advice_flags_low_sleep_and_battery(db_session):
    from vitals.i18n import current_lang
    current_lang.set("ru")
    low = GarminDaily(date=DAY, domain="garmin", sleep_score=50, body_battery_high=30)
    advice = garmin_service.recovery_advice(low)
    assert advice is not None
    assert "низкий сон" in advice

    fine = GarminDaily(date=DAY, domain="garmin", sleep_score=85, body_battery_high=90)
    assert garmin_service.recovery_advice(fine) is None
    assert garmin_service.recovery_advice(None) is None


async def test_recovery_advice_flags_low_spo2_and_breathing_disruption(db_session):
    from vitals.i18n import current_lang
    current_lang.set("ru")
    low_spo2 = GarminDaily(date=DAY, domain="garmin", spo2_lowest=85)
    advice = garmin_service.recovery_advice(low_spo2)
    assert advice is not None
    assert "SpO2" in advice

    disrupted = GarminDaily(date=DAY, domain="garmin", breathing_disruption="MILD")
    advice = garmin_service.recovery_advice(disrupted)
    assert advice is not None
    assert "дыхания" in advice

    fine = GarminDaily(date=DAY, domain="garmin", spo2_lowest=95, breathing_disruption="NONE")
    assert garmin_service.recovery_advice(fine) is None


# ── Health Auto Export backup channel ─────────────────────────────────────────
async def test_health_auto_export_ingest(db_session):
    payload = {
        "data": {
            "metrics": [
                {"name": "step_count", "units": "count",
                 "data": [{"date": "2026-06-10 00:00:00 +0000", "qty": 9000}]},
                {"name": "resting_heart_rate", "units": "count/min",
                 "data": [{"date": "2026-06-10 00:00:00 +0000", "qty": 50}]},
                {"name": "sleep_analysis", "units": "hr",
                 "data": [{"date": "2026-06-10 00:00:00 +0000", "qty": 7.5}]},
                {"name": "unmapped_metric", "units": "x",
                 "data": [{"date": "2026-06-10 00:00:00 +0000", "qty": 1}]},
            ]
        }
    }
    result = await garmin_service.ingest_health_auto_export(db_session, payload)
    await db_session.commit()
    assert result["dates"] == 1

    row = await garmin_service.get_daily(db_session, DAY)
    assert row is not None
    assert row.steps == 9000
    assert row.resting_hr == 50
    assert row.sleep_seconds == int(7.5 * 3600)
    assert row.source == "health_auto_export"
