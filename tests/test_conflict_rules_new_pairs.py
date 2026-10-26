"""The two cross-domain pairs the catalog was missing: glp1 ↔ labs (pancreatic
enzymes) and hrt ↔ skincare (peel over androgen-driven acne)."""
from __future__ import annotations

from sqlalchemy import select

from vitals.enums import Domain
from vitals.models.conflict_rule import ConflictRule
from vitals.services import (
    conflict_catalog,
    conflict_engine,
    glp1_service,
    hrt_catalog,
    labs_service,
    skincare_service,
)
from vitals.utils.timeutils import today_local


async def _rule_id(session, code: str) -> int:
    result = await session.execute(select(ConflictRule).where(ConflictRule.code == code))
    row = result.scalars().first()
    assert row is not None, f"rule {code} missing from the synced catalog"
    return row.id


# ── glp1 ↔ labs ───────────────────────────────────────────────────────────────
async def _glp1_on_lipase(db_session, *, value: float):
    await conflict_catalog.sync_catalog(db_session)
    conflict_engine.register_domain_resolver(Domain.GLP1.value, glp1_service.resolve_active)
    conflict_engine.register_domain_resolver(Domain.LABS.value, labs_service.resolve_latest)
    await glp1_service.add_dose_phase(
        db_session, start_date=today_local(), drug="semaglutide", dose_mg=1.0,
    )
    await labs_service.add_result(
        db_session, on_date=today_local(), marker="Липаза", value=value,
        ref_low=0, ref_high=60,
    )
    await db_session.commit()
    return await conflict_engine.evaluate(db_session, Domain.LABS.value)


async def test_glp1_high_lipase_fires(db_session):
    violations = await _glp1_on_lipase(db_session, value=180)
    rule_id = await _rule_id(db_session, "glp1_pancreatic_enzymes_elevated")
    fired = [v for v in violations if v.rule_id == rule_id]
    assert fired and fired[0].severity == "warn" and fired[0].category == "lab_safety"


async def test_glp1_normal_lipase_silent(db_session):
    violations = await _glp1_on_lipase(db_session, value=30)
    rule_id = await _rule_id(db_session, "glp1_pancreatic_enzymes_elevated")
    assert not any(v.rule_id == rule_id for v in violations)


# ── hrt ↔ skincare ────────────────────────────────────────────────────────────
async def _androgen_over_skincare(db_session, *, peel: bool):
    await hrt_catalog.sync_catalog(db_session)
    await conflict_catalog.sync_catalog(db_session)
    conflict_engine.register_domain_resolver(
        Domain.SKINCARE.value, skincare_service.resolve_today
    )
    # The routine day, not the calendar one: before day_end the resolver reads
    # yesterday's log, and a log written on today_local() would go unseen.
    await skincare_service.upsert_log(
        db_session, on_date=await skincare_service.today(db_session), peel=peel,
        moisturizer=True,
    )
    await db_session.commit()
    return await conflict_engine.evaluate(
        db_session, Domain.HRT.value,
        {"compound_key": "testosterone_enanthate", "compound_class": "testosterone"},
    )


async def test_androgens_peel_fires(db_session):
    violations = await _androgen_over_skincare(db_session, peel=True)
    rule_id = await _rule_id(db_session, "derm_androgens_peel_active_acne")
    fired = [v for v in violations if v.rule_id == rule_id]
    assert fired and fired[0].severity == "warn" and fired[0].category == "dermatology"


async def test_androgens_without_peel_silent(db_session):
    violations = await _androgen_over_skincare(db_session, peel=False)
    rule_id = await _rule_id(db_session, "derm_androgens_peel_active_acne")
    assert not any(v.rule_id == rule_id for v in violations)
