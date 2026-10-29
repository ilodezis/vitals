"""Conflict alerts follow the catalog's real state, not the row being saved.

A rule fires on what is actually active; its alert is bound to the entities the
rule matched, kept to one row per rule, and resolved once the rule stops firing
(e.g. a supplement is switched off). A dry-run check only reports the rules the
proposed item itself takes part in.
"""
from __future__ import annotations

import pytest

from vitals.models.conflict_rule import ConflictRule
from vitals.models.system_alert import SystemAlert
from vitals.services import (
    alerts_service,
    conflict_engine,
    conflict_registrations,
    genetics_service,
    supplements_service,
)
from vitals.services.conflict_engine import ConflictBlocked


def _labs(*items):
    async def _resolver(_session):
        return [dict(i) for i in items]
    return _resolver


async def _seed_rules(db_session) -> dict[str, int]:
    cortisol = ConflictRule(
        rule_type="soft_warn",
        domain_a="labs", condition_a={"marker": "Кортизол", "value": {"$lt": 140}},
        domain_b="supplements", condition_b={"key": "ashwagandha", "active": True},
        severity="warn", message="cortisol low + ashwagandha", active=True,
    )
    zinc_mg = ConflictRule(
        rule_type="timing_separation",
        domain_a="supplements", condition_a={"key": "zinc", "active": True},
        domain_b="supplements", condition_b={"key": "magnesium", "active": True},
        severity="warn", message="zinc + magnesium same slot", params={"hours": 2}, active=True,
    )
    db_session.add_all([cortisol, zinc_mg])
    await db_session.flush()
    return {"cortisol": cortisol.id, "zinc_mg": zinc_mg.id}


async def _catalog(db_session):
    ids = {}
    for name, key in (("Ashwagandha", "ashwagandha"), ("Magnesium", "magnesium"),
                      ("Zinc", "zinc"), ("Maca", "maca")):
        row = await supplements_service.add_supplement(
            db_session, name=name, key=key, timing="утро", active=True
        )
        ids[key] = row.id
    await db_session.commit()
    return ids


async def _active_conflict_rows(db_session, rule_id: int) -> list[SystemAlert]:
    return [
        a for a in await alerts_service.list_active(db_session)
        if a.alert_key == f"conflict:{rule_id}"
    ]


@pytest.fixture
def low_cortisol():
    conflict_registrations.register_all_resolvers()
    conflict_engine.register_domain_resolver("labs", _labs({"marker": "Кортизол", "value": 100}))


async def test_alert_is_bound_to_the_rule_entities_not_the_saved_row(db_session, low_cortisol):
    rules = await _seed_rules(db_session)
    ids = await _catalog(db_session)

    # Saving an unrelated supplement must not hang the ashwagandha alert on it.
    await supplements_service.update_supplement(
        db_session, ids["maca"], name="Maca", key="maca", timing="утро", active=False
    )
    await db_session.commit()

    rows = await _active_conflict_rows(db_session, rules["cortisol"])
    assert [r.entity_ref for r in rows] == ["supplement:ashwagandha"]
    assert not any(a.entity_ref == "supplement:maca" for a in await alerts_service.list_active(db_session))


async def test_one_active_row_per_rule_whoever_was_saved(db_session, low_cortisol):
    rules = await _seed_rules(db_session)
    ids = await _catalog(db_session)

    for key in ("zinc", "maca", "magnesium"):
        await supplements_service.update_supplement(
            db_session, ids[key], name=key.title(), key=key, timing="утро", active=True
        )
    await db_session.commit()

    assert len(await _active_conflict_rows(db_session, rules["cortisol"])) == 1
    zinc_rows = await _active_conflict_rows(db_session, rules["zinc_mg"])
    assert [r.entity_ref for r in zinc_rows] == ["supplement:magnesium,supplement:zinc"]


async def test_switching_a_supplement_off_resolves_its_conflict(db_session, low_cortisol):
    rules = await _seed_rules(db_session)
    ids = await _catalog(db_session)
    assert len(await _active_conflict_rows(db_session, rules["zinc_mg"])) == 1

    await supplements_service.set_active(db_session, ids["zinc"], False)
    await db_session.commit()

    assert await _active_conflict_rows(db_session, rules["zinc_mg"]) == []
    # The unrelated, still-true rule stays.
    assert len(await _active_conflict_rows(db_session, rules["cortisol"])) == 1


async def test_switching_off_through_an_edit_resolves_too(db_session, low_cortisol):
    rules = await _seed_rules(db_session)
    ids = await _catalog(db_session)

    await supplements_service.update_supplement(
        db_session, ids["zinc"], name="Zinc", key="zinc", timing="утро", active=False
    )
    await db_session.commit()

    assert await _active_conflict_rows(db_session, rules["zinc_mg"]) == []


async def test_deleting_a_supplement_resolves_its_conflict(db_session, low_cortisol):
    rules = await _seed_rules(db_session)
    ids = await _catalog(db_session)

    await supplements_service.delete_supplement(db_session, ids["ashwagandha"])
    await db_session.commit()

    assert await _active_conflict_rows(db_session, rules["cortisol"]) == []


async def test_misattributed_rows_collapse_into_one_bound_row(db_session, low_cortisol):
    """Rows raised by the old engine on whatever was saved get merged into one
    row bound to the rule's entities on the next catalog write."""
    rules = await _seed_rules(db_session)
    ids = await _catalog(db_session)
    key = f"conflict:{rules['cortisol']}"
    for row in await _active_conflict_rows(db_session, rules["cortisol"]):
        row.resolved_at = row.created_at
    for ref in ("supplement:zinc", "supplement:maca"):
        await alerts_service.raise_alert(
            db_session, domain="supplements", severity="warn",
            message="cortisol low + ashwagandha", alert_key=key, entity_ref=ref,
        )
    await db_session.commit()

    await supplements_service.set_active(db_session, ids["maca"], False)
    await db_session.commit()

    rows = await _active_conflict_rows(db_session, rules["cortisol"])
    assert [r.entity_ref for r in rows] == ["supplement:ashwagandha"]


async def test_dismissed_rule_is_not_resurrected_by_an_unrelated_toggle(db_session, low_cortisol):
    rules = await _seed_rules(db_session)
    ids = await _catalog(db_session)
    for row in await _active_conflict_rows(db_session, rules["cortisol"]):
        await alerts_service.resolve_alert(db_session, row.id)
    await db_session.commit()

    await supplements_service.set_active(db_session, ids["maca"], False)
    await db_session.commit()

    assert await _active_conflict_rows(db_session, rules["cortisol"]) == []


async def test_dry_run_honours_key_and_active(db_session, low_cortisol):
    await _seed_rules(db_session)
    await _catalog(db_session)

    # The low-cortisol rule is true of the catalog, but zinc takes no part in it.
    assert await conflict_engine.evaluate(
        db_session, "supplements", {"key": "zinc", "active": False}
    ) == []

    on = await conflict_engine.evaluate(
        db_session, "supplements", {"key": "zinc", "active": True, "timing_slot": "AM"}
    )
    assert [v.message for v in on] == ["zinc + magnesium same slot"]
    assert on[0].entity_refs == ("supplement:magnesium", "supplement:zinc")

    # Without a proposed item the whole catalog is evaluated.
    state = await conflict_engine.evaluate(db_session, "supplements")
    assert sorted(v.message for v in state) == ["cortisol low + ashwagandha", "zinc + magnesium same slot"]


async def test_mcp_check_conflicts_honours_key_and_active(db_session, session_factory, monkeypatch, low_cortisol):
    mcp_router = pytest.importorskip("web.routers.mcp")
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    await _seed_rules(db_session)
    await _catalog(db_session)

    assert await mcp_router.check_conflicts("supplements", {"key": "zinc", "active": False}) == []
    assert await mcp_router.check_conflicts("supplements", {"key": "maca", "active": True}) == []


async def test_unrelated_save_is_not_blocked_by_an_overridden_block(db_session):
    conflict_registrations.register_all_resolvers()
    db_session.add(ConflictRule(
        rule_type="hard_block",
        domain_a="genetics", condition_a={"marker": "hemochromatosis_carrier"},
        domain_b="supplements", condition_b={"key": "iron", "active": True},
        severity="block", message="iron blocked", active=True,
    ))
    await genetics_service.add_variant(
        db_session, gene="HFE", rsid="rs1800562", marker="hemochromatosis_carrier"
    )
    await supplements_service.add_supplement(
        db_session, name="Iron", key="iron", active=True, override=True
    )
    await db_session.commit()

    # Adding something unrelated goes through; editing iron itself still blocks.
    await supplements_service.add_supplement(db_session, name="Glycine", key="glycine", active=True)
    await db_session.commit()
    iron = next(s for s in await supplements_service.list_supplements(db_session) if s.key == "iron")
    with pytest.raises(ConflictBlocked):
        await supplements_service.update_supplement(
            db_session, iron.id, name="Iron", key="iron", dose="50 mg", active=True
        )
    await db_session.rollback()


async def test_editing_a_row_replaces_its_old_state(db_session):
    """An edit is checked against the catalog *after* the edit: moving zinc to
    the evening clears the same-slot warning instead of re-firing on the old row."""
    conflict_registrations.register_all_resolvers()
    rules = await _seed_rules(db_session)
    ids = await _catalog(db_session)
    assert len(await _active_conflict_rows(db_session, rules["zinc_mg"])) == 1

    await supplements_service.update_supplement(
        db_session, ids["zinc"], name="Zinc", key="zinc", timing="вечер", active=True
    )
    await db_session.commit()

    assert await _active_conflict_rows(db_session, rules["zinc_mg"]) == []


async def test_lab_threshold_is_compared_in_the_rules_unit(db_session):
    """"Кортизол < 140" is nmol/l: 10 µg/dl (~276 nmol/l) is normal, 3 µg/dl is not."""
    from datetime import date
    from vitals.services import labs_service

    conflict_registrations.register_all_resolvers()
    rules = await _seed_rules(db_session)
    await supplements_service.add_supplement(db_session, name="Ashwagandha", key="ashwagandha", active=True)
    await labs_service.add_result(
        db_session, on_date=date(2026, 3, 1), marker="Кортизол", value=10, unit="мкг/дл",
        ref_low=3.5, ref_high=18.3,
    )
    await db_session.commit()
    assert await _active_conflict_rows(db_session, rules["cortisol"]) == []
    assert not [v for v in await conflict_engine.evaluate(db_session, "supplements")
                if v.rule_id == rules["cortisol"]]

    await labs_service.add_result(
        db_session, on_date=date(2026, 3, 2), marker="Кортизол", value=3.0, unit="мкг/дл",
        ref_low=3.5, ref_high=18.3,
    )
    await db_session.commit()
    assert len(await _active_conflict_rows(db_session, rules["cortisol"])) == 1

    # A normal result afterwards ends the conflict.
    await labs_service.add_result(
        db_session, on_date=date(2026, 3, 3), marker="Кортизол", value=300, unit="нмоль/л",
        ref_low=140, ref_high=600,
    )
    await db_session.commit()
    assert await _active_conflict_rows(db_session, rules["cortisol"]) == []


def test_rule_value_converts_or_refuses():
    from vitals.services import labs_service

    assert labs_service.rule_value("Кортизол", 10, "мкг/дл") == 275.9
    assert labs_service.rule_value("Кортизол", 300, "нмоль/л") == 300
    assert labs_service.rule_value("Кортизол", 300, None) == 300
    assert labs_service.rule_value("Кортизол", 10, "мг/л") is None, "unknown scale: no comparison"
    assert labs_service.rule_value("Калий", 5.5, "мэкв/л") == 5.5
