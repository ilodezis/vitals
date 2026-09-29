"""Tests for the Signals API endpoints (/api/v1/signals)."""
from __future__ import annotations

from datetime import date
import pytest

from vitals.models.signals import Signal
from vitals.services import modules_service

URL = "/api/v1/signals"


async def test_signals_unauthenticated(client):
    r = await client.get(URL)
    assert r.status_code == 401


async def test_signals_module_gated(auth_client, db_session, redis):
    # Disable signals module
    state = await modules_service.set_module_enabled(db_session, key="signals", enabled=False)
    await db_session.commit()
    await modules_service.prime_cache(redis, state)

    r = await auth_client.get(URL)
    assert r.status_code == 404
    data = r.json()
    assert data.get("error") == "module_disabled"

    # Re-enable
    state = await modules_service.set_module_enabled(db_session, key="signals", enabled=True)
    await db_session.commit()
    await modules_service.prime_cache(redis, state)

    r = await auth_client.get(URL)
    assert r.status_code == 200


async def test_signals_read_misparse_and_delete(auth_client, db_session):
    # Create test signal row
    sig = Signal(
        date=date(2026, 9, 29),
        domain="signals",
        source="telegram",
        kind="symptom",
        key="headache",
        note="Голова раскалывается",
        batch_id="batch-123",
        misparse=False,
    )
    db_session.add(sig)
    await db_session.commit()
    await db_session.refresh(sig)

    # 1. Read
    r = await auth_client.get(URL)
    assert r.status_code == 200
    data = r.json()
    assert data["totalCount"] >= 1
    assert data["misparseCount"] == 0
    assert any(s["id"] == sig.id for s in data["signals"])

    # 2. Mark misparse
    r = await auth_client.post(f"{URL}/batch-123/misparse")
    assert r.status_code == 200
    assert r.json()["count"] >= 1

    r = await auth_client.get(URL)
    data = r.json()
    assert data["misparseCount"] >= 1
    found = next(s for s in data["signals"] if s["id"] == sig.id)
    assert found["misparse"] is True

    # 3. Delete
    r = await auth_client.delete(f"{URL}/{sig.id}")
    assert r.status_code == 204

    r = await auth_client.get(URL)
    data = r.json()
    assert not any(s["id"] == sig.id for s in data["signals"])
