"""MCP "full access" tools (Run 1):
  * B1 — override plumbing: a hard-block conflict returns a structured
    ``{"blocked": true, ...}`` payload instead of a 500, and ``override=True``
    saves anyway.
  * A1 — get_full_snapshot (cross-domain context).
  * A2 — export_everything (whole-lake LLM export).
  * A4 — get_data_overview (per-domain coverage map).

Same import-skip guard as the other MCP tool tests."""
from __future__ import annotations

import pytest

from vitals.models.conflict_rule import ConflictRule
from vitals.services import conflict_registrations, supplements_service, weight_service

mcp_router = pytest.importorskip("web.routers.mcp")


async def _seed_meal_block(db_session):
    """A hard block that fires on a meal named 'steak' while iron is in the stack.
    Cross-domain (supplements ↔ nutrition) so the block is reachable through the
    live save path of log_meal."""
    db_session.add(
        ConflictRule(
            rule_type="hard_block",
            domain_a="supplements",
            condition_a={"key": "iron", "active": True},
            domain_b="nutrition",
            condition_b={"name": "steak"},
            severity="block",
            message="Тестовый блок: стейк при приёме железа.",
            active=True,
        )
    )
    await supplements_service.add_supplement(db_session, name="Iron", key="iron", active=True)
    await db_session.commit()


# ── B1 override plumbing ──────────────────────────────────────────────────────
async def test_log_meal_blocked_returns_payload_not_500(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    conflict_registrations.register_all_resolvers()
    await _seed_meal_block(db_session)

    result = await mcp_router.log_meal(name="steak", calories=600)
    assert result.get("blocked") is True
    assert result["violations"]
    assert result["violations"][0]["severity"] == "block"
    # Nothing was saved.
    assert await mcp_router.search_meals(query="steak") == []


async def test_log_meal_override_saves_through_block(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    conflict_registrations.register_all_resolvers()
    await _seed_meal_block(db_session)

    saved = await mcp_router.log_meal(name="steak", calories=600, override=True)
    assert saved.get("blocked") is not True
    assert saved["id"] > 0
    assert saved["name"] == "steak"
    rows = await mcp_router.search_meals(query="steak")
    assert len(rows) == 1


# ── A1 get_full_snapshot ──────────────────────────────────────────────────────
async def test_get_full_snapshot_returns_cross_domain_context(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    from datetime import date

    await weight_service.log_weight(db_session, on_date=date(2026, 7, 1), weight_kg=90.0)
    await db_session.commit()

    snap = await mcp_router.get_full_snapshot()
    assert "user_profile" in snap
    assert snap["report_meta"]["period_days"] == 7
    assert "weight" in snap


# ── A2 export_everything ──────────────────────────────────────────────────────
async def test_export_everything_includes_history(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    from datetime import date

    await weight_service.log_weight(db_session, on_date=date(2026, 7, 2), weight_kg=88.5)
    await db_session.commit()

    export = await mcp_router.export_everything()
    assert "profile" in export
    assert "weight_history" in export
    assert any(row.get("weight_kg") == 88.5 for row in export["weight_history"])


# ── A4 get_data_overview ──────────────────────────────────────────────────────
async def test_get_data_overview_reports_counts_and_range(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    from datetime import date

    await weight_service.log_weight(db_session, on_date=date(2026, 6, 1), weight_kg=91.0)
    await weight_service.log_weight(db_session, on_date=date(2026, 6, 10), weight_kg=90.0)
    await db_session.commit()

    overview = await mcp_router.get_data_overview()
    assert overview["weight"]["count"] == 2
    assert overview["weight"]["earliest"] == "2026-06-01"
    assert overview["weight"]["latest"] == "2026-06-10"
    # Config/catalog tables report a count too (zero here).
    assert overview["supplements"]["count"] == 0
    assert "milestones" in overview
