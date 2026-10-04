"""Pure helpers over station samples — no database, no clock.

What "covered" means is the one rule every number here shares: a snapshot stands
for the time up to the next one, but never for more than ``GAP_CAP_S``. A station
that went quiet for ten minutes therefore does not turn its last reading into ten
minutes of "CO2 was high" — and coverage counts only the time it actually
reported. The final snapshot of a series stands for one snapshot interval.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Iterable, Optional, Sequence

# Longest span one snapshot may stand for.
GAP_CAP_S = 60.0
# How often the station produces a snapshot (it is fixed in the firmware).
SNAPSHOT_INTERVAL_S = 10.0


def percentile(values: Sequence[float], q: float) -> Optional[float]:
    """The ``q``-th percentile (0-100) by linear interpolation, like numpy's
    default. ``None`` for no values."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * (q / 100.0)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return float(ordered[low])
    return float(ordered[low] + (ordered[high] - ordered[low]) * (rank - low))


def mean(values: Sequence[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def intervals(timestamps: Sequence[datetime]) -> list[tuple[datetime, datetime]]:
    """The stretch of time each snapshot stands for, in order. ``timestamps``
    must be sorted ascending."""
    out: list[tuple[datetime, datetime]] = []
    for i, ts in enumerate(timestamps):
        if i + 1 < len(timestamps):
            span = min((timestamps[i + 1] - ts).total_seconds(), GAP_CAP_S)
        else:
            span = SNAPSHOT_INTERVAL_S
        out.append((ts, ts + timedelta(seconds=max(span, 0.0))))
    return out


def clip_seconds(interval: tuple[datetime, datetime], start: datetime, end: datetime) -> float:
    """Seconds of ``interval`` that fall inside ``[start, end)``."""
    low = max(interval[0], start)
    high = min(interval[1], end)
    return max((high - low).total_seconds(), 0.0)


def covered_seconds(timestamps: Sequence[datetime], start: datetime, end: datetime) -> float:
    return sum(clip_seconds(iv, start, end) for iv in intervals(timestamps))


def covered_by_hour(timestamps: Sequence[datetime]) -> dict[datetime, float]:
    """Seconds covered in each clock hour (keys are hour starts, UTC). An interval
    that straddles an hour boundary is split between the two."""
    out: dict[datetime, float] = {}
    for lo, hi in intervals(timestamps):
        hour = lo.replace(minute=0, second=0, microsecond=0)
        while hour < hi:
            nxt = hour + timedelta(hours=1)
            secs = clip_seconds((lo, hi), hour, nxt)
            if secs:
                out[hour] = out.get(hour, 0.0) + secs
            hour = nxt
    return out


def seconds_where(
    timestamps: Sequence[datetime],
    flags: Iterable[bool],
    start: datetime,
    end: datetime,
) -> float:
    """Covered seconds, inside ``[start, end)``, of the snapshots whose flag is true."""
    return sum(
        clip_seconds(iv, start, end)
        for iv, flag in zip(intervals(timestamps), flags)
        if flag
    )


def slope_per_hour(points: Sequence[tuple[datetime, float]]) -> Optional[float]:
    """Least-squares slope of ``value`` against time, per hour. ``None`` when the
    points are all at one instant."""
    if len(points) < 2:
        return None
    t0 = points[0][0]
    xs = [(ts - t0).total_seconds() for ts, _ in points]
    ys = [v for _, v in points]
    n = len(points)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    var = sum((x - mean_x) ** 2 for x in xs)
    if var == 0:
        return None
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    return cov / var * 3600.0
