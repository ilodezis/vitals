"""Tests for /api/v1/hrt endpoints."""
from datetime import date, timedelta

import pytest

from vitals.enums import CycleKind
from vitals.services import hrt_catalog, modules_service
from vitals.utils.timeutils import today_local

URL = "/api/v1/hrt"


async def _switch_off(db_session, redis, key: str):
    state = await modules_service.set_module_enabled(db_session, key=key, enabled=False)
    await db_session.commit()
    await modules_service.prime_cache(redis, state)


async def test_hrt_unauthenticated(client):
    r = await client.get(URL)
    assert r.status_code == 401
    assert r.json() == {"error": "unauthenticated"}


async def test_hrt_module_disabled(auth_client, db_session, redis):
    await _switch_off(db_session, redis, "hrt")
    r = await auth_client.get(URL)
    assert r.status_code == 404
    assert r.json() == {"error": "module_disabled"}


async def test_hrt_empty_screen(auth_client, db_session):
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()

    r = await auth_client.get(URL)
    assert r.status_code == 200
    data = r.json()
    assert "cycle" in data
    assert "doses" in data
    assert "sideEffects" in data
    assert "templates" in data
    assert "planned" in data
    assert "release" in data
    assert "compounds" in data
    assert data["cycle"] is None
    assert len(data["compounds"]) > 0


async def test_hrt_doses_crud(auth_client, db_session):
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    today = today_local()

    # Log dose
    payload = {
        "date": today.isoformat(),
        "compoundKey": "testosterone_enanthate",
        "dose": 250.0,
        "unit": "mg",
        "volumeMl": 1.0,
        "site": "glute_left",
        "brand": "Galenika",
        "note": "Smooth shot",
    }
    r = await auth_client.post(f"{URL}/doses", json=payload)
    assert r.status_code == 201
    dose_id = r.json()["id"]

    # Verify reflected in GET
    r = await auth_client.get(URL)
    assert r.status_code == 200
    data = r.json()
    assert len(data["doses"]) == 1
    assert data["doses"][0]["id"] == dose_id
    assert data["doses"][0]["compoundKey"] == "testosterone_enanthate"
    assert data["doses"][0]["site"] == "glute_left"
    assert data["siteCounts"]["glute_left"] == 1
    assert data["last"]["date"] == today.isoformat()

    # Patch dose
    patch_payload = {
        "dose": 200.0,
        "note": "Adjusted",
    }
    r = await auth_client.patch(f"{URL}/doses/{dose_id}", json=patch_payload)
    assert r.status_code == 200

    r = await auth_client.get(URL)
    assert r.json()["doses"][0]["doseVal"] == 200.0

    # Delete dose
    r = await auth_client.delete(f"{URL}/doses/{dose_id}")
    assert r.status_code == 204

    r = await auth_client.get(URL)
    assert len(r.json()["doses"]) == 0


async def test_hrt_cycles_and_items_lifecycle(auth_client, db_session):
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    today = today_local()

    # Create cycle
    c_payload = {
        "kind": CycleKind.COURSE.value,
        "startDate": today.isoformat(),
        "name": "TRT 2026",
        "endDate": (today + timedelta(days=84)).isoformat(),
        "note": "12-week test",
    }
    r = await auth_client.post(f"{URL}/cycles", json=c_payload)
    assert r.status_code == 201
    cycle_id = r.json()["id"]

    # Add cycle item
    item_payload = {
        "compoundKey": "testosterone_cypionate",
        "dose": 125.0,
        "intervalDays": 3.5,
        "startWeek": 1,
        "unit": "mg",
    }
    r = await auth_client.post(f"{URL}/cycles/{cycle_id}/items", json=item_payload)
    assert r.status_code == 201
    item_id = r.json()["id"]

    # Verify active cycle on screen
    r = await auth_client.get(URL)
    assert r.status_code == 200
    data = r.json()
    assert data["cycle"] is not None
    assert data["cycle"]["id"] == cycle_id
    assert data["cycle"]["name"] == "TRT 2026"
    assert len(data["cycle"]["items"]) == 1
    assert data["cycle"]["items"][0]["id"] == item_id

    # Edit item
    r = await auth_client.patch(f"{URL}/cycle-items/{item_id}", json={"dose": 150.0, "intervalDays": 3.5})
    assert r.status_code == 200

    # Close cycle
    r = await auth_client.post(f"{URL}/cycles/{cycle_id}/close", json={"endDate": today.isoformat()})
    assert r.status_code == 200

    # Delete item and cycle
    r = await auth_client.delete(f"{URL}/cycle-items/{item_id}")
    assert r.status_code == 204

    r = await auth_client.delete(f"{URL}/cycles/{cycle_id}")
    assert r.status_code == 204


async def test_hrt_templates(auth_client, db_session):
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    today = today_local()

    # Create a cycle first to template
    c_payload = {
        "kind": CycleKind.COURSE.value,
        "startDate": today.isoformat(),
        "name": "Template Source",
    }
    r = await auth_client.post(f"{URL}/cycles", json=c_payload)
    cycle_id = r.json()["id"]

    # Add an item to the cycle so it can be saved as template
    item_payload = {
        "compoundKey": "testosterone_cypionate",
        "dose": 100.0,
        "intervalDays": 7.0,
        "startWeek": 1,
        "unit": "mg",
    }
    r = await auth_client.post(f"{URL}/cycles/{cycle_id}/items", json=item_payload)
    assert r.status_code == 201

    # Save as template
    r = await auth_client.post(f"{URL}/cycles/{cycle_id}/save-template", json={"name": "My Standard TRT"})
    assert r.status_code == 201
    tpl_id = r.json()["id"]

    # Export template
    r = await auth_client.get(f"{URL}/templates/{tpl_id}/export")
    assert r.status_code == 200
    export_data = r.json()
    assert export_data["name"] == "My Standard TRT"

    # Delete template
    r = await auth_client.delete(f"{URL}/templates/{tpl_id}")
    assert r.status_code == 204


async def test_hrt_release_curve(auth_client):
    r = await auth_client.get(f"{URL}/release?days_back=10&days_forward=20")
    assert r.status_code == 200
    data = r.json()
    assert "series" in data
    assert "today" in data
    assert len(data["series"]) == 31  # 10 back + today + 20 forward
