"""The pure helpers behind the environment numbers."""
from __future__ import annotations

from datetime import timedelta

import pytest
from env_support import at

from vitals.services.environment import stats

T0 = at("2026-10-05T10:00:00")


def _ts(*seconds):
    return [T0 + timedelta(seconds=s) for s in seconds]


@pytest.mark.parametrize(
    "values, q, expected",
    [([], 50, None), ([7], 90, 7.0), ([1, 2, 3, 4], 50, 2.5), ([1, 2, 3, 4, 5], 50, 3.0),
     (list(range(1, 11)), 90, 9.1), ([5, 1, 3], 0, 1.0), ([5, 1, 3], 100, 5.0)],
)
def test_percentile_interpolates_like_numpy(values, q, expected):
    assert stats.percentile(values, q) == expected


def test_a_snapshot_stands_for_the_time_to_the_next_but_never_more_than_a_minute():
    ivs = stats.intervals(_ts(0, 10, 200))
    assert [(a - T0).total_seconds() for a, _ in ivs] == [0, 10, 200]
    assert [(b - a).total_seconds() for a, b in ivs] == [10, 60, 10]  # gap capped; the last = one interval


def test_covered_seconds_clip_to_the_window():
    ts = _ts(0, 10, 20)
    assert stats.covered_seconds(ts, T0, T0 + timedelta(seconds=30)) == 30
    assert stats.covered_seconds(ts, T0 + timedelta(seconds=15), T0 + timedelta(seconds=100)) == 15
    assert stats.covered_seconds(ts, T0 + timedelta(hours=1), T0 + timedelta(hours=2)) == 0


def test_seconds_where_counts_only_flagged_snapshots():
    ts = _ts(0, 10, 20, 30)
    assert stats.seconds_where(ts, [True, False, True, False], T0, T0 + timedelta(hours=1)) == 20


def test_covered_by_hour_splits_an_interval_across_the_boundary():
    out = stats.covered_by_hour([T0 + timedelta(minutes=59, seconds=45), T0 + timedelta(hours=1, seconds=30)])
    # The 45 s interval splits 15 / 30 around the boundary; the last snapshot adds its 10 s.
    assert out == {T0: 15.0, T0 + timedelta(hours=1): 40.0}


def test_slope_is_per_hour():
    pts = [(T0 + timedelta(seconds=10 * i), 600 + i) for i in range(10)]
    assert stats.slope_per_hour(pts) == pytest.approx(360.0)
    assert stats.slope_per_hour([(T0, 1.0)]) is None
    assert stats.slope_per_hour([(T0, 1.0), (T0, 2.0)]) is None  # one instant has no slope
