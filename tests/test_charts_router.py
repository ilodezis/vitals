"""Router tests for the custom chart builder — page render, create/delete
flows, validation errors, and the auth guard."""
from __future__ import annotations

from datetime import date

import pytest

from vitals.models.weight import WeightLog
from vitals.services import custom_charts_service

pytestmark = pytest.mark.asyncio

DAY = date(2026, 6, 1)


async def test_charts_page_requires_auth(client):
    r = await client.get("/charts")
    assert r.status_code in (302, 303, 401)


async def test_charts_page_renders(auth_client):
    r = await auth_client.get("/charts")
    assert r.status_code == 200
    assert "chartBuilder" in r.text
    assert "Кастомные графики" in r.text or "charts.page_title" not in r.text


async def test_create_chart_valid_series(auth_client, db_session):
    db_session.add(WeightLog(date=DAY, domain="weight", source="manual", weight_kg=88.0, superseded=False))
    await db_session.commit()

    r = await auth_client.post("/charts", data={
        "name": "Вес и стресс",
        "domain": ["weight", "garmin"],
        "metric_key": ["weight.weight_kg", "garmin.avg_stress"],
        "param": ["", ""],
    })
    assert r.status_code == 303
    assert r.headers["location"] == "/charts"

    charts = await custom_charts_service.list_charts(db_session, redis=None)
    assert len(charts) == 1
    assert charts[0]["name"] == "Вес и стресс"
    assert len(charts[0]["series"]) == 2

    page = await auth_client.get("/charts")
    assert "Вес и стресс" in page.text
    assert 'id="customChart-' in page.text


async def test_create_chart_invalid_metric_redirects_with_error(auth_client, db_session):
    r = await auth_client.post("/charts", data={
        "name": "Bad chart",
        "domain": ["weight"],
        "metric_key": ["no.such.metric"],
        "param": [""],
    })
    assert r.status_code == 303
    assert r.headers["location"] == "/charts?error=invalid"

    charts = await custom_charts_service.list_charts(db_session, redis=None)
    assert charts == []


async def test_create_chart_with_param(auth_client, db_session):
    r = await auth_client.post("/charts", data={
        "name": "TSH trend",
        "domain": ["labs"],
        "metric_key": ["labs.marker"],
        "param": ["TSH"],
    })
    assert r.status_code == 303
    charts = await custom_charts_service.list_charts(db_session, redis=None)
    assert charts[0]["series"][0]["param"] == "TSH"


async def test_delete_chart(auth_client, db_session):
    created = await custom_charts_service.create_chart(
        db_session, name="To delete", series=[{"domain": "weight", "metric_key": "weight.weight_kg"}]
    )
    await db_session.commit()

    r = await auth_client.post(f"/charts/{created['id']}/delete")
    assert r.status_code == 303

    charts = await custom_charts_service.list_charts(db_session, redis=None)
    assert charts == []


async def test_charts_page_lists_and_renders_saved_chart_data(auth_client, db_session):
    db_session.add(WeightLog(date=DAY, domain="weight", source="manual", weight_kg=88.0, superseded=False))
    await custom_charts_service.create_chart(
        db_session, name="Weight only", series=[{"domain": "weight", "metric_key": "weight.weight_kg"}]
    )
    await db_session.commit()

    r = await auth_client.get("/charts")
    assert r.status_code == 200
    assert "vitalsCustomCharts" in r.text
    assert "88.0" in r.text
