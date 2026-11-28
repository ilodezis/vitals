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
from vitals.services.analytics.rolling import rolling_mean_by_date

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


def project_from_level(
    level: float,
    level_date: date,
    slope_per_day: Optional[float],
    target_value: float,
    *,
    max_days: int = 730,
) -> Optional[date]:
    """The date a series sitting at ``level`` on ``level_date`` reaches
    ``target_value`` when it keeps moving at ``slope_per_day``.

    The one goal projection every surface uses: start from where the series *is*
    (its latest smoothed value, on the date that value describes — not today, and
    not wherever a fitted line happens to pass), move at the current rate. ``None``
    when there is no rate, the rate is flat, it moves away from the target, the
    target is already reached, or the crossing lies beyond ``max_days``.
    """
    if slope_per_day is None or abs(slope_per_day) < _FLAT_SLOPE_EPS:
        return None
    gap = target_value - level
    if gap == 0 or (gap > 0) != (slope_per_day > 0):
        return None
    days = gap / slope_per_day
    if not math.isfinite(days) or days > max_days:
        return None
    return level_date + timedelta(days=max(1, round(days)))


def fit_trend_windowed(
    points: Iterable[Point],
    window_days: Optional[int],
    *,
    exclude: Optional[Sequence[Tuple[date, Optional[date]]]] = None,
) -> Optional[Trend]:
    """Least-squares line over the recent window only.

    The window is ``[last - (window_days - 1), last]`` where ``last`` is the date of
    the final point left after ``exclude``. Fewer than two points on two distinct
    dates in the window gives ``None`` — it never widens back to the whole history,
    because an old fast-loss period would then masquerade as the current rate.
    ``window_days=None`` fits the whole history.
    """
    if window_days is not None and window_days < 1:
        raise ValueError("window_days must be >= 1")
    pts = sorted(
        exclude_ranges(points, exclude) if exclude else list(points),
        key=lambda p: p[0],
    )
    if not pts:
        return None
    if window_days is not None:
        start = pts[-1][0] - timedelta(days=window_days - 1)
        pts = [p for p in pts if p[0] >= start]
    return fit_trend(pts)


@dataclass(frozen=True)
class TrendSummary:
    trend: Optional[Trend]            # windowed fit (None when it is undefined)
    rolling_last: Point               # latest rolling mean and the date it describes
    projection_date: Optional[date]   # when the series reaches the target, if any


def trend_summary(
    points: Iterable[Point],
    *,
    fit_window_days: Optional[int],
    rolling_window_days: int = 7,
    target: Optional[float] = None,
    fallback_to_all: bool = False,
) -> Optional[TrendSummary]:
    """Windowed slope + latest rolling mean + projected target date for one series.

    ``points`` must already be noise-free. The slope is ``fit_trend_windowed`` (so it
    matches the weight chart's trend exactly); the projection starts from the latest
    rolling mean via ``project_from_level``. ``fallback_to_all`` re-fits the whole
    history when the window holds under two points — for sparse series (labs) whose
    samples are weeks apart; weight leaves it off. ``None`` for an empty series.
    """
    pts = sorted(points, key=lambda p: p[0])
    if not pts:
        return None
    trend = fit_trend_windowed(pts, fit_window_days)
    if trend is None and fallback_to_all and fit_window_days is not None:
        trend = fit_trend(pts)
    rolling_last = rolling_mean_by_date(pts, window_days=rolling_window_days)[-1]
    projection_date = None
    if target is not None and trend is not None:
        projection_date = project_from_level(
            rolling_last[1], rolling_last[0], trend.slope_per_day, target
        )
    return TrendSummary(trend=trend, rolling_last=rolling_last, projection_date=projection_date)


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
    # Materialise once: ``points`` may be a generator, and the noise-excluded points
    # (not the raw ones) decide both the fit and where "now" is.
    pts = sorted(
        exclude_ranges(points, exclude) if exclude else list(points),
        key=lambda p: p[0],
    )
    trend = fit_trend(pts)
    if trend is None or abs(trend.slope_per_day) < _FLAT_SLOPE_EPS:
        return None

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
