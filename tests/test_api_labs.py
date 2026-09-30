"""Tests for the Labs API endpoints (/api/v1/labs)."""
from __future__ import annotations

import io
from datetime import date, timedelta
import pytest

from vitals.utils.timeutils import today_local

URL = "/api/v1/labs"


class FakeLLM:
    def __init__(self, payload: dict):
        self.payload = payload
        self.image_urls: list[str] = []

    async def extract_json(self, prompt, *, system=None, image_url=None, image_urls=None, **kw):
        if image_url:
            self.image_urls.append(image_url)
        if image_urls:
            self.image_urls.extend(image_urls)
        return self.payload


async def test_labs_unauthenticated(client):
    r = await client.get(URL)
    assert r.status_code == 401


async def test_labs_read_empty(auth_client):
    r = await auth_client.get(URL)
    assert r.status_code == 200
    data = r.json()
    assert "markers" in data
    assert data["markers"] == []
    assert "collectedIso" in data
    assert "lab" in data


async def test_labs_results_crud_and_markers(auth_client, db_session):
    today = today_local()

    # 1. Create a lab result manually
    create_payload = {
        "date": today.isoformat(),
        "marker": "TSH",
        "value": 5.5,
        "unit": "mIU/L",
        "refLow": 0.4,
        "refHigh": 4.0,
        "labName": "Invitro",
        "note": "Morning fasting",
    }
    r = await auth_client.post(f"{URL}/results", json=create_payload)
    assert r.status_code == 201
    result_id = r.json()["id"]

    # 2. Verify in /api/v1/labs
    r = await auth_client.get(URL)
    assert r.status_code == 200
    data = r.json()
    assert len(data["markers"]) == 1
    m = data["markers"][0]
    assert m["name"] == "TSH"
    assert m["value"] == 5.5
    assert m["unit"] == "mIU/L"
    assert len(m["history"]) == 1

    # 3. Read marker detail
    r = await auth_client.get(f"{URL}/markers/TSH")
    assert r.status_code == 200
    detail = r.json()
    assert detail["name"] == "TSH"
    assert len(detail["history"]) >= 1
    marker_db_id = detail["id"]

    # 4. Patch marker catalog entry
    patch_payload = {
        "category": "hormones",
        "tier": 1,
        "refLow": 0.5,
        "refHigh": 4.2,
        "note": "Thyroid stimulating hormone",
    }
    r = await auth_client.patch(f"{URL}/markers/{marker_db_id}", json=patch_payload)
    assert r.status_code == 200

    # 5. Defer marker retesting
    defer_date = today + timedelta(days=90)
    r = await auth_client.post(
        f"{URL}/markers/TSH/defer",
        json={"until": defer_date.isoformat(), "note": "Checked recently"},
    )
    assert r.status_code == 200

    # 6. Delete result
    r = await auth_client.delete(f"{URL}/results/{result_id}")
    assert r.status_code == 204

    # Verify empty after deletion
    r = await auth_client.get(URL)
    assert r.status_code == 200
    assert len(r.json()["markers"]) == 0


async def test_labs_upload_and_confirm(auth_client, monkeypatch):
    today = today_local()
    payload = {
        "date": today.isoformat(),
        "lab_name": "Synevo",
        "results": [
            {"marker": "Ferritin", "value": 95.0, "unit": "ng/mL", "ref_low": 30.0, "ref_high": 400.0},
            {"marker": "Vitamin D", "value": 45.0, "unit": "ng/mL", "ref_low": 30.0, "ref_high": 100.0},
        ],
    }

    monkeypatch.setattr("web.api.labs.LLMClient", lambda: FakeLLM(payload))

    # Test file upload
    fake_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    files = {"file": ("report.png", io.BytesIO(fake_png), "image/png")}

    r = await auth_client.post(f"{URL}/upload", files=files)
    assert r.status_code == 200
    up_data = r.json()
    assert up_data["ok"] is True
    lab_preview = up_data["lab"]
    assert lab_preview is not None
    assert len(lab_preview["markers"]) == 2
    assert lab_preview["labName"] == "Synevo"

    # Confirm extracted results
    confirm_payload = {
        "date": lab_preview["date"],
        "labName": lab_preview["labName"],
        "fileKey": lab_preview["fileKey"],
        "rawPayloadId": lab_preview["rawPayloadId"],
        "markers": lab_preview["markers"],
        "override": False,
    }
    r = await auth_client.post(f"{URL}/confirm", json=confirm_payload)
    assert r.status_code == 200
    c_data = r.json()
    assert c_data["ok"] is True
    assert c_data["created"] == 2

    # Verify they show on labs dashboard
    r = await auth_client.get(URL)
    assert r.status_code == 200
    names = {m["name"] for m in r.json()["markers"]}
    assert "Ferritin" in names
    assert "Vitamin D" in names


async def test_labs_screen_carries_the_marker_catalog(auth_client):
    today = today_local()
    r = await auth_client.post(f"{URL}/results", json={"date": today.isoformat(), "marker": "TSH", "value": 2.0})
    assert r.status_code == 201
    marker_id = (await auth_client.get(f"{URL}/markers/TSH")).json()["id"]
    r = await auth_client.patch(f"{URL}/markers/{marker_id}", json={"tier": 1, "retestIntervalDays": 180})
    assert r.status_code == 200
    until = today + timedelta(days=30)
    r = await auth_client.post(f"{URL}/markers/TSH/defer", json={"until": until.isoformat()})
    assert r.status_code == 200

    catalog = (await auth_client.get(URL)).json()["catalog"]
    entry = next(c for c in catalog if c["name"] == "TSH")
    assert entry == {"name": "TSH", "tier": 1, "retestIntervalDays": 180, "deferUntil": until.isoformat()}
