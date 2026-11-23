"""A switched-off module must stay off for the tool surface too.

Turning a module off in settings is the owner saying "I don't track this". The web
routes honour it, and so must every MCP tool and underlying write handler for an
optional domain.

The classification test below is the part that lasts: any newly registered write
tool must be listed as gated or explicitly excused, so "don't forget the check"
stops being something anyone has to remember.
"""
from __future__ import annotations

import inspect

import pytest

mcp_router = pytest.importorskip("web.routers.mcp")


@pytest.fixture(autouse=True)
def _use_test_factory(session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)


# Registered MCP write tool name -> the optional module key it writes into.
GATED_WRITE_TOOLS: dict[str, str] = {
    "save_meal": "nutrition",
    "save_glp1": "glp1",
    "save_hrt": "hrt",
    "upsert_genetic_variant": "genetics",
    "save_skincare": "skincare",
    "save_supplement": "supplements",
    "log_body_scan": "body_comp",
    "save_event": "timeline",
    "save_signal": "signals",
}

# Registered MCP write tools that deliberately have no single-module gate.
UNGATED_WRITE_TOOLS: dict[str, str] = {
    "save_weight": "weight, body measurements, and noise markers are core",
    "save_lab": "labs is core",
    "log_note": "writes the note column of an already-existing row in any domain",
    "save_milestone": "goals are core",
    "delete_record": "gated per domain inside from _DELETE_TARGETS — see below",
    "manage_alerts": "alerts are raised by every domain, core ones included",
    "add_photo": "gated per kind inside: face -> skincare, progress -> weight (core)",
    "update_user_profile": "the profile is Settings, not an optional module",
    "update_settings": "gates optional sections inside: environment, week_template, conflict_rule",
    "sync_data": "garmin is core; source='hevy' is gated inside",
    "create_report": "digests and doctor reports are core; shared domains filter to enabled modules",
    "create_saved_chart": "charts is core",
}

# Underlying single-action write handlers still exported for direct callers.
GATED_WRITE_HANDLERS: dict[str, str] = {
    "log_meal": "nutrition",
    "update_meal": "nutrition",
    "log_glp1": "glp1",
    "update_glp1": "glp1",
    "log_side_effect": "glp1",
    "add_dose_phase": "glp1",
    "close_dose_phase": "glp1",
    "log_hrt_dose": "hrt",
    "update_hrt_dose": "hrt",
    "log_hrt_side_effect": "hrt",
    "add_hrt_cycle": "hrt",
    "add_hrt_cycle_item": "hrt",
    "close_hrt_cycle": "hrt",
    "upsert_genetic_variant": "genetics",
    "log_skincare_observation": "skincare",
    "add_skincare_product": "skincare",
    "update_skincare_product": "skincare",
    "set_skincare_check": "skincare",
    "set_skincare_note": "skincare",
    "add_supplement": "supplements",
    "update_supplement": "supplements",
    "set_supplement_active": "supplements",
    "log_body_scan": "body_comp",
    "log_event": "timeline",
    "update_event": "timeline",
    "log_signal": "signals",
    "mark_signal_misparse": "signals",
    "log_day_context": "signals",
    "set_week_template": "signals",
    "set_conflict_rule_active": "interactions",
    "set_environment_settings": "environment",
    "sync_hevy": "hevy",
}


async def _all_registered_tools(db_session):
    from vitals.services import modules_service

    for key in sorted(modules_service.OPTIONAL_KEYS):
        await modules_service.set_module_enabled(db_session, key=key, enabled=True)
    await db_session.commit()
    return await mcp_router.mcp.list_tools()


async def test_every_registered_write_tool_is_classified(db_session):
    """Any newly registered non-read-only tool must be listed as gated or
    explicitly excused — otherwise it ships ungated and nobody notices."""
    tools = await _all_registered_tools(db_session)
    write_tools = {t.name for t in tools if not t.annotations.read_only_hint}
    assert write_tools == set(GATED_WRITE_TOOLS) | set(UNGATED_WRITE_TOOLS)


def test_gated_write_tools_are_in_visibility_map():
    for name, module_key in GATED_WRITE_TOOLS.items():
        assert mcp_router.TOOL_MODULES[name] == module_key


@pytest.mark.parametrize("tool_name,module_key", sorted(GATED_WRITE_TOOLS.items()))
async def test_gated_write_tool_refuses_when_module_is_off(tool_name, module_key):
    """Modules default to off for optional domains, so no setup is needed: every
    one of these must refuse before touching the database."""
    tool = getattr(mcp_router, tool_name)
    args = [1 for p in inspect.signature(tool).parameters.values()
            if p.default is inspect.Parameter.empty]
    result = await tool(*args)
    assert result == {"error": f"module '{module_key}' is disabled"}


@pytest.mark.parametrize("handler_name,module_key", sorted(GATED_WRITE_HANDLERS.items()))
async def test_gated_write_handler_refuses_when_module_is_off(handler_name, module_key):
    """Direct handlers exported on web.routers.mcp stay gated individually too."""
    fn = getattr(mcp_router, handler_name)
    args = [1 for p in inspect.signature(fn).parameters.values()
            if p.default is inspect.Parameter.empty]
    result = await fn(*args)
    assert result == {"error": f"module '{module_key}' is disabled"}


async def test_cross_domain_tools_gate_optional_sections():
    assert await mcp_router.update_settings(
        section="environment", values={"co2_warn": 1100}
    ) == {"error": "module 'environment' is disabled"}
    assert await mcp_router.update_settings(
        section="week_template", values={"mon": {"where": "remote"}}
    ) == {"error": "module 'signals' is disabled"}
    assert await mcp_router.update_settings(
        section="conflict_rule", rule_id=1, active=False
    ) == {"error": "module 'interactions' is disabled"}
    assert await mcp_router.sync_data(source="hevy") == {
        "error": "module 'hevy' is disabled"
    }
    assert await mcp_router.get_settings(section="environment") == {
        "error": "module 'environment' is disabled"
    }


@pytest.mark.parametrize(
    "domain,module_key",
    sorted(
        (domain, key)
        for domain, (key, _, _) in mcp_router._DELETE_TARGETS.items()
        if key is not None
    ),
)
async def test_delete_record_refuses_a_disabled_domain(domain, module_key):
    """``delete_record`` carries the gate for every optional domain: the map is
    the only place a domain can lose its module key."""
    assert await mcp_router.delete_record(domain, 1) == {
        "error": f"module '{module_key}' is disabled"
    }


async def test_delete_record_unknown_domain_lists_the_valid_ones():
    result = await mcp_router.delete_record("meals", 1)
    assert "Unknown domain 'meals'" in result["error"]
    assert "nutrition" in result["error"]


async def test_delete_record_deletes_a_core_domain_row(db_session):
    """Core domains have no gate — and a missing id is a clean ``deleted: false``."""
    from datetime import date

    from vitals.services import weight_service

    row = await weight_service.log_weight(db_session, on_date=date(2026, 7, 1), weight_kg=90.0)
    await db_session.commit()

    assert await mcp_router.delete_record("weight", row.id, confirm=True) == {
        "deleted": True, "domain": "weight", "record_id": row.id,
    }
    assert await mcp_router.delete_record("weight", row.id, confirm=True) == {
        "deleted": False, "domain": "weight", "record_id": row.id,
    }


async def test_gated_write_tool_works_once_the_module_is_on():
    await mcp_router.update_settings(section="modules", key="nutrition", enabled=True)
    row = await mcp_router.save_meal(name="Lunch", calories=500, on_date="2026-07-01")
    assert row["calories"] == 500


# ── Read tools of an optional module ──────────────────────────────────────────
#
# The bedroom-air tool only reads, but the module is optional and a station may
# never exist: with it switched off it refuses when called and is not listed, so
# the owner who doesn't track it carries none of its schema.

GATED_ENVIRONMENT_READ_HANDLERS: dict[str, str] = {
    "get_environment": "environment",
    "get_environment_live": "environment",
    "get_environment_series": "environment",
    "get_environment_night": "environment",
    "get_environment_alerts": "environment",
    "get_environment_vs_sleep": "environment",
    "get_environment_settings": "environment",
}


def test_the_environment_tool_is_in_the_visibility_map():
    assert mcp_router.TOOL_MODULES["get_environment"] == "environment"


@pytest.mark.parametrize("handler_name,module_key", sorted(GATED_ENVIRONMENT_READ_HANDLERS.items()))
async def test_gated_read_handler_refuses_when_module_is_off(handler_name, module_key):
    fn = getattr(mcp_router, handler_name)
    assert await fn() == {"error": f"module '{module_key}' is disabled"}


@pytest.mark.parametrize("view", ("live", "series", "night", "vs_sleep", "alerts", "settings"))
async def test_get_environment_refuses_every_view_when_off(view):
    assert await mcp_router.get_environment(view=view) == {
        "error": "module 'environment' is disabled"
    }


async def test_environment_tool_is_listed_only_while_the_module_is_on():
    listed = {t.name for t in await mcp_router.mcp.list_tools()}
    assert "get_environment" not in listed

    await mcp_router.set_module("environment", True)

    listed = {t.name for t in await mcp_router.mcp.list_tools()}
    assert "get_environment" in listed

    await mcp_router.set_module("environment", False)

    listed = {t.name for t in await mcp_router.mcp.list_tools()}
    assert "get_environment" not in listed


async def test_environment_tool_answers_every_view_once_the_module_is_on():
    await mcp_router.set_module("environment", True)

    live = await mcp_router.get_environment(view="live")
    assert live["station"]["status"] == "never"  # no station has reported — an answer, not an error
    assert "error" not in await mcp_router.get_environment(view="night", on_date="2026-09-30")
    assert "error" not in await mcp_router.get_environment(view="alerts")
    assert "error" not in await mcp_router.get_environment(view="vs_sleep")
    assert "error" not in await mcp_router.get_environment(view="series")
    assert "error" not in await mcp_router.get_environment(view="settings")
