"""Tests for ``/api/v1/weight`` — dashboard, measurements, noise markers, photos,
scans, and Garmin export.
"""
import datetime as dt
from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest

from vitals.enums import Source
from vitals.models.body_scan import BodyScan, BodyScanMetric
from vitals.models.weight import DOMAIN as WEIGHT_DOMAIN, WeightLog
from vitals.services import body_scan_service, modules_service, weight_service
from vitals.utils.timeutils import today_local

WEIGHT = "/api/v1/weight"
MEASURES = "/api/v1/weight/measures"


async def _set_module(db_session, redis, key: str, enabled: bool):
    state = await modules_service.set_module_enabled(db_session, key=key, enabled=enabled)
    await db_session.commit()
    await modules_service.prime_cache(redis, state)


async def test_weight_dashboard_guarded(client):
    r = await client.get(WEIGHT)
    assert r.status_code == 401
    assert r.json() == {"error": "unauthenticated"}


async def test_weight_dashboard_empty_shape(auth_client):
    r = await auth_client.get(WEIGHT)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {
        "latest_kg", "latest_date", "average7", "week_delta_kg", "body_fat_pct",
        "body_fat_source", "drug", "weighings", "trend", "dose_phases",
        "history", "pace", "last_scan",
    }  # fmt: skip
    assert body["latest_kg"] is None
    assert body["weighings"] == []
    assert body["trend"] == []
    assert body["history"] == []


async def test_weight_dashboard_with_history_and_superseded(auth_client, db_session):
    today = today_local()
    # Garmin row
    garmin_row = WeightLog(
        date=today,
        domain=WEIGHT_DOMAIN,
        source=Source.GARMIN_API.value,
        weight_kg=86.5,
        superseded=True,
    )
    # Manual row outranks Garmin
    manual_row = WeightLog(
        date=today,
        domain=WEIGHT_DOMAIN,
        source=Source.MANUAL.value,
        weight_kg=86.0,
        superseded=False,
        note="Morning reading",
    )
    db_session.add_all([garmin_row, manual_row])
    await db_session.commit()

    r = await auth_client.get(WEIGHT)
    assert r.status_code == 200
    body = r.json()

    assert body["latest_kg"] == 86.0
    assert len(body["history"]) == 2
    active_hist = next(h for h in body["history"] if not h["superseded"])
    superseded_hist = next(h for h in body["history"] if h["superseded"])
    assert active_hist["weight_kg"] == 86.0
    assert active_hist["source"] == "manual"
    assert active_hist["note"] == "Morning reading"
    assert superseded_hist["weight_kg"] == 86.5
    assert superseded_hist["source"] == "garmin"


async def test_weight_measures_shape(auth_client):
    r = await auth_client.get(MEASURES)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {
        "latest_kg", "average7", "body_fat_pct", "body_fat_source", "week_delta_kg",
        "height_cm", "sex", "body_comp_enabled", "llm_configured", "headline_metrics",
        "measurements", "scans", "photos", "noise_markers",
    }  # fmt: skip


async def test_body_measurements_crud(auth_client, db_session):
    today = today_local()
    # Create
    payload = {
        "date": today.isoformat(),
        "neck_cm": 38.5,
        "waist_cm": 84.0,
        "note": "Tape test",
        "override": False,
    }
    r = await auth_client.post(f"{WEIGHT}/measures", json=payload)
    assert r.status_code == 201
    created = r.json()
    assert "id" in created
    assert created["body_fat_pct"] is not None

    m_id = created["id"]

    # Verify in measures list
    r_list = await auth_client.get(MEASURES)
    assert r_list.status_code == 200
    meas_list = r_list.json()["measurements"]
    assert any(m["id"] == m_id and m["neck_cm"] == 38.5 for m in meas_list)

    # Delete
    r_del = await auth_client.delete(f"{WEIGHT}/measures/{m_id}")
    assert r_del.status_code == 204

    # Delete non-existent -> 404
    r_del_again = await auth_client.delete(f"{WEIGHT}/measures/{m_id}")
    assert r_del_again.status_code == 404


async def test_noise_markers_crud(auth_client):
    today = today_local()
    # Create
    payload = {
        "start_date": today.isoformat(),
        "end_date": (today + dt.timedelta(days=3)).isoformat(),
        "reason": "Creatine loading",
        "direction": "up",
    }
    r = await auth_client.post(f"{WEIGHT}/noise-markers", json=payload)
    assert r.status_code == 201
    created = r.json()
    assert "id" in created

    n_id = created["id"]

    # Verify in measures list
    r_list = await auth_client.get(MEASURES)
    noise_list = r_list.json()["noise_markers"]
    assert any(n["id"] == n_id and n["reason"] == "Creatine loading" for n in noise_list)

    # Delete
    r_del = await auth_client.delete(f"{WEIGHT}/noise-markers/{n_id}")
    assert r_del.status_code == 204

    # Delete non-existent -> 404
    r_del_again = await auth_client.delete(f"{WEIGHT}/noise-markers/{n_id}")
    assert r_del_again.status_code == 404


async def test_photos_upload_and_delete(auth_client):
    today = today_local()
    fake_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
    files = [("files", ("progress.png", fake_png, "image/png"))]
    data = {"date": today.isoformat(), "note": "Front check"}

    r = await auth_client.post(f"{WEIGHT}/photos", data=data, files=files)
    assert r.status_code == 201
    items = r.json()
    assert len(items) == 1
    photo_id = items[0]["id"]
    assert items[0]["note"] == "Front check"

    # Delete
    r_del = await auth_client.delete(f"{WEIGHT}/photos/{photo_id}")
    assert r_del.status_code == 204

    # Delete non-existent
    r_del_again = await auth_client.delete(f"{WEIGHT}/photos/{photo_id}")
    assert r_del_again.status_code == 404


async def test_body_scans_gated_when_module_disabled(auth_client, db_session, redis):
    await _set_module(db_session, redis, "body_comp", False)
    r = await auth_client.post(
        f"{WEIGHT}/body-scans/upload",
        files=[("file", ("scan.jpg", b"123", "image/jpeg"))],
    )
    assert r.status_code == 404
    assert r.json() == {"error": "module_disabled"}


async def test_body_scans_confirm_and_delete(auth_client, db_session, redis):
    await _set_module(db_session, redis, "body_comp", True)
    today = today_local()
    payload = {
        "date": today.isoformat(),
        "device": "InBody 770",
        "note": "Clinic scan",
        "override": False,
        "metrics": [
            {"metric_key": "weight", "label": "Вес", "value": 85.5, "unit": "кг", "category": "composition"},
            {"metric_key": "body_fat_pct", "label": "Процент жира", "value": 18.2, "unit": "%", "category": "composition"},
            {"metric_key": "skeletal_muscle_mass", "label": "Скелетная масса", "value": 39.0, "unit": "кг", "category": "composition"},
        ],
    }
    r = await auth_client.post(f"{WEIGHT}/body-scans/confirm", json=payload)
    assert r.status_code == 200
    res = r.json()
    assert res["ok"] is True
    scan_id = res["scan_id"]
    assert scan_id is not None

    # Check that scan appears in measures
    r_m = await auth_client.get(MEASURES)
    assert r_m.status_code == 200
    scans = r_m.json()["scans"]
    assert any(s["id"] == scan_id and s["device"] == "InBody 770" for s in scans)

    # Delete scan
    r_del = await auth_client.delete(f"{WEIGHT}/body-scans/{scan_id}")
    assert r_del.status_code == 204


async def test_garmin_weight_export_endpoint(auth_client):
    r = await auth_client.post(f"{WEIGHT}/garmin-export")
    assert r.status_code == 200
    body = r.json()
    assert "ok" in body
    assert "status" in body


async def test_latest_weight_returns_newest_not_oldest(auth_client, db_session):
    """list_active_weights orders ascending, so latest_kg and
    latest_date must come from weights[-1], never weights[0]."""
    await weight_service.log_weight(
        db_session, on_date=dt.date(2026, 5, 1), weight_kg=88.2
    )
    await weight_service.log_weight(
        db_session, on_date=dt.date(2026, 6, 1), weight_kg=81.4
    )
    await db_session.commit()

    r_dash = await auth_client.get(WEIGHT)
    assert r_dash.status_code == 200
    dash = r_dash.json()
    assert dash["latest_kg"] == pytest.approx(81.4)
    assert dash["latest_date"] == "2026-06-01"

    r_meas = await auth_client.get(MEASURES)
    assert r_meas.status_code == 200
    assert r_meas.json()["latest_kg"] == pytest.approx(81.4)


async def test_weight_history_order_and_superseded_by(auth_client, db_session):
    """On a single date the active row comes first in history, and
    superseded rows carry the active row's source in superseded_by."""
    today = today_local()
    await weight_service.log_weight(
        db_session, on_date=today, weight_kg=80.0, source=Source.GARMIN_API.value
    )
    await weight_service.log_weight(
        db_session, on_date=today, weight_kg=79.5, source=Source.BODY_SCAN.value
    )
    await weight_service.log_weight(
        db_session, on_date=today, weight_kg=79.6, source=Source.MANUAL.value
    )
    await db_session.commit()

    r = await auth_client.get(WEIGHT)
    assert r.status_code == 200
    hist = r.json()["history"]
    assert len(hist) == 3
    assert hist[0]["superseded"] is False
    assert hist[0]["source"] == "manual"
    assert hist[0]["weight_kg"] == pytest.approx(79.6)
    assert hist[0]["superseded_by"] is None
    for row in hist[1:]:
        assert row["superseded"] is True
        assert row["superseded_by"] == "manual"


def test_web_api_routers_respect_service_boundary():
    """Routers under web/api/ must not run direct SQLAlchemy
    select(...) queries, import vitals.services.analytics, or swallow exceptions
    with bare except Exception: pass."""
    import ast
    from pathlib import Path

    api_dir = Path(__file__).resolve().parent.parent / "web" / "api"
    for py_file in sorted(api_dir.glob("*.py")):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("vitals.services.analytics"), (
                    f"{py_file.name} imports {node.module} directly"
                )
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id != "select", (
                    f"{py_file.name}:{node.lineno} calls select() directly in router"
                )
            if isinstance(node, ast.ExceptHandler):
                is_broad = node.type is None or (
                    isinstance(node.type, ast.Name) and node.type.id == "Exception"
                )
                is_pass = len(node.body) == 1 and isinstance(node.body[0], ast.Pass)
                assert not (is_broad and is_pass), (
                    f"{py_file.name}:{node.lineno} has bare except Exception: pass"
                )

