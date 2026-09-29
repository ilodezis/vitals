"""Tests for Doctor Reports API endpoints (/api/v1/share)."""
from __future__ import annotations

import pytest

URL = "/api/v1/share"


async def test_share_unauthenticated(client):
    r = await client.get(URL)
    assert r.status_code == 401


async def test_share_read(auth_client):
    r = await auth_client.get(URL)
    assert r.status_code == 200
    data = r.json()
    assert "reports" in data
    assert "availableDomains" in data
    assert "presets" in data
    assert "periodChoices" in data


async def test_share_create_revoke_delete(auth_client):
    # 1. Create a share report
    payload = {
        "title": "Отчёт для эндокринолога",
        "domains": ["weight", "labs"],
        "period": "90",
        "expiresDays": 14,
        "note": "Показатели за 3 месяца",
        "labsFlaggedOnly": False,
    }
    r = await auth_client.post(URL, json=payload)
    assert r.status_code == 201
    created = r.json()
    assert "id" in created
    assert "token" in created
    assert "password" in created
    assert len(created["password"]) >= 8
    report_id = created["id"]

    # 2. Verify it shows in share list
    r = await auth_client.get(URL)
    assert r.status_code == 200
    data = r.json()
    found = next((rep for rep in data["reports"] if rep["id"] == report_id), None)
    assert found is not None
    assert found["title"] == "Отчёт для эндокринолога"
    assert found["state"] == "live"

    # 3. Revoke report
    r = await auth_client.post(f"{URL}/{report_id}/revoke")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # Check revoked status
    r = await auth_client.get(URL)
    data = r.json()
    found = next((rep for rep in data["reports"] if rep["id"] == report_id), None)
    assert found is not None
    assert found["state"] == "revoked"

    # 4. Delete report
    r = await auth_client.delete(f"{URL}/{report_id}")
    assert r.status_code == 204

    # Verify gone
    r = await auth_client.get(URL)
    data = r.json()
    assert not any(rep["id"] == report_id for rep in data["reports"])
