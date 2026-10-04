"""Thresholds and alert switches for the environment module.

One ``app_settings`` row (``environment_prefs``), sanitized the way
``proactive.prefs`` is: a hand-editable JSON blob is a trust boundary, so any stored
value is projected onto a field registry with hard bounds and a safe fallback, and
the getter **never raises** — a settings row edited into nonsense degrades to the
defaults instead of taking a screen or a job down with it.

The numbers are product heuristics, not medical norms, which is why the owner can
change every one of them.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import time as time_type
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from vitals.models.app_settings import AppSetting

logger = logging.getLogger(__name__)

SETTINGS_KEY = "environment_prefs"  # app_settings.key
MODULE_KEY = "environment"

CO2_RANGE = (400, 5000)
TEMP_RANGE = (-10.0, 45.0)
RH_RANGE = (0.0, 100.0)

DEFAULT_NIGHT_START = "00:00"
DEFAULT_NIGHT_END = "12:00"


@dataclass(frozen=True)
class EnvSettings:
    # CO2 zones: good < co2_ok_max <= ok < co2_warn <= warn < co2_bad <= bad.
    co2_ok_max: int = 800
    co2_warn: int = 1000
    co2_bad: int = 1400
    # Comfort range by day; the alert rules fire one degree beyond it.
    temp_day_min: float = 18.0
    temp_day_max: float = 26.0
    # Range for sleeping — drawn on the night layer and used by the brief, never
    # by an alert (nobody needs a ping about 21 degrees at 3 a.m.).
    temp_sleep_min: float = 17.0
    temp_sleep_max: float = 20.0
    # Humidity: the comfort band, and the wider band outside which an alert fires.
    rh_min: float = 35.0
    rh_max: float = 60.0
    rh_alert_low: float = 30.0
    rh_alert_high: float = 70.0
    # What "the night" means as a summary window: the date is the day you wake up.
    night_start: str = DEFAULT_NIGHT_START
    night_end: str = DEFAULT_NIGHT_END
    alerts_enabled: bool = True
    alert_telegram: bool = True

    def thresholds_dict(self) -> dict[str, Any]:
        """The numbers a chart draws as lines (no switches, no night window)."""
        return {
            "co2_ok_max": self.co2_ok_max,
            "co2_warn": self.co2_warn,
            "co2_bad": self.co2_bad,
            "temp_day_min": self.temp_day_min,
            "temp_day_max": self.temp_day_max,
            "temp_sleep_min": self.temp_sleep_min,
            "temp_sleep_max": self.temp_sleep_max,
            "rh_min": self.rh_min,
            "rh_max": self.rh_max,
            "rh_alert_low": self.rh_alert_low,
            "rh_alert_high": self.rh_alert_high,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.thresholds_dict(),
            "night_window": {"start": self.night_start, "end": self.night_end},
            "alerts_enabled": self.alerts_enabled,
            "alert_telegram": self.alert_telegram,
        }

    def night_times(self) -> tuple[time_type, time_type]:
        return (
            time_type.fromisoformat(self.night_start),
            time_type.fromisoformat(self.night_end),
        )


DEFAULTS = EnvSettings()


# ── Sanitizing ────────────────────────────────────────────────────────────────
def _number(raw: Any, default: float, low: float, high: float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if value != value:  # NaN compares unequal to itself and would pass min/max
        return default
    return max(low, min(high, value))


def _hhmm(raw: Any, default: str) -> str:
    try:
        return time_type.fromisoformat(str(raw)).strftime("%H:%M")
    except (TypeError, ValueError):
        return default


def _bool(raw: Any, default: bool) -> bool:
    if isinstance(raw, bool):
        return raw
    return default


def _night_window(src: dict[str, Any]) -> tuple[str, str]:
    window = src.get("night_window")
    if isinstance(window, dict):
        start = _hhmm(window.get("start"), DEFAULT_NIGHT_START)
        end = _hhmm(window.get("end"), DEFAULT_NIGHT_END)
    else:
        start, end = DEFAULT_NIGHT_START, DEFAULT_NIGHT_END
    # An empty window is a summary that never has any data in it.
    if start == end:
        return DEFAULT_NIGHT_START, DEFAULT_NIGHT_END
    return start, end


def sanitize(raw: Any) -> EnvSettings:
    """Arbitrary stored data → a full, in-range ``EnvSettings``. Never raises."""
    src = raw if isinstance(raw, dict) else {}
    d = DEFAULTS

    co2_ok = int(_number(src.get("co2_ok_max"), d.co2_ok_max, *CO2_RANGE))
    co2_warn = int(_number(src.get("co2_warn"), d.co2_warn, *CO2_RANGE))
    co2_bad = int(_number(src.get("co2_bad"), d.co2_bad, *CO2_RANGE))
    # The zones must stay ordered or a reading could be "bad" and "good" at once.
    co2_warn = max(co2_warn, co2_ok + 1)
    co2_bad = max(co2_bad, co2_warn + 1)

    def _pair(low_key: str, high_key: str, low_d: float, high_d: float, bounds):
        low = _number(src.get(low_key), low_d, *bounds)
        high = _number(src.get(high_key), high_d, *bounds)
        if high <= low:  # a band with no width can never hold a reading
            high = min(bounds[1], low + 1.0)
            low = min(low, high - 1.0)
        return round(low, 1), round(high, 1)

    temp_day_min, temp_day_max = _pair(
        "temp_day_min", "temp_day_max", d.temp_day_min, d.temp_day_max, TEMP_RANGE
    )
    temp_sleep_min, temp_sleep_max = _pair(
        "temp_sleep_min", "temp_sleep_max", d.temp_sleep_min, d.temp_sleep_max, TEMP_RANGE
    )
    rh_min, rh_max = _pair("rh_min", "rh_max", d.rh_min, d.rh_max, RH_RANGE)
    rh_alert_low, rh_alert_high = _pair(
        "rh_alert_low", "rh_alert_high", d.rh_alert_low, d.rh_alert_high, RH_RANGE
    )
    night_start, night_end = _night_window(src)

    return EnvSettings(
        co2_ok_max=co2_ok,
        co2_warn=co2_warn,
        co2_bad=co2_bad,
        temp_day_min=temp_day_min,
        temp_day_max=temp_day_max,
        temp_sleep_min=temp_sleep_min,
        temp_sleep_max=temp_sleep_max,
        rh_min=rh_min,
        rh_max=rh_max,
        rh_alert_low=rh_alert_low,
        rh_alert_high=rh_alert_high,
        night_start=night_start,
        night_end=night_end,
        alerts_enabled=_bool(src.get("alerts_enabled"), d.alerts_enabled),
        alert_telegram=_bool(src.get("alert_telegram"), d.alert_telegram),
    )


# ── Storage ───────────────────────────────────────────────────────────────────
async def get_settings(session: AsyncSession) -> EnvSettings:
    """The stored settings, or the defaults. Never raises."""
    try:
        row = await session.get(AppSetting, SETTINGS_KEY)
    except Exception:
        logger.warning("environment settings: DB read failed; using defaults", exc_info=True)
        return DEFAULTS
    return sanitize(row.value if row is not None else None)


async def set_settings(session: AsyncSession, patch: dict[str, Any]) -> EnvSettings:
    """Merge ``patch`` onto the stored settings, sanitize, store. Flushes; the
    caller commits.

    A patch is partial: omitted fields keep their stored value. ``night_window``
    may itself be partial (just ``start``).
    """
    row = await session.get(AppSetting, SETTINGS_KEY)
    current = sanitize(row.value if row is not None else None).to_dict()

    merged = dict(current)
    for key, value in (patch or {}).items():
        if key == "night_window" and isinstance(value, dict):
            merged["night_window"] = {**current["night_window"], **value}
        elif key in current:
            merged[key] = value
    clean = sanitize(merged)

    if row is None:
        session.add(AppSetting(key=SETTINGS_KEY, value=clean.to_dict()))
    else:
        row.value = clean.to_dict()  # a new dict, so SQLAlchemy sees the change
    await session.flush()
    return clean


def with_overrides(settings: EnvSettings, **changes: Any) -> EnvSettings:
    """A copy with fields replaced — for tests and what-if reads."""
    return sanitize({**settings.to_dict(), **changes})


__all__ = [
    "DEFAULTS",
    "EnvSettings",
    "MODULE_KEY",
    "SETTINGS_KEY",
    "get_settings",
    "sanitize",
    "set_settings",
    "with_overrides",
]
