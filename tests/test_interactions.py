"""/interactions — the curated conflict-rule catalog browser + toggle."""
from __future__ import annotations

from sqlalchemy import select

from vitals.models.conflict_rule import ConflictRule
from vitals.models.system_alert import SystemAlert
from vitals.services import conflict_catalog


async def test_dashboard_renders_synced_catalog(auth_client, db_session):
    await conflict_catalog.sync_catalog(db_session)
    await db_session.commit()

    r = await auth_client.get("/interactions", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert "Кросс-доменные взаимодействия" in r.text
    # A rule from each of the two dermatology seed codes should render somewhere.
    assert "Ретиноид и пилинг" in r.text


async def test_dashboard_filters_by_domain(auth_client, db_session):
    await conflict_catalog.sync_catalog(db_session)
    await db_session.commit()

    r = await auth_client.get("/interactions", params={"domain": "genetics"}, headers={"Accept": "text/html"})
    assert r.status_code == 200
    result = await db_session.execute(select(ConflictRule).where(ConflictRule.domain_a == "genetics"))
    some_genetics_rule = result.scalars().first()
    assert some_genetics_rule.message in r.text


async def test_toggle_flips_active_and_persists(auth_client, db_session):
    await conflict_catalog.sync_catalog(db_session)
    await db_session.commit()

    result = await db_session.execute(select(ConflictRule).limit(1))
    rule = result.scalar_one()
    assert rule.active is True

    r = await auth_client.post(f"/interactions/{rule.id}/toggle", data={"active": "false"})
    assert r.status_code == 204

    await db_session.refresh(rule)
    assert rule.active is False


async def test_toggle_unknown_rule_404s(auth_client):
    r = await auth_client.post("/interactions/999999/toggle", data={"active": "false"})
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

    r = await auth_client.get("/interactions", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert "Срабатывает сейчас" in r.text
