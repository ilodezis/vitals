"""Tests for the Interactions API endpoints (/api/v1/interactions)."""
from __future__ import annotations

import pytest

from vitals.models.conflict_rule import ConflictRule
from vitals.services import modules_service

URL = "/api/v1/interactions"


async def test_interactions_unauthenticated(client):
    r = await client.get(URL)
    assert r.status_code == 401


async def test_interactions_module_gated(auth_client, db_session, redis):
    # Disable interactions module
    state = await modules_service.set_module_enabled(db_session, key="interactions", enabled=False)
    await db_session.commit()
    await modules_service.prime_cache(redis, state)

    r = await auth_client.get(URL)
    assert r.status_code == 404
    data = r.json()
    assert data.get("error") == "module_disabled"

    # Re-enable
    state = await modules_service.set_module_enabled(db_session, key="interactions", enabled=True)
    await db_session.commit()
    await modules_service.prime_cache(redis, state)

    r = await auth_client.get(URL)
    assert r.status_code == 200


async def test_interactions_read_and_toggle(auth_client, db_session):
    # Ensure at least one rule exists
    rule = ConflictRule(
        code="test_iron_zinc",
        rule_type="timing_separation",
        domain_a="supplements",
        condition_a={"key": "iron"},
        domain_b="supplements",
        condition_b={"key": "zinc"},
        severity="warn",
        message="Разнесите приём железа и цинка",
        category="absorption",
        params={"hours": 2},
        active=True,
    )
    db_session.add(rule)
    await db_session.commit()
    await db_session.refresh(rule)

    # 1. Read interactions
    r = await auth_client.get(URL)
    assert r.status_code == 200
    data = r.json()
    assert data["totalCount"] >= 1
    assert "absorption" in data["byCategory"]
    found = next((x for x in data["rules"] if x["id"] == rule.id), None)
    assert found is not None
    assert found["code"] == "test_iron_zinc"
    assert found["hours"] == 2
    assert found["active"] is True

    # 2. Filter by domain
    r = await auth_client.get(f"{URL}?domain=supplements")
    assert r.status_code == 200
    assert any(x["id"] == rule.id for x in r.json()["rules"])

    # 3. Toggle off
    r = await auth_client.post(f"{URL}/{rule.id}/toggle", json={"active": False})
    assert r.status_code == 200
    assert r.json()["active"] is False

    # 4. Verify toggled
    r = await auth_client.get(URL)
    data = r.json()
    updated = next(x for x in data["rules"] if x["id"] == rule.id)
    assert updated["active"] is False
