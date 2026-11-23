"""Profile and nutrition-goal overrides stored in ``app_settings``.

The owner's profile (height, sex, age, timezone, program, goals) and nutrition
goals used to live only in ``.env``, which the process reads once at start. A
save now goes into one ``app_settings`` row (``profile_overrides``, a JSON map
of ``VITALS_*`` key to text) and into the in-process overlay
(:mod:`vitals.runtime_settings`), so ``load_config()``, the Navy formula, the
nutrition corridor and the local clock see it on the next call. ``.env`` stays
the fallback for keys that were never saved, so existing installs keep working
untouched.

:func:`save` flushes but does not commit: the caller owns the transaction. The
overlay is updated at save time, so a caller that rolls back should call
:func:`load` to resync it.
"""
from __future__ import annotations

from typing import Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from vitals import runtime_settings
from vitals.models.app_settings import AppSetting

SETTINGS_KEY = "profile_overrides"

# ``VITALS_*`` key -> (public field name, default shown when nothing is set).
PROFILE_KEYS: dict[str, tuple[str, str]] = {
    "VITALS_HEIGHT_CM": ("height_cm", "190"),
    "VITALS_SEX": ("sex", "male"),
    "VITALS_USER_AGE": ("user_age", "18"),
    "VITALS_TIMEZONE": ("timezone", "Europe/Chisinau"),
    "VITALS_USER_PROGRAM": ("user_program", ""),
    "VITALS_USER_GOALS": ("user_goals", ""),
}

NUTRITION_KEYS: dict[str, tuple[str, str]] = {
    "VITALS_NUTRITION_PROTEIN_TARGET_G": ("nutrition_protein_target_g", "150"),
    "VITALS_NUTRITION_CALORIES_MIN": ("nutrition_calories_min", "1300"),
    "VITALS_NUTRITION_CALORIES_MAX": ("nutrition_calories_max", "1700"),
}

ALLOWED_KEYS = frozenset(PROFILE_KEYS) | frozenset(NUTRITION_KEYS)


def _clean(raw: object) -> dict[str, str]:
    """Keep only known keys with text values; a malformed row reads as empty."""
    if not isinstance(raw, dict):
        return {}
    return {
        key: value
        for key, value in raw.items()
        if key in ALLOWED_KEYS and isinstance(value, str)
    }


async def read(session: AsyncSession) -> dict[str, str]:
    """The stored overrides, without touching the overlay."""
    row = await session.get(AppSetting, SETTINGS_KEY)
    return _clean(row.value) if row is not None else {}


async def load(session: AsyncSession) -> dict[str, str]:
    """Read the stored overrides and make them the process overlay."""
    overrides = await read(session)
    runtime_settings.replace(overrides)
    return overrides


async def save(session: AsyncSession, updates: Mapping[str, str]) -> dict[str, str]:
    """Merge ``updates`` into the stored row and the overlay; return the full map.

    Flushes, never commits. Unknown keys are a programming error, not input to
    filter, so they raise.
    """
    unknown = set(updates) - ALLOWED_KEYS
    if unknown:
        raise ValueError(f"not a profile setting: {', '.join(sorted(unknown))}")
    if not updates:
        return await read(session)

    row = await session.get(AppSetting, SETTINGS_KEY)
    merged = _clean(row.value) if row is not None else {}
    merged.update({key: str(value) for key, value in updates.items()})
    if row is None:
        session.add(AppSetting(key=SETTINGS_KEY, value=merged))
    else:
        # A fresh dict, so the JSON column registers the change.
        row.value = dict(merged)
    await session.flush()
    runtime_settings.replace(merged)
    return merged
