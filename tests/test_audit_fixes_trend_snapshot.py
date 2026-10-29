"""Regression tests for audit fixes: Item 6 (trend projection & window) and Item 16 (snapshot sections)."""
from datetime import date, timedelta
import pytest

from vitals.models.genetics import GeneticVariant
from vitals.services import modules_service, weight_service
from web.routers import mcp as mcp_router


@pytest.mark.asyncio
async def test_get_trend_unknown_metric_suggests_alternatives(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)

    result = await mcp_router.get_trend("weight.kg")
    assert "error" in result
    assert "Unknown metric 'weight.kg'" in result["error"]
    assert "weight.weight_kg" in result["error"]  # suggested close match!
    assert "available_metrics" in result
    assert "weight.weight_kg" in result["available_metrics"]


@pytest.mark.asyncio
async def test_get_trend_projects_from_rolling_mean(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)

    # 4 points, steady weight loss: 100, 99, 98, 97 over 4 weeks
    d0 = date(2026, 6, 1)
    for i, w in enumerate([100.0, 99.0, 98.0, 97.0]):
        await weight_service.log_weight(db_session, on_date=d0 + timedelta(days=7 * i), weight_kg=w)
    await db_session.commit()

    # Target 95 kg from rolling mean (~97.0)
    res = await mcp_router.get_trend("weight.weight_kg", target=95.0, fit_window_days=56)
    assert res["points"] == 4
    assert res["trend"]["slope_per_week"] == -1.0
    assert "projection" in res
    assert res["projection"]["target"] == 95.0
    assert res["projection"]["projected_from"] == 97.0
    # From 97 to 95 at -1 kg/week = 2 weeks (14 days) from 2026-06-22 -> 2026-07-06
    assert res["projection"]["date"] == "2026-07-06"


@pytest.mark.asyncio
async def test_get_full_snapshot_sections_filter(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    today = date(2026, 7, 1)

    await modules_service.set_module_enabled(db_session, key="genetics", enabled=True)
    await weight_service.log_weight(db_session, on_date=today, weight_kg=90.0)
    variant = GeneticVariant(
        gene="MTHFR",
        rsid="rs1801133",
        genotype="CT",
        impact="Reduced folate conversion",
        interpretation="Heterozygous",
    )
    db_session.add(variant)
    await db_session.commit()

    # 1. Default call: compact snapshot — genetics and body_comp are None
    snap_default = await mcp_router.get_full_snapshot(on_date="2026-07-02", period_days=7)
    assert "weight" in snap_default
    assert snap_default["weight"] is not None
    assert snap_default["genetics"] is None
    assert snap_default["body_comp"] is None

    # 2. Explicit sections request including genetics
    snap_genetics = await mcp_router.get_full_snapshot(
        on_date="2026-07-02", period_days=7, sections=["weight", "genetics"]
    )
    assert snap_genetics["weight"] is not None
    assert snap_genetics["genetics"] is not None
    assert len(snap_genetics["genetics"]) >= 1
    assert snap_genetics["body_comp"] is None

    # 3. All sections request
    snap_all = await mcp_router.get_full_snapshot(
        on_date="2026-07-02", period_days=7, sections=["all"]
    )
    assert snap_all["weight"] is not None
    assert snap_all["genetics"] is not None
