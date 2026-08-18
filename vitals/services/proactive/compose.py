"""Шов 3 — a message is a list of blocks; text happens once, at the very end.

The deterministic blocks are built here by code, from the same cross-domain
context the weekly digest assembles. The model contributes exactly **one** block
— the interpretation — and it is appended by :mod:`brief`, not by this module.

That split is the whole point:

  * the model stays silent or OpenRouter is down → that one block is simply
    absent and everything else still goes out (the fallback the weekly digest
    never had);
  * changing what the brief *contains* is reordering or dropping blocks, without
    touching the model or the delivery channel.

Numbers reach the model already computed, so there is nothing for it to get
wrong; the header prints them itself rather than trusting prose about them.

Text is Russian and inline, like :mod:`inbound` — the bot has one reader. The
web UI keeps going through ``i18n``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type
from typing import Iterable, Optional

# Block kinds (also the priority ladder below).
KIND_GARMIN = "garmin"
KIND_WEIGHT = "weight"
KIND_DAY = "day"        # what kind of day it is — see ``day_plan``
KIND_ASK = "ask"        # a question to the owner, answered in free text
KIND_NARRATIVE = "narrative"

# Protocol stays out of the brief entirely: no doses, no compounds, no
# injection schedule, no supplements. Nothing here is advisable day-to-day, it
# would fight the weekly digest for the same conclusions, and the most sensitive
# rows in the lake have no business travelling through Telegram. The digest still
# sees all of it — this filter is only applied on the way into a brief.
PROTOCOL_KEYS = ("glp1", "hrt", "supplements")

# How stale the newest Garmin row may be and still count as "there is data".
# ``latest_daily`` happily returns a row from three weeks ago, so an empty-day
# check that only looked for *a* row would never fire.
FRESH_DAYS = 1

_RECOVERY_KEYS = (
    "sleep_score",
    "hrv_avg",
    "resting_hr",
    "body_battery_high",
)

# What a personal norm is computed for. The recovery four plus SpO2 — the header
# doesn't print SpO2, but the model is handed it and was caught calling a
# "просадка" on it with nothing to call it against.
BASELINE_KEYS = _RECOVERY_KEYS + ("spo2_lowest",)

# Any one of these present means Garmin has closed and scored last night. All
# three absent on *today's* row means the night is still running.
NIGHT_SCORED_KEYS = ("sleep_score", "sleep_seconds", "sleep_end")

# Everything on a day row that is derived from the night. Absent is not the same
# as "not there yet": Garmin fills resting HR and Body Battery from the day so
# far, so mid-night they hold real-looking numbers that mean nothing.
_NIGHT_KEYS = _RECOVERY_KEYS + (
    "spo2_lowest",
    "body_battery_change",
    "breathing_disruption",
    "training_readiness",
    "advice",
)

LINE_NIGHT_PENDING = "Ночь ещё не размечена — цифр восстановления за сегодня нет."

# Below this the day-to-day wobble of these metrics swamps the difference, and a
# "(норма 82)" printed next to 81 teaches him to skip the parenthesis — which is
# the one place the header says anything he can't already read off the watch.
# Relative rather than per-metric: 5% is ~3 bpm of resting HR and ~4 points of
# sleep score, which is the same size of "actually different" on both.
_BASELINE_NOTABLE = 0.05


@dataclass(frozen=True)
class Block:
    """One piece of a message. ``priority`` orders the render, low first."""

    kind: str
    text: str
    priority: int = 50


def render(blocks: Iterable[Block]) -> str:
    """Blocks → the string that actually gets sent. The only place text is joined."""
    ordered = sorted(blocks, key=lambda b: b.priority)
    return "\n\n".join(b.text.strip() for b in ordered if b.text and b.text.strip())


def strip_protocol(ctx: dict) -> dict:
    """The brief's view of the context — everything except the protocol."""
    out = {k: v for k, v in ctx.items() if k not in PROTOCOL_KEYS}
    # Context v2 also carries domain metadata and cross-domain lists. Removing
    # only the first-class block would still disclose that a protocol exists —
    # or even repeat an HRT alert message — through those secondary surfaces.
    if isinstance(out.get("coverage"), dict):
        out["coverage"] = {
            key: value
            for key, value in out["coverage"].items()
            if key not in PROTOCOL_KEYS
        }
    if isinstance(out.get("alerts"), list):
        out["alerts"] = [
            row for row in out["alerts"] if row.get("domain") not in PROTOCOL_KEYS
        ] or None
    if isinstance(out.get("timeline"), list):
        out["timeline"] = [
            row for row in out["timeline"] if row.get("domain") not in PROTOCOL_KEYS
        ] or None
    if isinstance(out.get("milestones"), list):
        out["milestones"] = [
            row
            for row in out["milestones"]
            if row.get("domain") not in PROTOCOL_KEYS
        ]
    return out


def is_empty_day(ctx: dict, *, on_date: date_type) -> bool:
    """Nothing anywhere → there is no brief worth sending.

    Silence is more honest than "нет данных" three mornings in a row; the web
    gets a passive ``info`` alert instead so the gap is still visible.

    Garmin is the usual reason a morning is worth writing about, but it is not
    the only one. Gating the whole brief on a fresh recovery row meant the watch
    sitting on the charger silenced every morning — while the scale, the food
    log, the gym and his own signals kept filling. A day is empty only when it is
    empty everywhere.
    """
    garmin = ctx.get("garmin") or {}
    if _is_fresh(garmin.get("date"), on_date) and any(
        garmin.get(key) is not None for key in _RECOVERY_KEYS
    ):
        return False
    # Weight is the one field here that is not already scoped to the day: the rest
    # of the context is built with ``period_days=1``, but ``latest_kg`` is the
    # newest weigh-in *ever*. Read bare it would mean the brief could never go
    # quiet again once he had stood on the scale a single time — the exact silence
    # this check exists to produce.
    weight = ctx.get("weight") or {}
    if weight.get("latest_kg") is not None and _is_fresh(weight.get("latest_date"), on_date):
        return False
    return not (
        (ctx.get("hevy") or {}).get("total_workouts")
        or ctx.get("nutrition")
        or ctx.get("signals")
    )


def night_pending(ctx: dict, *, on_date: date_type) -> bool:
    """Today's Garmin row is here, but last night has not been scored yet.

    That is the watch still on a sleeping wrist at brief time. Body Battery reads
    its overnight *low*, resting HR is half a day's worth, and there is no sleep
    score at all — numbers that look like a terrible morning and are simply the
    middle of the night. Judging recovery off them is reading the night before it
    ended, and the brief is persisted: the misreading outlives the morning and
    every report downstream quotes it back as fact.

    A row for another date is not pending — that is stale data, which the
    freshness rules already govern.
    """
    garmin = ctx.get("garmin") or {}
    if garmin.get("date") != on_date.isoformat():
        return False
    return all(garmin.get(key) is None for key in NIGHT_SCORED_KEYS)


def drop_unscored_night(ctx: dict) -> dict:
    """Blank every night-derived number and mark the context as such.

    A gap is honest and a mid-night number is not, so the brief prints neither
    them nor a verdict built on them — and ``night_pending`` in the stored context
    is what tells the digest, months later, why this morning has no numbers.
    """
    garmin = {**(ctx.get("garmin") or {}), "night_pending": True}
    for key in _NIGHT_KEYS:
        garmin[key] = None
    return {**ctx, "garmin": garmin}


def _is_fresh(value, on_date: date_type) -> bool:
    """Is this ISO date recent enough to count as "something happened"?"""
    parsed = _parse_date(value)
    return parsed is not None and (on_date - parsed).days <= FRESH_DAYS


def header_blocks(ctx: dict) -> list[Block]:
    """The deterministic header: recovery numbers, then weight and its trend.

    Each number carries his own norm when today is far enough off it to matter.
    Four bare absolutes are the same line every morning — whether they are good or
    bad is a comparison, and printing it here is what stops that comparison from
    being left to prose that has no baseline to make it from.
    """
    blocks: list[Block] = []

    garmin = ctx.get("garmin") or {}
    baseline = garmin.get("baseline") or {}
    parts = [
        label + " " + _num(garmin[key]) + _vs_baseline(garmin[key], baseline.get(key))
        for key, label in (
            ("sleep_score", "Сон"),
            ("hrv_avg", "HRV"),
            ("resting_hr", "Пульс покоя"),
            ("body_battery_high", "Body Battery"),
        )
        if garmin.get(key) is not None
    ]
    if parts:
        blocks.append(Block(KIND_GARMIN, " · ".join(parts), 10))
    elif garmin.get("night_pending"):
        # Otherwise a brief that gave up waiting reads as a brief that broke.
        blocks.append(Block(KIND_GARMIN, LINE_NIGHT_PENDING, 10))

    weight = ctx.get("weight") or {}
    wparts = []
    if weight.get("latest_kg") is not None:
        wparts.append(f"Вес {_num(weight['latest_kg'])} кг")
    slope = weight.get("trend_kg_per_week")
    if slope is not None:
        wparts.append(f"тренд {slope:+.2f} кг/нед")
    if wparts:
        line = " · ".join(wparts)
        # A noise marker means the scale is lying in a known direction, so the
        # trend must never be printed bare next to it — that is the one number in
        # the header that can mislead while being technically correct.
        marker = (weight.get("noise_markers") or [None])[0]
        if marker and slope is not None:
            reason = (marker.get("reason") or "").strip()
            line += f"\n⚠️ тренд зашумлён{f': {reason}' if reason else ''}"
        blocks.append(Block(KIND_WEIGHT, line, 20))

    return blocks


def _vs_baseline(value, mean) -> str:
    """`` (норма 85)`` — or "" when there is no norm yet, or today sits on it."""
    try:
        value, mean = float(value), float(mean)
    except (TypeError, ValueError):
        return ""
    if not mean or abs(value - mean) / abs(mean) < _BASELINE_NOTABLE:
        return ""
    return f" (норма {_num(mean)})"


def _num(value) -> str:
    """``86.0 → "86"``, ``86.1 → "86.1"`` — no trailing-zero noise in a message."""
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


def _parse_date(value) -> Optional[date_type]:
    try:
        return date_type.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
