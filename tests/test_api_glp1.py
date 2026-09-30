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


# ── PATCH /api/v1/glp1/injections/{id} ────────────────────────────────────────


async def _injection(auth_client, **fields):
    payload = {
        "date": today_local().isoformat(), "doseMg": 0.5, "drug": "semaglutide",
        "site": "abdomen_left", "note": "First shot", **fields,
    }
    r = await auth_client.post(f"{URL}/injections", json=payload)
    assert r.status_code == 201
    return r.json()["id"]


async def _block_every_injection(db_session):
    from vitals.models.conflict_rule import ConflictRule

    db_session.add(
        ConflictRule(
            domain_a="glp1", domain_b="glp1", condition_a={}, condition_b={},
            rule_type="hard_block", severity="block", message="Simulated block", active=True,
        )
    )
    await db_session.commit()


async def test_the_new_glp1_writes_are_guarded(client):
    body = {"date": today_local().isoformat(), "doseMg": 0.5, "drug": "semaglutide"}
    r = await client.patch(f"{URL}/injections/1", json=body)
    assert r.status_code == 401
    r = await client.delete(f"{URL}/cycles/1")
    assert r.status_code == 401


async def test_an_injection_is_edited(auth_client):
    inj_id = await _injection(auth_client)
    yesterday = today_local() - timedelta(days=1)

    r = await auth_client.patch(
        f"{URL}/injections/{inj_id}",
        json={
            "date": yesterday.isoformat(), "doseMg": 1.0, "drug": "tirzepatide",
            "site": "thigh_right", "note": "Corrected",
        },
    )

    assert r.status_code == 200
    assert r.json() == {"id": inj_id}
    (inj,) = (await auth_client.get(URL)).json()["injections"]
    assert inj == {
        "id": inj_id, "dateIso": yesterday.isoformat(), "site": "thigh_right",
        "doseMg": 1.0, "drug": "tirzepatide", "note": "Corrected",
    }


async def test_editing_an_injection_that_is_not_there_is_a_404(auth_client):
    r = await auth_client.patch(
        f"{URL}/injections/9999",
        json={"date": today_local().isoformat(), "doseMg": 0.5, "drug": "semaglutide"},
    )
    assert r.status_code == 404
    assert r.json() == {"error": "not_found"}


async def test_an_invalid_injection_edit_is_a_400(auth_client):
    inj_id = await _injection(auth_client)
    body = {"date": today_local().isoformat(), "drug": "semaglutide"}

    for bad in ({"doseMg": -1.0}, {"doseMg": 0.5, "site": "forehead"}):
        r = await auth_client.patch(f"{URL}/injections/{inj_id}", json={**body, **bad})
        assert r.status_code == 400, bad
        assert r.json()["error"] == "invalid"

    (inj,) = (await auth_client.get(URL)).json()["injections"]
    assert inj["doseMg"] == 0.5


async def test_a_blocked_injection_edit_is_a_409_until_overridden(auth_client, db_session):
    inj_id = await _injection(auth_client)
    await _block_every_injection(db_session)
    body = {"date": today_local().isoformat(), "doseMg": 1.0, "drug": "semaglutide"}

    blocked = await auth_client.patch(f"{URL}/injections/{inj_id}", json=body)

    assert blocked.status_code == 409
    assert blocked.json()["error"] == "conflict"
    assert blocked.json()["violations"][0]["message"] == "Simulated block"
    (inj,) = (await auth_client.get(URL)).json()["injections"]
    assert inj["doseMg"] == 0.5

    kept = await auth_client.patch(f"{URL}/injections/{inj_id}", json={**body, "override": True})

    assert kept.status_code == 200
    (inj,) = (await auth_client.get(URL)).json()["injections"]
    assert inj["doseMg"] == 1.0


# ── DELETE /api/v1/glp1/cycles/{id} ───────────────────────────────────────────


async def test_a_dose_phase_is_deleted(auth_client):
    r = await auth_client.post(
        f"{URL}/cycles",
        json={"startDate": today_local().isoformat(), "drug": "semaglutide", "doseMg": 0.25},
    )
    phase_id = r.json()["id"]

    r = await auth_client.delete(f"{URL}/cycles/{phase_id}")

    assert r.status_code == 204
    assert (await auth_client.get(URL)).json()["dosePhases"] == []

    again = await auth_client.delete(f"{URL}/cycles/{phase_id}")
    assert again.status_code == 404
    assert again.json() == {"error": "not_found"}


async def test_the_screen_tells_the_running_phase_from_the_closed_ones(auth_client):
    """A closed phase and the running one both carry an end date on the chart; the
    list of phases has to know which of them can still be closed."""
    today = today_local()
    for start, dose in ((today - timedelta(days=30), 0.25), (today, 0.5)):
        r = await auth_client.post(
            f"{URL}/cycles", json={"startDate": start.isoformat(), "drug": "semaglutide", "doseMg": dose}
        )
        assert r.status_code == 201

    phases = (await auth_client.get(URL)).json()["dosePhases"]

    assert [(p["doseMg"], p["open"]) for p in phases] == [(0.25, False), (0.5, True)]
