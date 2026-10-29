"""Regression tests for audit fixes: Item 2 (GLP-1 in snapshot) and Item 5 (meal eaten_at)."""
from datetime import date, time, timedelta
import pytest
from sqlalchemy import select

from vitals.enums import Domain
from vitals.models.glp1 import DosePhase, Injection
from vitals.models.nutrition import MealLog
from vitals.services import digest_service, nutrition_service
from web.routers import mcp as mcp_router


@pytest.mark.asyncio
async def test_glp1_coverage_and_injections_in_snapshot(db_session):
    today = date(2026, 10, 28)
    # Inject a dose phase starting months ago
    phase = DosePhase(
        start_date=date(2026, 5, 24),
        drug="Semaglutide",
        dose_mg=1.0,
        domain=Domain.GLP1.value,
    )
    db_session.add(phase)

    # Injections on Oct 18 and Oct 25
    inj1 = Injection(
        date=date(2026, 10, 18),
        drug="Semaglutide",
        dose_mg=1.0,
        domain=Domain.GLP1.value,
    )
    inj2 = Injection(
        date=date(2026, 10, 25),
        drug="Semaglutide",
        dose_mg=1.0,
        domain=Domain.GLP1.value,
    )
    db_session.add_all([inj1, inj2])
    await db_session.commit()

    # Request snapshot for 1 day ending Oct 27 (no injection on Oct 27) with glp1 enabled
    ctx = await digest_service.assemble_context(
        db_session, on_date=today, period_days=1, enabled_modules={"glp1": True}
    )

    assert ctx["glp1"] is not None
    assert ctx["glp1"]["last_injection"] == "2026-10-25"
    assert ctx["glp1"]["injections"] == []  # empty list, not null!

    cov = ctx["coverage"]["glp1"]
    assert cov["last_date"] == "2026-10-25"
    period_end = date.fromisoformat(ctx["report_meta"]["period_end"])
    assert cov["freshness_days"] == (period_end - date(2026, 10, 25)).days
    assert cov["last_injection"] == "2026-10-25"

    # Also verify module names in coverage
    assert ctx["coverage"]["milestones"]["module"] == "milestones"
    assert ctx["coverage"]["day_context"]["module"] == "day_context"


@pytest.mark.asyncio
async def test_meal_eaten_at_nullable_and_logged_at(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    today = date(2026, 10, 28)

    # Log meal without eaten_at
    meal = await nutrition_service.log_meal(
        db_session,
        on_date=today,
        name="Skyr with berries",
        calories=250.0,
    )
    await db_session.commit()

    assert meal.eaten_at is None

    # Search meals via MCP
    results = await mcp_router.search_meals(query="Skyr")
    assert len(results) >= 1
    found = next(r for r in results if r["name"] == "Skyr with berries")
    assert found["eaten_at"] is None
    assert "logged_at" in found

    # Verify that un-timed meal does not falsely increment meals_after_21
    ctx = await digest_service.assemble_context(
        db_session, on_date=today + timedelta(days=1), period_days=1, enabled_modules={"nutrition": True}
    )
    assert ctx["nutrition"]["meals_after_21"] == 0
