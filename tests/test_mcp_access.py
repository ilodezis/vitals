"""MCP "full access" tools:
  * Override plumbing: a hard-block conflict returns a structured
    ``{"blocked": true, ...}`` payload instead of a 500, and ``override=True``
    saves anyway.
  * get_full_snapshot (cross-domain context).
  * export_everything (whole-lake LLM export).
  * get_data_overview (per-domain coverage map).

Same import-skip guard as the other MCP tool tests."""
from __future__ import annotations

import pytest

from vitals.models.conflict_rule import ConflictRule
from vitals.services import conflict_registrations, supplements_service, weight_service

mcp_router = pytest.importorskip("web.routers.mcp")


@pytest.fixture(autouse=True)
async def _optional_modules_on(session_factory):
    """Optional modules default to off, and the MCP write tools honour that
    (web/routers/mcp.gated). These tests write to optional domains — switch them on."""
    from vitals.services import modules_service

    async with session_factory() as session:
        for key in sorted(modules_service.OPTIONAL_KEYS):
            await modules_service.set_module_enabled(session, key=key, enabled=True)
        await session.commit()



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


# ── Override plumbing ─────────────────────────────────────────────────────────
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


# ── get_full_snapshot ─────────────────────────────────────────────────────────
async def test_get_full_snapshot_returns_cross_domain_context(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    from datetime import date

    await weight_service.log_weight(db_session, on_date=date(2026, 7, 1), weight_kg=90.0)
    await db_session.commit()

    snap = await mcp_router.get_full_snapshot()
    assert "user_profile" in snap
    assert snap["schema_version"] == 2
    assert snap["report_meta"]["period_days"] == 7
    assert "weight" in snap


async def test_get_full_snapshot_rejects_unbounded_period(
    db_session, session_factory, monkeypatch
):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)

    result = await mcp_router.get_full_snapshot(period_days=91)

    assert result == {"error": "period_days must be between 1 and 90"}


# ── export_everything ─────────────────────────────────────────────────────────
async def test_export_everything_includes_history(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    from datetime import timedelta

    from vitals.utils.timeutils import today_local

    await weight_service.log_weight(
        db_session, on_date=today_local() - timedelta(days=3), weight_kg=88.5
    )
    await db_session.commit()

    export = await mcp_router.export_everything()
    assert "profile" in export
    assert "weight_history" in export
    assert any(row.get("weight_kg") == 88.5 for row in export["weight_history"])


async def test_export_everything_defaults_to_the_last_90_days(
    db_session, session_factory, monkeypatch
):
    """Without a window the export is years of daily rows — it fills the conversation
    before the question gets asked. The default is a window; the full history is a
    deliberate ask."""
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    from datetime import timedelta

    from vitals.utils.timeutils import today_local

    recent = today_local() - timedelta(days=10)
    ancient = today_local() - timedelta(days=400)
    await weight_service.log_weight(db_session, on_date=recent, weight_kg=88.5)
    await weight_service.log_weight(db_session, on_date=ancient, weight_kg=110.0)
    await db_session.commit()

    default = await mcp_router.export_everything()
    assert [r["weight_kg"] for r in default["weight_history"]] == [88.5]

    # The whole history is one explicit argument away.
    full = await mcp_router.export_everything(since="2000-01-01")
    assert sorted(r["weight_kg"] for r in full["weight_history"]) == [88.5, 110.0]


async def test_export_everything_honours_until_window(
    db_session, session_factory, monkeypatch
):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    from datetime import date

    await weight_service.log_weight(db_session, on_date=date(2025, 1, 10), weight_kg=105.0)
    await weight_service.log_weight(db_session, on_date=date(2025, 2, 10), weight_kg=101.0)
    await weight_service.log_weight(db_session, on_date=date(2025, 3, 10), weight_kg=98.0)
    await db_session.commit()

    sliced = await mcp_router.export_everything(since="2025-02-01", until="2025-02-28")
    assert sliced["profile"]["period"] == {"since": "2025-02-01", "until": "2025-02-28"}
    assert [r["weight_kg"] for r in sliced["weight_history"]] == [101.0]

    # When only `until` is given, the default 90-day window anchors to `until`.
    anchored = await mcp_router.export_everything(until="2025-02-28")
    assert [r["weight_kg"] for r in anchored["weight_history"]] == [105.0, 101.0]

    inverted = await mcp_router.export_everything(since="2025-03-01", until="2025-02-01")
    assert "error" in inverted


async def test_export_everything_narrows_to_named_domains(
    db_session, session_factory, monkeypatch
):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    from datetime import timedelta

    from vitals.utils.timeutils import today_local

    await weight_service.log_weight(
        db_session, on_date=today_local() - timedelta(days=1), weight_kg=88.5
    )
    await db_session.commit()

    only_weight = await mcp_router.export_everything(domains=["weight_history"])
    assert set(only_weight) == {"profile", "weight_history"}
    assert only_weight["weight_history"]

    err = await mcp_router.export_everything(domains=["weight_history", "нет_такого"])
    assert "нет_такого" in err["error"]
    assert "biomarkers" in err["error"]  # the valid names come back with the refusal


# ── get_data_overview ─────────────────────────────────────────────────────────
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


async def test_get_garmin_metrics_exposes_sleep_series_and_stages(
    db_session, session_factory, monkeypatch
):
    """The night's data reaches Claude by two independent switches: point series
    through ``intraday``, the stage timeline off the daily row's JSONB column
    through ``sleep_detail``. Separate so that asking for one night's shape does
    not also pull every curve of the window (see test_mcp_tool_budget.py)."""
    from datetime import date, datetime

    from vitals.models.garmin import GarminDaily, GarminIntraday

    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    db_session.add_all([
        GarminDaily(
            date=date(2026, 6, 10), domain="garmin", source="garmin_api",
            sleep_score=78,
            sleep_stages=[
                {"start": "2026-06-09T23:00:00", "end": "2026-06-10T01:00:00", "stage": "deep"},
            ],
        ),
        # Recorded the evening before, filed under the night's date.
        GarminIntraday(
            date=date(2026, 6, 10), domain="garmin", source="garmin_api",
            series_type="sleep_hr", ts=datetime(2026, 6, 9, 23, 10), value=58.0,
        ),
        GarminIntraday(
            date=date(2026, 6, 10), domain="garmin", source="garmin_api",
            series_type="sleep_spo2", ts=datetime(2026, 6, 10, 1, 0), value=91.0,
        ),
    ])
    await db_session.commit()

    result = await mcp_router.get_garmin_metrics(
        start_date="2026-06-10", end_date="2026-06-10", intraday=True, sleep_detail=True
    )
    assert [p["value"] for p in result["intraday"]["sleep_hr"]] == [58.0]
    assert [p["value"] for p in result["intraday"]["sleep_spo2"]] == [91.0]
    assert result["daily_recovery"][0]["sleep_stages"][0]["stage"] == "deep"


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
