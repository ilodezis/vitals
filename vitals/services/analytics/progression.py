"""Strength-progression engine (pure, no DB).

Given the chronological history of an exercise's *working* sets, decide what to do
next. Two schemes (per the module-5 spec):

  * ``double_progression`` — work a rep range ``[rep_min, rep_max]`` at a fixed
    weight. When **every** working set reaches ``rep_max`` → 🟢 advance the weight
    by ``increment_kg`` (and drop back to the bottom of the range). Otherwise 🟡
    hold and keep adding reps.
  * ``linear`` — a fixed step every session that meets the target (``rep_min``);
    🟢 advance by ``increment_kg``.

Stop rule (both schemes): if the lifter fails to reach ``rep_min`` in a working
set for ``stop_after_failures`` consecutive sessions → 🔴 deload (reduce the
weight ~10%). The product is a navigator — this is a suggestion, never enforced.

The caller (``hevy_service``) reduces DB rows to :class:`SessionResult` objects
(one per session: the top working weight and that weight's set reps); everything
here is side-effect-free and unit-tested.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional, Sequence

DOUBLE_PROGRESSION = "double_progression"
LINEAR = "linear"

# UI signal chips.
ADVANCE = "advance"   # 🟢 ready to add weight
HOLD = "hold"         # 🟡 keep working the current weight
DELOAD = "deload"     # 🔴 stop rule tripped — back the weight off

_SIGNAL = {ADVANCE: "🟢", HOLD: "🟡", DELOAD: "🔴"}

# Round a suggested weight to the nearest loadable increment (2.5 kg ≈ small
# plates per side). Keeps "−10 %" from suggesting a 83.7 kg barbell.
_PLATE_STEP = 2.5


@dataclass(frozen=True)
class ProgressionConfig:
    scheme: str = DOUBLE_PROGRESSION
    rep_min: int = 8
    rep_max: int = 12
    increment_kg: float = 2.5
    deload_factor: float = 0.9
    stop_after_failures: int = 2


@dataclass(frozen=True)
class SessionResult:
    """One session's top working weight and the reps of each set at that weight."""

    on_date: date
    weight_kg: float
    reps: Sequence[int]


@dataclass(frozen=True)
class ProgressionVerdict:
    status: str                       # advance | hold | deload
    signal: str                       # 🟢 | 🟡 | 🔴
    message: str
    suggested_weight_kg: Optional[float]
    current_weight_kg: Optional[float]


def _round_to_plate(weight: float) -> float:
    return round(weight / _PLATE_STEP) * _PLATE_STEP


def _failure_streak(sessions: Sequence[SessionResult], rep_min: int) -> int:
    """Count trailing sessions where the worst working set fell below ``rep_min``."""
    streak = 0
    for s in reversed(sessions):
        worst = min(s.reps) if s.reps else 0
        if worst < rep_min:
            streak += 1
        else:
            break
    return streak


def evaluate_progression(
    sessions: Sequence[SessionResult], config: ProgressionConfig
) -> Optional[ProgressionVerdict]:
    """Decide the next move for an exercise from its session history (chronological,
    oldest → newest). Returns ``None`` when there's no history to judge."""
    sessions = [s for s in sessions if s.reps]
    if not sessions:
        return None

    latest = sessions[-1]
    current = latest.weight_kg

    # ── Stop rule first: a deload signal overrides everything ───────────────────
    streak = _failure_streak(sessions, config.rep_min)
    if streak >= config.stop_after_failures:
        suggested = _round_to_plate(current * config.deload_factor)
        return ProgressionVerdict(
            status=DELOAD,
            signal=_SIGNAL[DELOAD],
            message=(
                f"{streak} сессии подряд ниже {config.rep_min} повт. — "
                f"снизить вес ~10% до {suggested:g} кг."
            ),
            suggested_weight_kg=suggested,
            current_weight_kg=current,
        )

    # The "all sets hit X" gate is just "the worst set hit X".
    worst = min(latest.reps)

    if config.scheme == LINEAR:
        # Hit the target in every working set → step up.
        if worst >= config.rep_min:
            suggested = _round_to_plate(current + config.increment_kg)
            return ProgressionVerdict(
                ADVANCE, _SIGNAL[ADVANCE],
                f"Цель {config.rep_min} повт. взята — +{config.increment_kg:g} кг "
                f"до {suggested:g} кг.",
                suggested, current,
            )
        return ProgressionVerdict(
            HOLD, _SIGNAL[HOLD],
            f"Держим {current:g} кг до {config.rep_min} повт. во всех сетах.",
            current, current,
        )

    # ── double_progression ─────────────────────────────────────────────────────
    if worst >= config.rep_max:
        suggested = _round_to_plate(current + config.increment_kg)
        return ProgressionVerdict(
            ADVANCE, _SIGNAL[ADVANCE],
            f"Верх диапазона ({config.rep_max} повт.) взят во всех сетах — "
            f"+{config.increment_kg:g} кг до {suggested:g} кг.",
            suggested, current,
        )
    return ProgressionVerdict(
        HOLD, _SIGNAL[HOLD],
        f"Добираем повторы к {config.rep_max} на {current:g} кг "
        f"(сейчас минимум {worst}).",
        current, current,
    )
