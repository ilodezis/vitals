"""``/api/v1/recovery`` — schemas for the recovery dashboard, sleep nights, and activities."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from pydantic import BaseModel


class RecoveryNorm(BaseModel):
    lo: float
    hi: float
    better: int  # 1 or -1
    unit: str  # "" | "ms" | "bpm" — a code; the screen prints it in its language


class RecoveryHeadline(BaseModel):
    sleep_score: Optional[int] = None
    sleep_minutes: Optional[int] = None
    hrv: Optional[float] = None
    hrv_nights_below: int = 0
    rhr: Optional[int] = None
    rhr_note: str = ""  # "" | "normal" | "upper" | "above" | "below"
    body_battery_from: Optional[int] = None
    body_battery_to: Optional[int] = None


class RecoveryNightPreview(BaseModel):
    date: dt.date
    start: str
    end: str
    stages: list[int] = []  # 0: awake, 1: rem, 2: light, 3: deep
    stage_minutes: list[int] = []  # [awake, rem, light, deep]


class RecoveryBar(BaseModel):
    key: str  # 'sleep' | 'hrv' | 'rhr' | 'stress'
    min: float
    max: float
    value: Optional[float] = None
    lo: Optional[float] = None  # no corridor until there is enough history
    hi: Optional[float] = None
    tone: str = ""
    unit: str = ""  # "" | "ms" | "bpm" — a code, like the norm's


class RecoveryDayItem(BaseModel):
    date: dt.date
    sleep: Optional[int] = None
    hrv: Optional[float] = None
    rhr: Optional[int] = None
    stress: Optional[int] = None
    steps: Optional[int] = None
    bb: Optional[int] = None
    awake_count: Optional[int] = None


class RecoveryActivity(BaseModel):
    """The shown day's movement: steps, stress, intensity minutes and active calories."""
    steps: Optional[int] = None
    stress: Optional[int] = None
    intensity_moderate: Optional[int] = None
    intensity_vigorous: Optional[int] = None
    active_calories: Optional[int] = None


class IntradayPoint(BaseModel):
    ts: str  # local wall-clock ISO datetime
    value: float


class RecoveryIntraday(BaseModel):
    """The shown day's curves; a series the watch did not record is empty."""
    stress: list[IntradayPoint] = []
    body_battery: list[IntradayPoint] = []
    heart_rate: list[IntradayPoint] = []


class RecoveryView(BaseModel):
    date: dt.date
    today_date: dt.date
    is_today: bool
    is_configured: bool
    last_sync: Optional[str] = None  # local ISO datetime of the last successful sync
    headline: RecoveryHeadline
    activity: RecoveryActivity = RecoveryActivity()
    intraday: RecoveryIntraday = RecoveryIntraday()
    advice: Optional[str] = None  # the recovery observation, in the user's language
    night: Optional[RecoveryNightPreview] = None
    norms: dict[str, RecoveryNorm]  # only the metrics with enough history
    norms_days: int = 0  # how many days the corridors were computed from
    norms_min_days: int = 0  # how many it takes before a corridor is shown
    bars: list[RecoveryBar] = []
    days: list[RecoveryDayItem] = []


# ── Sleep Night Detail ────────────────────────────────────────────────────────


class SleepStageSegment(BaseModel):
    stage: str  # "deep" | "light" | "rem" | "awake"
    start_min: int
    end_min: int
    duration_min: int


class IntradaySeriesPoint(BaseModel):
    time: str
    value: float
    ts: str = ""  # local wall-clock ISO datetime; a night crosses midnight


class SleepNightView(BaseModel):
    date: dt.date
    today_date: dt.date
    is_today: bool
    score: Optional[int] = None
    duration_seconds: Optional[int] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    rhr: Optional[int] = None
    spo2_min: Optional[float] = None
    bb_change: Optional[int] = None
    awake_count: Optional[int] = None
    restless_moments: Optional[int] = None
    sleep_need_minutes: Optional[int] = None
    breathing_disrupted: bool = False
    deep_seconds: Optional[int] = None
    light_seconds: Optional[int] = None
    rem_seconds: Optional[int] = None
    awake_seconds: Optional[int] = None
    stages_minutes: dict[str, int] = {}
    stages_series: list[SleepStageSegment] = []
    heart_rate: list[IntradaySeriesPoint] = []
    respiration: list[IntradaySeriesPoint] = []
    hrv: list[IntradaySeriesPoint] = []
    movement: list[IntradaySeriesPoint] = []
    spo2: list[IntradaySeriesPoint] = []
    stress: list[IntradaySeriesPoint] = []
    body_battery: list[IntradaySeriesPoint] = []
    prev_date: Optional[dt.date] = None
    next_date: Optional[dt.date] = None


# ── Nights List ───────────────────────────────────────────────────────────────


class NightListItem(BaseModel):
    date: dt.date
    score: Optional[int] = None
    duration_seconds: Optional[int] = None
    start_time: Optional[str] = None  # "HH:MM", lights out
    end_time: Optional[str] = None  # "HH:MM", wake-up
    awake_count: Optional[int] = None
    bb_change: Optional[int] = None
    hrv: Optional[float] = None
    rhr: Optional[int] = None
    deep_seconds: Optional[int] = None
    rem_seconds: Optional[int] = None
    light_seconds: Optional[int] = None
    awake_seconds: Optional[int] = None


class NightsListView(BaseModel):
    nights: list[NightListItem]
    total: int


# ── Activities List ───────────────────────────────────────────────────────────


class ActivityZone(BaseModel):
    zone: int
    seconds: float


class ActivitySplit(BaseModel):
    index: int
    distance_meters: Optional[float] = None
    duration_seconds: Optional[float] = None
    avg_hr: Optional[int] = None


class ActivityItem(BaseModel):
    id: str
    name: str
    activity_type: str
    start_time: str
    duration_seconds: int
    distance_meters: Optional[float] = None
    calories: Optional[int] = None
    avg_hr: Optional[int] = None
    max_hr: Optional[int] = None
    training_effect_aerobic: Optional[float] = None
    training_effect_anaerobic: Optional[float] = None
    elevation_gain_meters: Optional[float] = None
    avg_power: Optional[int] = None
    hr_zones: list[ActivityZone] = []
    splits: list[ActivitySplit] = []  # only when there is more than one lap


class ActivitiesListView(BaseModel):
    activities: list[ActivityItem]
    total: int


# ── Sync & Import ─────────────────────────────────────────────────────────────


class GarminSyncResponse(BaseModel):
    ok: bool
    synced_days: int = 0
    error: Optional[str] = None


class GarminImportResponse(BaseModel):
    ok: bool
    # How many days the file filled in.
    imported_days: int = 0
    imported_dates: list[str] = []
    message: Optional[str] = None
