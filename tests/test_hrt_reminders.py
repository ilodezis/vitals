"""HRT PR3 tests — bloodwork/injection reminders, the hrt↔labs conflict rules,
and the MCP tools."""
from __future__ import annotations

from datetime import timedelta

import pytest

from vitals.enums import Domain
from vitals.services import (
    alerts_service,
    conflict_catalog,
    conflict_engine,
    hrt_catalog,
    hrt_cycle_service,
    hrt_reminders,
    hrt_service,
    labs_service,
)
from vitals.utils.timeutils import today_local

pytestmark = pytest.mark.asyncio


# ── Hormone panel seed ────────────────────────────────────────────────────────
async def test_seed_hormone_panel_idempotent(db_session):
    r1 = await hrt_reminders.seed_hormone_panel(db_session)
    await db_session.commit()
    assert r1["created"] == len(hrt_reminders.HORMONE_PANEL)
    r2 = await hrt_reminders.seed_hormone_panel(db_session)
    await db_session.commit()
    assert r2["created"] == 0
    alt = await labs_service.get_marker(db_session, "АЛТ")
    assert alt is not None and alt.retest_interval_days == 90


# ── Bloodwork-due reminder ────────────────────────────────────────────────────
async def test_labs_due_raised_on_cycle_without_bloodwork(db_session):
    await hrt_reminders.seed_hormone_panel(db_session)
    await hrt_cycle_service.add_cycle(
        db_session, kind="blast", start_date=today_local() - timedelta(days=3),
    )
    await db_session.commit()
    await hrt_reminders.refresh_labs_due(db_session)
    await db_session.commit()
    alerts = await alerts_service.list_active(db_session, domain=Domain.HRT.value)
    assert any(a.alert_key == hrt_reminders.LABS_DUE_KEY for a in alerts)


async def test_labs_due_cleared_by_recent_panel_result(db_session):
    await hrt_reminders.seed_hormone_panel(db_session)
    await hrt_cycle_service.add_cycle(
        db_session, kind="blast", start_date=today_local() - timedelta(days=3),
    )
    await db_session.commit()
    await hrt_reminders.refresh_labs_due(db_session)
    await db_session.commit()
    # A fresh panel result clears it.
    await labs_service.add_result(
        db_session, on_date=today_local(), marker="Тестостерон общий", value=25,
    )
    await db_session.commit()
    await hrt_reminders.refresh_labs_due(db_session)
    await db_session.commit()
    alerts = await alerts_service.list_active(db_session, domain=Domain.HRT.value)
    assert not any(a.alert_key == hrt_reminders.LABS_DUE_KEY for a in alerts)


async def test_labs_due_absent_without_active_cycle(db_session):
    await hrt_reminders.seed_hormone_panel(db_session)
    await db_session.commit()
    await hrt_reminders.refresh_labs_due(db_session)
    await db_session.commit()
    alerts = await alerts_service.list_active(db_session, domain=Domain.HRT.value)
    assert not any(a.alert_key == hrt_reminders.LABS_DUE_KEY for a in alerts)


# ── Injection-due reminder ────────────────────────────────────────────────────
async def test_injection_due_raised_when_shot_missed(db_session):
    await hrt_catalog.sync_catalog(db_session)
    cycle = await hrt_cycle_service.add_cycle(
        db_session, kind="trt_baseline", start_date=today_local() - timedelta(days=10),
    )
    await db_session.commit()
    await hrt_cycle_service.add_cycle_item(
        db_session, cycle.id, compound_key="testosterone_enanthate",
        schedule=[{"dose": 125, "interval_days": 3.5}],
    )
    await db_session.commit()
    # No doses logged over 10 days of an E3.5D plan → overdue.
    await hrt_reminders.refresh_injection_due(db_session)
    await db_session.commit()
    alerts = await alerts_service.list_active(db_session, domain=Domain.HRT.value)
    due = [a for a in alerts if a.alert_key == hrt_reminders.INJECTION_DUE_KEY]
    assert due and due[0].entity_ref == "testosterone_enanthate"


async def test_injection_due_cleared_after_logging(db_session):
    await hrt_catalog.sync_catalog(db_session)
    cycle = await hrt_cycle_service.add_cycle(
        db_session, kind="trt_baseline", start_date=today_local() - timedelta(days=10),
    )
    await db_session.commit()
    await hrt_cycle_service.add_cycle_item(
        db_session, cycle.id, compound_key="testosterone_enanthate",
        schedule=[{"dose": 125, "interval_days": 3.5}],
    )
    await db_session.commit()
    await hrt_reminders.refresh_injection_due(db_session)
    await db_session.commit()
    # Logging today's shot catches the grid up → resolved.
    await hrt_service.log_dose(
        db_session, compound_key="testosterone_enanthate", on_date=today_local(),
        dose=125, unit="mg",
    )
    await db_session.commit()
    await hrt_reminders.refresh_injection_due(db_session)
    await db_session.commit()
    alerts = await alerts_service.list_active(db_session, domain=Domain.HRT.value)
    assert not any(a.alert_key == hrt_reminders.INJECTION_DUE_KEY for a in alerts)


# ── Conflict rules (hrt ↔ labs) ───────────────────────────────────────────────
async def _register_hrt_labs_resolvers():
    conflict_engine.register_domain_resolver(Domain.HRT.value, hrt_service.resolve_active)
    conflict_engine.register_domain_resolver(Domain.LABS.value, labs_service.resolve_latest)


async def test_oral_17aa_high_alt_fires_soft_warn(db_session):
    await hrt_catalog.sync_catalog(db_session)
    await conflict_catalog.sync_catalog(db_session)
    await _register_hrt_labs_resolvers()
    # High ALT on the panel.
    await labs_service.add_result(
        db_session, on_date=today_local(), marker="АЛТ", value=120,
        ref_low=0, ref_high=40,
    )
    await db_session.commit()
    # Logging an oral 17aa while ALT is high fires the soft_warn.
    violations = await conflict_engine.evaluate(
        db_session, Domain.HRT.value,
        {"compound_key": "oxandrolone", "compound_class": "oral_aas"},
    )
    assert any(v.category == "lab_safety" and v.severity == "warn" for v in violations)


async def test_testosterone_high_hematocrit_fires(db_session):
    await hrt_catalog.sync_catalog(db_session)
    await conflict_catalog.sync_catalog(db_session)
    await _register_hrt_labs_resolvers()
    await labs_service.add_result(
        db_session, on_date=today_local(), marker="Гематокрит", value=55,
        ref_low=39, ref_high=50,
    )
    await db_session.commit()
    violations = await conflict_engine.evaluate(
        db_session, Domain.HRT.value,
        {"compound_key": "testosterone_enanthate", "compound_class": "testosterone"},
    )
    assert any(v.category == "lab_safety" for v in violations)


async def test_no_conflict_when_labs_normal(db_session):
    await hrt_catalog.sync_catalog(db_session)
    await conflict_catalog.sync_catalog(db_session)
    await _register_hrt_labs_resolvers()
    await labs_service.add_result(
        db_session, on_date=today_local(), marker="АЛТ", value=25,
        ref_low=0, ref_high=40,  # normal
    )
    await db_session.commit()
    violations = await conflict_engine.evaluate(
        db_session, Domain.HRT.value,
        {"compound_key": "oxandrolone", "compound_class": "oral_aas"},
    )
    assert not any(v.category == "lab_safety" for v in violations)


# ── MCP tools ─────────────────────────────────────────────────────────────────
mcp_router = pytest.importorskip("web.routers.mcp")


async def test_mcp_log_and_get_hrt_dose(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()

    res = await mcp_router.log_hrt_dose(
        compound_key="testosterone_enanthate", volume_ml=1.0, on_date="2026-06-01",
        brand="Pharmacom",
    )
    assert "error" not in res
    assert res["dose"] == pytest.approx(250.0)  # 1 ml × 250 mg/ml catalog conc
    assert res["brand"] == "Pharmacom"

    logs = await mcp_router.get_hrt_logs()
    assert len(logs["doses"]) == 1


async def test_mcp_add_cycle_and_item(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()

    cycle = await mcp_router.add_hrt_cycle(kind="blast", name="Test", start_date="2026-06-01")
    assert "error" not in cycle
    item = await mcp_router.add_hrt_cycle_item(
        cycle_id=cycle["id"], compound_key="trenbolone_acetate",
        dose=50, interval_days=2, duration_days=56,
    )
    assert "error" not in item and item["compound_key"] == "trenbolone_acetate"

    cycles = await mcp_router.get_hrt_cycles()
    assert cycles["cycles"][0]["name"] == "Test"
    assert len(cycles["cycles"][0]["items"]) == 1


async def test_mcp_add_item_unknown_cycle(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    res = await mcp_router.add_hrt_cycle_item(
        cycle_id=9999, compound_key="oxandrolone", dose=20, interval_days=1,
    )
    assert "error" in res


async def test_injection_due_not_raised_before_item_offset(db_session):
    """A compound scheduled from week 5 must not nag during weeks 1-4."""
    await hrt_catalog.sync_catalog(db_session)
    cycle = await hrt_cycle_service.add_cycle(
        db_session, kind="blast", start_date=today_local() - timedelta(days=3),
    )
    await db_session.commit()
    await hrt_cycle_service.add_cycle_item(
        db_session, cycle.id, compound_key="stanozolol_oral",
        schedule=[{"dose": 30, "interval_days": 1, "duration_days": 28}],
        start_offset_days=28,
    )
    await db_session.commit()
    await hrt_reminders.refresh_injection_due(db_session)
    await db_session.commit()
    alerts = await alerts_service.list_active(db_session, domain=Domain.HRT.value)
    assert not any(
        a.alert_key == hrt_reminders.INJECTION_DUE_KEY
        and a.entity_ref == "stanozolol_oral"
        for a in alerts
    )
