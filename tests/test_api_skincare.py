"""Tests for the Skincare API endpoints (/api/v1/skincare)."""
from __future__ import annotations

import pytest

from vitals.services import modules_service

URL = "/api/v1/skincare"


async def test_skincare_unauthenticated(client):
    r = await client.get(URL)
    assert r.status_code == 401


async def test_skincare_module_gated(auth_client, db_session, redis):
    # Disable skincare module
    state = await modules_service.set_module_enabled(db_session, key="skincare", enabled=False)
    await db_session.commit()
    await modules_service.prime_cache(redis, state)

    r = await auth_client.get(URL)
    assert r.status_code == 404
    data = r.json()
    assert data.get("error") == "module_disabled"

    # Re-enable
    state = await modules_service.set_module_enabled(db_session, key="skincare", enabled=True)
    await db_session.commit()
    await modules_service.prime_cache(redis, state)

    r = await auth_client.get(URL)
    assert r.status_code == 200


async def test_skincare_products_crud(auth_client):
    # 1. Create product
    payload = {
        "name": "Дифферин",
        "type": "Ретиноид",
        "activeIngredient": "Адапален 0.1%",
        "defaultTime": "evening",
        "scheduleDays": [1, 3, 5],
        "active": True,
        "description": "Топический ретиноид",
    }
    r = await auth_client.post(f"{URL}/products", json=payload)
    assert r.status_code == 201
    prod_id = r.json()["id"]

    # 2. View in /api/v1/skincare
    r = await auth_client.get(URL)
    assert r.status_code == 200
    data = r.json()
    assert data["activeCount"] == 1
    assert data["totalCount"] == 1
    assert len(data["products"]) == 1
    p = data["products"][0]
    assert p["name"] == "Дифферин"
    assert p["activeIngredient"] == "Адапален 0.1%"
    assert p["scheduleDays"] == [1, 3, 5]

    # 3. Patch product
    r = await auth_client.patch(f"{URL}/products/{prod_id}", json={"name": "Дифферин гель", "scheduleDays": [1, 2, 4]})
    assert r.status_code == 200
    assert r.json()["name"] == "Дифферин гель"
    assert r.json()["scheduleDays"] == [1, 2, 4]

    # 4. Delete product
    r = await auth_client.delete(f"{URL}/products/{prod_id}")
    assert r.status_code == 204

    r = await auth_client.get(URL)
    assert r.json()["totalCount"] == 0


async def test_skincare_logs_and_observations(auth_client):
    # 1. Log checklist for 2026-09-29
    log_payload = {
        "date": "2026-09-29",
        "retinoid": True,
        "moisturizer": True,
        "note": "Кожа спокойная",
    }
    r = await auth_client.post(f"{URL}/logs", json=log_payload)
    assert r.status_code == 200
    log_data = r.json()
    assert log_data["retinoid"] is True
    assert log_data["moisturizer"] is True
    log_id = log_data["id"]

    # 2. Add observation
    obs_payload = {
        "date": "2026-09-29",
        "inflammation": 2,
        "pih": 3,
        "zone": "подбородок",
        "note": "Одно небольшое воспаление",
    }
    r = await auth_client.post(f"{URL}/observations", json=obs_payload)
    assert r.status_code == 201
    obs_id = r.json()["id"]

    # 3. View in dashboard
    r = await auth_client.get(URL)
    assert r.status_code == 200
    data = r.json()
    assert len(data["logs"]) >= 1
    assert len(data["observations"]) >= 1

    # 4. Delete log and observation
    r = await auth_client.delete(f"{URL}/logs/{log_id}")
    assert r.status_code == 204

    r = await auth_client.delete(f"{URL}/observations/{obs_id}")
    assert r.status_code == 204
