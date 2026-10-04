"""Прогон 6 — every knob the owner turns, in one ``app_settings`` row.

What lives here: when the brief and the evening block go out, when the bot must
stay quiet, how many self-initiated messages a day are allowed, which nudge
categories are live, and how often Garmin is polled — the freshness of the data
those messages are made of.

Shape copied from ``modules_service`` and the week template: one JSON row, a
sanitizer that projects arbitrary stored data onto a field registry, and a getter
that **never raises**. A settings row edited into nonsense must degrade to the
defaults, not take the scheduler down with it.

**Why the DB and not ``.env``:** these are exactly the settings that have to take
effect without a container restart — a save re-registers the jobs on the
running scheduler. The ``.env`` path (``web/services/env_writer``) is for secrets
and startup-time values, and it costs a restart every time.

No Redis cache on purpose: two scheduler reads a day plus one per outgoing
message is not traffic, and a cache here would mean a saved setting that quietly
doesn't apply for five minutes.
"""
from __future__ import annotations

import logging
from datetime import time as time_type
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from vitals.models.app_settings import AppSetting

logger = logging.getLogger(__name__)

SETTINGS_KEY = "proactive"  # app_settings.key

# The module that gates the whole proactive layer. Off → the bot says nothing
# (enforced in ``delivery.send``) and ``/signals`` behaves as if it isn't there.
MODULE_KEY = "signals"

# ── Nudge categories ─────────────────────────────────────────────────────────
# They live here rather than in ``nudges`` because a category *is* a settings
# toggle: one switch per group, because "не пиши мне про активность" is the
# decision a person actually makes. ``nudges`` re-exports them.
CATEGORY_ACTIVITY = "activity"
CATEGORY_NUTRITION = "nutrition"
CATEGORY_DATA = "data"
# The bedroom-air station's alerts (stuffy, hot, dry, station silent).
CATEGORY_ENVIRONMENT = "environment"
NUDGE_CATEGORIES: tuple[str, ...] = (
    CATEGORY_ACTIVITY,
    CATEGORY_NUTRITION,
    CATEGORY_DATA,
    CATEGORY_ENVIRONMENT,
)

# ── Hard bounds (the UI shows them, the sanitizer enforces them) ─────────────
BUDGET_RANGE = (1, 12)
SYNC_HOURS_RANGE = (1, 24)
WEIGHT_EXPORT_MINUTES_RANGE = (5, 1440)
# Thirty days is a hard safety ceiling: increasing it would turn the latest-only
# export into a progressively deeper history backfill.
WEIGHT_MAX_AGE_DAYS_RANGE = (1, 30)
# 60 s floor / 3600 s ceiling: the Home Assistant Garmin integration — same
# library author, thousands of users — polls every 300 s and refuses to go below
# 60. A *read* costs nothing; it is the credential *login* Garmin rate-limits,
# and the login breaker is what rations those.
PULSE_SECONDS_RANGE = (60, 3600)

DEFAULTS: dict[str, Any] = {
    "brief_time": "11:00",
    "evening_time": "23:45",
    "quiet_start": "02:00",
    "quiet_end": "10:00",
    "daily_budget": 4,
    # Every 6h = the same four polls a day the fixed 3/11/16/22 cron did.
    "garmin_sync_hours": 6,
    "garmin_weight_export_minutes": 15,
    "garmin_weight_max_age_days": 30,
    "pulse_seconds": 900,  # 0 = the light pulse is off entirely
    "pulse_start_hour": 8,
    "pulse_end_hour": 24,
    "nudges": {c: True for c in NUDGE_CATEGORIES},
}


# ── Sanitizing (a hand-editable JSON blob is a trust boundary) ────────────────
def _time(raw: Any, default: str) -> str:
    try:
        return time_type.fromisoformat(str(raw)).strftime("%H:%M")
    except (TypeError, ValueError):
        return default


def _int(raw: Any, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(raw)))
    except (TypeError, ValueError):
        return default


def sanitize(raw: Any) -> dict[str, Any]:
    """Arbitrary stored data → a full, in-range settings dict. Never raises."""
    src = raw if isinstance(raw, dict) else {}
    stored_nudges = src.get("nudges")
    if not isinstance(stored_nudges, dict):
        stored_nudges = {}

    pulse_raw = src.get("pulse_seconds", DEFAULTS["pulse_seconds"])
    try:
        pulse = int(pulse_raw)
    except (TypeError, ValueError):
        pulse = DEFAULTS["pulse_seconds"]
    pulse = 0 if pulse <= 0 else max(PULSE_SECONDS_RANGE[0], min(PULSE_SECONDS_RANGE[1], pulse))

    start_hour = _int(src.get("pulse_start_hour"), DEFAULTS["pulse_start_hour"], 0, 23)
    end_hour = _int(src.get("pulse_end_hour"), DEFAULTS["pulse_end_hour"], 1, 24)
    # An end at or before the start is a window the pulse could never run in —
    # a dead job that looks configured. Widen it by an hour instead.
    end_hour = max(end_hour, start_hour + 1)

    return {
        "brief_time": _time(src.get("brief_time"), DEFAULTS["brief_time"]),
        "evening_time": _time(src.get("evening_time"), DEFAULTS["evening_time"]),
        "quiet_start": _time(src.get("quiet_start"), DEFAULTS["quiet_start"]),
        "quiet_end": _time(src.get("quiet_end"), DEFAULTS["quiet_end"]),
        "daily_budget": _int(src.get("daily_budget"), DEFAULTS["daily_budget"], *BUDGET_RANGE),
        "garmin_sync_hours": _int(
            src.get("garmin_sync_hours"), DEFAULTS["garmin_sync_hours"], *SYNC_HOURS_RANGE
        ),
        "garmin_weight_export_minutes": _int(
            src.get("garmin_weight_export_minutes"),
            DEFAULTS["garmin_weight_export_minutes"],
            *WEIGHT_EXPORT_MINUTES_RANGE,
        ),
        "garmin_weight_max_age_days": _int(
            src.get("garmin_weight_max_age_days"),
            DEFAULTS["garmin_weight_max_age_days"],
            *WEIGHT_MAX_AGE_DAYS_RANGE,
        ),
        "pulse_seconds": pulse,
        "pulse_start_hour": start_hour,
        "pulse_end_hour": end_hour,
        "nudges": {c: bool(stored_nudges.get(c, True)) for c in NUDGE_CATEGORIES},
    }


def hhmm(value: str) -> tuple[int, int]:
    """``"23:45"`` → ``(23, 45)``, for an APScheduler cron trigger."""
    parsed = time_type.fromisoformat(value)
    return parsed.hour, parsed.minute


def as_time(value: str) -> time_type:
    return time_type.fromisoformat(value)


# ── Storage ───────────────────────────────────────────────────────────────────
async def get_prefs(session: AsyncSession) -> dict[str, Any]:
    """The stored settings, or the defaults. Never raises."""
    try:
        row = await session.get(AppSetting, SETTINGS_KEY)
    except Exception:
        logger.warning("proactive prefs: DB read failed; using defaults", exc_info=True)
        return sanitize(None)
    return sanitize(row.value if row is not None else None)


async def set_prefs(session: AsyncSession, raw: Any) -> dict[str, Any]:
    """Store the settings (sanitized). Flushes; the caller commits."""
    clean = sanitize(raw)
    row = await session.get(AppSetting, SETTINGS_KEY)
    if row is None:
        session.add(AppSetting(key=SETTINGS_KEY, value=clean))
    else:
        row.value = clean  # a new dict, so SQLAlchemy sees the change
    await session.flush()
    return clean


async def bot_enabled(session: AsyncSession) -> bool:
    """Is the proactive layer switched on at all (the emergency switch)?

    Deliberately reads the module registry rather than a setting of its own:
    "выключить модуль signals" is one action in the UI and must silence the bot,
    hide ``/signals`` and stop the capture domain together.
    """
    from vitals.services import modules_service

    state = await modules_service.get_enabled_modules(session)
    return bool(state.get(MODULE_KEY))
