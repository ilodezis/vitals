"""Least-squares linear trend + target-date projection.

Used to project when weight will reach a goal. Noise ranges are excluded by the
caller (or pass them through ``exclude``); the fit itself is a plain numpy
``polyfit`` on (days-since-first-point, value).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Optional, Sequence, Tuple

import numpy as np

from vitals.services.analytics import Point, exclude_ranges

# Slopes below this (value-units per day) are treated as flat — numpy.polyfit on
# a level series returns a ~1e-16 slope rather than exactly 0, which would
# otherwise project an absurd, overflow-prone crossing date.
_FLAT_SLOPE_EPS = 1e-9


@dataclass(frozen=True)
class Trend:
    slope_per_day: float   # value units per day (negative = losing)
    intercept: float       # value at the first point's date
    anchor: date           # the first point's date (x = 0)
    n: int                 # number of points used

    @property
    def slope_per_week(self) -> float:
        return self.slope_per_day * 7.0

    def value_on(self, d: date) -> float:
        return self.intercept + self.slope_per_day * (d - self.anchor).days


def fit_trend(
    points: Iterable[Point],
    *,
    exclude: Optional[Sequence[Tuple[date, Optional[date]]]] = None,
) -> Optional[Trend]:
    """Least-squares line through the points. Returns None when there aren't at
    least two points on two distinct dates (a slope is undefined)."""
    pts = list(points)
    if exclude:
        pts = exclude_ranges(pts, exclude)
    pts = sorted(pts, key=lambda p: p[0])
    if len(pts) < 2:
        return None

    anchor = pts[0][0]
    xs = np.array([(d - anchor).days for (d, _v) in pts], dtype=float)
    ys = np.array([v for (_d, v) in pts], dtype=float)
    if len(set(xs.tolist())) < 2:
        return None  # all on one date → no slope

    slope, intercept = np.polyfit(xs, ys, 1)
    return Trend(
        slope_per_day=float(slope),
        intercept=float(intercept),
        anchor=anchor,
        n=len(pts),
    )


def project_date_for_value(
    points: Iterable[Point],
    target_value: float,
    *,
    exclude: Optional[Sequence[Tuple[date, Optional[date]]]] = None,
    max_days: int = 3650,
) -> Optional[date]:
    """Project the date the trend crosses ``target_value``.

    Returns None when there's no usable trend, the slope is flat, or the target
    lies on the wrong side of the trend (already passed, or moving away from it),
    or the crossing is further out than ``max_days`` (default ~10y — keeps a
    near-flat slope from yielding an absurd century-away date).
    """
    trend = fit_trend(points, exclude=exclude)
    if trend is None or abs(trend.slope_per_day) < _FLAT_SLOPE_EPS:
        return None

    pts = sorted(points, key=lambda p: p[0])
    last_date = pts[-1][0]
    current = trend.value_on(last_date)

    # Days from the anchor until the line reaches the target. Guard against a
    # near-flat slope yielding a non-finite / overflowing offset.
    days_from_anchor = (target_value - trend.intercept) / trend.slope_per_day
    if not math.isfinite(days_from_anchor) or abs(days_from_anchor) > max_days + 36500:
        return None
    crossing = trend.anchor + timedelta(days=round(days_from_anchor))

    if crossing <= last_date:
        return None  # already crossed (target on the wrong side / behind us)

    # Must actually be heading toward the target.
    moving_toward = (target_value < current and trend.slope_per_day < 0) or (
        target_value > current and trend.slope_per_day > 0
    )
    if not moving_toward:
        return None
    if (crossing - last_date).days > max_days:
        return None
    return crossing
