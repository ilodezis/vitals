"""A switched-off module must stay off for the tool surface too.

Turning a module off in settings is the owner saying "I don't track this". The web
routes honour it; the tool surface honoured it on three writes out of forty, so a
conversation could refill a domain the owner had just emptied out of the UI.

The classification test below is the part that lasts: a newly added write tool has
to be listed as gated or explicitly excused, so "don't forget the check" stops
being a thing anyone has to remember.
"""
from __future__ import annotations

import inspect

import pytest

mcp_router = pytest.importorskip("web.routers.mcp")


@pytest.fixture(autouse=True)
def _use_test_factory(session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)


# tool name → the optional module key it writes into
GATED_WRITE_TOOLS: dict[str, str] = {
    "log_meal": "nutrition",
    "update_meal": "nutrition",
    "log_glp1": "glp1",
    "update_glp1": "glp1",
    "log_side_effect": "glp1",
    "add_dose_phase": "glp1",
    "log_hrt_dose": "hrt",
    "update_hrt_dose": "hrt",
    "log_hrt_side_effect": "hrt",
    "add_hrt_cycle": "hrt",
    "add_hrt_cycle_item": "hrt",
    "close_hrt_cycle": "hrt",
    "upsert_genetic_variant": "genetics",
    "log_skincare": "skincare",
    "log_skincare_observation": "skincare",
    "add_supplement": "supplements",
    "update_supplement": "supplements",
    "set_supplement_active": "supplements",
    "log_body_scan": "body_comp",
    "log_event": "timeline",
    "update_event": "timeline",
    "log_signal": "signals",
    "mark_signal_misparse": "signals",
    # Day context lives in the signals domain, which is also the master switch for
    # the whole proactive layer — off means the day is not being tracked at all.
    "log_day_context": "signals",
    "set_week_template": "signals",
}

# Write tools that deliberately have no module gate, each with the reason.
UNGATED_WRITE_TOOLS: dict[str, str] = {
    "log_weight": "weight is a core module — always on",
    "log_measurement": "weight is core",
    "update_measurement": "weight is core",
    "add_noise_marker": "weight is core",
    "log_lab_result": "labs is core",
    "log_lab_results": "labs is core",
    "update_lab_result": "labs is core",
    "log_note": "writes the note column of an already-existing row in any domain",
    "create_milestone": "goals are core",
    "update_milestone": "goals are core",
    "delete_record": "gated per domain inside, from _DELETE_TARGETS — see below",
    "resolve_alert": "alerts are raised by every domain, core ones included",
    "override_alert": "same — an alert is not owned by an optional module",
    "set_module": "this is the toggle itself",
    "generate_digest_now": "reports is core",
}

_WRITE_PREFIXES = ("log_", "add_", "create_", "update_", "upsert_", "delete_", "set_",
                   "mark_", "close_", "resolve_", "override_", "generate_")


def _write_tool_names() -> set[str]:
    return {
        name
        for name in dir(mcp_router)
        if name.startswith(_WRITE_PREFIXES)
        and inspect.iscoroutinefunction(getattr(mcp_router, name))
        and getattr(mcp_router, name).__module__ == mcp_router.__name__
    }


def test_every_write_tool_is_classified():
    """A new write tool must be listed as gated or explicitly excused — otherwise
    it ships ungated and nobody notices until a disabled domain fills up again."""
    assert _write_tool_names() == set(GATED_WRITE_TOOLS) | set(UNGATED_WRITE_TOOLS)


@pytest.mark.parametrize("tool_name,module_key", sorted(GATED_WRITE_TOOLS.items()))
async def test_gated_write_tool_refuses_when_module_is_off(tool_name, module_key):
    """Modules default to off for optional domains, so no setup is needed: every
    one of these must refuse before touching the database."""
    tool = getattr(mcp_router, tool_name)
    # Positional-only stand-ins for whatever required args the tool takes — the
    # gate fires before any of them is looked at.
    args = [1 for p in inspect.signature(tool).parameters.values()
            if p.default is inspect.Parameter.empty]
    result = await tool(*args)
    assert result == {"error": f"module '{module_key}' is disabled"}


@pytest.mark.parametrize(
    "domain,module_key",
    sorted(
        (domain, key)
        for domain, (key, _, _) in mcp_router._DELETE_TARGETS.items()
        if key is not None
    ),
)
async def test_delete_record_refuses_a_disabled_domain(domain, module_key):
    """``delete_record`` carries the gate for eighteen former tools, so it is checked
    per domain: the map is the only place a domain can lose its module key."""
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

    assert await mcp_router.delete_record("weight", row.id) == {
        "deleted": True, "domain": "weight", "record_id": row.id,
    }
    assert await mcp_router.delete_record("weight", row.id) == {
        "deleted": False, "domain": "weight", "record_id": row.id,
    }


async def test_gated_write_tool_works_once_the_module_is_on():
    await mcp_router.set_module("nutrition", True)
    row = await mcp_router.log_meal(name="Обед", calories=500, on_date="2026-07-01")
    assert row["calories"] == 500


# ── Read tools of an optional module ──────────────────────────────────────────
#
# The bedroom-air tools only read, but the module is optional and a station may
# never exist: with it switched off they refuse when called and are not listed, so
# the owner who doesn't track it carries none of their schemas.

# tool name → the optional module key it belongs to
GATED_READ_TOOLS: dict[str, str] = {
    "get_environment_live": "environment",
    "get_environment": "environment",
    "get_environment_night": "environment",
    "get_environment_alerts": "environment",
}


def test_every_environment_read_tool_is_classified():
    """A fifth ``get_environment_*`` tool has to be gated too, not just the four."""
    names = {
        name
        for name in dir(mcp_router)
        if name.startswith("get_environment")
        and inspect.iscoroutinefunction(getattr(mcp_router, name))
        and getattr(mcp_router, name).__module__ == mcp_router.__name__
    }
    assert names == set(GATED_READ_TOOLS)


def test_the_environment_tools_are_in_the_visibility_map():
    for name, module_key in GATED_READ_TOOLS.items():
        assert mcp_router.TOOL_MODULES[name] == module_key


@pytest.mark.parametrize("tool_name,module_key", sorted(GATED_READ_TOOLS.items()))
async def test_gated_read_tool_refuses_when_module_is_off(tool_name, module_key):
    tool = getattr(mcp_router, tool_name)
    assert await tool() == {"error": f"module '{module_key}' is disabled"}


async def test_environment_tools_are_listed_only_while_the_module_is_on():
    listed = {t.name for t in await mcp_router.mcp.list_tools()}
    assert not set(GATED_READ_TOOLS) & listed

    await mcp_router.set_module("environment", True)

    listed = {t.name for t in await mcp_router.mcp.list_tools()}
    assert set(GATED_READ_TOOLS) <= listed

    await mcp_router.set_module("environment", False)

    listed = {t.name for t in await mcp_router.mcp.list_tools()}
    assert not set(GATED_READ_TOOLS) & listed


async def test_environment_tools_answer_once_the_module_is_on():
    await mcp_router.set_module("environment", True)

    live = await mcp_router.get_environment_live()
    assert live["station"]["status"] == "never"  # no station has reported — an answer, not an error
    assert "error" not in await mcp_router.get_environment_night(on_date="2026-09-30")
    assert "error" not in await mcp_router.get_environment_alerts()
    assert "error" not in await mcp_router.get_environment()
