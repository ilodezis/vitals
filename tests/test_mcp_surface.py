"""Tests for the consolidated MCP surface: ServerInstructions, ToolAnnotations,
tool-count budget, consolidated routing, and live DB-backed profile updates."""
from __future__ import annotations

from datetime import timedelta

import pytest

from vitals.utils.timeutils import today_local

mcp_router = pytest.importorskip("web.routers.mcp")


@pytest.fixture(autouse=True)
def _use_test_factory(session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(mcp_router, "_redis_or_none", lambda: None)


async def _enable_all_modules(db_session):
    from vitals.services import modules_service

    for key in sorted(modules_service.OPTIONAL_KEYS):
        await modules_service.set_module_enabled(db_session, key=key, enabled=True)
    await db_session.commit()


# ── Instructions, budget, and annotations ─────────────────────────────────────
def test_server_instructions_are_concise_and_accurate():
    text = mcp_router.mcp.instructions
    assert isinstance(text, str) and 200 <= len(text) <= 2500
    for needle in (
        "get_today",
        "export_data",
        "get_full_snapshot",
        "get_trend",
        "delete_record",
        "manage_alerts",
        "create_report",
        "get_settings",
        "update_settings",
        "override=true",
        "confirm=true",
    ):
        assert needle in text


async def test_consolidated_tool_count_stays_within_budget(db_session):
    # Optional modules default off -> lean core surface.
    core_tools = await mcp_router.mcp.list_tools()
    assert 20 <= len(core_tools) <= 30

    # All optional modules on -> full consolidated surface within 35..45 tools.
    await _enable_all_modules(db_session)
    all_tools = await mcp_router.mcp.list_tools()
    assert 35 <= len(all_tools) <= 45


async def test_every_registered_tool_has_complete_annotations(db_session):
    await _enable_all_modules(db_session)
    tools = await mcp_router.mcp.list_tools()
    by_name = {t.name: t for t in tools}

    for name, tool in by_name.items():
        ann = tool.annotations
        assert ann is not None, f"{name} is missing ToolAnnotations"
        assert isinstance(ann.read_only_hint, bool), f"{name}: read_only_hint unset"
        assert isinstance(ann.destructive_hint, bool), f"{name}: destructive_hint unset"
        assert isinstance(ann.idempotent_hint, bool), f"{name}: idempotent_hint unset"
        assert isinstance(ann.open_world_hint, bool), f"{name}: open_world_hint unset"

        if name.startswith("get_") or name == "export_data":
            assert ann.read_only_hint is True, f"{name} should be readOnlyHint=True"
            assert ann.destructive_hint is False, f"{name} should be destructiveHint=False"
            assert ann.idempotent_hint is True, f"{name} should be idempotentHint=True"
            assert ann.open_world_hint is False, f"{name} should be openWorldHint=False"
        else:
            assert ann.read_only_hint is False, f"{name} should be readOnlyHint=False"

    # Destructive operations explicitly marked.
    assert by_name["delete_record"].annotations.destructive_hint is True
    assert by_name["manage_alerts"].annotations.destructive_hint is True
    for safe_write in (
        "save_weight", "save_meal", "save_lab", "save_glp1", "save_hrt",
        "save_skincare", "save_supplement", "save_event", "save_milestone",
        "save_signal", "update_user_profile", "update_settings", "log_note",
    ):
        assert by_name[safe_write].annotations.destructive_hint is False

    # External-world operations explicitly marked.
    assert by_name["sync_data"].annotations.open_world_hint is True
    assert by_name["create_report"].annotations.open_world_hint is True
    assert by_name["create_saved_chart"].annotations.open_world_hint is False


def test_backward_compatible_package_exports():
    for name in (
        "mcp",
        "get_mcp_app",
        "MCPAuthMiddleware",
        "ModuleVisibilityMiddleware",
        "TOOL_MODULES",
        "serialize_row",
        "serialize_written",
    ):
        assert hasattr(mcp_router, name)


# ── Consolidated tool routing & validation ────────────────────────────────────
async def test_consolidated_weight_and_export_roundtrip(db_session):
    created = await mcp_router.save_weight(entry="weight", weight_kg=89.5, on_date="2026-07-10")
    assert created["weight_kg"] == 89.5

    edited = await mcp_router.save_weight(
        entry="weight", record_id=created["id"], weight_kg=89.0, note="corrected"
    )
    assert edited["weight_kg"] == 89.0 and edited["note"] == "corrected"

    measured = await mcp_router.save_weight(
        entry="measurement", on_date="2026-07-10", neck_cm=40.0, waist_cm=90.0
    )
    assert measured["waist_cm"] == 90.0 and measured["body_fat_pct_navy"] > 0

    noise = await mcp_router.save_weight(
        entry="noise_marker", start_date="2026-07-10", reason="travel"
    )
    assert noise["reason"] == "travel"

    overview = await mcp_router.export_data(mode="overview")
    assert overview["weight"]["count"] == 1
    exported = await mcp_router.export_data(mode="export", domains=["weight_history"])
    assert "weight_history" in exported

    # Validation errors on unknown entry, unused args, missing args
    assert "unknown entry" in (await mcp_router.save_weight(entry="bogus"))["error"]
    assert "does not take" in (
        await mcp_router.save_weight(entry="weight", weight_kg=80.0, waist_cm=90.0)
    )["error"]
    assert "needs:" in (await mcp_router.save_weight(entry="weight"))["error"]
    assert "unknown mode" in (await mcp_router.export_data(mode="bogus"))["error"]


async def test_consolidated_nutrition_labs_milestones_alerts_and_settings(db_session):
    await _enable_all_modules(db_session)

    # Nutrition
    meal = await mcp_router.save_meal(name="Eggs", calories=420, protein_g=32, on_date="2026-07-11")
    assert meal["name"] == "Eggs"
    edited = await mcp_router.save_meal(record_id=meal["id"], name="Boiled Eggs")
    assert edited["name"] == "Boiled Eggs" and edited["calories"] == 420.0
    summary = await mcp_router.get_nutrition(view="summary", start_date="2026-07-11")
    assert summary["totals"]["calories"] == 420.0
    meals = await mcp_router.get_nutrition(view="meals", query="Boiled")
    assert [m["id"] for m in meals["meals"]] == [meal["id"]]

    # Labs
    lab = await mcp_router.save_lab(entry="result", marker="Glucose", value=5.1, on_date="2026-07-11")
    assert lab["marker"] == "Glucose"
    updated_lab = await mcp_router.save_lab(entry="result", record_id=lab["id"], value=5.3)
    assert updated_lab["value"] == 5.3
    labs_read = await mcp_router.get_labs(view="results", marker="Glucose")
    assert len(labs_read["results"]) == 1
    markers = await mcp_router.get_labs(view="markers")
    assert isinstance(markers, dict)

    # Milestones
    ms = await mcp_router.save_milestone(name="Hit 85 kg", target_value=85.0, target_unit="kg")
    assert ms["name"] == "Hit 85 kg"
    ms2 = await mcp_router.save_milestone(record_id=ms["id"], status="achieved")
    assert ms2["status"] == "achieved"

    # Alerts & conflicts
    active = await mcp_router.get_alerts(view="active")
    assert isinstance(active, list)
    rules = await mcp_router.get_alerts(view="rules")
    assert isinstance(rules, list)

    # Settings read + write
    all_settings = await mcp_router.get_settings(section="all")
    assert "profile" in all_settings and "modules" in all_settings
    proactive = await mcp_router.update_settings(
        section="proactive", values={"brief_time": "08:30"}
    )
    assert proactive["prefs"]["brief_time"] == "08:30"
    assert "unknown section" in (await mcp_router.get_settings(section="nope"))["error"]
    assert "unknown section" in (await mcp_router.update_settings(section="nope"))["error"]


async def test_delete_record_covers_shared_report_link_and_saved_chart(db_session):
    # Create a saved chart and delete it via two-step delete_record.
    chart = await mcp_router.create_saved_chart(
        name="Weight curve", series=[{"metric_key": "weight.weight_kg"}]
    )
    assert "id" in chart
    preview = await mcp_router.delete_record("saved_chart", chart["id"])
    assert preview["confirm_required"] is True
    deleted = await mcp_router.delete_record("saved_chart", chart["id"], confirm=True)
    assert deleted == {"deleted": True, "domain": "saved_chart", "record_id": chart["id"]}

    charts_view = await mcp_router.get_reports(view="charts")
    assert all(c["id"] != chart["id"] for c in charts_view["charts"])

    # Create a shared report (needs at least a couple of recent entries in the period).
    for i in range(3):
        await mcp_router.save_weight(
            entry="weight",
            weight_kg=88.0 - i * 0.2,
            on_date=(today_local() - timedelta(days=i + 1)).isoformat(),
        )
    rep_preview = await mcp_router.create_report(
        kind="shared", title="Doctor visit", domains=["weight"], period="30"
    )
    assert rep_preview["confirm_required"] is True
    rep = await mcp_router.create_report(
        kind="shared", title="Doctor visit", domains=["weight"], period="30", confirm=True
    )
    assert rep["url"].startswith("/r/") and rep["password"]

    # Revoke its link via two-step delete_record("shared_report_link", ...).
    rev_preview = await mcp_router.delete_record("shared_report_link", rep["id"])
    assert rev_preview["confirm_required"] is True
    rev = await mcp_router.delete_record("shared_report_link", rep["id"], confirm=True)
    assert rev == {"deleted": True, "domain": "shared_report_link", "record_id": rep["id"]}


async def test_update_user_profile_applies_live_without_restart(db_session):
    """Profile and nutrition changes via MCP immediately update Navy body-fat
    height, nutrition summary targets, and get_settings without pending_restart."""
    await _enable_all_modules(db_session)

    updated = await mcp_router.update_user_profile(
        height_cm=175.0,
        sex="male",
        age=29,
        protein_target_g=185.0,
        calories_min=1800,
        calories_max=2200,
    )
    assert "pending_restart" not in updated
    assert updated["height_cm"] == 175.0
    assert updated["nutrition_goals"] == {
        "protein_target_g": 185.0,
        "calories_min": 1800,
        "calories_max": 2200,
    }

    # Nutrition summary immediately reflects the new goals.
    summary = await mcp_router.get_nutrition(view="summary", start_date="2026-07-12")
    assert summary["goals"]["protein_target_g"] == 185.0
    assert summary["goals"]["calories_min"] == 1800
    assert summary["goals"]["calories_max"] == 2200

    # Navy formula immediately uses the new height (175 cm instead of 190 cm).
    from vitals.services.analytics.navy import navy_body_fat_pct

    await mcp_router.save_weight(entry="weight", weight_kg=80.0, on_date="2026-07-12")
    m = await mcp_router.save_weight(
        entry="measurement", on_date="2026-07-12", neck_cm=38.0, waist_cm=88.0
    )
    expected_bf = round(navy_body_fat_pct(height_cm=175.0, neck_cm=38.0, waist_cm=88.0, sex="male"), 2)
    assert m["body_fat_pct_navy"] == pytest.approx(expected_bf, abs=0.1)

    # Reading back via get_settings(section="profile") has no pending_restart either.
    prof = await mcp_router.get_settings(section="profile")
    assert "pending_restart" not in prof
    assert prof["height_cm"] == 175.0
