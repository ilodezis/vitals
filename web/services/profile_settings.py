"""The owner's profile and nutrition goals: read and written in one place.

Saved values live in the ``app_settings`` table (``vitals.services.profile_store``)
and in the process's runtime overlay, so a save reaches the computations (the
Navy formula, the nutrition corridor, the local clock) on the next call, with no
container restart. ``.env`` stays the fallback for anything never saved, so an
existing install shows and uses exactly what it did before. The Settings screen
and the MCP tools both go through here, so the two can neither disagree on what
is stored nor on what a valid value is.

Each ``apply_*`` takes already-typed-as-text values, keeps the ones that pass the
rules the Settings form always applied, stores them, and returns the
``VITALS_*`` keys it wrote. The caller commits.
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession

from vitals.services import profile_store
from vitals.services.profile_store import NUTRITION_KEYS, PROFILE_KEYS
from web.services.env_writer import read_key

logger = logging.getLogger(__name__)

__all__ = [
    "NUTRITION_KEYS",
    "PROFILE_KEYS",
    "SEXES",
    "apply_nutrition_goals",
    "apply_profile",
    "apply_timezone_to_scheduler",
    "is_valid_timezone",
    "read_nutrition_goals",
    "read_profile",
]

SEXES = ("male", "female")


def is_valid_timezone(name: str) -> bool:
    """True for an IANA zone name this machine can load (``Europe/Berlin``).

    A saved zone now applies at once to every local-time reading, so a typo
    would break "today" across the app instead of waiting for a restart.
    """
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def _read(keys: dict[str, tuple[str, str]], overrides: dict[str, str]) -> dict[str, str]:
    """Saved override, else the ``.env`` file, else the default."""
    return {
        field: overrides.get(env) or read_key(env) or default
        for env, (field, default) in keys.items()
    }


async def read_profile(session: AsyncSession) -> dict[str, str]:
    """The profile as the Settings screen shows it (strings, defaults filled in)."""
    return _read(PROFILE_KEYS, await profile_store.load(session))


async def read_nutrition_goals(session: AsyncSession) -> dict[str, str]:
    return _read(NUTRITION_KEYS, await profile_store.load(session))


async def apply_profile(
    session: AsyncSession,
    *,
    height_cm: Optional[str] = None,
    sex: Optional[str] = None,
    user_age: Optional[str] = None,
    timezone: Optional[str] = None,
    user_program: Optional[str] = None,
    user_goals: Optional[str] = None,
) -> dict[str, str]:
    """Store the fields that were given and pass the form's rules. ``None`` = keep."""
    updates: dict[str, str] = {}
    if height_cm is not None and height_cm.strip():
        updates["VITALS_HEIGHT_CM"] = height_cm.strip()
    if sex is not None and sex in SEXES:
        updates["VITALS_SEX"] = sex
    if user_age is not None and user_age.strip().isdigit():
        updates["VITALS_USER_AGE"] = user_age.strip()
    if timezone is not None and timezone.strip() and is_valid_timezone(timezone.strip()):
        updates["VITALS_TIMEZONE"] = timezone.strip()
    if user_program is not None:
        updates["VITALS_USER_PROGRAM"] = " ".join(user_program.split())
    if user_goals is not None:
        updates["VITALS_USER_GOALS"] = user_goals.strip()
    if updates:
        await profile_store.save(session, updates)
    return updates


async def apply_nutrition_goals(
    session: AsyncSession,
    *,
    protein_target_g: Optional[str] = None,
    calories_min: Optional[str] = None,
    calories_max: Optional[str] = None,
) -> dict[str, str]:
    """Same contract as :func:`apply_profile`, for the nutrition goals."""
    updates: dict[str, str] = {}
    if protein_target_g is not None and protein_target_g.strip():
        updates["VITALS_NUTRITION_PROTEIN_TARGET_G"] = protein_target_g.strip()
    if calories_min is not None and calories_min.strip():
        updates["VITALS_NUTRITION_CALORIES_MIN"] = calories_min.strip()
    if calories_max is not None and calories_max.strip():
        updates["VITALS_NUTRITION_CALORIES_MAX"] = calories_max.strip()
    if updates:
        await profile_store.save(session, updates)
    return updates


def apply_timezone_to_scheduler(app: Any, tz_name: str) -> None:
    """Move the running scheduler's cron jobs onto ``tz_name``.

    APScheduler builds a string trigger in ``scheduler.timezone`` when a job is
    added, so the zone is swapped first and the job registry re-applied, which
    re-adds every job with a trigger in the new zone. Best-effort like
    ``apply_schedule``: the zone is already saved, so a scheduler that isn't
    running (tests, a worker without one) must not turn the save into a 500.
    """
    from vitals.scheduler.scheduler import apply_registry
    from web.deps import get_redis_client, get_session_factory

    scheduler = getattr(getattr(app, "state", None), "scheduler", None)
    if scheduler is None:
        return
    try:
        from apscheduler.util import astimezone

        zone = astimezone(tz_name)
        if str(getattr(scheduler, "timezone", "")) == str(zone):
            return
        scheduler.timezone = zone
        apply_registry(scheduler, get_session_factory(), get_redis_client())
    except Exception:
        logger.exception("could not move the scheduler to the new timezone; it applies on restart")
