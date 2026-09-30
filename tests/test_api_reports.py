"""Tests for the Reports API endpoints (/api/v1/reports)."""
from __future__ import annotations

import pytest

URL = "/api/v1/reports"


async def test_reports_unauthenticated(client):
    r = await client.get(URL)
    assert r.status_code == 401


async def test_reports_read(auth_client):
    r = await auth_client.get(URL)
    assert r.status_code == 200
    data = r.json()
    assert "activeGoals" in data
    assert "closedGoals" in data
    assert "goalDomains" in data
    assert data["today"] is not None


async def test_reports_milestone_crud(auth_client):
    # 1. Create milestone
    payload = {
        "name": "Дойти до 82 кг",
        "domain": "weight",
        "targetValue": 82.0,
        "targetUnit": "кг",
        "deadline": "2026-12-31",
        "note": "К концу года",
    }
    r = await auth_client.post(f"{URL}/milestones", json=payload)
    assert r.status_code == 201
    m_id = r.json()["id"]

    # 2. View in reports
    r = await auth_client.get(URL)
    assert r.status_code == 200
    data = r.json()
    assert data["activeGoalsCount"] >= 1
    found = next((g for g in data["activeGoals"] if g["id"] == m_id), None)
    assert found is not None
    assert found["name"] == "Дойти до 82 кг"
    assert found["status"] == "active"

    # 3. Update status to achieved
    r = await auth_client.patch(
        f"{URL}/milestones/{m_id}/status", json={"status": "achieved"}
    )
    assert r.status_code == 200
    assert r.json()["status"] == "achieved"

    # 4. View in closed goals
    r = await auth_client.get(URL)
    data = r.json()
    assert any(g["id"] == m_id for g in data["closedGoals"])

    # 5. Delete milestone
    r = await auth_client.delete(f"{URL}/milestones/{m_id}")
    assert r.status_code == 204

    r = await auth_client.get(URL)
    data = r.json()
    assert not any(g["id"] == m_id for g in data["closedGoals"])


async def test_a_digest_without_an_llm_key_says_so_instead_of_failing(auth_client, monkeypatch):
    monkeypatch.delenv("VITALS_OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("VITALS_ENV_FILE", "/nonexistent/.env")
    r = await auth_client.post("/api/v1/reports/digests", json={"periodDays": 7})
    assert r.status_code == 400
    assert r.json()["error"] == "invalid"
    assert "VITALS_OPENROUTER_API_KEY" in r.json()["message"]
