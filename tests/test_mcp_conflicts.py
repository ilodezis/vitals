"""MCP conflict-engine tools — check_supplement_conflicts (fixed name->key
normalization), list_conflict_rules, check_conflicts. Skipped where FastMCP
can't import, same constraint as the other MCP tool tests."""
from __future__ import annotations

import pytest

from vitals.models.conflict_rule import ConflictRule
from vitals.services import conflict_registrations, genetics_service

mcp_router = pytest.importorskip("web.routers.mcp")


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


async def test_check_supplement_conflicts_normalizes_cyrillic_name(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    conflict_registrations.register_all_resolvers()
    await _seed_iron_rule(db_session)
    await genetics_service.add_variant(
        db_session, gene="HFE", rsid="rs1800562", marker="hemochromatosis_carrier"
    )
    await db_session.commit()

    violations = await mcp_router.check_supplement_conflicts("Железо")
    assert len(violations) == 1
    assert violations[0]["severity"] == "block"


async def test_check_supplement_conflicts_no_match_when_safe(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    conflict_registrations.register_all_resolvers()
    await _seed_iron_rule(db_session)
    await db_session.commit()  # no hemochromatosis marker on file

    assert await mcp_router.check_supplement_conflicts("Железо") == []


async def test_list_conflict_rules_filters_by_domain_and_category(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    from vitals.services import conflict_catalog

    await conflict_catalog.sync_catalog(db_session)
    await db_session.commit()

    genetics_rules = await mcp_router.list_conflict_rules(domain="genetics")
    assert len(genetics_rules) > 0
    assert all(r["domain_a"] == "genetics" or r["domain_b"] == "genetics" for r in genetics_rules)

    derm_rules = await mcp_router.list_conflict_rules(category="dermatology")
    assert len(derm_rules) > 0
    assert all(r["category"] == "dermatology" for r in derm_rules)


async def test_check_conflicts_generic_domain_payload(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    conflict_registrations.register_all_resolvers()
    from vitals.services import supplements_service

    db_session.add(
        ConflictRule(
            rule_type="hard_block",
            domain_a="supplements", condition_a={"key": "potassium", "active": True},
            domain_b="labs", condition_b={"marker": "Калий", "value": {"$gt": 5.0}},
            severity="block", message="Гиперкалиемия.", active=True,
        )
    )
    await supplements_service.add_supplement(db_session, name="Potassium", key="potassium", active=True)
    await db_session.commit()

    violations = await mcp_router.check_conflicts("labs", {"marker": "Калий", "value": 5.5})
    assert len(violations) == 1


async def test_check_conflicts_unknown_domain_returns_error(session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    result = await mcp_router.check_conflicts("not_a_real_domain", {})
    assert result == [{"error": result[0]["error"]}]
    assert "Unknown domain" in result[0]["error"]
