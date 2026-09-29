"""Tests for the Supplements API endpoints (/api/v1/supplements)."""
from __future__ import annotations

import pytest

from vitals.services import modules_service

URL = "/api/v1/supplements"


async def test_supplements_unauthenticated(client):
    r = await client.get(URL)
    assert r.status_code == 401


async def test_supplements_module_gated(auth_client, db_session, redis):
    # Disable supplements module
    state = await modules_service.set_module_enabled(db_session, key="supplements", enabled=False)
    await db_session.commit()
    await modules_service.prime_cache(redis, state)

    r = await auth_client.get(URL)
    assert r.status_code == 404
    data = r.json()
    assert data.get("error") == "module_disabled"

    # Re-enable
    state = await modules_service.set_module_enabled(db_session, key="supplements", enabled=True)
    await db_session.commit()
    await modules_service.prime_cache(redis, state)

    r = await auth_client.get(URL)
    assert r.status_code == 200


async def test_supplements_crud(auth_client):
    # 1. Create supplement
    payload = {
        "name": "Креатин моногидрат",
        "dose": "5 г",
        "timing": "Утро",
        "evidence": "A",
        "active": True,
        "note": "С первым приёмом пищи",
    }
    r = await auth_client.post(URL, json=payload)
    assert r.status_code == 201
    supp_id = r.json()["id"]

    # 2. View in /api/v1/supplements
    r = await auth_client.get(URL)
    assert r.status_code == 200
    data = r.json()
    assert data["activeCount"] == 1
    assert data["totalCount"] == 1
    # Check that it's in morning group
    morning_group = next(g for g in data["groups"] if g["key"] == "morning")
    assert len(morning_group["items"]) == 1
    assert morning_group["items"][0]["name"] == "Креатин моногидрат"
    assert morning_group["items"][0]["evidence"] == "A"

    # 3. Patch supplement
    r = await auth_client.patch(f"{URL}/{supp_id}", json={"dose": "10 г", "timing": "День"})
    assert r.status_code == 200
    updated = r.json()
    assert updated["dose"] == "10 г"
    assert updated["timing"] == "День"

    # 4. Toggle active -> false (archive)
    r = await auth_client.post(f"{URL}/{supp_id}/toggle", json={"active": False})
    assert r.status_code == 200
    assert r.json()["active"] is False

    r = await auth_client.get(URL)
    data = r.json()
    assert data["activeCount"] == 0
    assert len(data["archived"]) == 1
    assert data["archived"][0]["id"] == supp_id

    # 5. Delete
    r = await auth_client.delete(f"{URL}/{supp_id}")
    assert r.status_code == 204

    r = await auth_client.get(URL)
    data = r.json()
    assert data["totalCount"] == 0
    assert len(data["archived"]) == 0
