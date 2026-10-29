from datetime import date, datetime, timedelta
import pytest
from fastmcp.exceptions import ToolError

from vitals.enums import DigestKind
from vitals.models.environment import EnvironmentHourly
from vitals.models.garmin import GarminActivity
from vitals.models.glp1 import Injection
from vitals.models.milestones import WeeklyDigest
from vitals.models.weight import WeightLog
from vitals.models.hevy import HevyExercise, HevySet, HevyWorkout
from vitals.services import modules_service, weight_service
from vitals.services.environment.settings import EnvSettings
from vitals.utils.timeutils import today_local
from web.routers import mcp as mcp_router


# ── Item 17: Surrogate IDs in workouts ─────────────────────────────────────────
async def test_get_hevy_workouts_omits_surrogate_ids(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    await modules_service.set_module_enabled(db_session, key="hevy", enabled=True)

    today = today_local()
    w = HevyWorkout(
        external_id="hevy-ext-123",
        date=today,
        domain="workouts",
        source="hevy",
        title="Push Day",
        start_time=datetime(2026, 10, 28, 14, 0),
    )
    db_session.add(w)
    await db_session.flush()

    e = HevyExercise(
        workout_id=w.id,
        exercise_template_id="bench-press",
        title="Bench Press",
    )
    db_session.add(e)
    await db_session.flush()

    s = HevySet(
        exercise_id=e.id,
        set_type="normal",
        weight_kg=80.0,
        reps=8,
        set_index=0,
    )
    db_session.add(s)
    await db_session.commit()

    workouts = await mcp_router.get_hevy_workouts()
    assert len(workouts) >= 1
    w_out = next(item for item in workouts if item.get("external_id") == "hevy-ext-123")
    assert "id" not in w_out
    assert w_out["external_id"] == "hevy-ext-123"

    e_out = w_out["exercises"][0]
    assert "id" not in e_out
    assert "workout_id" not in e_out

    s_out = e_out["sets"][0]
    assert "id" not in s_out
    assert "exercise_id" not in s_out
    assert s_out["weight_kg"] == 80.0


# ── Item 18 & 19: get_today float rounding, trend unit, and empty field pruning ──
async def test_get_today_pruning_and_trend_unit(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    today = today_local()

    # Weight logs to create trend
    for i in range(14):
        db_session.add(WeightLog(
            date=today - timedelta(days=i),
            weight_kg=100.0 - (0.1 * i),
            domain="weight",
            source="manual",
        ))
    await db_session.commit()

    today_data = await mcp_router.get_today()
    figures = {f["key"]: f for f in today_data.get("figures", [])}

    # Weight figure has trend_unit
    if "weight" in figures:
        w_fig = figures["weight"]
        if w_fig.get("trend") is not None:
            assert w_fig.get("trend_unit") == "kg/week"
        # Pruned empty strings/nulls
        assert "tone" not in w_fig or w_fig["tone"] != ""
        assert "baseline" not in w_fig
        assert "corridor" not in w_fig

    # Feed does not contain empty placeholder brief
    feed = today_data.get("feed", [])
    for item in feed:
        if item.get("kind") == "brief":
            assert item.get("text") or item.get("value") is not None
        assert "text" not in item or item["text"] != ""
        assert "detail" not in item or item["detail"] != ""


# ── Item 18: Garmin activity float rounding and low_hr pruning ────────────────
def test_garmin_activity_serialization_rounding():
    act = GarminActivity(
        external_id="act-1",
        domain="garmin",
        source="garmin",
        date=today_local(),
        training_effect_aerobic=1.899999976158142,
        training_effect_anaerobic=0.500001,
        hr_zone_seconds=[
            {"zone": 1, "secs": 1760.996, "low_hr": None},
            {"zone": 2, "secs": 300.0, "low_hr": 120},
        ],
    )
    ser = mcp_router.serialize_row(act)
    assert ser["training_effect_aerobic"] == 1.9
    assert ser["training_effect_anaerobic"] == 0.5
    assert ser["hr_zone_seconds"][0]["secs"] == 1761.0
    assert "low_hr" not in ser["hr_zone_seconds"][0]
    assert ser["hr_zone_seconds"][1]["low_hr"] == 120


# ── «Мелочи»: _parse_date raises ToolError ────────────────────────────────────
def test_parse_date_raises_tool_error():
    with pytest.raises(ToolError, match="start_date must be a YYYY-MM-DD date"):
        mcp_router._parse_date("2026-13-01", field="start_date")


# ── «Мелочи»: get_data_overview filters weekly_digests by kind ────────────────
async def test_get_data_overview_filters_weekly_digests(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    today = today_local()

    # 1 weekly digest and 3 daily briefs
    db_session.add(WeeklyDigest(
        date=today - timedelta(days=7),
        domain="milestones",
        source="derived",
        kind=DigestKind.WEEKLY.value,
        content="Weekly summary",
    ))
    for i in range(3):
        db_session.add(WeeklyDigest(
            date=today - timedelta(days=i),
            domain="milestones",
            source="derived",
            kind=DigestKind.DAILY_BRIEF.value,
            content=f"Daily brief {i}",
        ))
    await db_session.commit()

    overview = await mcp_router.get_data_overview()
    assert overview["weekly_digests"]["count"] == 1


# ── «Мелочи»: get_glp1_logs preserves site: None ──────────────────────────────
async def test_get_glp1_logs_preserves_site_null(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    await modules_service.set_module_enabled(db_session, key="glp1", enabled=True)

    today = today_local()
    inj = Injection(
        date=today,
        domain="glp1",
        source="manual",
        drug="Ozempic",
        dose_mg=0.5,
        site=None,
    )
    db_session.add(inj)
    await db_session.commit()

    data = await mcp_router.get_glp1_logs()
    item = next(i for i in data["injections"] if i.get("date") == today.isoformat())
    assert "site" in item
    assert item["site"] is None


# ── «Мелочи»: co2_good_max in thresholds and settings ─────────────────────────
def test_co2_good_max_thresholds():
    s = EnvSettings(co2_ok_max=800)
    thresh = s.thresholds_dict()
    assert thresh["co2_good_max"] == 800
    assert thresh["co2_ok_max"] == 800
