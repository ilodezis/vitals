"""Tests for the Alerts API endpoints (/api/v1/alerts)."""
from __future__ import annotations

import pytest

from vitals.enums import Severity
from vitals.services import alerts_service

URL = "/api/v1/alerts"


async def test_alerts_unauthenticated(client):
    r = await client.get(URL)
    assert r.status_code == 401


async def test_alerts_read_and_resolve(auth_client, db_session):
    # 1. Raise test alert
    alert = await alerts_service.raise_alert(
        db_session,
        domain="weight",
        severity=Severity.WARN,
        alert_key="test_weight_spike",
        message="Вес подскочил",
        entity_ref="weight:2026-09-29",
    )
    await db_session.commit()

    # 2. Read alerts
    r = await auth_client.get(URL)
    assert r.status_code == 200
    data = r.json()
    assert data["count"] >= 1
    found = next((a for a in data["alerts"] if a["id"] == alert.id), None)
    assert found is not None
    assert found["message"] == "Вес подскочил"

    # 3. Filter by domain
    r = await auth_client.get(f"{URL}?domain=weight")
    assert r.status_code == 200
    assert any(a["id"] == alert.id for a in r.json()["alerts"])

    # 4. Resolve alert
    r = await auth_client.post(f"{URL}/{alert.id}/resolve")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # 5. Verify resolved
    r = await auth_client.get(URL)
    assert not any(a["id"] == alert.id for a in r.json()["alerts"])


async def test_an_alert_says_when_it_was_overridden(auth_client, db_session):
    """The banner marks a block the owner chose to save past."""
    kept = await alerts_service.raise_alert(
        db_session, domain="weight", severity=Severity.BLOCK, alert_key="kept", message="Kept"
    )
    plain = await alerts_service.raise_alert(
        db_session, domain="weight", severity=Severity.WARN, alert_key="plain", message="Plain"
    )
    await db_session.commit()
    await auth_client.post(f"{URL}/{kept.id}/override")

    alerts = {a["id"]: a for a in (await auth_client.get(f"{URL}?domain=weight")).json()["alerts"]}

    assert alerts[kept.id]["overridden"] is True
    assert alerts[plain.id]["overridden"] is False


async def test_hide_all_clears_one_domain_only(auth_client, db_session):
    for domain in ("weight", "weight", "labs"):
        await alerts_service.raise_alert(
            db_session, domain=domain, severity=Severity.WARN,
            alert_key=f"k{domain}", entity_ref=str(id(object())), message=domain,
        )
    await db_session.commit()

    r = await auth_client.post(f"{URL}/resolve-all?domain=weight")

    assert r.status_code == 200
    left = (await auth_client.get(URL)).json()["alerts"]
    assert [a["domain"] for a in left] == ["labs"]
