"""Lab results are filed by the scale they were measured on, and every flag that
leaves the server is judged against a reference range that belongs to the value.

All values are synthetic.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from vitals.enums import Domain, Source
from vitals.models.conflict_rule import ConflictRule
from vitals.models.labs import LabMarker, LabResult
from vitals.services import (
    alerts_service,
    conflict_registrations,
    digest_service,
    labs_service,
    supplements_service,
)

DAY = date(2026, 3, 10)


async def _add(db_session, marker, value, unit, lo=None, hi=None, on=DAY):
    return await labs_service.add_result(
        db_session, on_date=on, marker=marker, value=value, unit=unit, ref_low=lo, ref_high=hi,
    )


# ── Unit classes ──────────────────────────────────────────────────────────────

def test_unit_spellings_of_one_scale_are_compatible():
    assert labs_service.units_compatible("10^9/л", "10*9/л")
    assert labs_service.units_compatible("мМЕ/л", "мкМЕ/мл")
    assert labs_service.units_compatible("кл/мкл", "количество/мкл")
    assert labs_service.units_compatible("мМоль/л", "ммоль/л")
    assert labs_service.units_compatible("мм/ч", "мм/час")
    assert labs_service.units_compatible(None, "%")
    assert not labs_service.units_compatible("%", "10^9/л")
    assert not labs_service.units_compatible("г/л", "г/дл")
    assert not labs_service.units_compatible("10^12/л", "кл/мкл")


# ── Import: percentages and counts, blood and urine, never share a marker ────

async def test_differential_percent_and_count_go_to_their_own_markers(db_session):
    pct = await _add(db_session, "Лимфоциты", 27.6, "%", 19, 48)
    count = await _add(db_session, "Лимфоциты %", 2.1, "10^9/л", 0.9, 4.2)
    neutro = await _add(db_session, "Нейтрофилы сегментоядерные", 60, "%", 47, 72)

    assert pct.marker == "Лимфоциты %"
    assert count.marker == "Лимфоциты"
    assert neutro.marker == "Нейтрофилы %"
    assert {pct.flag, count.flag, neutro.flag} == {"normal"}


async def test_a_result_on_another_scale_gets_a_unit_qualified_marker(db_session):
    blood = await _add(db_session, "Эритроциты", 5.1, "10^12/л", 4.4, 5.6)
    urine = await _add(db_session, "Эритроциты", 12, "кл/мкл", 0, 19)
    urine_again = await _add(db_session, "Эритроциты", 2, "количество/мкл", 0, 13)
    blood_again = await _add(db_session, "Эритроциты", 5.3, "10*12/л", 4.4, 5.6)
    mchc_gl = await _add(db_session, "Средняя концентрация гемоглобина в эритроците", 337, "г/л", 300, 380)
    mchc_gdl = await _add(db_session, "Средняя концентрация гемоглобина в эритроците", 34.2, "г/дл", 32, 35)

    assert blood.marker == blood_again.marker == "Эритроциты"
    assert urine.marker == urine_again.marker == "Эритроциты (кл/мкл)"
    assert mchc_gl.marker == "Средняя концентрация гемоглобина в эритроците"
    assert mchc_gdl.marker == "Средняя концентрация гемоглобина в эритроците (г/дл)"


async def test_the_same_quantity_in_a_convertible_unit_keeps_its_marker(db_session):
    first = await _add(db_session, "Кортизол", 10, "мкг/дл", 3.5, 18.3)
    second = await _add(db_session, "Кортизол", 300, "нмоль/л", 140, 600)
    assert first.marker == second.marker == "Кортизол"


async def test_a_unitless_result_keeps_its_name(db_session):
    await _add(db_session, "Эритроциты", 5.1, "10^12/л", 4.4, 5.6)
    row = await _add(db_session, "Эритроциты", 5.0, None, 4.4, 5.6)
    assert row.marker == "Эритроциты"


async def test_catalog_range_on_another_scale_is_not_borrowed(db_session):
    await _add(db_session, "Тромбоциты", 300, "10^9/л", 150, 400)
    row = await _add(db_session, "Тромбоциты", 12, "кл/мкл")
    assert row.marker == "Тромбоциты (кл/мкл)"
    assert (row.ref_low, row.ref_high, row.flag) == (None, None, None)


# ── Suspect values ────────────────────────────────────────────────────────────

async def test_impossible_value_is_suspect_and_raises_nothing(db_session):
    rbc = await _add(db_session, "Эритроциты", 51.0, "10^12/л", 4.4, 5.6)
    pct = await _add(db_session, "Гематокрит", 150.0, "%", 40, 50)
    real_critical = await _add(db_session, "Калий", 7.2, "ммоль/л", 3.5, 5.1)
    await db_session.commit()

    assert rbc.flag == pct.flag == "suspect"
    assert real_critical.flag == "critical_high", "a real critical value is never suspect"

    await labs_service.refresh_alerts(db_session, on_date=DAY)
    await db_session.commit()
    texts = [a.message for a in await alerts_service.list_active(db_session, domain="labs")]
    assert any("Калий" in t for t in texts)
    assert not any("Эритроциты" in t or "Гематокрит" in t for t in texts)

    resolved = {i["marker"] for i in await labs_service.resolve_latest(db_session)}
    assert "Эритроциты" not in resolved and "Калий" in resolved


async def test_suspect_value_does_not_trip_a_safety_block(db_session):
    conflict_registrations.register_all_resolvers()
    db_session.add(ConflictRule(
        rule_type="hard_block",
        domain_a="supplements", condition_a={"key": "potassium", "active": True},
        domain_b="labs", condition_b={"marker": "Калий", "value": {"$gt": 5.0}},
        severity="block", message="hyperkalemia", active=True,
    ))
    await supplements_service.add_supplement(db_session, name="Potassium", key="potassium", active=True)
    await db_session.commit()

    row = await _add(db_session, "Калий", 55.0, "ммоль/л", 3.5, 5.1)  # 5.5 misread
    assert row.flag == "suspect"


# ── Reads judge stored rows now ───────────────────────────────────────────────

async def _legacy(db_session, marker, value, unit, lo=None, hi=None, flag=None, on=DAY):
    """A row as an older import wrote it: whatever flag it got back then."""
    row = LabResult(
        date=on, domain=Domain.LABS.value, source=Source.LAB_PARSER.value,
        marker=marker, value=value, unit=unit, ref_low=lo, ref_high=hi, flag=flag,
    )
    db_session.add(row)
    return row


async def test_a_row_without_range_is_flagged_by_the_catalog_range(db_session, session_factory, monkeypatch):
    db_session.add(LabMarker(domain="labs", name="25-ОН витамин D", unit="нг/мл", ref_low=30, ref_high=100))
    await _legacy(db_session, "25-ОН витамин D", 28.9, "нг/мл")
    await db_session.commit()

    mcp_router = pytest.importorskip("web.routers.mcp")
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    rows = await mcp_router.get_lab_results(marker="25-ОН витамин D")
    assert [(r["flag"], r["ref_low"], r["ref_high"]) for r in rows] == [("low", 30, 100)]

    ctx = await digest_service.assemble_context(db_session, on_date=DAY + timedelta(days=1), period_days=3)
    assert [r["flag"] for r in ctx["labs"]["results_in_period"]] == ["low"]
    assert [r["marker"] for r in ctx["labs"]["out_of_range"]] == ["25-ОН витамин D"]


async def test_a_stored_misread_reads_as_suspect(db_session):
    await _legacy(db_session, "Эритроциты", 51.0, "10^12/л", 4.4, 5.6, flag="critical_high")
    await db_session.commit()

    history = await labs_service.marker_history(db_session, "Эритроциты")
    assert [p["flag"] for p in history] == ["suspect"]


async def test_snapshot_trends_split_scales_and_keep_each_labs_range(db_session):
    # Legacy rows: a percentage and a count stored under one name, and two labs
    # with different ranges for the same count.
    await _legacy(db_session, "Моноциты", 6.9, "%", 4, 12.5, "normal", on=DAY - timedelta(days=40))
    await _legacy(db_session, "Моноциты", 0.52, "10^9/л", 0.19, 0.77, "normal", on=DAY - timedelta(days=40))
    await _legacy(db_session, "Моноциты", 8.9, "%", 3, 11, "normal", on=DAY - timedelta(days=2))
    await _legacy(db_session, "Моноциты", 0.69, "10^9/л", 0.08, 1.5, "normal", on=DAY - timedelta(days=2))
    await _legacy(db_session, "Тромбоциты", 315, "10^9/л", 166, 308, "high", on=DAY - timedelta(days=40))
    await _legacy(db_session, "Тромбоциты", 370, "10^9/л", 150, 400, "normal", on=DAY - timedelta(days=2))
    await db_session.commit()

    ctx = await digest_service.assemble_context(db_session, on_date=DAY, period_days=7)
    trends = {(t["marker"], t["unit"]): t for t in ctx["labs"]["trends"]}

    assert [p["value"] for p in trends[("Моноциты", "%")]["points"]] == [6.9, 8.9]
    assert [p["value"] for p in trends[("Моноциты", "10^9/л")]["points"]] == [0.52, 0.69]

    platelets = trends[("Тромбоциты", "10^9/л")]
    assert (platelets["ref_low"], platelets["ref_high"]) == (150, 400)
    old, new = platelets["points"]
    assert (old["flag"], old["ref_low"], old["ref_high"]) == ("high", 166, 308)
    assert new["flag"] == "normal" and "ref_low" not in new
