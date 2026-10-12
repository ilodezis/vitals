"""Garmin service tests — daily normalisation/upsert, the weight bridge with
manual-over-Garmin priority, activities, intraday stress/Body Battery series,
the nightly sleep series + hypnogram, recovery advice, the MFA alert path, the
Health Auto Export backup channel, and the client's credential-login breaker."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from vitals.config import Config
from vitals.integrations.garmin_client import (
    LOGIN_ATTEMPTS_KEY,
    LOGIN_PAUSE_KEY,
    MAX_LOGINS_PER_DAY,
    REDIS_SESSION_KEY,
    GarminClient,
    GarminLoginThrottled,
    GarminMFARequired,
)
from vitals.integrations.garmin_client import FAILED_KEY
from vitals.models.garmin import (
    SERIES_BODY_BATTERY,
    SERIES_HEART_RATE,
    SERIES_SLEEP_BB,
    SERIES_SLEEP_HR,
    SERIES_SLEEP_HRV,
    SERIES_SLEEP_MOVEMENT,
    SERIES_SLEEP_RESPIRATION,
    SERIES_SLEEP_SPO2,
    SERIES_SLEEP_STRESS,
    SERIES_STRESS,
    SLEEP_SERIES_TYPES,
    GarminActivity,
    GarminDaily,
    GarminIntraday,
)
from vitals.models.raw_payload import RawPayload
from vitals.models.system_alert import SystemAlert
from vitals.models.weight import WeightLog
from vitals.services import garmin_service, weight_service
from vitals.utils.timeutils import to_local_naive

# asyncio_mode=auto (pytest.ini) runs the async tests; the pure normalisation
# tests below stay synchronous, so no module-level asyncio mark here.

DAY = date(2026, 6, 10)

# GMT epoch ms for the sleep window used below (night of 2026-06-09 -> 06-10).
_SLEEP_START_GMT_MS = int(datetime(2026, 6, 9, 23, 0, tzinfo=timezone.utc).timestamp() * 1000)
_SLEEP_END_GMT_MS = int(datetime(2026, 6, 10, 6, 30, tzinfo=timezone.utc).timestamp() * 1000)


def _ms(hour: int, minute: int = 0) -> int:
    """GMT epoch ms for a moment on DAY (Garmin's intraday arrays are epoch-ms)."""
    return int(datetime(2026, 6, 10, hour, minute, tzinfo=timezone.utc).timestamp() * 1000)


def _night_ms(day: int, hour: int, minute: int = 0) -> int:
    """GMT epoch ms for a moment in the night of 06-09 → 06-10 (``day`` is 9 or 10)."""
    return int(datetime(2026, 6, day, hour, minute, tzinfo=timezone.utc).timestamp() * 1000)


def _night_iso(day: int, hour: int, minute: int = 0) -> str:
    """The *other* nightly timestamp shape in the same payload: an ISO-8601 GMT
    string with no offset marker and one fractional digit. Real form, verified
    against the watch's own responses — sleepLevels / sleepMovement / the SpO2
    epochs ship this, while sleepHeartRate / hrvData / … ship epoch ms."""
    return f"2026-06-{day:02d}T{hour:02d}:{minute:02d}:00.0"

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
            "avgSleepStress": 18,
            "avgHeartRate": 54,
            "lowestSpO2Value": 91,
            "lowestRespirationValue": 12.5,
            "highestRespirationValue": 16.0,
            "breathingDisruptionSeverity": "NONE",
            "nextSleepNeed": {"actual": 480},
        },
        "bodyBatteryChange": 55,
        # restlessMomentsCount ships at THIS level in the real payload, not inside
        # dailySleepDTO (verified against real nights 2026-07-16/17) — unlike
        # awakeCount, which does live in dailySleepDTO.
        "restlessMomentsCount": 8,
        # ── The night's minute-level arrays ───────────────────────────────────
        # Shapes verified against real responses from the watch: most arrays are
        # [{value, startGMT: epoch_ms}], but respiration renames both keys, SpO2
        # ships an ISO GMT string, and movement is ISO + its own value key.
        "sleepHeartRate": [
            {"value": 69, "startGMT": _night_ms(9, 23, 0)},
            {"value": 58, "startGMT": _night_ms(10, 2, 0)},
            {"value": 54, "startGMT": _night_ms(10, 5, 0)},
        ],
        "sleepStress": [
            {"value": 12, "startGMT": _night_ms(9, 23, 0)},
            {"value": 20, "startGMT": _night_ms(10, 2, 0)},
        ],
        "sleepBodyBattery": [
            {"value": 35, "startGMT": _night_ms(9, 23, 0)},
            {"value": 100, "startGMT": _night_ms(10, 6, 0)},
        ],
        "hrvData": [
            {"value": 47.0, "startGMT": _night_ms(9, 23, 30)},
            {"value": 52.0, "startGMT": _night_ms(10, 3, 0)},
        ],
        "wellnessEpochRespirationDataDTOList": [
            {"startTimeGMT": _night_ms(9, 23, 0), "respirationValue": 19.0},
            # -2 is Garmin's "no reading" sentinel, seen in the live payload's
            # respiration averages — absence of data, not a breath rate of -2.
            {"startTimeGMT": _night_ms(10, 1, 0), "respirationValue": -2.0},
            {"startTimeGMT": _night_ms(10, 4, 0), "respirationValue": 13.0},
        ],
        "wellnessEpochSPO2DataDTOList": [
            {"epochTimestamp": _night_iso(9, 23, 20), "spo2Reading": 96,
             "epochDuration": 60, "readingConfidence": 2},
            {"epochTimestamp": _night_iso(10, 3, 20), "spo2Reading": 91,
             "epochDuration": 60, "readingConfidence": 1},
        ],
        # Movement tracking starts before the sleep window itself — the first
        # sample here lands on the *previous* calendar evening in local time.
        "sleepMovement": [
            {"startGMT": _night_iso(9, 20, 19), "endGMT": _night_iso(9, 20, 20),
             "activityLevel": 6.14},
            {"startGMT": _night_iso(10, 3, 0), "endGMT": _night_iso(10, 3, 1),
             "activityLevel": 0.0},
        ],
        # The hypnogram: intervals, not points. activityLevel is a stage code
        # (0 deep / 1 light / 2 REM / 3 awake), not a measurement.
        "sleepLevels": [
            {"startGMT": _night_iso(9, 23, 0), "endGMT": _night_iso(9, 23, 30),
             "activityLevel": 1.0},
            {"startGMT": _night_iso(9, 23, 30), "endGMT": _night_iso(10, 1, 0),
             "activityLevel": 0.0},
            {"startGMT": _night_iso(10, 1, 0), "endGMT": _night_iso(10, 2, 0),
             "activityLevel": 2.0},
            {"startGMT": _night_iso(10, 2, 0), "endGMT": _night_iso(10, 6, 30),
             "activityLevel": 3.0},
        ],
        "breathingDisruptionData": [
            {"value": 0, "startGMT": _night_ms(9, 23, 0), "endGMT": _night_ms(10, 1, 0)},
            {"value": 1, "startGMT": _night_ms(10, 1, 0), "endGMT": _night_ms(10, 2, 0)},
        ],
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
    # get_stress_data carries BOTH intraday arrays (real shape, 3-min cadence).
    # Stress sentinels: -1 = no reading, -2 = watch off the wrist.
    "stress": {
        "calendarDate": "2026-06-10",
        "maxStressLevel": 88,
        "avgStressLevel": 30,
        "stressValueDescriptorsDTOList": [
            {"index": 0, "key": "timestamp"},
            {"index": 1, "key": "stressLevel"},
        ],
        "stressValuesArray": [
            [_ms(0, 0), -1],
            [_ms(0, 3), -2],
            [_ms(0, 6), 43],
            [_ms(0, 9), 37],
        ],
        # [timestamp, status, level, version] — the level is NOT the 2nd column.
        "bodyBatteryValueDescriptorsDTOList": [
            {"bodyBatteryValueDescriptorIndex": 0, "bodyBatteryValueDescriptorKey": "timestamp"},
            {"bodyBatteryValueDescriptorIndex": 1, "bodyBatteryValueDescriptorKey": "bodyBatteryStatus"},
            {"bodyBatteryValueDescriptorIndex": 2, "bodyBatteryValueDescriptorKey": "bodyBatteryLevel"},
            {"bodyBatteryValueDescriptorIndex": 3, "bodyBatteryValueDescriptorKey": "bodyBatteryVersion"},
        ],
        "bodyBatteryValuesArray": [
            [_ms(0, 0), "MODELED", 25, 3],
            [_ms(0, 3), "MEASURED", 27, 3],
            [_ms(0, 6), "MEASURED", 30, 3],
            [_ms(0, 9), "MEASURED", 34, 3],
        ],
    },
    # get_heart_rates(ds) — [timestamp, bpm], with a null for every stretch the
    # watch wasn't measuring (off the wrist, charging).
    "heart_rate": {
        "calendarDate": "2026-06-10",
        "heartRateValueDescriptors": [
            {"index": 0, "key": "timestamp"},
            {"index": 1, "key": "heartrate"},
        ],
        "heartRateValues": [
            [_ms(0, 0), None],
            [_ms(0, 2), 58],
            [_ms(0, 4), 61],
        ],
    },
    # get_body_battery(ds, ds) — the same series, but inflection points only and a
    # [timestamp, level] shape. Only a fallback when the stress payload has none.
    "body_battery": [
        {
            "date": "2026-06-10",
            "charged": 60,
            "drained": 40,
            "bodyBatteryValueDescriptorDTOList": [
                {"bodyBatteryValueDescriptorIndex": 0, "bodyBatteryValueDescriptorKey": "timestamp"},
                {"bodyBatteryValueDescriptorIndex": 1, "bodyBatteryValueDescriptorKey": "bodyBatteryLevel"},
            ],
            "bodyBatteryValuesArray": [[_ms(0, 0), 25], [_ms(8, 0), 82]],
        }
    ],
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
    def __init__(
        self, *, daily=None, activities=None, details=None, raise_exc=None,
        token_warnings=None,
    ):
        self._daily = daily if daily is not None else {DAY: RAW_DAY}
        self._activities = activities or []
        self._details = details or {}
        self._raise = raise_exc
        self.is_configured = True
        # The real client collects token-store failures here for the service to
        # turn into an alert.
        self.token_warnings = list(token_warnings or ())

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


# ── Intraday series parsing (stress + Body Battery) ───────────────────────────
def test_intraday_stress_drops_sentinel_readings():
    series = garmin_service._intraday_series(RAW_DAY)
    stress = series[SERIES_STRESS]
    # -1 (no reading) and -2 (off-wrist) are Garmin's sentinels, not stress of -1.
    assert len(stress) == 2
    assert stress[0] == (to_local_naive(datetime(2026, 6, 10, 0, 6, tzinfo=timezone.utc)), 43.0)
    assert stress[1][1] == 37.0


def test_intraday_body_battery_reads_level_column_not_second():
    series = garmin_service._intraday_series(RAW_DAY)
    bb = series[SERIES_BODY_BATTERY]
    # 4 points from the stress payload (full resolution), NOT the 2 inflection
    # points of the body_battery payload; values are the levels, not the status.
    assert len(bb) == 4
    assert [v for _, v in bb] == [25.0, 27.0, 30.0, 34.0]
    assert bb[0][0] == to_local_naive(datetime(2026, 6, 10, 0, 0, tzinfo=timezone.utc))


def test_intraday_body_battery_falls_back_to_range_payload_shape():
    raw = {"stress": {"stressValuesArray": []}, "body_battery": RAW_DAY["body_battery"]}
    bb = garmin_service._intraday_series(raw)[SERIES_BODY_BATTERY]
    # [timestamp, level] shape — the level sits in the 2nd column here.
    assert [v for _, v in bb] == [25.0, 82.0]


def test_intraday_reads_value_position_without_descriptors():
    # A firmware/endpoint variant with no descriptor list still parses: the first
    # numeric column after the timestamp is the value.
    raw = {"stress": {"bodyBatteryValuesArray": [[_ms(1, 0), "MEASURED", 40, 3]]}}
    bb = garmin_service._intraday_series(raw)[SERIES_BODY_BATTERY]
    assert [v for _, v in bb] == [40.0]


def test_intraday_heart_rate_drops_unmeasured_minutes():
    hr = garmin_service._intraday_series(RAW_DAY)[SERIES_HEART_RATE]
    # The ``[ts, null]`` row is "the watch wasn't measuring", not a heart rate of 0.
    assert [v for _, v in hr] == [58.0, 61.0]
    assert hr[0][0] == to_local_naive(datetime(2026, 6, 10, 0, 2, tzinfo=timezone.utc))


def test_intraday_series_absent_is_empty():
    series = garmin_service._intraday_series({"summary": {}})
    assert series[SERIES_STRESS] == []
    assert series[SERIES_BODY_BATTERY] == []
    assert series[SERIES_HEART_RATE] == []


# ── Nightly sleep series parsing ──────────────────────────────────────────────
def test_sleep_series_parse_epoch_ms_arrays():
    series = garmin_service._intraday_series(RAW_DAY)
    assert [v for _, v in series[SERIES_SLEEP_HR]] == [69.0, 58.0, 54.0]
    assert [v for _, v in series[SERIES_SLEEP_STRESS]] == [12.0, 20.0]
    assert [v for _, v in series[SERIES_SLEEP_BB]] == [35.0, 100.0]
    assert [v for _, v in series[SERIES_SLEEP_HRV]] == [47.0, 52.0]
    assert series[SERIES_SLEEP_HR][0][0] == to_local_naive(
        datetime(2026, 6, 9, 23, 0, tzinfo=timezone.utc)
    )


def test_sleep_respiration_reads_its_own_key_names_and_drops_sentinels():
    series = garmin_service._intraday_series(RAW_DAY)
    respiration = series[SERIES_SLEEP_RESPIRATION]
    # The -2 sample is dropped; the other two keep their order.
    assert [v for _, v in respiration] == [19.0, 13.0]
    assert respiration[0][0] == to_local_naive(
        datetime(2026, 6, 9, 23, 0, tzinfo=timezone.utc)
    )


def test_sleep_spo2_and_movement_parse_iso_gmt_timestamps():
    series = garmin_service._intraday_series(RAW_DAY)
    spo2 = series[SERIES_SLEEP_SPO2]
    assert [v for _, v in spo2] == [96.0, 91.0]
    # The ISO string carries no offset marker but is GMT — same conversion as
    # the epoch-ms arrays, so both shapes land on one comparable timeline.
    assert spo2[0][0] == to_local_naive(datetime(2026, 6, 9, 23, 20, tzinfo=timezone.utc))

    movement = series[SERIES_SLEEP_MOVEMENT]
    # 0.0 is a real reading (lying perfectly still), not a sentinel — only
    # negatives are absence of data, so this must survive.
    assert [v for _, v in movement] == [6.14, 0.0]


def test_sleep_series_absent_is_empty():
    series = garmin_service._intraday_series({"summary": {}})
    for series_type in SLEEP_SERIES_TYPES:
        assert series[series_type] == []


def test_normalize_sleep_stages_builds_hypnogram():
    stages = garmin_service._normalize_daily(RAW_DAY)["sleep_stages"]
    assert [s["stage"] for s in stages] == ["light", "deep", "rem", "awake"]
    # Stored as ISO strings: JSON has no datetime, and the chart plots them as-is.
    assert stages[0]["start"] == to_local_naive(
        datetime(2026, 6, 9, 23, 0, tzinfo=timezone.utc)
    ).isoformat()
    assert stages[0]["end"] == stages[1]["start"]


def test_normalize_breathing_events_keeps_every_interval():
    events = garmin_service._normalize_daily(RAW_DAY)["breathing_events"]
    # The undisturbed (value 0) spans are kept too — dropping them would lose the
    # difference between "measured and fine" and "not measured at all".
    assert [e["value"] for e in events] == [0, 1]
    assert events[1]["start"] == events[0]["end"]


def test_normalize_sleep_interval_fields_absent_are_none():
    f = garmin_service._normalize_daily({"summary": {}})
    assert f["sleep_stages"] is None
    assert f["breathing_events"] is None


# ── Nightly sleep series persistence ──────────────────────────────────────────
async def test_sync_persists_sleep_series(db_session):
    await garmin_service.sync(db_session, FakeGarminClient(), days=1, on_date=DAY)
    await db_session.commit()

    rows = (await db_session.execute(
        select(GarminIntraday).where(GarminIntraday.series_type == SERIES_SLEEP_HR)
        .order_by(GarminIntraday.ts)
    )).scalars().all()
    assert [r.value for r in rows] == [69.0, 58.0, 54.0]
    assert rows[0].raw_payload_id is not None

    spo2 = (await db_session.execute(
        select(GarminIntraday).where(GarminIntraday.series_type == SERIES_SLEEP_SPO2)
    )).scalars().all()
    assert len(spo2) == 2


async def test_sleep_samples_are_filed_under_the_nights_daily_date(db_session):
    """A sample recorded before midnight still belongs to the night it was part
    of — the date is the daily row's, not the sample's own calendar day. That's
    what makes "the night of the 10th" one queryable unit instead of two halves."""
    await garmin_service.sync(db_session, FakeGarminClient(), days=1, on_date=DAY)
    await db_session.commit()

    rows = (await db_session.execute(
        select(GarminIntraday).where(GarminIntraday.series_type == SERIES_SLEEP_MOVEMENT)
        .order_by(GarminIntraday.ts)
    )).scalars().all()
    assert rows[0].ts.date() == date(2026, 6, 9)  # the previous evening…
    assert all(r.date == DAY for r in rows)       # …filed under the night of the 10th


async def test_sync_persists_sleep_stages_and_breathing_events(db_session):
    await garmin_service.sync(db_session, FakeGarminClient(), days=1, on_date=DAY)
    await db_session.commit()

    row = await garmin_service.get_daily(db_session, DAY)
    assert [s["stage"] for s in row.sleep_stages] == ["light", "deep", "rem", "awake"]
    assert [e["value"] for e in row.breathing_events] == [0, 1]


async def test_sleep_series_reimport_replaces_without_duplicating(db_session):
    client = FakeGarminClient()
    await garmin_service.sync(db_session, client, days=1, on_date=DAY)
    await db_session.commit()
    await garmin_service.sync(db_session, client, days=1, on_date=DAY)
    await db_session.commit()

    n = (await db_session.execute(
        select(func.count()).select_from(GarminIntraday)
        .where(GarminIntraday.series_type == SERIES_SLEEP_HR)
    )).scalar()
    assert n == 3


# ── Intraday persistence ──────────────────────────────────────────────────────
async def test_sync_persists_intraday_series(db_session):
    client = FakeGarminClient()
    await garmin_service.sync(db_session, client, days=1, on_date=DAY)
    await db_session.commit()

    rows = (await db_session.execute(
        select(GarminIntraday).where(GarminIntraday.series_type == SERIES_STRESS)
        .order_by(GarminIntraday.ts)
    )).scalars().all()
    assert len(rows) == 2
    assert rows[0].value == 43.0
    assert rows[0].date == DAY
    assert rows[0].domain == "garmin"
    assert rows[0].source == "garmin_api"
    assert rows[0].raw_payload_id is not None

    bb = (await db_session.execute(
        select(GarminIntraday).where(GarminIntraday.series_type == SERIES_BODY_BATTERY)
    )).scalars().all()
    assert len(bb) == 4


async def test_intraday_reimport_replaces_without_duplicating(db_session):
    client = FakeGarminClient()
    await garmin_service.sync(db_session, client, days=1, on_date=DAY)
    await db_session.commit()
    await garmin_service.sync(db_session, client, days=1, on_date=DAY)
    await db_session.commit()

    n = (await db_session.execute(
        select(func.count()).select_from(GarminIntraday)
        .where(GarminIntraday.series_type == SERIES_STRESS)
    )).scalar()
    assert n == 2


async def test_intraday_empty_series_keeps_existing_rows(db_session):
    """A day whose fetch came back without the array (a Garmin hiccup) must not
    wipe the samples already captured — the lake never loses data to a bad poll."""
    await garmin_service.sync(db_session, FakeGarminClient(), days=1, on_date=DAY)
    await db_session.commit()

    empty_day = dict(RAW_DAY, stress={"stressValuesArray": []}, body_battery=None)
    await garmin_service.ingest_daily(db_session, DAY, empty_day)
    await db_session.commit()

    n = (await db_session.execute(
        select(func.count()).select_from(GarminIntraday).where(
            GarminIntraday.series_type.in_([SERIES_STRESS, SERIES_BODY_BATTERY])
        )
    )).scalar()
    assert n == 6  # 2 stress + 4 body battery, still there


async def _stored_daily_raw(db_session) -> RawPayload:
    return (await db_session.execute(
        select(RawPayload).where(RawPayload.external_id == f"daily:{DAY.isoformat()}")
    )).scalar_one()


async def test_a_failed_sub_metric_never_erases_a_stored_day(db_session):
    """A 429 on sleep after a good sync used to blank the column *and* the raw
    copy; with a two-day window, a hiccup on the last poll before midnight lost
    the night for good."""
    await garmin_service.sync(db_session, FakeGarminClient(), days=1, on_date=DAY)
    await db_session.commit()

    hiccup = dict(RAW_DAY, sleep=None, hrv=None, _failed=["sleep", "hrv"])
    await garmin_service.sync(
        db_session, FakeGarminClient(daily={DAY: hiccup}), days=1, on_date=DAY
    )
    await db_session.commit()

    row = await garmin_service.get_daily(db_session, DAY)
    assert row.sleep_seconds == 27000
    assert row.hrv_avg == 45.0
    raw = await _stored_daily_raw(db_session)
    assert raw.payload["sleep"] == RAW_DAY["sleep"]
    assert raw.payload["hrv"] == RAW_DAY["hrv"]
    assert "_failed" not in raw.payload


async def test_a_none_sub_metric_keeps_the_stored_one(db_session):
    await garmin_service.sync(db_session, FakeGarminClient(), days=1, on_date=DAY)
    await db_session.commit()

    await garmin_service.ingest_daily(db_session, DAY, dict(RAW_DAY, sleep=None))
    await db_session.commit()

    row = await garmin_service.get_daily(db_session, DAY)
    assert row.sleep_seconds == 27000
    assert (await _stored_daily_raw(db_session)).payload["sleep"] == RAW_DAY["sleep"]


async def test_a_fresh_sub_metric_still_replaces_the_stored_one(db_session):
    await garmin_service.sync(db_session, FakeGarminClient(), days=1, on_date=DAY)
    await db_session.commit()

    fresher = dict(RAW_DAY, summary={**RAW_DAY["summary"], "totalSteps": 9100})
    await garmin_service.ingest_daily(db_session, DAY, fresher)
    await db_session.commit()

    assert (await garmin_service.get_daily(db_session, DAY)).steps == 9100


async def test_a_sub_metric_failing_poll_after_poll_raises_an_alert_that_clears(db_session):
    """Keeping the stored day makes a persistent failure silent — the night just
    never fills in. Past a streak of failed polls it becomes a warn alert."""
    async def _sync(client):
        await garmin_service.sync(db_session, client, days=1, on_date=DAY)
        await db_session.commit()

    async def _active():
        return (await db_session.execute(
            select(SystemAlert).where(
                SystemAlert.alert_key == garmin_service.METRIC_ALERT_KEY,
                SystemAlert.resolved_at.is_(None),
            )
        )).scalars().all()

    failing = FakeGarminClient(daily={DAY: dict(RAW_DAY, sleep=None, _failed=["sleep"])})
    for _ in range(garmin_service.METRIC_FAILURE_STREAK - 1):
        await _sync(failing)
    assert await _active() == []

    await _sync(failing)
    assert [a.entity_ref for a in await _active()] == ["sleep"]

    await _sync(FakeGarminClient())
    assert await _active() == []


async def test_client_lists_the_sub_metrics_that_failed():
    class _Flaky:
        def __getattr__(self, name):
            if name == "get_sleep_data":
                def _boom(*a):
                    raise RuntimeError("429 Too Many Requests")
                return _boom
            return lambda *a: {"ok": name}

    client = GarminClient(Config(database_url="", redis_url=""))
    client._garmin = _Flaky()

    bundle = await client.fetch_daily(DAY)

    assert bundle["sleep"] is None
    assert bundle[FAILED_KEY] == ["sleep"]
    assert bundle["hrv"] == {"ok": "get_hrv_data"}


async def test_every_garmin_pull_shares_one_lock(session_factory, redis, monkeypatch):
    """The brief, the MCP tool, the web button and the poll used to pull at the
    same minute — double the requests, double the 429s."""
    calls = []

    class _Counting(FakeGarminClient):
        async def fetch_daily(self, on_date):
            calls.append(on_date)
            return await super().fetch_daily(on_date)

    monkeypatch.setattr(GarminClient, "from_config", classmethod(lambda cls, *a, **kw: _Counting()))

    # Held by another pull (fakeredis has no Lua, so the key is set by hand).
    lock_key = f"scheduler:lock:{garmin_service.PULL_LOCK_ID}"
    await redis.set(lock_key, "other-pull")
    busy = await garmin_service.sync_job(session_factory, redis, days=1)
    await redis.delete(lock_key)
    assert busy == {"days": 0, "activities": 0, "error": garmin_service.SYNC_BUSY}
    assert calls == []

    done = await garmin_service.sync_job(session_factory, redis, days=1)
    assert done["error"] is None
    assert len(calls) == 1


async def test_intraday_series_map_groups_by_type(db_session):
    await garmin_service.sync(db_session, FakeGarminClient(), days=1, on_date=DAY)
    await db_session.commit()

    series = await garmin_service.intraday_series_map(db_session, DAY)
    # Unfiltered, a day holds the whole-day curves *and* the night's series.
    assert {SERIES_STRESS, SERIES_BODY_BATTERY}.issubset(series)
    assert series[SERIES_STRESS][0]["value"] == 43.0
    # Points carry a local wall-clock timestamp the chart plots directly.
    assert series[SERIES_STRESS][0]["ts"].endswith(":06:00")
    assert len(series[SERIES_BODY_BATTERY]) == 4

    assert await garmin_service.intraday_series_map(db_session, date(2020, 1, 1)) == {}


async def test_intraday_series_map_filters_to_requested_series(db_session):
    """The day chart asks for the whole-day curves only; without the filter the
    night's ~2k samples would ride along into the page for nothing."""
    await garmin_service.sync(db_session, FakeGarminClient(), days=1, on_date=DAY)
    await db_session.commit()

    series = await garmin_service.intraday_series_map(
        db_session, DAY, series_types=(SERIES_STRESS, SERIES_BODY_BATTERY)
    )
    assert set(series) == {SERIES_STRESS, SERIES_BODY_BATTERY}

    night = await garmin_service.intraday_series_map(
        db_session, DAY, series_types=SLEEP_SERIES_TYPES
    )
    assert set(night) == set(SLEEP_SERIES_TYPES)


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


# ── Token store: silence is the failure mode ──────────────────────────────────
async def test_sync_raises_warn_alert_when_the_token_store_fails(db_session):
    """A token that can't be stored is invisible until the next restart, and then
    every single poll logs into Garmin again — which is how the account gets
    blocked. The sync itself succeeds, so only an alert can surface it."""
    from vitals.services import alerts_service

    client = FakeGarminClient(token_warnings=["could not write the session: boom"])
    summary = await garmin_service.sync(db_session, client, days=1, on_date=DAY)
    await db_session.commit()

    assert summary["error"] is None  # the data still arrived
    active = await alerts_service.list_active(db_session, domain="garmin")
    token_alerts = [a for a in active if a.alert_key == garmin_service.TOKEN_ALERT_KEY]
    assert len(token_alerts) == 1
    assert token_alerts[0].severity == "warn"


async def test_healthy_token_store_resolves_the_alert(db_session):
    from vitals.services import alerts_service

    await garmin_service.sync(
        db_session, FakeGarminClient(token_warnings=["boom"]), days=1, on_date=DAY
    )
    await db_session.commit()
    await garmin_service.sync(db_session, FakeGarminClient(), days=1, on_date=DAY)
    await db_session.commit()

    active = await alerts_service.list_active(db_session, domain="garmin")
    assert not [a for a in active if a.alert_key == garmin_service.TOKEN_ALERT_KEY]


@pytest.mark.integration
async def test_sync_finishes_vendor_reads_before_weight_ingest_lock(db_session):
    """A second Garmin fetch must not block a concurrent local weight save."""
    factory = async_sessionmaker(
        db_session.bind, expire_on_commit=False, class_=AsyncSession
    )
    second_fetch_started = asyncio.Event()
    resume_fetch = asyncio.Event()

    class PausingSecondDayClient(FakeGarminClient):
        def __init__(self):
            super().__init__()
            self.fetch_count = 0

        async def fetch_daily(self, on_date):
            self.fetch_count += 1
            if self.fetch_count == 2:
                second_fetch_started.set()
                await resume_fetch.wait()
            return RAW_DAY

        async def fetch_activities(self, start, end):
            return []

    client = PausingSecondDayClient()

    async def syncing():
        async with factory() as session:
            result = await garmin_service.sync(
                session, client, days=2, on_date=DAY
            )
            await session.commit()
            return result

    sync_task = asyncio.create_task(syncing())
    await asyncio.wait_for(second_fetch_started.wait(), timeout=2)

    async with factory() as session:
        await weight_service.log_weight(session, on_date=DAY, weight_kg=84.0)
        await asyncio.wait_for(session.commit(), timeout=2)

    resume_fetch.set()
    summary = await asyncio.wait_for(sync_task, timeout=2)
    assert summary["days"] == 2

    async with factory() as session:
        active = await weight_service.get_active_weight(session, DAY)
        assert active is not None
        assert active.weight_kg == 84.0


@pytest.mark.integration
async def test_concurrent_daily_ingests_take_advisory_before_raw_rows(
    db_session, monkeypatch
):
    """Regression for the former raw/day→advisory versus advisory→raw deadlock."""
    from vitals.services import garmin_weight_service

    factory = async_sessionmaker(
        db_session.bind, expire_on_commit=False, class_=AsyncSession
    )
    async with factory() as first_session, factory() as second_session:
        # Hold the transaction-scoped advisory in A before B begins.
        await garmin_service.ingest_daily(
            first_session, DAY.replace(day=DAY.day - 1), RAW_DAY
        )
        second_reached_lock = asyncio.Event()
        original_lock = garmin_weight_service.lock_active_weight_change

        async def signaling_lock(session):
            if session is second_session:
                second_reached_lock.set()
            await original_lock(session)

        monkeypatch.setattr(
            garmin_weight_service,
            "lock_active_weight_change",
            signaling_lock,
        )
        second_task = asyncio.create_task(
            garmin_service.ingest_daily(second_session, DAY, RAW_DAY)
        )
        await asyncio.wait_for(second_reached_lock.wait(), timeout=2)

        # B must still be waiting before it owns any raw/day row, so A can ingest
        # the same date and commit without forming the old lock-order cycle.
        await asyncio.wait_for(
            garmin_service.ingest_daily(first_session, DAY, RAW_DAY), timeout=2
        )
        await first_session.commit()
        await asyncio.wait_for(second_task, timeout=2)
        await second_session.commit()


# ── Credential-login breaker (the account-block guard) ────────────────────────
TOKEN_JSON = '{"di_token": "%s"}' % ("x" * 600)


class _FakeSession:
    """Stand-in for garminconnect's inner client — only the token-store surface
    this module actually touches."""

    def __init__(self, dumps_error=None):
        self._dumps_error = dumps_error

    def dumps(self):
        if self._dumps_error is not None:
            raise self._dumps_error
        return TOKEN_JSON

    def dump(self, path):
        return None


class _FakeGarmin:
    def __init__(self, dumps_error=None):
        self.client = _FakeSession(dumps_error)


def _login_client(redis, *, resume=None, dumps_error=None):
    """A GarminClient wired to fakeredis, with the two blocking login paths
    stubbed so nothing touches the network. ``resume`` is the object the token
    path returns (None = no usable token, so credentials are needed)."""
    client = GarminClient(
        Config(
            database_url="", redis_url="",
            garmin_email="user@example.com", garmin_password="secret",
        ),
        redis=redis,
    )
    client.logins = []

    def _fresh():
        client.logins.append(1)
        return _FakeGarmin(dumps_error)

    client._resume_blocking = lambda cached: resume
    client._fresh_login_blocking = _fresh
    return client


async def test_fourth_login_in_24h_is_not_performed(redis):
    """Garmin's limit sits on the login, counts per account, and every extra
    attempt extends the block — so the fourth attempt must not reach the network
    at all, not merely fail politely."""
    client = _login_client(redis)

    for _ in range(MAX_LOGINS_PER_DAY):
        client._garmin = None
        await client._ensure_login()

    client._garmin = None
    with pytest.raises(GarminLoginThrottled):
        await client._ensure_login()

    assert len(client.logins) == MAX_LOGINS_PER_DAY


async def test_refusal_sets_a_pause_that_outlives_the_counter(redis):
    """The pause is the part that matters: without it a counter reset (or a new
    day rolling over mid-block) would let the retries resume straight into
    Garmin's block and extend it."""
    client = _login_client(redis)
    for _ in range(MAX_LOGINS_PER_DAY):
        client._garmin = None
        await client._ensure_login()
    client._garmin = None
    with pytest.raises(GarminLoginThrottled):
        await client._ensure_login()

    assert await redis.get(LOGIN_PAUSE_KEY)

    await redis.delete(LOGIN_ATTEMPTS_KEY)
    client._garmin = None
    with pytest.raises(GarminLoginThrottled):
        await client._ensure_login()
    assert len(client.logins) == MAX_LOGINS_PER_DAY


async def test_resumed_token_session_spends_no_login(redis):
    """The breaker's budget is tiny on purpose, so a working token must never
    touch it — routine polling has to stay free."""
    client = _login_client(redis, resume=_FakeGarmin())

    await client._ensure_login()

    assert client.logins == []
    assert await redis.get(LOGIN_ATTEMPTS_KEY) is None


async def test_session_is_cached_in_redis_after_login(redis):
    """Regression: the caching used to go through ``garmin.garth``, an attribute
    the library dropped — and the failure was swallowed, so the cache was quietly
    dead while everything looked fine."""
    client = _login_client(redis, resume=_FakeGarmin())

    await client._ensure_login()

    assert await redis.get(REDIS_SESSION_KEY) == TOKEN_JSON
    assert client.token_warnings == []


async def test_token_serialisation_failure_is_recorded_not_swallowed(redis):
    client = _login_client(redis, resume=_FakeGarmin(dumps_error=AttributeError("garth")))

    await client._ensure_login()  # the sync still runs on the in-memory session

    assert client.token_warnings
    assert await redis.get(REDIS_SESSION_KEY) is None


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


async def test_sync_reports_a_throttled_login_separately_from_bad_credentials(db_session):
    """"Paused on purpose" and "your password is wrong" call for opposite
    reactions — the page must not tell you to go re-check credentials that are
    fine, because re-logging in is exactly what extends a Garmin block."""
    from vitals.services import alerts_service

    client = FakeGarminClient(raise_exc=GarminLoginThrottled("daily cap spent"))
    summary = await garmin_service.sync(db_session, client, days=1, on_date=DAY)
    await db_session.commit()

    assert summary["error"] == "throttled"
    active = await alerts_service.list_active(db_session, domain="garmin")
    assert any(a.alert_key == garmin_service.AUTH_ALERT_KEY for a in active)


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


# ── Historical reparse (recover new fields with zero new Garmin calls) ────────
async def test_reparse_daily_from_raw_recovers_new_fields_and_preserves_fetched_at(db_session):
    """A day synced before the sleep-detail/training-status columns existed: the
    raw response already had everything (get_sleep_data/get_stress_data always
    return the full payload), the old parser just discarded most of it.
    Reparsing the stored row — not re-fetching — must recover the new columns,
    and must not overwrite the original upstream fetch time with "now"."""
    old_fetched_at = to_local_naive(datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc))
    raw_row = RawPayload(
        domain="garmin", source="garmin_api",
        external_id=f"daily:{DAY.isoformat()}", payload=RAW_DAY,
        fetched_at=old_fetched_at,
    )
    db_session.add(raw_row)
    await db_session.flush()

    row = await garmin_service.reparse_daily_from_raw(db_session, raw_row)
    await db_session.commit()

    assert row.date == DAY
    assert row.spo2_lowest == 91
    assert row.body_battery_change == 55
    assert row.training_status == "PRODUCTIVE"
    assert raw_row.fetched_at == old_fetched_at


async def test_reparse_activity_from_raw_recovers_summary_fields_only(db_session):
    """An activity synced before the per-activity detail call existed has
    elevation/power/training-effect on its summary already (free to recover),
    but never made the hr-zones/splits detail call — those must stay null
    rather than being silently invented."""
    activity = {
        "activityId": 99001,
        "activityName": "Вечерняя пробежка",
        "activityType": {"typeKey": "running"},
        "startTimeGMT": "2026-06-10 18:00:00",
        "duration": 1800.0,
        "distance": 5000.0,
        "calories": 350,
        "averageHR": 140,
        "maxHR": 165,
        "elevationGain": 12.0,
        "avgPower": 200,
        "aerobicTrainingEffect": 2.8,
        "anaerobicTrainingEffect": 0.5,
        # No "_details" key — predates the per-activity detail fetch.
    }
    old_fetched_at = to_local_naive(datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc))
    raw_row = RawPayload(
        domain="garmin", source="garmin_api",
        external_id="activity:99001", payload=activity,
        fetched_at=old_fetched_at,
    )
    db_session.add(raw_row)
    await db_session.flush()

    await garmin_service.reparse_activity_from_raw(db_session, raw_row)
    await db_session.commit()

    row = (await db_session.execute(
        select(GarminActivity).where(GarminActivity.external_id == "99001")
    )).scalars().first()
    assert row.elevation_gain_m == 12.0
    assert row.avg_power == 200
    assert row.training_effect_aerobic == 2.8
    assert row.hr_zone_seconds is None
    assert row.splits is None
    assert raw_row.fetched_at == old_fetched_at


# ── Reads: night list / adjacent-night navigation (Sleep tab) ─────────────────
async def test_list_nights_excludes_days_without_sleep(db_session):
    """A day synced for steps/HR only (no sleep_seconds) is noise in a night
    list — list_nights must drop it, unlike list_daily."""
    db_session.add_all([
        GarminDaily(date=date(2026, 6, 8), domain="garmin", source="garmin_api", sleep_seconds=25200),
        GarminDaily(date=date(2026, 6, 9), domain="garmin", source="garmin_api", steps=8000),
        GarminDaily(date=date(2026, 6, 10), domain="garmin", source="garmin_api", sleep_seconds=27000),
    ])
    await db_session.commit()

    nights = await garmin_service.list_nights(db_session)
    assert [n.date for n in nights] == [date(2026, 6, 10), date(2026, 6, 8)]


async def test_list_nights_respects_limit(db_session):
    db_session.add_all([
        GarminDaily(date=date(2026, 6, 8), domain="garmin", source="garmin_api", sleep_seconds=25200),
        GarminDaily(date=date(2026, 6, 9), domain="garmin", source="garmin_api", sleep_seconds=26400),
        GarminDaily(date=date(2026, 6, 10), domain="garmin", source="garmin_api", sleep_seconds=27000),
    ])
    await db_session.commit()

    nights = await garmin_service.list_nights(db_session, limit=2)
    assert [n.date for n in nights] == [date(2026, 6, 10), date(2026, 6, 9)]


async def test_adjacent_night_dates_finds_nearest_neighbours_with_sleep(db_session):
    """The nearest earlier/later dates that also have sleep data — a day in
    between with no sleep_seconds must be skipped, not treated as a neighbour."""
    db_session.add_all([
        GarminDaily(date=date(2026, 6, 7), domain="garmin", source="garmin_api", sleep_seconds=24000),
        GarminDaily(date=date(2026, 6, 8), domain="garmin", source="garmin_api", steps=5000),  # no sleep
        GarminDaily(date=date(2026, 6, 10), domain="garmin", source="garmin_api", sleep_seconds=27000),
        GarminDaily(date=date(2026, 6, 12), domain="garmin", source="garmin_api", sleep_seconds=25000),
    ])
    await db_session.commit()

    prev_date, next_date = await garmin_service.adjacent_night_dates(db_session, date(2026, 6, 10))
    assert prev_date == date(2026, 6, 7)
    assert next_date == date(2026, 6, 12)


async def test_adjacent_night_dates_missing_neighbour_is_none(db_session):
    db_session.add_all([
        GarminDaily(date=date(2026, 6, 10), domain="garmin", source="garmin_api", sleep_seconds=27000),
    ])
    await db_session.commit()

    prev_date, next_date = await garmin_service.adjacent_night_dates(db_session, date(2026, 6, 10))
    assert prev_date is None
    assert next_date is None
