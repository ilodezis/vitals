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
    # The overview's table list is hand-maintained (unlike serialize_row's
    # reflection), so a new table has to be added to it explicitly.
    assert "garmin_intraday" in overview


# ── get_garmin_metrics: intraday series ───────────────────────────────────────
async def test_get_garmin_metrics_intraday_off_by_default(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    await _seed_intraday(db_session)

    default = await mcp_router.get_garmin_metrics(start_date="2026-06-10", end_date="2026-06-10")
    assert "intraday" not in default

    with_series = await mcp_router.get_garmin_metrics(
        start_date="2026-06-10", end_date="2026-06-10", intraday=True
    )
    assert with_series["intraday_truncated"] is False
    stress = with_series["intraday"]["stress"]
    assert [p["value"] for p in stress] == [43.0, 37.0]
    assert stress[0]["ts"] == "2026-06-10T08:00:00"
    assert len(with_series["intraday"]["body_battery"]) == 1


async def test_get_garmin_metrics_intraday_caps_and_flags_truncation(
    db_session, session_factory, monkeypatch
):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(mcp_router, "INTRADAY_POINT_CAP", 2)
    await _seed_intraday(db_session)

    result = await mcp_router.get_garmin_metrics(intraday=True)
    total = sum(len(points) for points in result["intraday"].values())
    assert total == 2
    assert result["intraday_truncated"] is True


async def _seed_intraday(db_session):
    from datetime import date, datetime

    from vitals.models.garmin import GarminIntraday

    db_session.add_all([
        GarminIntraday(
            date=date(2026, 6, 10), domain="garmin", source="garmin_api",
            series_type="stress", ts=datetime(2026, 6, 10, 8, 0), value=43.0,
        ),
        GarminIntraday(
            date=date(2026, 6, 10), domain="garmin", source="garmin_api",
            series_type="stress", ts=datetime(2026, 6, 10, 8, 3), value=37.0,
        ),
        GarminIntraday(
            date=date(2026, 6, 10), domain="garmin", source="garmin_api",
            series_type="body_battery", ts=datetime(2026, 6, 10, 8, 0), value=72.0,
        ),
    ])
    await db_session.commit()
