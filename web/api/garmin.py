"""``/api/v1/recovery`` — recovery overview, sleep nights, activities, sync and import."""
from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Optional

from fastapi import Depends, File, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.integrations.garmin_client import GarminClient
from vitals.models.garmin import (
    SERIES_SLEEP_BB,
    SERIES_SLEEP_HR,
    SERIES_SLEEP_HRV,
    SERIES_SLEEP_MOVEMENT,
    SERIES_SLEEP_RESPIRATION,
    SLEEP_SERIES_TYPES,
)
from vitals.services import garmin_service
from vitals.utils.timeutils import today_local, to_local_naive
from web.api.errors import ApiRouter, not_found
from web.api.schemas.garmin import (
    ActivitiesListView,
    ActivityItem,
    GarminImportResponse,
    GarminSyncResponse,
    IntradaySeriesPoint,
    NightListItem,
    NightsListView,
    RecoveryBar,
    RecoveryDayItem,
    RecoveryHeadline,
    RecoveryNightPreview,
    RecoveryNorm,
    RecoveryView,
    SleepNightView,
    SleepStageSegment,
)
from web.deps import get_redis, get_session, require_auth
from web.uploads import JSON_EXTS, read_capped, validate_extension

logger = logging.getLogger(__name__)

router = ApiRouter(prefix="/recovery", dependencies=[Depends(require_auth)])

# Unit codes per metric (the screen words them) and the scale each bar is drawn on.
_NORM_UNITS = {"hrv": "ms", "rhr": "bpm"}
_BAR_SCALES: dict[str, tuple[float, float]] = {
    "sleep": (40, 100),
    "hrv": (35, 75),
    "rhr": (40, 65),
    "stress": (0, 60),
}


def _norm_bar(key: str, value: Optional[float], norm: Optional[RecoveryNorm]) -> RecoveryBar:
    """One "against your norm" row. The scale stretches to keep both the corridor
    and the reading on the bar; with no corridor yet the row carries the value alone."""
    lo_scale, hi_scale = _BAR_SCALES[key]
    marks = [v for v in (value, norm.lo if norm else None, norm.hi if norm else None) if v is not None]
    tone = ""
    if value is not None and norm is not None:
        if norm.better > 0 and value < norm.lo:
            tone = "bad"
        elif norm.better < 0 and value > norm.hi:
            tone = "bad"
        elif norm.better > 0 and value >= norm.hi:
            tone = "good"
        elif norm.better < 0 and value <= norm.lo:
            tone = "good"
    return RecoveryBar(
        key=key,
        min=min([lo_scale, *marks]),
        max=max([hi_scale, *marks]),
        value=value,
        lo=norm.lo if norm else None,
        hi=norm.hi if norm else None,
        tone=tone,
        unit=_NORM_UNITS.get(key, ""),
    )


# ── GET /api/v1/recovery ──────────────────────────────────────────────────────


@router.get("", response_model=RecoveryView)
async def read_recovery_overview(
    db: AsyncSession = Depends(get_session),
    redis=Depends(get_redis),
) -> RecoveryView:
    """The Recovery screen: sleep score, HRV, resting HR, body battery, night preview,
    and 14-day recovery grid."""
    today = today_local()
    latest = await garmin_service.latest_daily(db)
    history = await garmin_service.list_daily(db, limit=14)

    client = GarminClient.from_config(redis=redis)
    is_configured = client.is_configured

    last_sync = None
    if redis is not None:
        last_sync_raw = await redis.get("sync:last_success:garmin")
        if last_sync_raw:
            try:
                from datetime import datetime, timezone
                dt_sync = datetime.fromtimestamp(int(last_sync_raw), timezone.utc)
                local_dt = to_local_naive(dt_sync)
                if local_dt:
                    last_sync = local_dt.strftime("%d-%m-%Y %H:%M")
            except (ValueError, TypeError, OverflowError):
                logger.debug("Invalid sync:last_success:garmin timestamp: %r", last_sync_raw)

    date_shown = latest.date if latest else today
    is_today = date_shown == today

    # His own corridors, off the days before the one on screen; a metric without
    # enough history simply has none.
    raw_norms = await garmin_service.personal_norms(db, date_shown)
    norms = {
        key: RecoveryNorm(lo=n["lo"], hi=n["hi"], better=n["better"], unit=_NORM_UNITS.get(key, ""))
        for key, n in raw_norms.items()
    }
    norms_days = max((n["days"] for n in raw_norms.values()), default=0)

    # Count recent nights where HRV was below norm
    hrv_norm = norms.get("hrv")
    hrv_nights_below = 0
    for d in history:
        if hrv_norm is None:
            break
        if d.hrv_avg is not None and d.hrv_avg < hrv_norm.lo:
            hrv_nights_below += 1
        elif d.hrv_avg is not None:
            break

    # RHR note
    rhr_norm = norms.get("rhr")
    # Where the resting pulse stands against the corridor — a code, the screen words
    # it; empty when there is no reading to place.
    rhr_note = ""
    if latest and latest.resting_hr is not None and rhr_norm is not None:
        if latest.resting_hr > rhr_norm.hi:
            rhr_note = "above"
        elif latest.resting_hr > (rhr_norm.lo + rhr_norm.hi) / 2:
            rhr_note = "upper"
        elif latest.resting_hr < rhr_norm.lo:
            rhr_note = "below"
        else:
            rhr_note = "normal"

    headline = RecoveryHeadline(
        sleep_score=latest.sleep_score if latest else None,
        sleep_minutes=round(latest.sleep_seconds / 60) if (latest and latest.sleep_seconds) else None,
        hrv=latest.hrv_avg if latest else None,
        hrv_nights_below=hrv_nights_below,
        rhr=latest.resting_hr if latest else None,
        rhr_note=rhr_note,
        body_battery_from=latest.body_battery_low if latest else None,
        body_battery_to=latest.body_battery_high if latest else None,
    )

    # Night preview
    night_preview = None
    if latest and latest.sleep_seconds:
        # No bedtime recorded is no bedtime shown — never a typical 23:00–07:00.
        start_str = latest.sleep_start.strftime("%H:%M") if latest.sleep_start else ""
        end_str = latest.sleep_end.strftime("%H:%M") if latest.sleep_end else ""

        stage_mins = [
            round((latest.awake_seconds or 0) / 60),
            round((latest.rem_sleep_seconds or 0) / 60),
            round((latest.light_sleep_seconds or 0) / 60),
            round((latest.deep_sleep_seconds or 0) / 60),
        ]
        # Map raw stages to numbers 0: awake, 1: rem, 2: light, 3: deep
        stages_num: list[int] = []
        if isinstance(latest.sleep_stages, list):
            stage_map = {"awake": 0, "rem": 1, "light": 2, "deep": 3}
            for s in latest.sleep_stages:
                if isinstance(s, dict) and "stage" in s:
                    stages_num.append(stage_map.get(s["stage"], 2))

        night_preview = RecoveryNightPreview(
            date=latest.date,
            start=start_str,
            end=end_str,
            stages=stages_num,
            stage_minutes=stage_mins,
        )

    # Bars: sleep, hrv, rhr, stress
    bars = [
        _norm_bar("sleep", float(latest.sleep_score) if (latest and latest.sleep_score) else None, norms.get("sleep")),
        _norm_bar("hrv", latest.hrv_avg if latest else None, norms.get("hrv")),
        _norm_bar("rhr", float(latest.resting_hr) if (latest and latest.resting_hr) else None, norms.get("rhr")),
        _norm_bar("stress", float(latest.avg_stress) if (latest and latest.avg_stress) else None, norms.get("stress")),
    ]

    # Days (oldest first for charts/matrix)
    days_sorted = sorted(history, key=lambda x: x.date)
    days_items = [
        RecoveryDayItem(
            date=d.date,
            sleep=d.sleep_score,
            hrv=d.hrv_avg,
            rhr=d.resting_hr,
            stress=d.avg_stress,
            steps=d.steps,
            bb=d.body_battery_high,
        )
        for d in days_sorted
    ]

    return RecoveryView(
        date=date_shown,
        today_date=today,
        is_today=is_today,
        is_configured=is_configured,
        last_sync=last_sync,
        headline=headline,
        night=night_preview,
        norms=norms,
        norms_days=norms_days,
        norms_min_days=garmin_service.NORM_MIN_DAYS,
        bars=bars,
        days=days_items,
    )


# ── GET /api/v1/recovery/sleep/{date} ─────────────────────────────────────────


@router.get("/sleep/{on_date}", response_model=SleepNightView)
async def read_sleep_night_detail(
    on_date: dt.date, db: AsyncSession = Depends(get_session)
) -> SleepNightView:
    """One night in detail: hypnogram, minute-level curves, left/right night navigation."""
    daily = await garmin_service.get_daily(db, on_date)
    if daily is None:
        return not_found()

    today = today_local()
    series = await garmin_service.intraday_series_map(db, on_date, series_types=SLEEP_SERIES_TYPES)
    prev_date, next_date = await garmin_service.adjacent_night_dates(db, on_date)

    stages_series: list[SleepStageSegment] = []
    if isinstance(daily.sleep_stages, list) and daily.sleep_start:
        base_time = daily.sleep_start
        for s in daily.sleep_stages:
            if isinstance(s, dict) and "stage" in s and "start" in s and "end" in s:
                try:
                    s_dt = dt.datetime.fromisoformat(s["start"].replace("Z", "+00:00"))
                    e_dt = dt.datetime.fromisoformat(s["end"].replace("Z", "+00:00"))
                    s_local = to_local_naive(s_dt)
                    e_local = to_local_naive(e_dt)
                    s_min = max(0, int((s_local - base_time).total_seconds() // 60))
                    e_min = max(s_min, int((e_local - base_time).total_seconds() // 60))
                    stages_series.append(
                        SleepStageSegment(
                            stage=s["stage"],
                            start_min=s_min,
                            end_min=e_min,
                            duration_min=e_min - s_min,
                        )
                    )
                except (ValueError, TypeError):
                    logger.debug("Skipping malformed sleep stage segment: %r", s)

    def _to_points(pts: list[dict]) -> list[IntradaySeriesPoint]:
        out = []
        for p in pts:
            t_str = p.get("ts") or p.get("time") or ""
            # Format time HH:MM if long
            if len(t_str) >= 16 and "T" in t_str:
                t_str = t_str[11:16]
            out.append(IntradaySeriesPoint(time=t_str, value=float(p.get("value", 0))))
        return out

    stages_minutes = {
        "deep": round((daily.deep_sleep_seconds or 0) / 60),
        "light": round((daily.light_sleep_seconds or 0) / 60),
        "rem": round((daily.rem_sleep_seconds or 0) / 60),
        "awake": round((daily.awake_seconds or 0) / 60),
    }

    return SleepNightView(
        date=daily.date,
        today_date=today,
        is_today=daily.date == today,
        score=daily.sleep_score,
        duration_seconds=daily.sleep_seconds,
        start_time=daily.sleep_start.strftime("%H:%M") if daily.sleep_start else None,
        end_time=daily.sleep_end.strftime("%H:%M") if daily.sleep_end else None,
        rhr=daily.avg_sleep_hr or daily.resting_hr,
        spo2_min=float(daily.spo2_lowest) if daily.spo2_lowest else None,
        bb_change=daily.body_battery_change,
        awake_count=daily.awake_count,
        restless_moments=daily.restless_moments,
        deep_seconds=daily.deep_sleep_seconds,
        light_seconds=daily.light_sleep_seconds,
        rem_seconds=daily.rem_sleep_seconds,
        awake_seconds=daily.awake_seconds,
        stages_minutes=stages_minutes,
        stages_series=stages_series,
        heart_rate=_to_points(series.get(SERIES_SLEEP_HR, [])),
        respiration=_to_points(series.get(SERIES_SLEEP_RESPIRATION, [])),
        hrv=_to_points(series.get(SERIES_SLEEP_HRV, [])),
        movement=_to_points(series.get(SERIES_SLEEP_MOVEMENT, [])),
        prev_date=prev_date,
        next_date=next_date,
    )


# ── GET /api/v1/recovery/nights ───────────────────────────────────────────────


@router.get("/nights", response_model=NightsListView)
async def read_nights_list(
    limit: int = 60, db: AsyncSession = Depends(get_session)
) -> NightsListView:
    """List recorded sleep sessions, newest first."""
    nights = await garmin_service.list_nights(db, limit=limit)
    items = [
        NightListItem(
            date=n.date,
            score=n.sleep_score,
            duration_seconds=n.sleep_seconds,
            hrv=n.hrv_avg,
            rhr=n.resting_hr or n.avg_sleep_hr,
            deep_seconds=n.deep_sleep_seconds,
            rem_seconds=n.rem_sleep_seconds,
            light_seconds=n.light_sleep_seconds,
            awake_seconds=n.awake_seconds,
        )
        for n in nights
    ]
    return NightsListView(nights=items, total=len(items))


# ── GET /api/v1/recovery/activities ───────────────────────────────────────────


@router.get("/activities", response_model=ActivitiesListView)
async def read_activities_list(
    limit: int = 30, db: AsyncSession = Depends(get_session)
) -> ActivitiesListView:
    """List recorded sport activities, newest first."""
    activities = await garmin_service.list_activities(db, limit=limit)
    items = [
        ActivityItem(
            id=str(a.external_id or a.id),
            name=a.name or a.activity_type or "Activity",
            activity_type=a.activity_type or "other",
            start_time=a.start_time.isoformat() if a.start_time else a.date.isoformat(),
            duration_seconds=a.duration_seconds or 0,
            distance_meters=a.distance_m,
            calories=a.calories,
            avg_hr=a.avg_hr,
            max_hr=a.max_hr,
        )
        for a in activities
    ]
    return ActivitiesListView(activities=items, total=len(items))


# ── Sync & Import ─────────────────────────────────────────────────────────────


@router.post("/sync", response_model=GarminSyncResponse)
async def sync_garmin_now(
    db: AsyncSession = Depends(get_session),
    redis=Depends(get_redis),
) -> GarminSyncResponse:
    """Trigger an on-demand sync of Garmin metrics."""
    client = GarminClient.from_config(redis=redis)
    if not client.is_configured:
        return GarminSyncResponse(ok=False, synced_days=0, error="not_configured")

    summary = await garmin_service.sync(db, client)
    await db.commit()

    if summary.get("error"):
        return GarminSyncResponse(ok=False, synced_days=0, error=summary["error"])

    import time
    if redis is not None:
        await redis.set("sync:last_success:garmin", str(int(time.time())))

    return GarminSyncResponse(ok=True, synced_days=summary.get("days", 0))


@router.post("/import", response_model=GarminImportResponse)
async def import_garmin_data(
    request: Request,
    file: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_session),
) -> GarminImportResponse:
    """Ingest a Health Auto Export JSON dump."""
    try:
        if file is not None:
            validate_extension(file.filename, JSON_EXTS)
            payload = json.loads((await read_capped(file)).decode("utf-8"))
        else:
            payload = await request.json()
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        raise ValueError("invalid JSON")

    result = await garmin_service.ingest_health_auto_export(db, payload)
    await db.commit()

    return GarminImportResponse(
        ok=True,
        imported_dates=[str(d) for d in result.get("dates", [])],
        message="Imported successfully",
    )
