"""/api/v1/interactions — the curated conflict-rule catalog browser + toggle."""
from __future__ import annotations

from sqlalchemy import select

from vitals.models.conflict_rule import ConflictRule
from vitals.models.system_alert import SystemAlert
from vitals.services import conflict_catalog

API = "/api/v1/interactions"


async def test_dashboard_filters_by_domain(auth_client, db_session):
    await conflict_catalog.sync_catalog(db_session)
    await db_session.commit()

    r = await auth_client.get(API, params={"domain": "genetics"})
    assert r.status_code == 200
    result = await db_session.execute(select(ConflictRule).where(ConflictRule.domain_a == "genetics"))
    some_genetics_rule = result.scalars().first()
    assert some_genetics_rule.id in {x["id"] for x in r.json()["rules"]}


async def test_toggle_unknown_rule_404s(auth_client):
    r = await auth_client.post(f"{API}/999999/toggle", json={"active": False})
    assert r.status_code == 404


async def test_firing_now_badge_reflects_active_alert(auth_client, db_session):
    await conflict_catalog.sync_catalog(db_session)
    await db_session.commit()

    result = await db_session.execute(select(ConflictRule).limit(1))
    rule = result.scalar_one()
    db_session.add(
        SystemAlert(
            domain=rule.domain_a,
            severity=rule.severity,
            message=rule.message,
            alert_key=f"conflict:{rule.id}",
            entity_ref="test",
        )
    )
    await db_session.commit()

    r = await auth_client.get(API)
    assert r.status_code == 200
    data = r.json()
    assert rule.id in data["firingIds"]
    assert data["firingCount"] >= 1
    assert next(x for x in data["rules"] if x["id"] == rule.id)["firing"] is True


