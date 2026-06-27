"""Pure-logic unit tests for the weight analytics (no DB)."""
from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from vitals.services.analytics import exclude_ranges
from vitals.services.analytics.navy import lean_body_mass_kg, navy_body_fat_pct
from vitals.services.analytics.regression import (
    fit_trend,
    project_date_for_value,
)
from vitals.services.analytics.rolling import rolling_mean_by_date


# ── Navy body fat ─────────────────────────────────────────────────────────────
def test_navy_male_known_value():
    bf = navy_body_fat_pct(waist_cm=85, neck_cm=38, height_cm=190, sex="male")
    # Independently computed from the spec formula ≈ 14.52
    assert bf == pytest.approx(14.52, abs=0.05)


def test_navy_male_smaller_waist_means_lower_bf():
    lean = navy_body_fat_pct(waist_cm=80, neck_cm=38, height_cm=190)
    fuller = navy_body_fat_pct(waist_cm=95, neck_cm=38, height_cm=190)
    assert lean < fuller


def test_navy_invalid_geometry_raises():
    with pytest.raises(ValueError):
        navy_body_fat_pct(waist_cm=38, neck_cm=38, height_cm=190)  # waist == neck


def test_navy_female_requires_hips():
    with pytest.raises(ValueError):
        navy_body_fat_pct(waist_cm=70, neck_cm=32, height_cm=170, sex="female")
    # with hips it computes
    bf = navy_body_fat_pct(
        waist_cm=70, neck_cm=32, height_cm=170, sex="female", hips_cm=95
    )
    assert 0 < bf < 60


def test_lean_body_mass():
    assert lean_body_mass_kg(88.0, 14.52) == pytest.approx(75.22, abs=0.02)


# ── Rolling mean (date-windowed) ──────────────────────────────────────────────
def test_rolling_mean_calendar_window_not_row_index():
    d1 = date(2026, 1, 1)
    d2 = date(2026, 1, 2)
    d8 = date(2026, 1, 8)
    out = rolling_mean_by_date([(d1, 1.0), (d2, 2.0), (d8, 8.0)], window_days=7)
    assert out[0] == (d1, 1.0)
    assert out[1] == (d2, 1.5)
    # d8 window is [d2..d8] → only d2 (2.0) and d8 (8.0); d1 falls outside.
    assert out[2] == (d8, 5.0)


def test_rolling_mean_sorts_input():
    d1 = date(2026, 1, 1)
    d2 = date(2026, 1, 2)
    out = rolling_mean_by_date([(d2, 2.0), (d1, 1.0)])
    assert [p[0] for p in out] == [d1, d2]


# ── Regression / projection ───────────────────────────────────────────────────
def _line(start: date, n: int, v0: float, slope: float):
    return [(start + timedelta(days=i), v0 + slope * i) for i in range(n)]


def test_fit_trend_recovers_slope():
    pts = _line(date(2026, 1, 1), 11, 100.0, -1.0)
    trend = fit_trend(pts)
    assert trend is not None
    assert trend.slope_per_day == pytest.approx(-1.0, abs=1e-9)
    assert trend.slope_per_week == pytest.approx(-7.0, abs=1e-9)


def test_fit_trend_needs_two_distinct_dates():
    assert fit_trend([(date(2026, 1, 1), 80.0)]) is None
    assert fit_trend([(date(2026, 1, 1), 80.0), (date(2026, 1, 1), 81.0)]) is None


def test_projection_reaches_target():
    pts = _line(date(2026, 1, 1), 11, 100.0, -1.0)  # 100→90 over Jan 1..11
    got = project_date_for_value(pts, 85.0)
    assert got == date(2026, 1, 16)


def test_projection_none_when_moving_away():
    pts = _line(date(2026, 1, 1), 11, 100.0, -1.0)  # losing
    # target above current → never reached on a downward trend
    assert project_date_for_value(pts, 120.0) is None


def test_projection_none_when_flat():
    pts = _line(date(2026, 1, 1), 11, 90.0, 0.0)
    assert project_date_for_value(pts, 85.0) is None


# ── Noise exclusion ───────────────────────────────────────────────────────────
def test_exclude_ranges_drops_points_in_range():
    pts = [(date(2026, 1, d), float(d)) for d in range(1, 11)]
    kept = exclude_ranges(pts, [(date(2026, 1, 3), date(2026, 1, 5))])
    kept_days = [d.day for (d, _v) in kept]
    assert 3 not in kept_days and 4 not in kept_days and 5 not in kept_days
    assert 2 in kept_days and 6 in kept_days


def test_exclude_ranges_open_ended():
    pts = [(date(2026, 1, d), float(d)) for d in range(1, 11)]
    kept = exclude_ranges(pts, [(date(2026, 1, 8), None)])
    kept_days = [d.day for (d, _v) in kept]
    assert max(kept_days) == 7


def test_projection_excludes_noise():
    # Clean downtrend, but inject a noisy spike inside an excluded range.
    pts = _line(date(2026, 1, 1), 11, 100.0, -1.0)
    pts_noisy = pts + [(date(2026, 1, 5), 130.0)]  # creatine water spike
    clean = project_date_for_value(
        pts_noisy, 85.0, exclude=[(date(2026, 1, 5), date(2026, 1, 5))]
    )
    assert clean == date(2026, 1, 16)
