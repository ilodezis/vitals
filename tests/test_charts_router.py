"""Custom chart builder over the JSON API — multi-series create, validation
errors, per-series parameter, and delete. Plain CRUD lives in test_api_charts."""
from __future__ import annotations

from datetime import date

from vitals.models.weight import WeightLog
from vitals.services import custom_charts_service

DAY = date(2026, 6, 1)
URL = "/api/v1/charts"


async def test_create_chart_valid_series(auth_client, db_session):
    db_session.add(WeightLog(date=DAY, domain="weight", source="manual", weight_kg=88.0, superseded=False))
    await db_session.commit()

    r = await auth_client.post(URL, json={
        "name": "Вес и стресс",
        "series": [
            {"domain": "weight", "metricKey": "weight.weight_kg"},
            {"domain": "garmin", "metricKey": "garmin.avg_stress"},
        ],
    })
    assert r.status_code == 201

    charts = await custom_charts_service.list_charts(db_session, redis=None)
    assert len(charts) == 1
    assert charts[0]["name"] == "Вес и стресс"
    assert len(charts[0]["series"]) == 2

    view = (await auth_client.get(URL)).json()
    saved = next(c for c in view["charts"] if c["name"] == "Вес и стресс")
    assert len(saved["series"]) == 2


async def test_create_chart_invalid_metric_is_rejected(auth_client, db_session):
    r = await auth_client.post(URL, json={
        "name": "Bad chart",
        "series": [{"domain": "weight", "metricKey": "no.such.metric"}],
    })
    assert r.status_code == 400
    assert r.json()["error"] == "invalid"

    charts = await custom_charts_service.list_charts(db_session, redis=None)
    assert charts == []


async def test_create_chart_with_param(auth_client, db_session):
    r = await auth_client.post(URL, json={
        "name": "TSH trend",
        "series": [{"domain": "labs", "metricKey": "labs.marker", "param": "TSH"}],
    })
    assert r.status_code == 201
    charts = await custom_charts_service.list_charts(db_session, redis=None)
    assert charts[0]["series"][0]["param"] == "TSH"


async def test_create_chart_requires_name_and_series(auth_client, db_session):
    r = await auth_client.post(URL, json={"name": "  ", "series": [{"domain": "weight", "metricKey": "weight.weight_kg"}]})
    assert r.status_code == 400
    r = await auth_client.post(URL, json={"name": "Empty", "series": []})
    assert r.status_code == 400
    assert await custom_charts_service.list_charts(db_session, redis=None) == []


async def test_delete_chart(auth_client, db_session):
    created = await custom_charts_service.create_chart(
        db_session, name="To delete", series=[{"domain": "weight", "metric_key": "weight.weight_kg"}]
    )
    await db_session.commit()

    r = await auth_client.delete(f"{URL}/{created['id']}")
    assert r.status_code == 204

    charts = await custom_charts_service.list_charts(db_session, redis=None)
    assert charts == []


async def test_saved_chart_carries_its_data_points(auth_client, db_session):
    db_session.add(WeightLog(date=DAY, domain="weight", source="manual", weight_kg=88.0, superseded=False))
    await custom_charts_service.create_chart(
        db_session, name="Weight only", series=[{"domain": "weight", "metric_key": "weight.weight_kg"}]
    )
    await db_session.commit()

    view = (await auth_client.get(URL)).json()
    chart = next(c for c in view["charts"] if c["name"] == "Weight only")
    assert [p["value"] for p in chart["series"][0]["points"]] == [88.0]
