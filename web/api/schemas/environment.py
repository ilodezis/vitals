"""Pydantic schemas for the environment API (``/api/v1/environment``).

Field names are snake_case, like the recovery screens. Instants are ISO-8601 UTC;
the screen converts them to the viewer's zone.
"""
from __future__ import annotations

import datetime as dt
from typing import Literal, Optional

from pydantic import BaseModel, Field

StationStatus = Literal["online", "stale", "offline", "never"]
Co2Zone = Literal["good", "ok", "warn", "bad", "none"]
Resolution = Literal["raw", "minute", "hour"]


class Thresholds(BaseModel):
    """The numbers a chart draws as lines."""

    co2_ok_max: int
    co2_warn: int
    co2_bad: int
    temp_day_min: float
    temp_day_max: float
    temp_sleep_min: float
    temp_sleep_max: float
    rh_min: float
    rh_max: float
    rh_alert_low: float
    rh_alert_high: float


class NightWindow(BaseModel):
    """What "the night" means as a summary window (local wall-clock ``HH:MM``)."""

    start: str = "00:00"
    end: str = "12:00"


class EnvSettings(Thresholds):
    night_window: NightWindow
    alerts_enabled: bool
    alert_telegram: bool


class EnvSettingsPatch(BaseModel):
    """A partial update: omitted fields keep their stored value. Out-of-range
    numbers are clamped, not rejected — the settings card shows the bounds."""

    co2_ok_max: Optional[int] = None
    co2_warn: Optional[int] = None
    co2_bad: Optional[int] = None
    temp_day_min: Optional[float] = None
    temp_day_max: Optional[float] = None
    temp_sleep_min: Optional[float] = None
    temp_sleep_max: Optional[float] = None
    rh_min: Optional[float] = None
    rh_max: Optional[float] = None
    rh_alert_low: Optional[float] = None
    rh_alert_high: Optional[float] = None
    night_window: Optional[NightWindow] = None
    alerts_enabled: Optional[bool] = None
    alert_telegram: Optional[bool] = None


class LiveStation(BaseModel):
    status: StationStatus
    last_seen_at: Optional[dt.datetime] = None
    age_s: Optional[int] = None
    rssi: Optional[int] = None
    fw: Optional[str] = None


class LiveNow(BaseModel):
    co2_ppm: Optional[int] = None
    temperature_c: Optional[float] = None
    humidity_pct: Optional[float] = None
    lux: Optional[float] = None
    co2_zone: Co2Zone = "none"
    # ppm per hour over the last 15 minutes; null until there are enough points.
    co2_trend_ppm_per_h: Optional[float] = None


class LiveView(BaseModel):
    # False when no station address is set at all — the screen's "not connected"
    # state, as opposed to a connected station that has not reported yet
    # (``station.status == "never"``).
    configured: bool
    station: LiveStation
    now: LiveNow
    thresholds: Thresholds


class Point(BaseModel):
    ts: dt.datetime
    co2_ppm: Optional[float] = None
    temperature_c: Optional[float] = None
    humidity_pct: Optional[float] = None
    lux: Optional[float] = None
    # Set on hour points only: the hour's CO2 extremes.
    co2_max: Optional[float] = None
    co2_min: Optional[float] = None


class Window(BaseModel):
    start: dt.datetime
    end: dt.datetime


class SeriesView(BaseModel):
    points: list[Point] = Field(default_factory=list)
    resolution: Resolution
    # Share of the window the station actually reported, 0-100.
    coverage_pct: float = 0.0
    thresholds: Thresholds
    window: Window


class Co2Stats(BaseModel):
    median: Optional[float] = None
    p90: Optional[float] = None
    max: Optional[float] = None
    minutes_above_warn: float = 0.0
    minutes_above_bad: float = 0.0


class RangeStats(BaseModel):
    min: Optional[float] = None
    mean: Optional[float] = None
    max: Optional[float] = None


class PeriodSummary(BaseModel):
    """A night window or a calendar day, summarised."""

    date: dt.date
    window: Window
    samples: int = 0
    coverage_pct: float = 0.0
    co2: Co2Stats
    temperature: RangeStats
    humidity: RangeStats


class PeriodView(BaseModel):
    """``GET /day/{date}`` and ``GET /night/{date}``: the summary plus the
    minute-resolution curve of the same window."""

    summary: PeriodSummary
    series: list[Point] = Field(default_factory=list)
    thresholds: Thresholds


class StationCheck(BaseModel):
    """The answer to "check the connection": a poll made right now."""

    ok: bool
    status: StationStatus
    # What failed, in words the settings card can show; absent when ok.
    error: Optional[str] = None
