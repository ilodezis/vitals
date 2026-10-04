"""Result shapes of the environment service layer.

Plain frozen dataclasses with a ``to_dict()`` that yields JSON-ready values
(datetimes as ISO-8601 UTC strings) — the REST layer validates that dict into its
schema, the MCP tools and the exports serialize it as is. Keeping one shape here
means the screen, the connector and the alert rules all read the same numbers.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import date as date_type
from datetime import datetime
from typing import Any, Literal, Optional

# Station status, from the age of the latest snapshot (see ``live``).
STATUS_ONLINE = "online"
STATUS_STALE = "stale"
STATUS_OFFLINE = "offline"
STATUS_NEVER = "never"
StationStatus = Literal["online", "stale", "offline", "never"]

# CO2 comfort zones (``none`` = no reading).
ZONE_GOOD = "good"
ZONE_OK = "ok"
ZONE_WARN = "warn"
ZONE_BAD = "bad"
ZONE_NONE = "none"
Co2Zone = Literal["good", "ok", "warn", "bad", "none"]

Resolution = Literal["raw", "minute", "hour"]


def jsonable(value: Any) -> Any:
    """A dataclass / datetime / date tree → plain JSON types."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date_type):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


class _Jsonable:
    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass(frozen=True)
class LiveStation(_Jsonable):
    status: StationStatus = STATUS_NEVER
    last_seen_at: Optional[datetime] = None
    age_s: Optional[int] = None
    rssi: Optional[int] = None
    fw: Optional[str] = None


@dataclass(frozen=True)
class LiveNow(_Jsonable):
    co2_ppm: Optional[int] = None
    temperature_c: Optional[float] = None
    humidity_pct: Optional[float] = None
    lux: Optional[float] = None
    co2_zone: Co2Zone = ZONE_NONE
    # ppm per hour, from the last 15 minutes; ``None`` until there are enough points.
    co2_trend_ppm_per_h: Optional[float] = None


@dataclass(frozen=True)
class LiveState(_Jsonable):
    station: LiveStation = field(default_factory=LiveStation)
    now: LiveNow = field(default_factory=LiveNow)


@dataclass(frozen=True)
class Point(_Jsonable):
    """One chart point. For ``minute`` and ``hour`` the values are means; an
    ``hour`` point also carries the hour's CO2 extremes."""

    ts: datetime
    co2_ppm: Optional[float] = None
    temperature_c: Optional[float] = None
    humidity_pct: Optional[float] = None
    lux: Optional[float] = None
    co2_max: Optional[float] = None
    co2_min: Optional[float] = None


@dataclass(frozen=True)
class Window(_Jsonable):
    start: datetime
    end: datetime


@dataclass(frozen=True)
class Co2Stats(_Jsonable):
    median: Optional[float] = None
    p90: Optional[float] = None
    max: Optional[float] = None
    # Minutes at or above the warn / bad threshold, summed over the real gaps
    # between snapshots (each gap capped, so a silent station is not "high CO2").
    minutes_above_warn: float = 0.0
    minutes_above_bad: float = 0.0


@dataclass(frozen=True)
class RangeStats(_Jsonable):
    min: Optional[float] = None
    mean: Optional[float] = None
    max: Optional[float] = None


@dataclass(frozen=True)
class PeriodSummary(_Jsonable):
    """What a stretch of time looked like: the night window of a date, or its
    whole calendar day. ``samples`` is how many snapshots stand behind it and
    ``coverage_pct`` how much of the window they actually cover."""

    date: date_type
    window: Window
    samples: int = 0
    coverage_pct: float = 0.0
    co2: Co2Stats = field(default_factory=Co2Stats)
    temperature: RangeStats = field(default_factory=RangeStats)
    humidity: RangeStats = field(default_factory=RangeStats)


# The two are the same shape over different windows; separate names keep a call
# site honest about which window it asked for.
NightSummary = PeriodSummary
DaySummary = PeriodSummary
