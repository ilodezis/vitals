"""Web routes for the Timeline module — feed page, create/delete annotation,
and the optional-module gate."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from vitals.models.timeline import Annotation

pytestmark = pytest.mark.asyncio


async def test_timeline_feed_renders(auth_client):
    response = await auth_client.get("/timeline", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "Хронология" in response.text


async def test_create_and_delete_annotation(auth_client, db_session):
    response = await auth_client.post(
        "/timeline",
        data={
            "title": "Поездка в Грузию",
            "date": "2026-06-01",
            "end_date": "2026-06-10",
            "kind": "travel",
            "domain": "timeline",
        },
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/timeline"

    result = await db_session.execute(select(Annotation))
    row = result.scalar_one()
    assert row.title == "Поездка в Грузию"
    assert row.kind == "travel"
    assert row.end_date is not None

    feed = await auth_client.get("/timeline", headers={"Accept": "text/html"})
    assert "Поездка в Грузию" in feed.text

    delete_resp = await auth_client.post(f"/timeline/{row.id}/delete")
    assert delete_resp.status_code == 303

    result2 = await db_session.execute(select(Annotation))
    assert result2.scalar_one_or_none() is None


async def test_disabled_timeline_module_redirects(auth_client):
    """A disabled Optional module's page redirects to the dashboard (browser GET)."""
    await auth_client.post("/settings/modules", data={"module": "timeline", "enabled": "false"})

    r = await auth_client.get("/timeline", headers={"Accept": "text/html"})
    assert r.status_code == 303
    assert r.headers["location"] == "/weight"

    await auth_client.post("/settings/modules", data={"module": "timeline", "enabled": "true"})
    r = await auth_client.get("/timeline", headers={"Accept": "text/html"})
    assert r.status_code == 200
