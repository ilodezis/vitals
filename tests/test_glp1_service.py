"""GLP-1 service tests — injections, dose phases (auto-close), side effects,
plateau detection, and the weight-chart phase overlay link."""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from vitals.enums import Drug, InjectionSite, Severity
from vitals.services import alerts_service, glp1_service, weight_service

pytestmark = pytest.mark.asyncio


# ── Injections ────────────────────────────────────────────────────────────────
async def test_log_and_list_injection(db_session):
    inj = await glp1_service.log_injection(
        db_session,
        on_date=date(2026, 6, 1),
        drug=Drug.SEMAGLUTIDE.value,
        dose_mg=0.25,
        site=InjectionSite.ABDOMEN_LEFT.value,
    )
    await db_session.commit()
    assert inj.id is not None
    rows = await glp1_service.list_injections(db_session)
    assert len(rows) == 1
    assert rows[0].drug == "semaglutide"
    last = await glp1_service.last_injection(db_session)
    assert last.site == "abdomen_left"


def test_site_frequency_counts_by_site():
    """Pure logic feeding the rotation mini-map (I1) — no DB needed."""
    rows = [
        SimpleNamespace(site=InjectionSite.ABDOMEN_LEFT.value),
        SimpleNamespace(site=InjectionSite.ABDOMEN_LEFT.value),
        SimpleNamespace(site=InjectionSite.THIGH_RIGHT.value),
        SimpleNamespace(site=None),  # logged without a site — must not crash/count
    ]
    counts = glp1_service.site_frequency(rows)
    assert counts == {"abdomen_left": 2, "thigh_right": 1}


def test_site_frequency_empty_when_no_injections():
    assert glp1_service.site_frequency([]) == {}


async def test_update_and_delete_injection(db_session):
    inj = await glp1_service.log_injection(
        db_session, on_date=date(2026, 6, 1), drug=Drug.SEMAGLUTIDE.value, dose_mg=0.25
    )
    await db_session.commit()

    await glp1_service.update_injection(
        db_session, inj.id, on_date=date(2026, 6, 2), drug=Drug.TIRZEPATIDE.value, dose_mg=2.5
    )
    await db_session.commit()
    await db_session.refresh(inj)
    assert inj.drug == "tirzepatide"
    assert inj.dose_mg == 2.5

    assert await glp1_service.delete_injection(db_session, inj.id) is True
    await db_session.commit()
    assert len(await glp1_service.list_injections(db_session)) == 0


# ── Dose phases ───────────────────────────────────────────────────────────────
async def test_open_phase_closes_previous(db_session):
    """A second open-ended phase closes the first the day before it starts."""
    p1 = await glp1_service.add_dose_phase(
        db_session, start_date=date(2026, 5, 1), drug=Drug.SEMAGLUTIDE.value, dose_mg=0.25
    )
    await db_session.commit()
    assert p1.end_date is None

    p2 = await glp1_service.add_dose_phase(
        db_session, start_date=date(2026, 6, 1), drug=Drug.SEMAGLUTIDE.value, dose_mg=0.5
    )
    await db_session.commit()

    await db_session.refresh(p1)
    assert p1.end_date == date(2026, 5, 31)
    assert p2.end_date is None

    active = await glp1_service.active_dose_phase(db_session, on_date=date(2026, 6, 15))
    assert active.id == p2.id
    assert active.dose_mg == 0.5


async def test_dose_phase_overlays(db_session):
    await glp1_service.add_dose_phase(
        db_session,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
        drug=Drug.SEMAGLUTIDE.value,
        dose_mg=0.25,
    )
    await db_session.commit()
    overlays = await glp1_service.dose_phase_overlays(db_session)
    assert overlays[0]["start"] == "2026-05-01"
    assert overlays[0]["end"] == "2026-05-31"
    assert "0.25" in overlays[0]["label"]


# ── Side effects ──────────────────────────────────────────────────────────────
async def test_side_effect_crud(db_session):
    se = await glp1_service.log_side_effect(
        db_session, on_date=date(2026, 6, 1), effect_type="Тошнота", severity=3
    )
    await db_session.commit()
    rows = await glp1_service.list_side_effects(db_session)
    assert len(rows) == 1 and rows[0].severity == 3

    assert await glp1_service.delete_side_effect(db_session, se.id) is True
    await db_session.commit()
    assert len(await glp1_service.list_side_effects(db_session)) == 0


# ── Plateau detection ─────────────────────────────────────────────────────────
async def _seed_phase_and_weights(db_session, weights_by_offset, *, start=date(2026, 5, 1)):
    await glp1_service.add_dose_phase(
        db_session, start_date=start, drug=Drug.SEMAGLUTIDE.value, dose_mg=0.5
    )
    for offset, kg in weights_by_offset:
        await weight_service.log_weight(db_session, on_date=start + timedelta(days=offset), weight_kg=kg)
    await db_session.commit()


async def test_no_plateau_before_min_days(db_session):
    start = date(2026, 5, 1)
    await _seed_phase_and_weights(db_session, [(0, 88.0), (5, 88.0)], start=start)
    # Only 5 days in → below PLATEAU_MIN_DAYS, no verdict.
    result = await glp1_service.evaluate_plateau(db_session, on_date=start + timedelta(days=5))
    assert result is None


async def test_plateau_detected_when_flat(db_session):
    start = date(2026, 5, 1)
    await _seed_phase_and_weights(
        db_session, [(0, 88.0), (7, 88.05), (14, 87.95), (18, 88.0)], start=start
    )
    today = start + timedelta(days=18)
    result = await glp1_service.evaluate_plateau(db_session, on_date=today)
    assert result is not None
    assert result["drug"] == "semaglutide"
    assert result["days_on_dose"] == 18


async def test_no_plateau_when_losing(db_session):
    start = date(2026, 5, 1)
    await _seed_phase_and_weights(
        db_session, [(0, 90.0), (7, 88.5), (14, 87.0), (18, 86.0)], start=start
    )
    today = start + timedelta(days=18)
    result = await glp1_service.evaluate_plateau(db_session, on_date=today)
    assert result is None


async def test_refresh_plateau_raises_and_resolves(db_session):
    start = date(2026, 5, 1)
    await _seed_phase_and_weights(
        db_session, [(0, 88.0), (7, 88.0), (14, 88.0), (18, 88.0)], start=start
    )
    today = start + timedelta(days=18)

    alert = await glp1_service.refresh_plateau_alert(db_session, on_date=today)
    await db_session.commit()
    assert alert is not None
    assert alert.severity == Severity.WARN.value

    active = await alerts_service.list_active(db_session, domain="glp1")
    assert any(a.alert_key == glp1_service.PLATEAU_ALERT_KEY for a in active)

    # Now add strong loss → plateau clears.
    await weight_service.log_weight(db_session, on_date=today, weight_kg=84.0)
    await db_session.commit()
    await glp1_service.refresh_plateau_alert(db_session, on_date=today)
    await db_session.commit()
    active = await alerts_service.list_active(db_session, domain="glp1")
    assert not any(a.alert_key == glp1_service.PLATEAU_ALERT_KEY for a in active)


# ── Weight chart overlay link ─────────────────────────────────────────────────
async def test_weight_chart_series_includes_glp1_phases(db_session):
    await glp1_service.add_dose_phase(
        db_session,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
        drug=Drug.SEMAGLUTIDE.value,
        dose_mg=0.25,
    )
    await db_session.commit()
    series = await weight_service.chart_series(db_session)
    assert "phases" in series
    assert len(series["phases"]) == 1
    assert series["phases"][0]["start"] == "2026-05-01"
    assert series["phases"][0]["drug"] == "semaglutide"
    assert series["phases"][0]["dose_mg"] == 0.25


# ── Write-path input validation (post-review run 1) ───────────────────────────
async def test_log_injection_rejects_nonpositive_dose(db_session):
    """A hallucinated non-positive dose from an MCP call is rejected cleanly at the
    service boundary, not left to surface as a raw DB IntegrityError."""
    with pytest.raises(ValueError):
        await glp1_service.log_injection(
            db_session, on_date=date(2026, 6, 1),
            drug=Drug.SEMAGLUTIDE.value, dose_mg=0,
        )
    with pytest.raises(ValueError):
        await glp1_service.log_injection(
            db_session, on_date=date(2026, 6, 1),
            drug=Drug.SEMAGLUTIDE.value, dose_mg=-5,
        )


async def test_log_injection_rejects_unknown_site(db_session):
    """A garbage injection site (not an InjectionSite) is rejected so it can't
    pollute the body-map rotation data."""
    with pytest.raises(ValueError):
        await glp1_service.log_injection(
            db_session, on_date=date(2026, 6, 1),
            drug=Drug.SEMAGLUTIDE.value, dose_mg=0.25, site="left_earlobe",
        )


async def test_update_injection_runs_conflict_engine(db_session):
    """Editing an injection is gated by the conflict engine just like logging one:
    a block rule with no override raises ConflictBlocked (regression for the update
    path that previously skipped enforce())."""
    from vitals.enums import Domain, RuleType
    from vitals.models.conflict_rule import ConflictRule
    from vitals.services.conflict_engine import ConflictBlocked

    inj = await glp1_service.log_injection(
        db_session, on_date=date(2026, 6, 1),
        drug=Drug.SEMAGLUTIDE.value, dose_mg=0.25,
    )
    await db_session.commit()

    # A self-referential block rule on glp1: any proposed injection state fires it.
    db_session.add(ConflictRule(
        rule_type=RuleType.HARD_BLOCK.value,
        domain_a=Domain.GLP1.value, condition_a={},
        domain_b=Domain.GLP1.value, condition_b={},
        severity=Severity.BLOCK.value, message="test block",
    ))
    await db_session.commit()

    with pytest.raises(ConflictBlocked):
        await glp1_service.update_injection(
            db_session, inj.id, on_date=date(2026, 6, 2),
            drug=Drug.TIRZEPATIDE.value, dose_mg=2.5,
        )
