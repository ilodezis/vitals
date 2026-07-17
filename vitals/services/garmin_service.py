"""Garmin activity & recovery service (module 6).

Owns the garmin domain:

  * **Daily sync** — pull the day's sub-metrics, keep the full payload in
    ``raw_payloads``, and normalise the wide ``garmin_daily`` row (sleep, HRV,
    RHR, stress, Body Battery, steps, calories, HR, intensity minutes, training
    readiness, …). Upsert by date, so re-syncing a day refreshes it.
  * **Intraday series** — the stress / Body Battery curves inside the same
    payload (~480 samples each per day) land in ``garmin_intraday``, one row per
    sample. Re-import rebuilds a day+series wholesale.
  * **Weight bridge** — a Garmin weigh-in for a date is pushed into the weight
    domain as a ``garmin_api`` row, where the weight service's manual-over-Garmin
    priority already lets a manual entry supersede it.
  * **Activities** — recorded sport sessions, upserted by Garmin activity id.
  * **Recovery advice** — a passive read (Sleep Score < 60 or Body Battery < 40)
    surfaced in the training block; never a popup.
  * **Auth/MFA alert** — a login/MFA failure raises a critical ``warn`` system
    alert (the user re-seeds the token store out-of-band).
  * **Health Auto Export** — a REST backup channel: parse the uploaded JSON into
    ``garmin_daily`` rows (``source='health_auto_export'``).

Normalisation (``_normalize_daily``) is pure and unit-tested; the service is
handed a client (tests pass a fake), never touching the network itself.
"""
from __future__ import annotations

import logging
from datetime import date as date_type, datetime, timedelta, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import Severity, Source
from vitals.i18n import t
from vitals.integrations.garmin_client import GarminAuthError, GarminMFARequired
from vitals.models.garmin import (
    DOMAIN,
    SERIES_BODY_BATTERY,
    SERIES_STRESS,
    GarminActivity,
    GarminDaily,
    GarminIntraday,
)
from vitals.services import alerts_service, raw_payload_service, weight_service
from vitals.utils.timeutils import now_local, to_local_naive

logger = logging.getLogger(__name__)

AUTH_ALERT_KEY = "garmin.auth"

SLEEP_SCORE_FLOOR = 60
BODY_BATTERY_FLOOR = 40
SPO2_FLOOR = 90


# ── Pure extraction helpers ───────────────────────────────────────────────────
def _dig(payload: Any, *path: str) -> Any:
    """Walk nested dict keys, tolerating missing keys / non-dicts → None."""
    cur = payload
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _num(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (ValueError, TypeError):
        return None


def _intish(value: Any) -> Optional[int]:
    n = _num(value)
    return int(round(n)) if n is not None else None


def _first(*values: Any) -> Any:
    """First non-None value (key-fallback chains across Garmin shape variants)."""
    for v in values:
        if v is not None:
            return v
    return None


def _strip_level_suffix(phrase: Optional[str]) -> Optional[str]:
    """Garmin's training-status feedback phrase carries a numeric intensity
    level suffix (e.g. ``"PRODUCTIVE_1"``) the wide column doesn't need -- the
    raw phrase is still kept in ``raw_payloads``."""
    if not isinstance(phrase, str):
        return phrase
    base, _, suffix = phrase.rpartition("_")
    return base if base and suffix.isdigit() else phrase


def _parse_sleep_boundary(sleep_dto: dict, prefix: str) -> Optional[datetime]:
    """Sleep bed/wake timestamp (``prefix`` is e.g. ``"sleepStart"``) -> local
    naive datetime.

    Garmin ships both a ``*TimestampGMT`` (a true UTC epoch, converted the same
    way as ``_parse_activity_start``) and a ``*TimestampLocal`` variant whose ms
    count already bakes the local offset in -- decoding THAT as UTC and just
    stripping tzinfo gives the right wall-clock time directly; running it through
    ``to_local_naive`` too would shift it a second time. GMT is preferred when
    both are present since it's unambiguous."""
    gmt_ms = _num(sleep_dto.get(f"{prefix}TimestampGMT"))
    if gmt_ms is not None:
        return to_local_naive(datetime.fromtimestamp(gmt_ms / 1000, tz=timezone.utc))
    local_ms = _num(sleep_dto.get(f"{prefix}TimestampLocal"))
    if local_ms is not None:
        return datetime.fromtimestamp(local_ms / 1000, tz=timezone.utc).replace(tzinfo=None)
    return None


# ── Intraday series (stress / Body Battery curves) ────────────────────────────
def _epoch_ms_to_local(value: Any) -> Optional[datetime]:
    """Garmin's intraday timestamps are true UTC epoch **milliseconds** (unlike
    the sleep DTO's ``*Local`` variant, which pre-bakes the offset)."""
    ms = _num(value)
    if ms is None:
        return None
    return to_local_naive(datetime.fromtimestamp(ms / 1000, tz=timezone.utc))


def _descriptor_index(descriptors: Any, wanted_key: str) -> Optional[int]:
    """Column position of ``wanted_key`` in a positional intraday array, read from
    the descriptor list Garmin ships next to it.

    Worth the indirection because the shapes genuinely differ per endpoint:
    ``get_stress_data`` returns Body Battery as ``[ts, status, level, version]``
    while ``get_body_battery`` returns ``[ts, level]`` — hard-coding a position
    would silently store the *status* column for one of them. Both the key and
    index field names also vary (``key``/``index`` for stress,
    ``bodyBatteryValueDescriptor*`` for Body Battery), hence the fallbacks."""
    if not isinstance(descriptors, list):
        return None
    for item in descriptors:
        if not isinstance(item, dict):
            continue
        key = _first(item.get("key"), item.get("bodyBatteryValueDescriptorKey"))
        if key == wanted_key:
            return _intish(_first(
                item.get("index"), item.get("bodyBatteryValueDescriptorIndex")
            ))
    return None


def _parse_intraday_points(
    rows: Any, *, value_index: Optional[int] = None
) -> list[tuple[datetime, float]]:
    """``[[epoch_ms, value, …], …]`` → ``[(local_ts, value), …]``, sorted by time.

    ``value_index`` comes from the descriptor list; without one we take the first
    numeric column after the timestamp, which lands on the value in every shape
    Garmin has been seen to return. Negative readings are Garmin's sentinels
    (stress ``-1`` = no reading, ``-2`` = watch off the wrist) and are dropped —
    they are absence of data, not a measurement, and would drag any average down.
    The raw array is kept whole in ``raw_payloads`` regardless."""
    out: list[tuple[datetime, float]] = []
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        ts = _epoch_ms_to_local(row[0])
        if ts is None:
            continue
        if value_index is not None and 0 <= value_index < len(row):
            value = _num(row[value_index])
        else:
            value = next((v for v in (_num(c) for c in row[1:]) if v is not None), None)
        if value is None or value < 0:
            continue
        out.append((ts, value))
    out.sort(key=lambda p: p[0])
    return out


def _intraday_series(raw: dict) -> dict[str, list[tuple[datetime, float]]]:
    """Every intraday curve in the day's bundle, keyed by ``series_type``. Pure.

    Both series ride in the one ``get_stress_data`` payload at full ~3-minute
    resolution; the separate ``get_body_battery`` payload only carries inflection
    points, so it's a fallback for when the stress payload came back without the
    array."""
    stress_payload = raw.get("stress") or {}

    stress_rows = stress_payload.get("stressValuesArray")
    stress_index = _descriptor_index(
        stress_payload.get("stressValueDescriptorsDTOList"), "stressLevel"
    )

    bb_rows = stress_payload.get("bodyBatteryValuesArray")
    bb_descriptors = stress_payload.get("bodyBatteryValueDescriptorsDTOList")
    if not bb_rows:
        bb_payload = raw.get("body_battery")
        bb0 = bb_payload[0] if isinstance(bb_payload, list) and bb_payload else bb_payload
        if isinstance(bb0, dict):
            bb_rows = bb0.get("bodyBatteryValuesArray")
            bb_descriptors = _first(
                bb0.get("bodyBatteryValueDescriptorDTOList"),
                bb0.get("bodyBatteryValueDescriptorsDTOList"),
            )
    bb_index = _descriptor_index(bb_descriptors, "bodyBatteryLevel")

    return {
        SERIES_STRESS: _parse_intraday_points(stress_rows, value_index=stress_index),
        SERIES_BODY_BATTERY: _parse_intraday_points(bb_rows, value_index=bb_index),
    }


async def ingest_intraday(
    session: AsyncSession,
    on_date: date_type,
    series_type: str,
    points: Sequence[tuple[datetime, float]],
    *,
    raw_payload_id: Optional[int] = None,
    source: str = Source.GARMIN_API.value,
) -> int:
    """Replace the day's samples for one ``series_type``. Returns rows written.

    Rebuild-on-reimport (delete + insert, like ``hevy_service._upsert_workout``
    does with its children) rather than a per-sample upsert: Garmin re-models the
    whole curve as later readings arrive, so the array is the unit of truth, not
    the point. An **empty** ``points`` is a no-op — a poll that came back without
    the array is a hiccup, and must not delete samples already captured. Does not
    commit."""
    if not points:
        return 0
    await session.execute(
        GarminIntraday.__table__.delete().where(
            GarminIntraday.date == on_date,
            GarminIntraday.series_type == series_type,
        )
    )
    session.add_all([
        GarminIntraday(
            date=on_date,
            domain=DOMAIN,
            source=source,
            raw_payload_id=raw_payload_id,
            series_type=series_type,
            ts=ts,
            value=value,
        )
        for ts, value in points
    ])
    await session.flush()
    return len(points)


def _normalize_daily(raw: dict) -> dict:
    """Reduce the raw per-day sub-payload bundle to ``garmin_daily`` column values.
    Pure (no DB); every field defaults to None so a sparse day is fine."""
    summary = raw.get("summary") or {}
    sleep_dto = _dig(raw, "sleep", "dailySleepDTO") or {}
    hrv = _dig(raw, "hrv", "hrvSummary") or {}
    tr = raw.get("training_readiness")
    tr0 = tr[0] if isinstance(tr, list) and tr else (tr if isinstance(tr, dict) else {})
    mm = raw.get("max_metrics")
    mm0 = mm[0] if isinstance(mm, list) and mm else (mm if isinstance(mm, dict) else {})
    ts_map = _dig(raw, "training_status", "mostRecentTrainingStatus", "latestTrainingStatusData")
    ts0 = next(iter(ts_map.values()), {}) if isinstance(ts_map, dict) else {}
    if not isinstance(ts0, dict):
        ts0 = {}
    acute_load_dto = ts0.get("acuteTrainingLoadDTO") or {}

    return {
        # Sleep
        "sleep_seconds": _intish(sleep_dto.get("sleepTimeSeconds")),
        "sleep_score": _intish(_dig(sleep_dto, "sleepScores", "overall", "value")),
        "deep_sleep_seconds": _intish(sleep_dto.get("deepSleepSeconds")),
        "light_sleep_seconds": _intish(sleep_dto.get("lightSleepSeconds")),
        "rem_sleep_seconds": _intish(sleep_dto.get("remSleepSeconds")),
        "awake_seconds": _intish(sleep_dto.get("awakeSleepSeconds")),
        "sleep_start": _parse_sleep_boundary(sleep_dto, "sleepStart"),
        "sleep_end": _parse_sleep_boundary(sleep_dto, "sleepEnd"),
        "awake_count": _intish(sleep_dto.get("awakeCount")),
        "restless_moments": _intish(sleep_dto.get("restlessMomentsCount")),
        "avg_sleep_stress": _intish(sleep_dto.get("avgSleepStress")),
        "avg_sleep_hr": _intish(sleep_dto.get("avgHeartRate")),
        "spo2_lowest": _intish(sleep_dto.get("lowestSpO2Value")),
        "respiration_lowest": _num(sleep_dto.get("lowestRespirationValue")),
        "respiration_highest": _num(sleep_dto.get("highestRespirationValue")),
        "body_battery_change": _intish(_dig(raw, "sleep", "bodyBatteryChange")),
        "breathing_disruption": sleep_dto.get("breathingDisruptionSeverity"),
        "sleep_need_actual": _intish(_first(
            _dig(sleep_dto, "nextSleepNeed", "actual"),
            _dig(raw, "sleep", "nextSleepNeed", "actual"),
        )),
        # Heart / HRV / respiration
        "resting_hr": _intish(_first(summary.get("restingHeartRate"), _dig(raw, "rhr", "restingHeartRate"))),
        "avg_hr": _intish(summary.get("averageHeartRate")),
        "max_hr": _intish(summary.get("maxHeartRate")),
        "min_hr": _intish(summary.get("minHeartRate")),
        "hrv_avg": _num(_first(hrv.get("lastNightAvg"), hrv.get("weeklyAvg"))),
        "hrv_status": hrv.get("status"),
        "avg_respiration": _num(summary.get("avgWakingRespirationValue")),
        "spo2_avg": _num(_first(summary.get("averageSpo2"), summary.get("averageSpo2Value"))),
        # Stress / Body Battery
        "avg_stress": _intish(summary.get("averageStressLevel")),
        "max_stress": _intish(summary.get("maxStressLevel")),
        "body_battery_high": _intish(summary.get("bodyBatteryHighestValue")),
        "body_battery_low": _intish(summary.get("bodyBatteryLowestValue")),
        # Activity / energy
        "steps": _intish(summary.get("totalSteps")),
        "floors_climbed": _intish(summary.get("floorsAscended")),
        "active_calories": _intish(summary.get("activeKilocalories")),
        "bmr_calories": _intish(summary.get("bmrKilocalories")),
        "total_calories": _intish(summary.get("totalKilocalories")),
        "intensity_minutes_moderate": _intish(summary.get("moderateIntensityMinutes")),
        "intensity_minutes_vigorous": _intish(summary.get("vigorousIntensityMinutes")),
        # Training
        "training_readiness": _intish(tr0.get("score") if isinstance(tr0, dict) else None),
        "vo2max": _num(_dig(mm0, "generic", "vo2MaxValue") if isinstance(mm0, dict) else None),
        "training_status": _strip_level_suffix(ts0.get("trainingStatusFeedbackPhrase")),
        "acute_load": _num(acute_load_dto.get("acuteTrainingLoad")),
        "load_ratio": _num(acute_load_dto.get("acwrPercent")),
    }


def _extract_weight_kg(raw: dict) -> Optional[float]:
    """Garmin weigh-in (grams) → kg, if the day had one."""
    grams = _first(
        _dig(raw, "body_composition", "totalAverage", "weight"),
        _dig(raw, "summary", "weight"),
    )
    kg = _num(grams)
    if kg is None:
        return None
    # Garmin reports weight in grams; guard the odd payload already in kg.
    return round(kg / 1000.0, 2) if kg > 1000 else round(kg, 2)


# ── Daily upsert ──────────────────────────────────────────────────────────────
async def get_daily(session: AsyncSession, on_date: date_type) -> Optional[GarminDaily]:
    result = await session.execute(select(GarminDaily).where(GarminDaily.date == on_date))
    return result.scalars().first()


async def ingest_daily(
    session: AsyncSession,
    on_date: date_type,
    raw: dict,
    *,
    source: str = Source.GARMIN_API.value,
) -> GarminDaily:
    """Store the raw bundle, upsert the normalized daily row, rebuild the day's
    intraday series, and bridge any weigh-in into the weight domain. Does not
    commit."""
    raw_row = await raw_payload_service.upsert_raw_payload(
        session,
        domain=DOMAIN,
        source=source,
        external_id=f"daily:{on_date.isoformat()}",
        payload=raw,
    )
    fields = _normalize_daily(raw)

    row = await get_daily(session, on_date)
    if row is None:
        row = GarminDaily(date=on_date, domain=DOMAIN)
        session.add(row)
    row.source = source
    row.raw_payload_id = raw_row.id
    for key, value in fields.items():
        setattr(row, key, value)
    await session.flush()
    raw_row.processed_at = now_local()

    for series_type, points in _intraday_series(raw).items():
        await ingest_intraday(
            session, on_date, series_type, points,
            raw_payload_id=raw_row.id, source=source,
        )

    weight_kg = _extract_weight_kg(raw)
    if weight_kg is not None:
        # The weight service enforces manual-over-Garmin priority for the date.
        await weight_service.log_weight(
            session, on_date=on_date, weight_kg=weight_kg, source=Source.GARMIN_API.value
        )
    return row


# ── Activities ────────────────────────────────────────────────────────────────
async def ingest_activities(session: AsyncSession, activities: Sequence[dict]) -> int:
    """Upsert recorded activities by Garmin activity id. Returns rows written."""
    written = 0
    for raw in activities:
        external_id = str(raw.get("activityId") or raw.get("activityid") or "").strip()
        if not external_id:
            continue
        raw_row = await raw_payload_service.upsert_raw_payload(
            session,
            domain=DOMAIN,
            source=Source.GARMIN_API.value,
            external_id=f"activity:{external_id}",
            payload=raw,
        )
        start = _parse_activity_start(raw)
        result = await session.execute(
            select(GarminActivity).where(GarminActivity.external_id == external_id)
        )
        row = result.scalars().first()
        if row is None:
            row = GarminActivity(external_id=external_id, domain=DOMAIN)
            session.add(row)
        row.source = Source.GARMIN_API.value
        row.raw_payload_id = raw_row.id
        row.date = (start or now_local()).date()
        row.activity_type = _dig(raw, "activityType", "typeKey") or raw.get("activityType")
        row.name = raw.get("activityName")
        row.start_time = start
        row.duration_seconds = _intish(raw.get("duration"))
        row.distance_m = _num(raw.get("distance"))
        row.calories = _intish(raw.get("calories"))
        row.avg_hr = _intish(raw.get("averageHR"))
        row.max_hr = _intish(raw.get("maxHR"))
        # Per-activity detail (run 3). Scalars are already on the summary; the two
        # arrays come from the best-effort detail bundle merged under ``_details``.
        row.elevation_gain_m = _num(raw.get("elevationGain"))
        row.avg_power = _intish(raw.get("avgPower"))
        row.training_effect_aerobic = _num(raw.get("aerobicTrainingEffect"))
        row.training_effect_anaerobic = _num(raw.get("anaerobicTrainingEffect"))
        row.hr_zone_seconds = _normalize_hr_zones(raw)
        row.splits = _normalize_splits(raw)
        await session.flush()
        raw_row.processed_at = now_local()
        written += 1
    return written


def _normalize_hr_zones(raw: dict) -> Optional[list]:
    """Seconds-in-HR-zone as a compact array. Prefers the per-activity
    ``get_activity_hr_zones`` detail (carries each zone's low HR boundary); falls
    back to the ``hrTimeInZone_N`` fields already on the activity summary."""
    detail = _dig(raw, "_details", "hr_zones")
    if isinstance(detail, list) and detail:
        out = [
            {
                "zone": _intish(z.get("zoneNumber")),
                "secs": _num(z.get("secsInZone")),
                "low_hr": _intish(z.get("zoneLowBoundary")),
            }
            for z in detail
            if isinstance(z, dict)
        ]
        if out:
            return out
    fallback = [
        {"zone": n, "secs": _num(raw.get(f"hrTimeInZone_{n}")), "low_hr": None}
        for n in range(1, 6)
        if raw.get(f"hrTimeInZone_{n}") is not None
    ]
    return fallback or None


def _normalize_splits(raw: dict) -> Optional[list]:
    """Per-lap splits from the ``get_activity_splits`` detail (``lapDTOs``). Only
    outdoor/interval activities carry more than one lap; strength has none."""
    laps = _dig(raw, "_details", "splits", "lapDTOs")
    if not isinstance(laps, list) or not laps:
        return None
    out = [
        {
            "index": _intish(lap.get("lapIndex")),
            "distance_m": _num(lap.get("distance")),
            "duration_s": _num(lap.get("duration")),
            "avg_hr": _intish(lap.get("averageHR")),
            "max_hr": _intish(lap.get("maxHR")),
            "avg_speed_mps": _num(lap.get("averageSpeed")),
        }
        for lap in laps
        if isinstance(lap, dict)
    ]
    return out or None


async def _enrich_activity_details(client: Any, activities: Sequence[dict]) -> None:
    """Fetch each in-window activity's detail bundle (HR zones + splits) and merge
    it under a synthetic ``_details`` key so the whole thing lands in
    ``raw_payloads`` and the normalizers can read it. Best-effort and bounded —
    only the handful of activities in the sync window. A client without the
    method (or a failing call) leaves the activity detail-less, not broken."""
    fetch = getattr(client, "fetch_activity_details", None)
    if not callable(fetch):
        return
    for act in activities:
        if not isinstance(act, dict):
            continue
        activity_id = act.get("activityId") or act.get("activityid")
        if activity_id is None:
            continue
        try:
            act["_details"] = await fetch(activity_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("Garmin activity-detail fetch failed for %s: %s", activity_id, e)


def _parse_activity_start(raw: dict) -> Optional[datetime]:
    for key in ("startTimeGMT", "startTimeLocal"):
        value = raw.get(key)
        if value:
            try:
                text = str(value).replace("Z", "+00:00")
                return to_local_naive(datetime.fromisoformat(text))
            except (ValueError, TypeError):
                continue
    return None


# ── Sync orchestration ────────────────────────────────────────────────────────
async def sync(
    session: AsyncSession,
    client: Any,
    *,
    days: int = 2,
    on_date: Optional[date_type] = None,
) -> dict:
    """Sync the last ``days`` days of daily metrics + that window's activities.
    Default is 2 (yesterday + today) for routine polling; pass a larger value
    for backfill. Catches auth/MFA failures and raises a critical ``warn`` alert
    instead of bubbling them. Does not commit."""
    today = on_date or now_local().date()
    start = today - timedelta(days=days - 1)
    summary = {"days": 0, "activities": 0, "error": None}

    try:
        for offset in range(days):
            day = start + timedelta(days=offset)
            raw = await client.fetch_daily(day)
            await ingest_daily(session, day, raw)
            summary["days"] += 1

        activities = await client.fetch_activities(start, today)
        await _enrich_activity_details(client, activities)
        summary["activities"] = await ingest_activities(session, activities)

        await alerts_service.resolve_by_key(session, alert_key=AUTH_ALERT_KEY)
    except (GarminAuthError, GarminMFARequired) as e:
        is_mfa = isinstance(e, GarminMFARequired)
        message = (
            t("alert.garmin_mfa")
            if is_mfa
            else t("alert.garmin_auth_fail", error=str(e))
        )
        await alerts_service.raise_alert(
            session,
            domain=DOMAIN,
            severity=Severity.WARN.value,
            message=message,
            alert_key=AUTH_ALERT_KEY,
        )
        summary["error"] = "mfa" if is_mfa else "auth"
    return summary


# ── Health Auto Export (backup channel) ───────────────────────────────────────
# Map Health Auto Export metric names → the daily column they populate, with the
# unit conversion needed (HAE reports minutes for sleep, count for steps, etc.).
_HAE_METRIC_MAP = {
    "step_count": ("steps", lambda q: _intish(q)),
    "active_energy": ("active_calories", lambda q: _intish(q)),
    "basal_energy_burned": ("bmr_calories", lambda q: _intish(q)),
    "resting_heart_rate": ("resting_hr", lambda q: _intish(q)),
    "heart_rate_variability": ("hrv_avg", lambda q: _num(q)),
    "respiratory_rate": ("avg_respiration", lambda q: _num(q)),
    "blood_oxygen_saturation": ("spo2_avg", lambda q: _num(q)),
    "sleep_analysis": ("sleep_seconds", lambda q: _intish((q or 0) * 3600)),  # hours → s
}


async def ingest_health_auto_export(session: AsyncSession, payload: dict) -> dict:
    """Ingest a Health Auto Export JSON dump into ``garmin_daily`` rows
    (``source='health_auto_export'``). The full payload is kept raw. Tolerant of
    the documented shape ``{"data": {"metrics": [{name, data: [{date, qty}]}]}}``."""
    metrics = _dig(payload, "data", "metrics") or payload.get("metrics") or []
    # Accumulate per-date field values from the flat metric list.
    by_date: dict[date_type, dict] = {}
    for metric in metrics:
        name = (metric or {}).get("name")
        mapping = _HAE_METRIC_MAP.get(name)
        if not mapping:
            continue
        column, convert = mapping
        for point in metric.get("data") or []:
            day = _parse_hae_date(point.get("date"))
            if day is None:
                continue
            value = convert(point.get("qty"))
            if value is not None:
                by_date.setdefault(day, {})[column] = value

    written = 0
    for day, fields in sorted(by_date.items()):
        raw_row = await raw_payload_service.upsert_raw_payload(
            session,
            domain=DOMAIN,
            source=Source.HEALTH_AUTO_EXPORT.value,
            external_id=f"hae:{day.isoformat()}",
            payload={"metrics": fields, "source_payload": True},
        )
        row = await get_daily(session, day)
        if row is None:
            row = GarminDaily(date=day, domain=DOMAIN)
            session.add(row)
        # Only fill columns HAE provides; don't clobber existing Garmin-API values
        # with nulls (HAE is a supplementary backup, not the source of truth).
        row.source = Source.HEALTH_AUTO_EXPORT.value
        if row.raw_payload_id is None:
            row.raw_payload_id = raw_row.id
        for key, value in fields.items():
            setattr(row, key, value)
        await session.flush()
        raw_row.processed_at = now_local()
        written += 1

    return {"dates": written}


def _parse_hae_date(value: Any) -> Optional[date_type]:
    if not value:
        return None
    text = str(value)
    # HAE dates look like "2026-06-10 00:00:00 +0000" — take the date prefix.
    try:
        return date_type.fromisoformat(text[:10])
    except ValueError:
        return None


# ── Reads / advice ────────────────────────────────────────────────────────────
def recovery_advice(daily: Optional[GarminDaily]) -> Optional[str]:
    """Passive recovery hint for the training block, or None when recovery is fine."""
    if daily is None:
        return None
    notes: list[str] = []
    if daily.sleep_score is not None and daily.sleep_score < SLEEP_SCORE_FLOOR:
        notes.append(t("alert.recovery_sleep", score=daily.sleep_score))
    if daily.body_battery_high is not None and daily.body_battery_high < BODY_BATTERY_FLOOR:
        notes.append(t("alert.recovery_battery", value=daily.body_battery_high))
    if daily.spo2_lowest is not None and daily.spo2_lowest < SPO2_FLOOR:
        notes.append(t("alert.recovery_spo2", value=daily.spo2_lowest))
    if daily.breathing_disruption and daily.breathing_disruption != "NONE":
        notes.append(t("alert.recovery_breathing"))
    if not notes:
        return None
    return t("alert.recovery_prefix") + ", ".join(notes) + t("alert.recovery_suffix")


async def list_daily(
    session: AsyncSession, *, limit: int = 30
) -> Sequence[GarminDaily]:
    result = await session.execute(
        select(GarminDaily).order_by(GarminDaily.date.desc()).limit(limit)
    )
    return result.scalars().all()


async def list_activities(
    session: AsyncSession, *, limit: int = 20
) -> Sequence[GarminActivity]:
    result = await session.execute(
        select(GarminActivity).order_by(GarminActivity.date.desc(), GarminActivity.start_time.desc()).limit(limit)
    )
    return result.scalars().all()


async def list_intraday(
    session: AsyncSession,
    *,
    start: Optional[date_type] = None,
    end: Optional[date_type] = None,
    series_types: Optional[Sequence[str]] = None,
    limit: Optional[int] = None,
) -> Sequence[GarminIntraday]:
    """Intraday samples over a date window, oldest first (a curve reads in time
    order). A day holds ~480 samples per series, so callers cap the window."""
    stmt = select(GarminIntraday)
    if start is not None:
        stmt = stmt.where(GarminIntraday.date >= start)
    if end is not None:
        stmt = stmt.where(GarminIntraday.date <= end)
    if series_types:
        stmt = stmt.where(GarminIntraday.series_type.in_(list(series_types)))
    stmt = stmt.order_by(GarminIntraday.ts, GarminIntraday.series_type)
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return result.scalars().all()


async def intraday_series_map(
    session: AsyncSession,
    on_date: date_type,
    *,
    series_types: Optional[Sequence[str]] = None,
) -> dict[str, list[dict]]:
    """One day's curves as ``{series_type: [{"ts", "value"}, …]}`` — the shape the
    dashboard chart and the MCP tool both consume. Series with no samples are
    absent rather than empty, so a caller can just check for the key."""
    rows = await list_intraday(session, start=on_date, end=on_date, series_types=series_types)
    out: dict[str, list[dict]] = {}
    for row in rows:
        out.setdefault(row.series_type, []).append(
            {"ts": row.ts.isoformat(), "value": row.value}
        )
    return out


async def latest_daily(
    session: AsyncSession, *, before_or_on: Optional[date_type] = None
) -> Optional[GarminDaily]:
    stmt = select(GarminDaily)
    if before_or_on is not None:
        stmt = stmt.where(GarminDaily.date <= before_or_on)
    stmt = stmt.order_by(GarminDaily.date.desc()).limit(1)
    result = await session.execute(stmt)
    return result.scalars().first()


async def daily_count(session: AsyncSession) -> int:
    """Count days with at least one real metric (excludes ghost rows from initial sync)."""
    from sqlalchemy import or_
    result = await session.execute(
        select(func.count()).select_from(GarminDaily).where(
            or_(
                GarminDaily.sleep_score.is_not(None),
                GarminDaily.resting_hr.is_not(None),
                GarminDaily.hrv_avg.is_not(None),
            )
        )
    )
    return int(result.scalar() or 0)


# ── Scheduler job ─────────────────────────────────────────────────────────────
async def sync_job(session_factory, redis=None) -> None:
    """Garmin poll (registered in vitals/scheduler/jobs.py). No-ops cleanly when
    Garmin isn't configured."""
    from vitals.integrations.garmin_client import GarminClient

    client = GarminClient.from_config(redis=redis)
    if not client.is_configured:
        return
    async with session_factory() as session:
        from vitals.services.language_service import get_language
        from vitals.i18n import current_lang
        lang = await get_language(session, redis)
        current_lang.set(lang)

        summary = await sync(session, client)
        await session.commit()
        if redis is not None and summary.get("error") is None:
            import time
            await redis.set("sync:last_success:garmin", str(int(time.time())))
