"""Date-windowed rolling mean.

The window is by **calendar date**, not row index, so it stays correct on the
irregular / sparse sampling weight data really has (you don't weigh in every
day). For each point at date ``d`` the mean covers every value whose date is in
``[d − (window_days − 1), d]``.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Iterable, List

from vitals.services.analytics import Point


def rolling_mean_by_date(points: Iterable[Point], window_days: int = 7) -> List[Point]:
    """Trailing rolling mean over a calendar-day window.

    Returns one ``(date, mean)`` per input point, sorted by date. Duplicate dates
    are kept (each contributes), which is fine for charting. ``window_days`` must
    be >= 1.
    """
    if window_days < 1:
        raise ValueError("window_days must be >= 1")

    pts = sorted(points, key=lambda p: p[0])
    out: List[Point] = []
    # Two-pointer sliding window: dates are sorted ascending, so the window's left
    # bound only ever moves forward — O(n) instead of the naive O(n²) re-scan.
    lo = 0
    running = 0.0
    for hi, (d, v) in enumerate(pts):
        running += v
        window_start = d - timedelta(days=window_days - 1)
        while pts[lo][0] < window_start:
            running -= pts[lo][1]
            lo += 1
        count = hi - lo + 1
        out.append((d, round(running / count, 3)))
    return out
