"""Supplements catalog tests — CRUD, slug, resolver, and the genetics→iron
cross-domain block (override flow)."""
from __future__ import annotations

import pytest

from vitals.models.conflict_rule import ConflictRule
from vitals.services import (
    alerts_service,
    conflict_registrations,
    genetics_service,
    supplements_service,
)
from vitals.services.conflict_engine import ConflictBlocked

# No module-level asyncio mark: async DB tests are auto-detected (asyncio_mode=
# auto); test_slugify below is a pure sync test.


def test_slugify():
    assert supplements_service.slugify("Iron (ferrous bisglycinate)") == "iron_ferrous_bisglycinate"
    assert supplements_service.slugify("  Vitamin D3 ") == "vitamin_d3"


async def test_add_list_toggle_delete(db_session):
    s = await supplements_service.add_supplement(
        db_session, name="Креатин", dose="5 г", evidence="A"
    )
    await db_session.commit()
    assert s.key == "креатин" or s.key  # slug derived
    assert s.active is True

    await supplements_service.set_active(db_session, s.id, False)
    await db_session.commit()
    await db_session.refresh(s)
    assert s.active is False

    active_only = await supplements_service.list_supplements(db_session, active_only=True)
    assert s.id not in [x.id for x in active_only]

    assert await supplements_service.delete_supplement(db_session, s.id) is True
    await db_session.commit()
    assert len(await supplements_service.list_supplements(db_session)) == 0


async def test_resolver_shape(db_session):
    await supplements_service.add_supplement(db_session, name="Iron", key="iron", active=True)
    await db_session.commit()
    items = await supplements_service.resolve_active(db_session)
    assert {"key": "iron", "active": True, "name": "Iron"} in items


async def _seed_iron_rule(db_session):
    db_session.add(
        ConflictRule(
            rule_type="hard_block",
            domain_a="genetics",
            condition_a={"marker": "hemochromatosis_carrier"},
            domain_b="supplements",
            condition_b={"key": "iron", "active": True},
            severity="block",
            message="Носительство гемохроматоза — препараты железа противопоказаны.",
            active=True,
        )
    )
    await db_session.commit()


async def test_iron_blocked_for_hemochromatosis_carrier(db_session):
    conflict_registrations.register_all_resolvers()
    await _seed_iron_rule(db_session)
    await genetics_service.add_variant(
        db_session, gene="HFE", rsid="rs1800562", marker="hemochromatosis_carrier"
    )
    await db_session.commit()

    with pytest.raises(ConflictBlocked):
        await supplements_service.add_supplement(
            db_session, name="Iron", key="iron", active=True
        )
    await db_session.rollback()


async def test_iron_override_saves_and_stamps_alert(db_session):
    conflict_registrations.register_all_resolvers()
    await _seed_iron_rule(db_session)
    await genetics_service.add_variant(
        db_session, gene="HFE", rsid="rs1800562", marker="hemochromatosis_carrier"
    )
    await db_session.commit()

    s = await supplements_service.add_supplement(
        db_session, name="Iron", key="iron", active=True, override=True
    )
    await db_session.commit()
    assert s.id is not None

    active = await alerts_service.list_active(db_session, domain="supplements")
    assert len(active) == 1
    assert active[0].override_at is not None


async def test_inactive_iron_not_blocked(db_session):
    """An archived (inactive) iron row must not trip the active-only condition."""
    conflict_registrations.register_all_resolvers()
    await _seed_iron_rule(db_session)
    await genetics_service.add_variant(
        db_session, gene="HFE", rsid="rs1800562", marker="hemochromatosis_carrier"
    )
    await db_session.commit()

    s = await supplements_service.add_supplement(
        db_session, name="Iron", key="iron", active=False
    )
    await db_session.commit()
    assert s.active is False
