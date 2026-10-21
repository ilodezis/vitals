"""``/api/v1/skincare`` — the day's ticks, the face photo diary, the product flag."""
from __future__ import annotations

import os

from vitals.models.conflict_rule import ConflictRule
from vitals.utils.timeutils import today_local

URL = "/api/v1/skincare"

FAKE_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
)


def _today_dow() -> int:
    return (today_local().weekday() + 1) % 7


async def _create(auth_client, name, *, flag=None, time="evening"):
    body = {
        "name": name,
        "type": "test",
        "defaultTime": time,
        "scheduleDays": [_today_dow()],
        "active": True,
    }
    if flag is not None:
        body["activeFlag"] = flag
    r = await auth_client.post(f"{URL}/products", json=body)
    assert r.status_code == 201
    return r.json()["id"]


async def test_the_view_carries_todays_plan(auth_client):
    pid = await _create(auth_client, "Дифферин", flag="retinoid")
    view = (await auth_client.get(URL)).json()

    assert view["plan"]["evening"] == [
        {
            "productId": pid,
            "name": "Дифферин",
            "flag": "retinoid",
            "planned": True,
            "done": False,
            "doneAt": None,
        }
    ]
    assert view["plan"]["morning"] == []
    assert "retinoid" in view["flags"]
    assert view["history"] == []
    assert view["photos"] == []


async def test_tick_and_untick(auth_client):
    pid = await _create(auth_client, "Крем", flag="moisturizer")
    today = today_local().isoformat()

    r = await auth_client.post(
        f"{URL}/checks", json={"date": today, "slot": "evening", "productId": pid, "done": True}
    )
    assert r.status_code == 200
    assert r.json()["evening"][0]["done"] is True
    view = (await auth_client.get(URL)).json()
    assert view["todayLog"]["moisturizer"] is True

    r = await auth_client.post(
        f"{URL}/checks", json={"date": today, "slot": "evening", "productId": pid, "done": False}
    )
    assert r.json()["evening"][0]["done"] is False


async def test_whole_slot_tick(auth_client):
    await _create(auth_client, "A")
    await _create(auth_client, "B")
    today = today_local().isoformat()
    r = await auth_client.post(f"{URL}/checks", json={"date": today, "slot": "evening"})
    assert r.status_code == 200
    assert all(i["done"] for i in r.json()["evening"])


async def test_conflict_answers_409_and_override_saves(auth_client, db_session):
    db_session.add(
        ConflictRule(
            rule_type="hard_block",
            domain_a="skincare",
            condition_a={"retinoid": True},
            domain_b="skincare",
            condition_b={"peel": True},
            severity="block",
            message="Ретиноид и пилинг в один вечер.",
            active=True,
        )
    )
    await db_session.commit()
    ret = await _create(auth_client, "Дифферин", flag="retinoid")
    peel = await _create(auth_client, "Пилинг", flag="peel")
    today = today_local().isoformat()
    tick = {"date": today, "slot": "evening", "done": True}

    assert (await auth_client.post(f"{URL}/checks", json={**tick, "productId": ret})).status_code == 200
    r = await auth_client.post(f"{URL}/checks", json={**tick, "productId": peel})
    assert r.status_code == 409
    assert r.json()["error"] == "conflict"

    r = await auth_client.post(f"{URL}/checks", json={**tick, "productId": peel, "override": True})
    assert r.status_code == 200
    assert all(i["done"] for i in r.json()["evening"])


async def test_bad_slot_and_unknown_product(auth_client):
    today = today_local().isoformat()
    r = await auth_client.post(f"{URL}/checks", json={"date": today, "slot": "noon", "productId": 1})
    assert r.status_code == 400
    r = await auth_client.post(f"{URL}/checks", json={"date": today, "slot": "evening", "productId": 999})
    assert r.status_code == 404


async def test_patch_keeps_the_flag_unless_it_is_sent(auth_client):
    pid = await _create(auth_client, "Дифферин", flag="retinoid")

    r = await auth_client.patch(f"{URL}/products/{pid}", json={"name": "Дифферин 0.1"})
    assert r.json()["activeFlag"] == "retinoid"

    r = await auth_client.patch(f"{URL}/products/{pid}", json={"activeFlag": None})
    assert r.json()["activeFlag"] is None

    # Not a flag the rules know → stored as none rather than as a key nothing reads.
    r = await auth_client.patch(f"{URL}/products/{pid}", json={"activeFlag": "glitter"})
    assert r.json()["activeFlag"] is None


async def test_photos_upload_list_and_delete(auth_client, monkeypatch, tmp_path):
    from web.api import skincare as skincare_api

    monkeypatch.setattr(skincare_api, "STATIC_DIR", str(tmp_path))
    today = today_local().isoformat()
    files = [
        ("files", ("a.png", FAKE_PNG, "image/png")),
        ("files", ("b.jpg", FAKE_PNG, "image/jpeg")),
    ]
    r = await auth_client.post(f"{URL}/photos", data={"date": today, "note": " утро "}, files=files)
    assert r.status_code == 201
    items = r.json()
    assert len(items) == 2 and items[0]["note"] == "утро"
    stored = tmp_path / items[0]["url"].removeprefix("/static/")
    assert stored.exists()

    view = (await auth_client.get(URL)).json()
    assert {p["id"] for p in view["photos"]} == {i["id"] for i in items}

    assert (await auth_client.delete(f"{URL}/photos/{items[0]['id']}")).status_code == 204
    assert not os.path.exists(stored)
    assert (await auth_client.delete(f"{URL}/photos/{items[0]['id']}")).status_code == 404


async def test_photos_refuse_non_images_and_too_many(auth_client, monkeypatch, tmp_path):
    from web.api import skincare as skincare_api

    monkeypatch.setattr(skincare_api, "STATIC_DIR", str(tmp_path))
    today = today_local().isoformat()
    r = await auth_client.post(
        f"{URL}/photos", data={"date": today}, files=[("files", ("x.html", b"<script>", "text/html"))]
    )
    assert r.status_code == 415
    six = [("files", (f"{i}.png", FAKE_PNG, "image/png")) for i in range(6)]
    r = await auth_client.post(f"{URL}/photos", data={"date": today}, files=six)
    assert r.status_code == 400
