"""Owner profile, nutrition goals and module switches."""
from __future__ import annotations

from typing import Optional


from vitals.config import load_config
from vitals.services import modules_service
from web.routers.mcp._core import (
    WRITE, get_session_factory, tool,
)

# ── Profile and nutrition goals ──────────────────────────────────────────────

async def get_user_profile() -> dict:
    """The owner's profile as Settings holds it — height, sex, age, timezone,
    goals, program — and the nutrition goals (protein target, calorie corridor).
    Saved values are live: the Navy formula, the nutrition corridor and the local
    clock already use them."""
    from web.services import profile_settings

    session_factory = get_session_factory()
    async with session_factory() as session:
        saved = {
            **await profile_settings.read_profile(session),
            **await profile_settings.read_nutrition_goals(session),
        }
    cfg = load_config()

    def _num(raw: str, cast, fallback):
        try:
            return cast(raw)
        except (TypeError, ValueError):
            return fallback

    goals = [g.strip() for g in saved["user_goals"].split(",") if g.strip()] or cfg.user_goals
    return {
        "height_cm": _num(saved["height_cm"], float, cfg.height_cm),
        "sex": saved["sex"],
        "age": _num(saved["user_age"], int, cfg.user_age),
        "timezone": saved["timezone"],
        "goals": goals,
        "program": saved["user_program"] or cfg.user_program,
        "nutrition_goals": {
            "protein_target_g": _num(saved["nutrition_protein_target_g"], float, cfg.nutrition_protein_target_g),
            "calories_min": _num(saved["nutrition_calories_min"], int, cfg.nutrition_calories_min),
            "calories_max": _num(saved["nutrition_calories_max"], int, cfg.nutrition_calories_max),
        },
    }


_HEIGHT_RANGE = (100.0, 250.0)
_AGE_RANGE = (10, 120)
_PROTEIN_RANGE = (0.0, 500.0)
_CALORIES_RANGE = (500, 8000)


@tool(WRITE, idempotent=True)
async def update_user_profile(
    height_cm: Optional[float] = None,
    age: Optional[int] = None,
    sex: Optional[str] = None,
    timezone: Optional[str] = None,
    program: Optional[str] = None,
    goals: Optional[list[str]] = None,
    protein_target_g: Optional[float] = None,
    calories_min: Optional[int] = None,
    calories_max: Optional[int] = None,
) -> dict:
    """Changes the owner's profile and nutrition goals — the "About me" and
    nutrition cards in Settings, with the same rules. Only the fields you pass
    change, and they apply at once (no restart).

    ``sex`` is male or female (it switches the Navy body-fat formula);
    ``timezone`` an IANA name ("Europe/Chisinau") — it moves "today" and the bot's
    schedule; ``goals`` the full new list (short phrases, no commas inside one);
    ``program`` one line describing the current program. ``calories_min`` /
    ``calories_max`` are the daily corridor the nutrition summary measures
    against; ``protein_target_g`` the daily protein goal. Returns the profile as
    now stored."""
    from web.routers.mcp import _core
    from web.services import profile_settings

    def _bounded(name, value, bounds):
        low, high = bounds
        if value is not None and not low <= value <= high:
            raise ValueError(f"{name} must be between {low:g} and {high:g}")

    def _text(value):
        return None if value is None else f"{value:g}" if isinstance(value, float) else str(value)

    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            _bounded("height_cm", height_cm, _HEIGHT_RANGE)
            _bounded("age", age, _AGE_RANGE)
            _bounded("protein_target_g", protein_target_g, _PROTEIN_RANGE)
            _bounded("calories_min", calories_min, _CALORIES_RANGE)
            _bounded("calories_max", calories_max, _CALORIES_RANGE)
            if sex is not None and sex not in profile_settings.SEXES:
                raise ValueError(f"sex must be one of {', '.join(profile_settings.SEXES)}")
            if timezone is not None and not profile_settings.is_valid_timezone(timezone.strip()):
                raise ValueError(f"unknown timezone {timezone!r} — use an IANA name")
            if goals is not None and any("," in g for g in goals):
                raise ValueError("a goal cannot contain a comma — goals are stored comma-separated")
            stored = await profile_settings.read_nutrition_goals(session)
            low = calories_min if calories_min is not None else int(float(stored["nutrition_calories_min"]))
            high = calories_max if calories_max is not None else int(float(stored["nutrition_calories_max"]))
            if low > high:
                raise ValueError(f"calories_min ({low}) is above calories_max ({high})")

            written = await profile_settings.apply_profile(
                session,
                height_cm=_text(height_cm),
                sex=sex,
                user_age=_text(age),
                timezone=timezone,
                user_program=program,
                user_goals=None if goals is None else ", ".join(g.strip() for g in goals if g.strip()),
            )
            written.update(await profile_settings.apply_nutrition_goals(
                session,
                protein_target_g=_text(protein_target_g),
                calories_min=_text(calories_min),
                calories_max=_text(calories_max),
            ))
        except ValueError as e:
            await session.rollback()
            return {"error": str(e)}
        if not written:
            return {"error": "nothing to change — pass at least one field"}
        await session.commit()
    if "VITALS_TIMEZONE" in written:
        profile_settings.apply_timezone_to_scheduler(_core._HOST_APP, written["VITALS_TIMEZONE"])
    return await get_user_profile()


# ── Modules (optional-domain toggles) ─────────────────────────────────────────
async def get_modules() -> dict:
    """Returns which optional domains are enabled, plus which module keys are core
    (always-on, locked) vs optional (toggleable). Check this before calling a
    module-gated write tool (log_body_scan, log_event) so you know if it's on."""

    session_factory = get_session_factory()
    async with session_factory() as session:
        enabled = await modules_service.get_enabled_modules(session)
    return {
        "enabled": enabled,
        "core": sorted(modules_service.CORE_KEYS),
        "optional": sorted(modules_service.OPTIONAL_KEYS),
    }


_MODULE_DATA_DESCRIPTIONS = {
    "environment": "air quality, CO2, temperature, humidity readings",
    "hevy": "workout logs, exercises, sets, and volume",
    "nutrition": "food and meal logs, calories, macronutrients",
    "glp1": "GLP-1 injection logs and side effects",
    "hrt": "hormone replacement therapy logs",
    "genetics": "genetic traits, SNP markers, and carrier status",
    "supplements": "supplement regimes, intake logs, and timing",
    "skincare": "skincare routines and products",
    "interactions": "drug and supplement interactions and conflicts",
    "signals": "free-text capture logs and proactive Telegram bot alerts",
    "body_comp": "BIA scans (InBody/MedAss) and body composition metrics",
    "timeline": "chronological health event journal",
}


async def set_module(key: str, enabled: bool) -> dict:
    """Enables or disables an optional module (e.g. body_comp, timeline, glp1,
    nutrition). Core modules are locked and return an error. Disabling a module
    hides its data from today, snapshots, and navigation. WRITE tool — returns
    the new enabled-module map, status, and impact note."""

    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            state = await modules_service.set_module_enabled(
                session, key=key, enabled=enabled
            )
        except modules_service.ModuleToggleError as e:
            return {"error": str(e)}
        await session.commit()
        action = "enabled" if enabled else "disabled"
        desc = _MODULE_DATA_DESCRIPTIONS.get(key, f"{key} domain data")
        impact = "now visible in" if enabled else "hidden from"
        note = f"Module '{key}' {action}. Its data ({desc}) is {impact} today, snapshot, and navigation."
        return {"enabled": state, "module": key, "status": action, "note": note}
