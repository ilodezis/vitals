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


async def test_the_screen_lists_a_saved_template_with_its_share_payload(auth_client, db_session):
    """The screen has to survive a template existing: it lists each one with the
    compounds in it and the payload the copy button hands over."""
    import json

    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    r = await auth_client.post(
        f"{URL}/cycles", json={"kind": CycleKind.COURSE.value, "startDate": today_local().isoformat()}
    )
    cycle_id = r.json()["id"]
    await auth_client.post(
        f"{URL}/cycles/{cycle_id}/items",
        json={"compoundKey": "testosterone_cypionate", "dose": 100.0, "intervalDays": 7.0, "startWeek": 3},
    )
    r = await auth_client.post(f"{URL}/cycles/{cycle_id}/save-template", json={"name": "Standard"})
    tpl_id = r.json()["id"]

    r = await auth_client.get(URL)

    assert r.status_code == 200
    (tpl,) = r.json()["templates"]
    assert (tpl["id"], tpl["name"]) == (tpl_id, "Standard")
    assert len(tpl["items"]) == 1
    assert json.loads(tpl["exportJson"]) == (await auth_client.get(f"{URL}/templates/{tpl_id}/export")).json()

    # A shared payload comes back in as a template of its own; the very same one
    # pasted again is a mistake and is refused.
    shared = json.dumps({**json.loads(tpl["exportJson"]), "name": "From a friend"})
    r = await auth_client.post(f"{URL}/templates/import", json={"payload": shared})
    assert r.status_code == 201
    r = await auth_client.post(f"{URL}/templates/import", json={"payload": tpl["exportJson"]})
    assert r.status_code == 400
    assert len((await auth_client.get(URL)).json()["templates"]) == 2

    r = await auth_client.post(f"{URL}/templates/import", json={"payload": "not json"})
    assert r.status_code == 400
    assert r.json()["error"] == "invalid"


async def test_a_plan_item_says_whether_its_schedule_is_one_flat_dose(auth_client, db_session):
    """The edit form offers dose and interval only for a single flat segment: saving
    them over a ramp would replace the whole schedule."""
    from vitals.services import hrt_cycle_service

    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    today = today_local()
    r = await auth_client.post(
        f"{URL}/cycles", json={"kind": CycleKind.COURSE.value, "startDate": today.isoformat()}
    )
    cycle_id = r.json()["id"]
    await hrt_cycle_service.add_cycle_item(
        db_session, cycle_id, compound_key="testosterone_cypionate",
        schedule=[{"dose": 100.0, "interval_days": 7.0, "duration_days": 28}],
    )
    await hrt_cycle_service.add_cycle_item(
        db_session, cycle_id, compound_key="testosterone_enanthate",
        schedule=[
            {"dose": 100.0, "interval_days": 7.0, "duration_days": 28},
            {"dose": 150.0, "interval_days": 7.0},
        ],
    )
    await db_session.commit()

    items = (await auth_client.get(URL)).json()["cycle"]["items"]

    assert {it["compoundKey"]: it["flat"] for it in items} == {
        "testosterone_cypionate": True,
        "testosterone_enanthate": False,
    }


async def test_the_screen_carries_what_the_forms_choose_from(auth_client, db_session):
    """Units and cycle kinds come from the server, compounds carry their ester, a dose its vial,
    and a planned administration its dose as a number."""
    from vitals.enums import DoseUnit

    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    today = today_local()

    r = await auth_client.post(
        f"{URL}/doses",
        json={
            "date": today.isoformat(),
            "compoundKey": "testosterone_enanthate",
            "volumeMl": 0.5,
            "concentrationMgMl": 250.0,
            "lab": "Pharmacy",
            "batch": "B-12",
        },
    )
    assert r.status_code == 201
    r = await auth_client.post(f"{URL}/cycles", json={"kind": CycleKind.COURSE.value, "startDate": today.isoformat()})
    cycle_id = r.json()["id"]
    r = await auth_client.post(
        f"{URL}/cycles/{cycle_id}/items",
        json={"compoundKey": "testosterone_cypionate", "dose": 125.0, "intervalDays": 3.5, "startWeek": 1},
    )
    assert r.status_code == 201

    data = (await auth_client.get(URL)).json()
    assert data["units"] == [u.value for u in DoseUnit]
    assert data["cycleKinds"] == [k.value for k in CycleKind]
    enanthate = next(c for c in data["compounds"] if c["key"] == "testosterone_enanthate")
    assert enanthate["ester"]
    dose = data["doses"][0]
    assert dose["ml"] == 0.5
    assert dose["concMgMl"] == 250.0
    assert dose["doseVal"] == 125.0  # 0.5 ml × 250 mg/ml
    assert (dose["lab"], dose["batch"]) == ("Pharmacy", "B-12")
    assert data["planned"]
    first = data["planned"][0]
    assert first["compoundKey"] == "testosterone_cypionate"
    assert first["doseVal"] == 125.0
    assert first["unit"] == "mg"
    assert data["cycle"]["cadence"] > 0
