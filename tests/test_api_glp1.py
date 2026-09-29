"""Tests for /api/v1/glp1 endpoints."""
from datetime import date, timedelta

import pytest

from vitals.services import glp1_service, modules_service
from vitals.utils.timeutils import today_local

URL = "/api/v1/glp1"


async def _switch_off(db_session, redis, key: str):
    state = await modules_service.set_module_enabled(db_session, key=key, enabled=False)
    await db_session.commit()
    await modules_service.prime_cache(redis, state)


async def test_glp1_unauthenticated(client):
    r = await client.get(URL)
    assert r.status_code == 401
    assert r.json() == {"error": "unauthenticated"}


async def test_glp1_module_disabled(auth_client, db_session, redis):
    await _switch_off(db_session, redis, "glp1")
    r = await auth_client.get(URL)
    assert r.status_code == 404
    assert r.json() == {"error": "module_disabled"}


async def test_glp1_empty_screen(auth_client):
    r = await auth_client.get(URL)
    assert r.status_code == 200
    data = r.json()
    assert "drug" in data
    assert "doseMg" in data
    assert "cycle" in data
    assert "dosePhases" in data
    assert "trend" in data
    assert "siteLabels" in data
    assert "injections" in data
    assert "sideEffects" in data
    assert data["cycle"]["unscheduled"] is True


async def test_glp1_injections_crud(auth_client, db_session):
    today = today_local()
    # Log injection
    payload = {
        "date": today.isoformat(),
        "doseMg": 0.5,
        "drug": "Семаглутид",
        "site": "abdomen_left",
        "note": "First shot",
    }
    r = await auth_client.post(f"{URL}/injections", json=payload)
    assert r.status_code == 201
    inj_id = r.json()["id"]

    # Verify reflected in GET
    r = await auth_client.get(URL)
    assert r.status_code == 200
    data = r.json()
    assert len(data["injections"]) == 1
    assert data["injections"][0]["id"] == inj_id
    assert data["injections"][0]["doseMg"] == 0.5
    assert data["injections"][0]["site"] == "abdomen_left"
    assert data["cycle"]["unscheduled"] is False
    assert data["cycle"]["lastIso"] == today.isoformat()

    # Delete injection
    r = await auth_client.delete(f"{URL}/injections/{inj_id}")
    assert r.status_code == 204

    # Verify deleted
    r = await auth_client.get(URL)
    assert len(r.json()["injections"]) == 0

    # Delete non-existent
    r = await auth_client.delete(f"{URL}/injections/99999")
    assert r.status_code == 404


async def test_glp1_cycles_create_and_close(auth_client, db_session):
    today = today_local()
    # Create cycle
    payload = {
        "startDate": today.isoformat(),
        "drug": "Семаглутид",
        "doseMg": 0.25,
        "note": "Phase 1",
    }
    r = await auth_client.post(f"{URL}/cycles", json=payload)
    assert r.status_code == 201
    cycle_id = r.json()["id"]

    # Check screen
    r = await auth_client.get(URL)
    assert r.status_code == 200
    data = r.json()
    assert data["drug"] == "Семаглутид"
    assert data["doseMg"] == 0.25
    assert len(data["dosePhases"]) == 1

    # Close cycle
    close_payload = {
        "action": "close",
        "cycleId": cycle_id,
        "endDate": today.isoformat(),
    }
    r = await auth_client.post(f"{URL}/cycles", json=close_payload)
    assert r.status_code == 201
    assert r.json()["ok"] is True


async def test_glp1_side_effects(auth_client):
    today = today_local()
    payload = {
        "date": today.isoformat(),
        "effectType": "Тошнота",
        "severity": 2,
        "note": "Mild",
    }
    r = await auth_client.post(f"{URL}/side-effects", json=payload)
    assert r.status_code == 201
    se_id = r.json()["id"]

    r = await auth_client.get(URL)
    data = r.json()
    assert len(data["sideEffects"]) == 1
    assert data["sideEffects"][0]["name"] == "Тошнота"
    assert data["sideEffects"][0]["severity"] == 2

    # Delete
    r = await auth_client.delete(f"{URL}/side-effects/{se_id}")
    assert r.status_code == 204


async def test_glp1_injection_validation(auth_client):
    today = today_local()
    # Zero or negative dose
    r = await auth_client.post(
        f"{URL}/injections",
        json={"date": today.isoformat(), "doseMg": -1.0, "drug": "Семаглутид"},
    )
    assert r.status_code in (400, 422)

    # Unknown site
    r = await auth_client.post(
        f"{URL}/injections",
        json={"date": today.isoformat(), "doseMg": 0.5, "drug": "Семаглутид", "site": "forehead"},
    )
    assert r.status_code == 400
