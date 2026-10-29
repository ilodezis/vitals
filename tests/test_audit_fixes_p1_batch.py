from datetime import date, datetime, timedelta
import pytest
from sqlalchemy import select

from vitals.enums import Domain, RuleType, Severity
from vitals.models.garmin import GarminDaily
from vitals.models.labs import LabMarker, LabResult
from vitals.models.milestones import Milestone
from vitals.models.supplements import Supplement
from vitals.models.weight import BodyMeasurement
from vitals.models.body_scan import BodyScan, BodyScanMetric
from vitals.models.conflict_rule import ConflictRule
from vitals.services import (
    alerts_service,
    conflict_engine,
    conflict_registrations,
    labs_service,
    language_service,
    milestones_service,
    modules_service,
    supplements_service,
)
from vitals.utils.timeutils import today_local
from web.routers import mcp as mcp_router


@pytest.fixture(autouse=True)
def _register_resolvers():
    conflict_registrations.register_all_resolvers()
    yield
    conflict_engine.clear_domain_resolvers()


# ── Item 9: Garmin units & fields ──────────────────────────────────────────────
async def test_garmin_metrics_item9_units_and_flags(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    today = today_local()
    yesterday = today - timedelta(days=1)

    db_session.add_all([
        GarminDaily(
            date=today,
            domain="garmin",
            source="garmin",
            sleep_need_actual=480,
            sleep_stages=[{"stage": "deep", "start": "23:00", "end": "01:00"}],
            breathing_events=[{"time": "02:00"}],
        ),
        GarminDaily(
            date=yesterday,
            domain="garmin",
            source="garmin",
            sleep_need_actual=500,
        ),
    ])
    await db_session.commit()

    # Default folded
    data = await mcp_router.get_garmin_metrics()
    daily = {r["date"]: r for r in data["daily_recovery"]}

    today_row = daily[today.isoformat()]
    assert today_row["is_partial_day"] is True
    assert today_row["sleep_need_minutes"] == 480
    assert "sleep_need_actual" not in today_row
    assert today_row["sleep_stages_count"] == 1
    assert today_row["breathing_events_count"] == 1
    assert "sleep_stages" not in today_row

    yesterday_row = daily[yesterday.isoformat()]
    assert yesterday_row["is_partial_day"] is False
    assert yesterday_row["sleep_need_minutes"] == 500

    # With sleep_detail=True
    detailed = await mcp_router.get_garmin_metrics(sleep_detail=True)
    today_det = next(r for r in detailed["daily_recovery"] if r["date"] == today.isoformat())
    assert today_det["sleep_stages_count"] == 1
    assert len(today_det["sleep_stages"]) == 1


# ── Item 10: Marker normalization ──────────────────────────────────────────────
def test_normalize_marker_item10():
    assert labs_service.normalize_marker("Средний объём тромбоцитов") == "Средний объем тромбоцитов"
    assert labs_service.normalize_marker("Средний объем тромбоцитов") == "Средний объем тромбоцитов"
    assert labs_service.normalize_marker("Средний объём эритроцитов") == "Средний объем эритроцитов"
    assert labs_service.normalize_marker("Средняя концентрация Hb в эритроците") == "Средняя концентрация гемоглобина в эритроците"
    assert labs_service.normalize_marker("Эпителий переходной") == "Эпителий переходный"
    assert labs_service.normalize_marker("Эпителий переходный") == "Эпителий переходный"
    assert labs_service.normalize_marker("Лимфоциты, %") == "Лимфоциты %"
    assert labs_service.normalize_marker("Лимфоциты %") == "Лимфоциты %"


# ── Item 11: Overdue retests appear in get_active_alerts ──────────────────────
async def test_get_active_alerts_populates_overdue_retests(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    today = today_local()
    # Marker with 30-day interval, tested 60 days ago
    m = LabMarker(name="Тестостерон общий", domain="labs", retest_interval_days=30)
    db_session.add(m)
    await db_session.flush()

    res = LabResult(
        domain="labs",
        source="labs",
        marker="Тестостерон общий",
        date=today - timedelta(days=60),
        value=15.0,
        unit="нмоль/л",
    )
    db_session.add(res)
    await db_session.commit()

    alerts = await mcp_router.get_active_alerts(domain="labs")
    retest_alerts = [a for a in alerts if a.get("alert_key") == labs_service.RETEST_DUE_KEY]
    assert len(retest_alerts) >= 1
    assert "Тестостерон общий" in retest_alerts[0]["message"]


# ── Item 12: Lab rule aging threshold (>180 days softens to note) ──────────────
async def test_conflict_rule_softens_for_old_labs(db_session):
    today = today_local()
    old_date = today - timedelta(days=200)

    # Old cortisol result
    db_session.add(LabResult(
        domain="labs",
        source="labs",
        marker="Кортизол",
        date=old_date,
        value=50.0,
        unit="нмоль/л",
    ))
    # Active ashwagandha supplement
    db_session.add(Supplement(
        name="Ашваганда",
        key="ashwagandha",
        domain="supplements",
        source="manual",
        active=True,
    ))
    # Rule: ashwagandha when cortisol is low
    rule = ConflictRule(
        code="ashwagandha_low_cortisol",
        domain_a="supplements",
        domain_b="labs",
        rule_type=RuleType.HARD_BLOCK.value,
        severity=Severity.BLOCK.value,
        condition_a={"key": "ashwagandha", "active": True},
        condition_b={"marker": "Кортизол"},
        message="Кортизол уже ниже нормы",
        active=True,
    )
    db_session.add(rule)
    await db_session.commit()

    violations = await conflict_engine.evaluate(db_session, domain="supplements")
    v = next(v for v in violations if v.rule_id == rule.id)
    assert v.severity == Severity.NOTE.value
    assert f"по анализу от {old_date.strftime('%d.%m.%Y')}" in v.message


# ── Item 13: Language preference in get_today ──────────────────────────────────
async def test_get_today_uses_configured_language(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    await language_service.set_language(db_session, "ru")
    await db_session.commit()

    today_data = await mcp_router.get_today()
    # Should run with current_lang = 'ru'
    assert isinstance(today_data, dict)


# ── Item 14: Method labeling on body fat ───────────────────────────────────────
async def test_body_fat_method_labeling(db_session):
    today = today_local()

    # Measurement with Navy body fat
    meas = BodyMeasurement(
        date=today,
        domain="weight",
        source="manual",
        neck_cm=40.0,
        waist_cm=88.0,
        hips_cm=100.0,
        body_fat_pct=19.5,
        lbm_kg=78.0,
    )
    # Scan metric with BIA body fat
    scan = BodyScan(
        date=today,
        domain="body_comp",
        source="manual",
        device="InBody",
    )
    db_session.add_all([meas, scan])
    await db_session.flush()

    scan_metric = BodyScanMetric(
        scan_id=scan.id,
        metric_key="body_fat_pct",
        label="Процент жира",
        value=30.0,
        unit="%",
    )
    db_session.add(scan_metric)

    # Milestone for body fat
    milestone = Milestone(
        name="18% Body-fat",
        domain=Domain.BODY_COMPOSITION.value,
        status="active",
        target_value=18.0,
        target_unit="%",
    )
    db_session.add(milestone)
    await db_session.commit()

    ser_meas = mcp_router.serialize_row(meas)
    assert ser_meas["body_fat_pct_navy"] == 19.5
    assert ser_meas["method"] == "navy"

    ser_metric = mcp_router.serialize_row(scan_metric)
    assert ser_metric["body_fat_pct_bia"] == 30.0
    assert ser_metric["method"] == "bia"

    prog = await milestones_service.progress(db_session, milestone)
    assert "method" in prog


# ── Item 15: Supplement key lookup and catalog periods ─────────────────────────
async def test_supplement_find_by_key_and_catalog_periods(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    await modules_service.set_module_enabled(db_session, key="supplements", enabled=True)
    s1 = Supplement(
        name="Теанин утро",
        key="l_theanine",
        domain="supplements",
        source="manual",
        timing="утро",
        active=True,
    )
    s2 = Supplement(
        name="Теанин вечер",
        key="l_theanine",
        domain="supplements",
        source="manual",
        timing="вечер",
        active=True,
    )
    s3 = Supplement(
        name="Бор",
        key="boron",
        domain="supplements",
        source="manual",
        active=False,
    )
    db_session.add_all([s1, s2, s3])
    await db_session.commit()

    # Ambiguous key raises ValueError
    with pytest.raises(ValueError, match="Ambiguous supplement key 'l_theanine'"):
        await supplements_service.find_by_key(db_session, "l_theanine")

    # Unique key returns record
    boron = await supplements_service.find_by_key(db_session, "boron")
    assert boron is not None
    assert boron.id == s3.id

    # Catalog includes periods list for all supplements
    catalog = await mcp_router.get_supplements_catalog()
    boron_cat = next(c for c in catalog if c["key"] == "boron")
    assert "periods" in boron_cat
    assert isinstance(boron_cat["periods"], list)
