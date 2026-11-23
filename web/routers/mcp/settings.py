"""Cross-domain settings tools: profile, modules, proactive schedule, week
template, bedroom-station thresholds and conflict-rule switches."""
from __future__ import annotations

from typing import Optional

from web.routers.mcp._core import READ, WRITE, choice_error, route, tool
from web.routers.mcp.alerts import set_conflict_rule_active
from web.routers.mcp.environment import get_environment_settings, set_environment_settings
from web.routers.mcp.profile import get_modules, get_user_profile, set_module
from web.routers.mcp.signals import (
    get_proactive_state,
    set_proactive_settings,
    set_week_template,
)

_READ_SECTIONS = ("all", "profile", "modules", "proactive", "environment")
_WRITE_SECTIONS = ("modules", "conflict_rule", "proactive", "week_template", "environment")


@tool(READ)
async def get_settings(
    section: str = "all",
    limit: Optional[int] = None,
) -> dict:
    """Reads Vitals configuration (mirrors the Settings screen).

    ``section``:
      * ``all`` (default) — ``{"profile": ..., "modules": ...}``: the owner's
        physical profile, timezone, nutrition goals, and which optional modules
        are enabled vs core.
      * ``profile`` — physical profile, timezone, goals, program, and nutrition
        targets only (change with ``update_user_profile``).
      * ``modules`` — enabled map plus core/optional module lists.
      * ``proactive`` — Telegram bot state, schedule preferences, week template
        and the last ``limit`` (default 10) notifications sent.
      * ``environment`` — bedroom station thresholds, night window and alert
        switches (requires the ``environment`` module to be enabled)."""
    if section == "all":
        if limit is not None:
            return {"error": "get_settings(section='all') does not take: limit"}
        return {
            "profile": await get_user_profile(),
            "modules": await get_modules(),
        }
    if section == "profile":
        return await route(get_user_profile, "get_settings(section='profile')", dict(limit=limit))
    if section == "modules":
        return await route(get_modules, "get_settings(section='modules')", dict(limit=limit))
    if section == "proactive":
        return await route(
            get_proactive_state, "get_settings(section='proactive')", dict(limit=limit)
        )
    if section == "environment":
        return await route(
            get_environment_settings, "get_settings(section='environment')", dict(limit=limit)
        )
    return choice_error("section", section, _READ_SECTIONS)


@tool(WRITE, idempotent=True)
async def update_settings(
    section: str,
    key: Optional[str] = None,
    enabled: Optional[bool] = None,
    rule_id: Optional[int] = None,
    active: Optional[bool] = None,
    values: Optional[dict] = None,
) -> dict:
    """Changes Vitals settings (for profile and nutrition goals use
    ``update_user_profile`` instead). Every change applies immediately — no
    container restart.

    ``section``:
      * ``modules`` — switches an optional module ``key`` (e.g. ``body_comp``,
        ``timeline``, ``glp1``, ``nutrition``) via ``enabled`` (true/false).
        Core modules are locked. Only toggle when explicitly asked.
      * ``conflict_rule`` — switches one rule ``rule_id`` (from
        ``get_alerts(view="rules")``) via ``active`` (or ``enabled``). Turning
        off a ``block`` rule removes a safety check — only on explicit request.
        Requires the ``interactions`` module.
      * ``proactive`` — changes Telegram bot schedule/nudges/sync cadence via
        ``values`` dict (only passed fields change; keys from
        ``get_settings(section="proactive").prefs`` — e.g. ``brief_time``,
        ``evening_time``, ``quiet_start``, ``quiet_end``, ``daily_budget``,
        ``nudges``, ``garmin_sync_hours``, ``pulse_seconds``). Re-times the
        scheduler immediately.
      * ``week_template`` — merges weekday defaults via ``values`` dict keyed
        ``"mon"``..``"sun"`` with ``{"where": "office"|"remote"|"off",
        "gym": bool}``. Requires the ``signals`` module.
      * ``environment`` — changes bedroom-station thresholds and alert switches
        via ``values`` dict (keys from ``get_settings(section="environment")``,
        plus ``night_start``/``night_end`` HH:MM). Requires the ``environment``
        module."""
    if section == "modules":
        return await route(
            set_module, "update_settings(section='modules')",
            dict(key=key, enabled=enabled, rule_id=rule_id, active=active, values=values),
        )
    if section == "conflict_rule":
        flag = active if active is not None else enabled
        extra = dict(key=key, values=values)
        if active is not None and enabled is not None:
            extra["enabled"] = enabled
        return await route(
            set_conflict_rule_active, "update_settings(section='conflict_rule')",
            {"rule_id": rule_id, "active": flag, **extra},
        )
    if section == "proactive":
        unused = [k for k, v in dict(key=key, enabled=enabled, rule_id=rule_id, active=active).items() if v is not None]
        if unused:
            return {"error": f"update_settings(section='proactive') does not take: {', '.join(sorted(unused))}"}
        if not isinstance(values, dict):
            return {"error": "update_settings(section='proactive') needs: values (dict of changed fields)"}
        return await route(set_proactive_settings, "update_settings(section='proactive')", values)
    if section == "week_template":
        return await route(
            set_week_template, "update_settings(section='week_template')",
            dict(values=values, key=key, enabled=enabled, rule_id=rule_id, active=active),
            rename={"values": "template"},
        )
    if section == "environment":
        unused = [k for k, v in dict(key=key, enabled=enabled, rule_id=rule_id, active=active).items() if v is not None]
        if unused:
            return {"error": f"update_settings(section='environment') does not take: {', '.join(sorted(unused))}"}
        if not isinstance(values, dict):
            return {"error": "update_settings(section='environment') needs: values (dict of changed fields)"}
        return await route(set_environment_settings, "update_settings(section='environment')", values)
    return choice_error("section", section, _WRITE_SECTIONS)
