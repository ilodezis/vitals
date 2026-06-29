"""Unit tests for the pure strength-progression engine (no DB)."""
from __future__ import annotations

from datetime import date, timedelta

from vitals.services.analytics.progression import (
    ADVANCE,
    DELOAD,
    DOUBLE_PROGRESSION,
    HOLD,
    LINEAR,
    ProgressionConfig,
    SessionResult,
    evaluate_progression,
)

START = date(2026, 5, 1)


def _sessions(specs):
    """specs: list of (weight, reps_list) → chronological SessionResults."""
    return [
        SessionResult(on_date=START + timedelta(days=i * 3), weight_kg=w, reps=r)
        for i, (w, r) in enumerate(specs)
    ]


def test_no_history_returns_none():
    assert evaluate_progression([], ProgressionConfig()) is None
    # Sessions with no recorded reps are ignored too.
    s = [SessionResult(START, 80.0, [])]
    assert evaluate_progression(s, ProgressionConfig()) is None


def test_double_progression_advance_when_all_sets_hit_top():
    cfg = ProgressionConfig(scheme=DOUBLE_PROGRESSION, rep_min=8, rep_max=12, increment_kg=2.5)
    s = _sessions([(80.0, [12, 12, 12])])
    v = evaluate_progression(s, cfg)
    assert v.status == ADVANCE
    assert v.signal == "🟢"
    assert v.suggested_weight_kg == 82.5
    assert v.current_weight_kg == 80.0


def test_double_progression_holds_when_a_set_misses_top():
    cfg = ProgressionConfig(scheme=DOUBLE_PROGRESSION, rep_min=8, rep_max=12)
    s = _sessions([(80.0, [12, 11, 10])])
    v = evaluate_progression(s, cfg)
    assert v.status == HOLD
    assert v.signal == "🟡"
    assert v.suggested_weight_kg == 80.0


def test_deload_after_consecutive_failures():
    cfg = ProgressionConfig(rep_min=8, rep_max=12, stop_after_failures=2, deload_factor=0.9)
    # Two consecutive sessions with a working set below rep_min (8).
    s = _sessions([(80.0, [10, 9, 8]), (80.0, [7, 7]), (80.0, [6, 5])])
    v = evaluate_progression(s, cfg)
    assert v.status == DELOAD
    assert v.signal == "🔴"
    # 80 * 0.9 = 72 → already on a 2.5 plate grid.
    assert v.suggested_weight_kg == 72.5 or v.suggested_weight_kg == 72.0
    # round(72/2.5)*2.5 = round(28.8)*2.5 = 29*2.5 = 72.5
    assert v.suggested_weight_kg == 72.5


def test_single_failure_does_not_deload():
    cfg = ProgressionConfig(rep_min=8, rep_max=12, stop_after_failures=2)
    s = _sessions([(80.0, [12, 12, 12]), (80.0, [7, 7])])
    v = evaluate_progression(s, cfg)
    assert v.status != DELOAD  # only one failing session → hold


def test_linear_advances_when_target_met():
    cfg = ProgressionConfig(scheme=LINEAR, rep_min=5, rep_max=5, increment_kg=2.5)
    s = _sessions([(100.0, [5, 5, 5])])
    v = evaluate_progression(s, cfg)
    assert v.status == ADVANCE
    assert v.suggested_weight_kg == 102.5


def test_linear_holds_when_below_target_but_not_deload_streak():
    cfg = ProgressionConfig(scheme=LINEAR, rep_min=5, rep_max=5, stop_after_failures=3)
    s = _sessions([(100.0, [5, 5]), (100.0, [4, 4])])
    v = evaluate_progression(s, cfg)
    assert v.status == HOLD


def test_recovery_after_failure_breaks_streak():
    """A good session resets the failure streak — no deload."""
    cfg = ProgressionConfig(rep_min=8, rep_max=12, stop_after_failures=2)
    s = _sessions([(80.0, [7, 7]), (80.0, [12, 12, 12])])
    v = evaluate_progression(s, cfg)
    assert v.status == ADVANCE  # latest session crushed it
