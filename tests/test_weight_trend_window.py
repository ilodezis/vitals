"""The weight trend is a recent-window fit and every surface shares one projection.

Covers: the windowed slope ignoring an old fast-loss period, the chart projection and
the weeks-to-goal count describing one forecast, MCP ``get_trend`` printing the same
slope and date as ``chart_series``, the weekly delta refusing to span a logging gap,
and the dose-phase delta skipping noise ranges.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from vitals.services import milestones_service, weight_service
from vitals.services.analytics.regression import (
    fit_trend,
    fit_trend_windowed,
    project_date_for_value,
    project_from_level,
    trend_summary,
)
from web.routers import mcp as mcp_router

START = date(2026, 6, 1)
FAST_DAYS = 40  # days 0..39 drop 1.0 kg/day, days 40..67 drop 0.1 kg/day
LAST = START + timedelta(days=67)


async def _log_decelerating_loss(db_session) -> None:
    for i in range(68):
        kg = 120.0 - i if i < FAST_DAYS else 80.0 - 0.1 * (i - FAST_DAYS)
        await weight_service.log_weight(
            db_session, on_date=START + timedelta(days=i), weight_kg=round(kg, 3)
        )
    await db_session.commit()


# ── pure functions ───────────────────────────────────────────────────────────
def test_fit_trend_windowed_ignores_old_fast_loss():
    pts = [
        (START + timedelta(days=i), 120.0 - i if i < FAST_DAYS else 80.0 - 0.1 * (i - FAST_DAYS))
        for i in range(68)
    ]
    windowed = fit_trend_windowed(pts, 28)
    assert windowed is not None
    assert windowed.n == 28  # window is [last - 27, last], inclusive
    assert windowed.slope_per_week == pytest.approx(-0.7, abs=1e-6)
    # The whole-history fit is several times steeper: the bug this window removes.
    assert fit_trend(pts).slope_per_week < -3.0


def test_fit_trend_windowed_has_no_whole_history_fallback():
    pts = [(date(2026, 1, 1), 100.0), (date(2026, 1, 2), 99.0), (date(2026, 3, 1), 90.0)]
    # Only one point lies in the 28 days ending 03-01 → no slope, not the old line.
    assert fit_trend_windowed(pts, 28) is None
    assert fit_trend_windowed(pts, None) is not None


def test_fit_trend_windowed_excludes_noise_before_windowing():
    pts = [(START + timedelta(days=i), 100.0 - 0.5 * i) for i in range(10)]
    pts.append((START + timedelta(days=60), 150.0))  # spike far past the rest
    noise = [(START + timedelta(days=60), None)]
    trend = fit_trend_windowed(pts, 28, exclude=noise)
    assert trend is not None
    assert trend.slope_per_day == pytest.approx(-0.5, abs=1e-9)


def test_project_date_for_value_accepts_generator():
    pts = [(date(2026, 1, 1) + timedelta(days=i), 100.0 - i) for i in range(11)]
    assert project_date_for_value((p for p in pts), 85.0) == date(2026, 1, 16)


def test_project_date_for_value_anchors_on_last_clean_point():
    pts = [(date(2026, 1, 1) + timedelta(days=i), 100.0 - i) for i in range(11)]
    pts.append((date(2026, 1, 13), 130.0))  # later than every clean point, but noise
    got = project_date_for_value(
        pts, 87.5, exclude=[(date(2026, 1, 13), date(2026, 1, 13))]
    )
    # 87.5 is crossed on Jan 13 (round of 12.5 days). Measured against the noisy
    # Jan 13 "last" date that crossing looked already behind us and came back None.
    assert got is not None


def test_trend_summary_projects_from_rolling_level():
    pts = [(date(2026, 6, 1) + timedelta(days=7 * i), 100.0 - i) for i in range(4)]
    s = trend_summary(pts, fit_window_days=28, rolling_window_days=7, target=95.0)
    assert s is not None and s.trend is not None
    assert s.rolling_last == (date(2026, 6, 22), 97.0)
    assert s.projection_date == project_from_level(
        97.0, date(2026, 6, 22), s.trend.slope_per_day, 95.0
    )
    assert trend_summary([], fit_window_days=28) is None


# ── chart_series / weeks_to_goal ─────────────────────────────────────────────
async def test_chart_series_trend_uses_recent_window(db_session):
    await _log_decelerating_loss(db_session)
    series = await weight_service.chart_series(db_session)
    trend = series["trend"]
    assert trend["slope_per_week"] == pytest.approx(-0.7, abs=0.01)
    assert trend["window_days"] == weight_service.TREND_WINDOW_DAYS == 28
    assert trend["n"] == 28
    assert await weight_service.weekly_trend_delta(db_session) == pytest.approx(-0.7, abs=0.01)


async def test_chart_trend_is_none_with_too_few_points_in_window(db_session):
    await weight_service.log_weight(db_session, on_date=date(2026, 1, 1), weight_kg=100.0)
    await weight_service.log_weight(db_session, on_date=date(2026, 1, 3), weight_kg=99.0)
    await weight_service.log_weight(db_session, on_date=date(2026, 6, 1), weight_kg=90.0)
    await db_session.commit()
    series = await weight_service.chart_series(db_session, goal_kg=85.0)
    assert series["trend"] is None
    assert series["projection"] is None
    assert await weight_service.weekly_trend_delta(db_session) is None


async def test_projection_starts_from_latest_ma_and_agrees_with_weeks_to_goal(db_session):
    await _log_decelerating_loss(db_session)
    goal = 75.0
    series = await weight_service.chart_series(db_session, goal_kg=goal)

    ma_date, ma_level = LAST, series["trend_ma"][-1]["weight_kg"]
    assert date.fromisoformat(series["trend_ma"][-1]["date"]) == ma_date
    per_week = series["trend"]["slope_per_week"]
    expected = project_from_level(ma_level, ma_date, per_week / 7.0, goal)
    assert expected is not None
    proj = date.fromisoformat(series["projection"]["date"])
    assert abs((proj - expected).days) <= 1  # slope is rounded to 3 decimals on the wire
    # 77.6 kg at 0.1 kg/day → ~26 days, not the ~12 days the whole-history slope gave.
    assert 24 <= (proj - ma_date).days <= 28

    weeks = weight_service.weeks_to_goal(ma_level, goal, per_week)
    assert weeks is not None and weeks >= 1
    assert abs(weeks * 7 - (proj - ma_date).days) <= 4  # same forecast, in whole weeks


async def test_collect_goal_weeks_matches_chart_projection(db_session):
    await _log_decelerating_loss(db_session)
    await milestones_service.create_milestone(
        db_session, name="goal", target_value=75.0, target_unit="kg"
    )
    await db_session.commit()

    payload = await weight_service.collect(db_session)
    series = await weight_service.chart_series(db_session, goal_kg=75.0)
    days = (date.fromisoformat(series["projection"]["date"]) - LAST).days
    weeks = payload["pace"]["goal"]["weeks"]
    assert weeks is not None
    assert abs(weeks * 7 - days) <= 4
    assert payload["pace"]["per_week_kg"] == series["trend"]["slope_per_week"]


def test_weeks_to_goal_semantics():
    assert weight_service.weeks_to_goal(None, 90.0, -0.5) is None
    assert weight_service.weeks_to_goal(95.0, 90.0, None) is None
    assert weight_service.weeks_to_goal(95.0, 90.0, 0.2) is None  # moving away
    assert weight_service.weeks_to_goal(89.0, 90.0, -0.5) is None  # already below
    assert weight_service.weeks_to_goal(90.1, 90.0, -1.0) == 1  # never 0
    assert weight_service.weeks_to_goal(95.0, 90.0, -0.5) == 10


# ── weekly_delta ─────────────────────────────────────────────────────────────
async def test_weekly_delta_is_none_across_a_logging_gap(db_session):
    for i in range(3):
        await weight_service.log_weight(
            db_session, on_date=date(2026, 6, 1) + timedelta(days=i), weight_kg=100.0
        )
    # Next weigh-in 17 days later: the only earlier MA point is far outside 7-10 days.
    await weight_service.log_weight(db_session, on_date=date(2026, 6, 19), weight_kg=90.0)
    await db_session.commit()
    series = await weight_service.chart_series(db_session)
    assert series["weekly_delta"] is None


async def test_weekly_delta_uses_point_seven_to_ten_days_back(db_session):
    await weight_service.log_weight(db_session, on_date=date(2026, 6, 1), weight_kg=100.0)
    await weight_service.log_weight(db_session, on_date=date(2026, 6, 9), weight_kg=99.0)
    await db_session.commit()
    series = await weight_service.chart_series(db_session)
    assert series["weekly_delta"] == pytest.approx(-1.0, abs=0.01)  # 8 days apart


# ── dose_phase_delta ─────────────────────────────────────────────────────────
async def test_dose_phase_delta_excludes_noise_ranges(db_session):
    phase_start = date(2026, 6, 1)
    await weight_service.log_weight(db_session, on_date=phase_start, weight_kg=90.0)
    await weight_service.log_weight(db_session, on_date=date(2026, 6, 5), weight_kg=89.0)
    await weight_service.log_weight(db_session, on_date=date(2026, 6, 9), weight_kg=95.0)  # spike
    await weight_service.add_noise_marker(
        db_session, start_date=date(2026, 6, 9), end_date=date(2026, 6, 9), reason="sodium"
    )
    await db_session.commit()

    assert await weight_service.dose_phase_delta(db_session, phase_start) == -1.0
    # Same answer when the caller hands the weigh-ins in.
    weights = await weight_service.list_active_weights(db_session)
    phase = {"from_date": phase_start, "to_date": None}
    assert await weight_service.dose_phase_delta(db_session, phase, weights=weights) == -1.0


async def test_dose_phase_delta_none_when_noise_leaves_one_point(db_session):
    phase_start = date(2026, 6, 1)
    await weight_service.log_weight(db_session, on_date=phase_start, weight_kg=90.0)
    await weight_service.log_weight(db_session, on_date=date(2026, 6, 4), weight_kg=95.0)
    await weight_service.add_noise_marker(
        db_session, start_date=date(2026, 6, 4), end_date=None, reason="sodium"
    )
    await db_session.commit()
    assert await weight_service.dose_phase_delta(db_session, phase_start) is None


# ── MCP get_trend parity ─────────────────────────────────────────────────────
async def test_mcp_get_trend_matches_chart_series(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    await _log_decelerating_loss(db_session)

    series = await weight_service.chart_series(db_session, goal_kg=75.0)
    res = await mcp_router.get_trend("weight.weight_kg", target=75.0)

    assert res["trend"]["fit_window_days"] == weight_service.TREND_WINDOW_DAYS
    assert res["trend"]["slope_per_week"] == pytest.approx(
        series["trend"]["slope_per_week"], abs=1e-3
    )
    assert res["projection"]["projected_from"] == series["trend_ma"][-1]["weight_kg"]
    assert res["projection"]["date"] == series["projection"]["date"]

    # fit_window_days=None still means the whole (much steeper) history.
    whole = await mcp_router.get_trend("weight.weight_kg", fit_window_days=None)
    assert whole["trend"]["slope_per_week"] < -3.0
