"""Tests for the Charts API endpoints (/api/v1/charts)."""
from __future__ import annotations

import pytest

URL = "/api/v1/charts"


async def test_charts_unauthenticated(client):
    r = await client.get(URL)
    assert r.status_code == 401


async def test_charts_read_and_crud(auth_client):
    # 1. Read empty
    r = await auth_client.get(URL)
    assert r.status_code == 200
    data = r.json()
    assert "charts" in data
    assert "catalog" in data
    assert "weight" in data["catalog"]

    # 2. Create chart
    payload = {
        "name": "Вес и шаги",
        "normalize": False,
        "series": [
            {
                "domain": "weight",
                "metricKey": "weight.weight_kg",
            }
        ],
    }
    r = await auth_client.post(URL, json=payload)
    assert r.status_code == 201
    chart_id = r.json()["id"]

    # 3. Read back
    r = await auth_client.get(URL)
    assert r.status_code == 200
    data = r.json()
    assert data["empty"] is False
    found = next((c for c in data["charts"] if c["id"] == chart_id), None)
    assert found is not None
    assert found["name"] == "Вес и шаги"
    assert len(found["series"]) == 1

    # 4. Delete chart
    r = await auth_client.delete(f"{URL}/{chart_id}")
    assert r.status_code == 204

    r = await auth_client.get(URL)
    assert not any(c["id"] == chart_id for c in r.json()["charts"])
