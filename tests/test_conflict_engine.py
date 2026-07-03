"""Predicate-matcher unit tests (pure logic, no DB) — see conflict_engine._matches.

Covers backward-compatible scalar equality, the comparison/membership/presence
operators, and the $any/$all/$not top-level combinators.
"""
from __future__ import annotations

import pytest

from vitals.models.conflict_rule import ConflictRule
from vitals.services import conflict_engine, conflict_registrations, labs_service, supplements_service
from vitals.services.conflict_engine import ConflictBlocked, _matches
from vitals.utils.timeutils import today_local

# No module-level asyncio mark: async DB tests are auto-detected (asyncio_mode=
# auto); the tests above this point are pure sync tests.


# ── Backward compatibility: plain scalar equality (the original behavior) ──────

def test_scalar_equality_matches():
    assert _matches({"key": "iron", "active": True}, {"key": "iron", "active": True})


def test_scalar_equality_mismatch():
    assert not _matches({"key": "iron"}, {"key": "zinc"})


def test_scalar_equality_missing_key_does_not_match():
    assert not _matches({"active": True}, {"key": "iron"})


def test_empty_condition_matches_any_item():
    assert _matches({}, {"anything": 1})
    assert _matches({}, {})


# ── Comparison operators ────────────────────────────────────────────────────

def test_gt():
    assert _matches({"dose_mg": {"$gt": 2.0}}, {"dose_mg": 2.5})
    assert not _matches({"dose_mg": {"$gt": 2.0}}, {"dose_mg": 2.0})
    assert not _matches({"dose_mg": {"$gt": 2.0}}, {"dose_mg": 1.0})


def test_gte():
    assert _matches({"dose_mg": {"$gte": 2.0}}, {"dose_mg": 2.0})
    assert not _matches({"dose_mg": {"$gte": 2.0}}, {"dose_mg": 1.9})


def test_lt():
    assert _matches({"calories": {"$lt": 4000}}, {"calories": 3999})
    assert not _matches({"calories": {"$lt": 4000}}, {"calories": 4000})


def test_lte():
    assert _matches({"value": {"$lte": 5.0}}, {"value": 5.0})
    assert not _matches({"value": {"$lte": 5.0}}, {"value": 5.1})


def test_combined_range_on_one_field():
    cond = {"value": {"$gt": 5.0, "$lte": 10.0}}
    assert _matches(cond, {"value": 7})
    assert _matches(cond, {"value": 10.0})
    assert not _matches(cond, {"value": 5.0})
    assert not _matches(cond, {"value": 10.1})


def test_comparison_missing_field_never_matches():
    assert not _matches({"dose_mg": {"$gt": 2.0}}, {})


def test_comparison_type_mismatch_is_safe_no_crash():
    # A string can't be compared to a number — must fail closed, not raise.
    assert not _matches({"dose_mg": {"$gt": 2.0}}, {"dose_mg": "a lot"})


# ── Membership operators ─────────────────────────────────────────────────────

def test_in():
    assert _matches({"marker": {"$in": ["Калий", "Натрий"]}}, {"marker": "Калий"})
    assert not _matches({"marker": {"$in": ["Калий", "Натрий"]}}, {"marker": "Кальций"})


def test_nin():
    assert _matches({"marker": {"$nin": ["Калий"]}}, {"marker": "Кальций"})
    assert not _matches({"marker": {"$nin": ["Калий"]}}, {"marker": "Калий"})


# ── Presence / substring operators ──────────────────────────────────────────

def test_exists_true():
    assert _matches({"dose_mg": {"$exists": True}}, {"dose_mg": 5})
    assert not _matches({"dose_mg": {"$exists": True}}, {})
    assert not _matches({"dose_mg": {"$exists": True}}, {"dose_mg": None})


def test_exists_false():
    assert _matches({"dose_mg": {"$exists": False}}, {})
    assert not _matches({"dose_mg": {"$exists": False}}, {"dose_mg": 5})


def test_contains():
    assert _matches({"note": {"$contains": "grapefruit"}}, {"note": "avoid grapefruit juice"})
    assert not _matches({"note": {"$contains": "grapefruit"}}, {"note": "plain water"})
    assert not _matches({"note": {"$contains": "grapefruit"}}, {})


# ── Top-level logic: $any (OR) / $all (AND) / $not ──────────────────────────

def test_any_or():
    cond = {"$any": [{"key": "iron"}, {"key": "ferrous_sulfate"}]}
    assert _matches(cond, {"key": "iron"})
    assert _matches(cond, {"key": "ferrous_sulfate"})
    assert not _matches(cond, {"key": "zinc"})


def test_all_and():
    cond = {"$all": [{"key": "iron"}, {"active": True}]}
    assert _matches(cond, {"key": "iron", "active": True})
    assert not _matches(cond, {"key": "iron", "active": False})


def test_not():
    cond = {"$not": {"active": True}}
    assert _matches(cond, {"key": "iron", "active": False})
    assert _matches(cond, {"key": "iron"})  # missing field -> not-active
    assert not _matches(cond, {"key": "iron", "active": True})


def test_logic_combined_with_plain_fields():
    # active must be True AND (key == iron OR key == ferrous_sulfate)
    cond = {"active": True, "$any": [{"key": "iron"}, {"key": "ferrous_sulfate"}]}
    assert _matches(cond, {"key": "iron", "active": True})
    assert not _matches(cond, {"key": "iron", "active": False})
    assert not _matches(cond, {"key": "zinc", "active": True})


def test_nested_any_of_all():
    cond = {
        "$any": [
            {"$all": [{"key": "iron"}, {"dose_mg": {"$gte": 45}}]},
            {"key": "vitamin_c", "dose_mg": {"$gte": 1000}},
        ]
    }
    assert _matches(cond, {"key": "iron", "dose_mg": 50})
    assert not _matches(cond, {"key": "iron", "dose_mg": 20})
    assert _matches(cond, {"key": "vitamin_c", "dose_mg": 1200})


# ── Resolver shapes (Phase 2) — DB-touching, default sqlite is fine here ────

async def test_glp1_resolve_active_empty_without_phase(db_session):
    from vitals.services import glp1_service

    assert await glp1_service.resolve_active(db_session) == []


async def test_glp1_resolve_active_shape(db_session):
    from vitals.services import glp1_service

    await glp1_service.add_dose_phase(
        db_session, start_date=today_local(), drug="semaglutide", dose_mg=1.0
    )
    await db_session.commit()
    items = await glp1_service.resolve_active(db_session)
    assert items == [{"drug": "semaglutide", "dose_mg": 1.0, "active": True}]


async def test_labs_resolve_latest_shape(db_session):
    await labs_service.add_result(
        db_session, on_date=today_local(), marker="Калий", value=5.5, ref_low=3.5, ref_high=5.1
    )
    await db_session.commit()
    items = await labs_service.resolve_latest(db_session)
    assert items == [{"marker": "Калий", "value": 5.5, "flag": "high"}]


async def test_nutrition_resolve_today_shape(db_session):
    from vitals.services import nutrition_service

    await nutrition_service.log_meal(db_session, on_date=today_local(), name="Test meal", calories=500, protein_g=40)
    await db_session.commit()
    items = await nutrition_service.resolve_today(db_session)
    assert items[0]["calories"] == 500
    assert items[0]["protein_g"] == 40


# ── Timing-separation slot gating (Phase 2.2), end to end via evaluate() ────

async def _seed_iron_zinc_timing_rule(db_session):
    db_session.add(
        ConflictRule(
            rule_type="timing_separation",
            domain_a="supplements", condition_a={"key": "iron", "active": True},
            domain_b="supplements", condition_b={"key": "zinc", "active": True},
            severity="warn",
            message="Железо и цинк конкурируют за всасывание — разнести на 2+ часа.",
            params={"hours": 2},
            active=True,
        )
    )
    await db_session.commit()


async def test_timing_separation_fires_when_same_slot(db_session):
    conflict_registrations.register_all_resolvers()
    await _seed_iron_zinc_timing_rule(db_session)
    await supplements_service.add_supplement(db_session, name="Iron", key="iron", timing="утро", active=True)
    await supplements_service.add_supplement(db_session, name="Zinc", key="zinc", timing="утро", active=True)
    await db_session.commit()

    violations = await conflict_engine.evaluate(db_session, "supplements")
    assert any(v.rule_type == "timing_separation" for v in violations)


async def test_timing_separation_silent_when_different_slot(db_session):
    conflict_registrations.register_all_resolvers()
    await _seed_iron_zinc_timing_rule(db_session)
    await supplements_service.add_supplement(db_session, name="Iron", key="iron", timing="утро", active=True)
    await supplements_service.add_supplement(db_session, name="Zinc", key="zinc", timing="вечер", active=True)
    await db_session.commit()

    violations = await conflict_engine.evaluate(db_session, "supplements")
    assert not any(v.rule_type == "timing_separation" for v in violations)


async def test_timing_separation_silent_when_slot_unknown(db_session):
    conflict_registrations.register_all_resolvers()
    await _seed_iron_zinc_timing_rule(db_session)
    await supplements_service.add_supplement(db_session, name="Iron", key="iron", active=True)  # no timing
    await supplements_service.add_supplement(db_session, name="Zinc", key="zinc", active=True)  # no timing
    await db_session.commit()

    violations = await conflict_engine.evaluate(db_session, "supplements")
    assert not any(v.rule_type == "timing_separation" for v in violations)


# ── Operator-based rule end to end: labs value threshold blocks a supplement ─

async def test_operator_rule_fires_on_lab_value_threshold(db_session):
    conflict_registrations.register_all_resolvers()
    db_session.add(
        ConflictRule(
            rule_type="hard_block",
            domain_a="supplements", condition_a={"key": "potassium", "active": True},
            domain_b="labs", condition_b={"marker": "Калий", "value": {"$gt": 5.0}},
            severity="block",
            message="Гиперкалиемия — препараты калия противопоказаны.",
            active=True,
        )
    )
    await labs_service.add_result(
        db_session, on_date=today_local(), marker="Калий", value=5.5, ref_low=3.5, ref_high=5.1
    )
    await db_session.commit()

    with pytest.raises(ConflictBlocked):
        await supplements_service.add_supplement(db_session, name="Potassium", key="potassium", active=True)


async def test_violation_carries_catalog_metadata(db_session):
    conflict_registrations.register_all_resolvers()
    db_session.add(
        ConflictRule(
            rule_type="hard_block",
            domain_a="supplements", condition_a={"key": "potassium", "active": True},
            domain_b="labs", condition_b={"marker": "Калий", "value": {"$gt": 5.0}},
            severity="block", message="test", category="lab_safety",
            source="NIH reference", evidence="A", active=True,
        )
    )
    await labs_service.add_result(
        db_session, on_date=today_local(), marker="Калий", value=5.5, ref_low=3.5, ref_high=5.1
    )
    await db_session.commit()

    violations = await conflict_engine.evaluate(db_session, "supplements", {"key": "potassium", "active": True})
    assert len(violations) == 1
    v = violations[0]
    assert v.category == "lab_safety"
    assert v.source == "NIH reference"
    assert v.evidence == "A"
    assert v.to_dict()["category"] == "lab_safety"


async def test_operator_rule_silent_when_lab_value_below_threshold(db_session):
    conflict_registrations.register_all_resolvers()
    db_session.add(
        ConflictRule(
            rule_type="hard_block",
            domain_a="supplements", condition_a={"key": "potassium", "active": True},
            domain_b="labs", condition_b={"marker": "Калий", "value": {"$gt": 5.0}},
            severity="block",
            message="Гиперкалиемия — препараты калия противопоказаны.",
            active=True,
        )
    )
    await labs_service.add_result(
        db_session, on_date=today_local(), marker="Калий", value=4.2, ref_low=3.5, ref_high=5.1
    )
    await db_session.commit()

    # Must not raise — value is in range, the $gt condition should not match.
    await supplements_service.add_supplement(db_session, name="Potassium", key="potassium", active=True)
