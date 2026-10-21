"""The owner's profile and nutrition goals — read and written in one place.

Both live in ``.env`` (``VITALS_HEIGHT_CM``, ``VITALS_NUTRITION_*``…), which the
running process reads once at start: a saved value shows on the Settings screen
at once and reaches the computations (the Navy formula, the nutrition corridor)
after the next restart. The Settings screen and the MCP tools both go through
here, so the two can neither disagree on what is stored nor on what a valid value
is.

Each ``apply_*`` takes already-typed-as-text values, keeps the ones that pass the
rules the Settings form always applied, and returns the ``.env`` keys it wrote.
"""
from __future__ import annotations

from typing import Optional

from web.services.env_writer import read_key, write_keys

# ``.env`` key → (public field name, default shown when the key is absent).
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

SEXES = ("male", "female")


def _read(keys: dict[str, tuple[str, str]]) -> dict[str, str]:
    return {field: read_key(env) or default for env, (field, default) in keys.items()}


def read_profile() -> dict[str, str]:
    """The profile as the Settings screen shows it (strings, defaults filled in)."""
    return _read(PROFILE_KEYS)


def read_nutrition_goals() -> dict[str, str]:
    return _read(NUTRITION_KEYS)


def apply_profile(
    *,
    height_cm: Optional[str] = None,
    sex: Optional[str] = None,
    user_age: Optional[str] = None,
    timezone: Optional[str] = None,
    user_program: Optional[str] = None,
    user_goals: Optional[str] = None,
) -> dict[str, str]:
    """Write the fields that were given and pass the form's rules. ``None`` = keep."""
    updates: dict[str, str] = {}
    if height_cm is not None and height_cm.strip():
        updates["VITALS_HEIGHT_CM"] = height_cm.strip()
    if sex is not None and sex in SEXES:
        updates["VITALS_SEX"] = sex
    if user_age is not None and user_age.strip().isdigit():
        updates["VITALS_USER_AGE"] = user_age.strip()
    if timezone is not None and timezone.strip():
        updates["VITALS_TIMEZONE"] = timezone.strip()
    if user_program is not None:
        updates["VITALS_USER_PROGRAM"] = " ".join(user_program.split())
    if user_goals is not None:
        updates["VITALS_USER_GOALS"] = user_goals.strip()
    if updates:
        write_keys(updates)
    return updates


def apply_nutrition_goals(
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
        write_keys(updates)
    return updates
