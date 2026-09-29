"""``/api/v1/recovery`` — schemas for the recovery dashboard, sleep nights, and activities."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from pydantic import BaseModel


class RecoveryNorm(BaseModel):
    lo: float
    hi: float
    better: int  # 1 or -1
    unit: str


class RecoveryHeadline(BaseModel):
    sleep_score: Optional[int] = None
    sleep_minutes: Optional[int] = None
    hrv: Optional[float] = None
    hrv_nights_below: int = 0
    rhr: Optional[int] = None
    rhr_note: str = ""
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
    lo: float
    hi: float
    tone: str = ""


class RecoveryDayItem(BaseModel):
    date: dt.date
    sleep: Optional[int] = None
    hrv: Optional[float] = None
    rhr: Optional[int] = None
    stress: Optional[int] = None
    steps: Optional[int] = None
    bb: Optional[int] = None


class RecoveryView(BaseModel):
    date: dt.date
    today_date: dt.date
    is_today: bool
    is_configured: bool
    last_sync: Optional[str] = None
    headline: RecoveryHeadline
    night: Optional[RecoveryNightPreview] = None
    norms: dict[str, RecoveryNorm]
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
    prev_date: Optional[dt.date] = None
    next_date: Optional[dt.date] = None


# ── Nights List ───────────────────────────────────────────────────────────────


class NightListItem(BaseModel):
    date: dt.date
    score: Optional[int] = None
    duration_seconds: Optional[int] = None
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
    imported_dates: list[str] = []
    message: Optional[str] = None
