"""Cross-endpoint parity tests: weight trend, dose phase delta, and goal progress."""
from __future__ import annotations

from datetime import timedelta

import pytest

from vitals.enums import Domain, Drug
from vitals.services import glp1_service, milestones_service, weight_service
from vitals.utils.timeutils import today_local


async def test_cross_endpoint_parity(auth_client, db_session):
    """The same figure must match on every endpoint that reports it:
    1. /api/v1/today (figures[weight].trend) == /api/v1/weight (pace.per_week_kg)
       == /api/v1/session (rail[weight].delta_kg)
    2. /api/v1/weight (pace.dose.delta_kg) == /api/v1/glp1 (deltaOnDoseKg & summary)
    3. /api/v1/today (goal.pct) == /api/v1/reports (goals[0].pct)
       == milestones_service.dashboard_cards()[0]["pct"]
    """
    today = today_local()

    # 2 GLP-1 dose phases: phase 1 (days -9..-6), phase 2 active (days -5..today)
    await glp1_service.add_dose_phase(
        db_session,
        start_date=today - timedelta(days=9),
        end_date=today - timedelta(days=6),
        drug=Drug.SEMAGLUTIDE.value,
        dose_mg=0.25,
    )
    await glp1_service.add_dose_phase(
        db_session,
        start_date=today - timedelta(days=5),
        drug=Drug.SEMAGLUTIDE.value,
        dose_mg=0.5,
    )

    # 10 days of weights with a noise spike on day -4
    weights_by_days_ago = [
        (9, 90.0),
        (8, 89.7),
        (7, 89.4),
        (6, 89.1),
        (5, 88.8),  # start of 0.5 mg phase
        (4, 92.5),  # water-weight noise spike
        (3, 88.2),
        (2, 87.9),
        (1, 87.6),
        (0, 87.4),  # end of 0.5 mg phase -> delta on dose = 87.4 - 88.8 = -1.4
    ]
    for days_ago, kg in weights_by_days_ago:
        await weight_service.log_weight(
            db_session, on_date=today - timedelta(days=days_ago), weight_kg=kg
        )

    await weight_service.add_noise_marker(
        db_session,
        start_date=today - timedelta(days=4),
        end_date=today - timedelta(days=4),
        reason="Salty dinner",
        direction="up",
    )

    # Active weight milestone: start=90.0, current=87.4, target=80.0 -> 26%
    await milestones_service.create_milestone(
        db_session,
        name="Target 80 kg",
        domain=Domain.WEIGHT.value,
        target_value=80.0,
        target_unit="kg",
        deadline=today + timedelta(days=60),
    )
    await db_session.commit()

    r_today = await auth_client.get("/api/v1/today")
    r_weight = await auth_client.get("/api/v1/weight")
    r_session = await auth_client.get("/api/v1/session")
    r_glp1 = await auth_client.get("/api/v1/glp1")
    r_reports = await auth_client.get("/api/v1/reports")

    assert r_today.status_code == 200
    assert r_weight.status_code == 200
    assert r_session.status_code == 200
    assert r_glp1.status_code == 200
    assert r_reports.status_code == 200

    today_body = r_today.json()
    weight_body = r_weight.json()
    session_body = r_session.json()
    glp1_body = r_glp1.json()
    reports_body = r_reports.json()

    # 1. Weight weekly trend parity across /today, /weight, and /session
    today_weight_fig = next(f for f in today_body["figures"] if f["key"] == "weight")
    session_weight_rail = next(r for r in session_body["rail"] if r["key"] == "weight")
    assert today_weight_fig["trend"] is not None
    assert today_weight_fig["trend"] == pytest.approx(weight_body["pace"]["per_week_kg"])
    assert today_weight_fig["trend"] == pytest.approx(session_weight_rail["delta_kg"])

    # 2. Dose phase delta parity across /weight and /glp1 (negative on weight loss)
    weight_dose_delta = weight_body["pace"]["dose"]["delta_kg"]
    assert weight_dose_delta == pytest.approx(-1.4)
    assert glp1_body["deltaOnDoseKg"] == pytest.approx(weight_dose_delta)
    assert "−1.4" in glp1_body["summary"]

    # 3. Goal pct parity across /today, /reports, and milestones_service
    cards = await milestones_service.dashboard_cards(db_session)
    assert len(cards) == 1
    expected_pct = 26  # round((90.0 - 87.4) / (90.0 - 80.0) * 100)
    assert cards[0]["pct"] == expected_pct
    assert today_body["goal"]["pct"] == expected_pct
    assert reports_body["activeGoals"][0]["pct"] == expected_pct
