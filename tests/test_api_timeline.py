"""Tests for the Timeline API endpoints (/api/v1/timeline)."""
from __future__ import annotations

import pytest

from vitals.services import modules_service

URL = "/api/v1/timeline"


async def test_timeline_unauthenticated(client):
    r = await client.get(URL)
    assert r.status_code == 401


async def test_timeline_module_gated(auth_client, db_session, redis):
    # Disable timeline module
    state = await modules_service.set_module_enabled(db_session, key="timeline", enabled=False)
    await db_session.commit()
    await modules_service.prime_cache(redis, state)

    r = await auth_client.get(URL)
    assert r.status_code == 404
    data = r.json()
    assert data.get("error") == "module_disabled"

    # Re-enable
    state = await modules_service.set_module_enabled(db_session, key="timeline", enabled=True)
    await db_session.commit()
    await modules_service.prime_cache(redis, state)

    r = await auth_client.get(URL)
    assert r.status_code == 200


async def test_timeline_annotation_crud(auth_client):
    # 1. Create annotation
    payload = {
        "title": "Поездка в горы",
        "date": "2026-09-29",
        "endDate": "2026-10-02",
        "kind": "travel",
        "domain": "timeline",
        "note": "Акклиматизация",
    }
    r = await auth_client.post(f"{URL}/annotations", json=payload)
    assert r.status_code == 201
    ann_id = r.json()["id"]

    # 2. View in timeline
    r = await auth_client.get(URL)
    assert r.status_code == 200
    data = r.json()
    assert data["manualCount"] >= 1
    found = next((e for e in data["events"] if e["id"] == ann_id), None)
    assert found is not None
    assert found["title"] == "Поездка в горы"
    assert found["kind"] == "travel"
    assert found["manual"] is True

    # 3. Patch annotation
    r = await auth_client.patch(
        f"{URL}/annotations/{ann_id}",
        json={"title": "Поездка на Кавказ", "note": "Высота 2000м"},
    )
    assert r.status_code == 200
    assert r.json()["title"] == "Поездка на Кавказ"
    assert r.json()["detail"] == "Высота 2000м"

    # 4. Filter by domain
    r = await auth_client.get(f"{URL}?domain=timeline")
    assert r.status_code == 200
    assert any(e["id"] == ann_id for e in r.json()["events"])

    # 5. Delete annotation
    r = await auth_client.delete(f"{URL}/annotations/{ann_id}")
    assert r.status_code == 204

    r = await auth_client.get(URL)
    assert not any(e["id"] == ann_id for e in r.json()["events"])
