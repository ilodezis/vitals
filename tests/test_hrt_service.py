"""HRT domain tests — compound catalog sync, dose log (ml→mg computation and
grey-market fields), side effects, conflict resolver, and the dashboard route."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from vitals.services import hrt_catalog, hrt_service
from vitals.utils.timeutils import today_local

pytestmark = pytest.mark.asyncio


# ── Catalog sync ──────────────────────────────────────────────────────────────
async def test_sync_catalog_is_idempotent(db_session):
    r1 = await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    assert r1["inserted"] == r1["total"] > 0
    assert r1["updated"] == 0

    r2 = await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    assert r2["inserted"] == 0
    assert r2["updated"] == r2["total"] == r1["total"]

    compounds = await hrt_service.list_compounds(db_session)
    assert len(compounds) == r1["total"]


async def test_sync_catalog_loads_blend_components(db_session):
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    sust = await hrt_service.get_compound(db_session, "sustanon_250")
    assert sust is not None
    esters = {c.ester: c.mg for c in sust.components}
    assert esters == {
        "propionate": 30.0,
        "phenylpropionate": 60.0,
        "isocaproate": 60.0,
        "decanoate": 100.0,
    }
    # Re-sync must not duplicate the blend's components.
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    sust2 = await hrt_service.get_compound(db_session, "sustanon_250")
    assert len(sust2.components) == 4


# ── Dose logging ──────────────────────────────────────────────────────────────
async def test_log_dose_direct_amount(db_session):
    row = await hrt_service.log_dose(
        db_session, compound_key="testosterone_enanthate",
        on_date=date(2026, 6, 1), dose=250, unit="mg",
    )
    await db_session.commit()
    assert row.id is not None
    assert row.dose == 250 and row.unit == "mg"
    assert row.compound_key == "testosterone_enanthate"


async def test_log_dose_computes_mg_from_volume_and_catalog_conc(db_session):
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    # test enanthate catalog concentration is 250 mg/ml → 1 ml == 250 mg.
    row = await hrt_service.log_dose(
        db_session, compound_key="testosterone_enanthate",
        on_date=date(2026, 6, 1), volume_ml=1.0,
    )
    await db_session.commit()
    assert row.dose == pytest.approx(250.0)
    assert row.unit == "mg"
    assert row.compound_id is not None


async def test_measured_concentration_overrides_catalog(db_session):
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    # Grey-market vial underdosed at 200 mg/ml → 1 ml == 200 mg, not 250.
    row = await hrt_service.log_dose(
        db_session, compound_key="testosterone_enanthate",
        on_date=date(2026, 6, 1), volume_ml=1.0, concentration_mg_ml=200,
        brand="Pharmacom", lab="UGL", batch="A123",
    )
    await db_session.commit()
    assert row.dose == pytest.approx(200.0)
    assert (row.brand, row.lab, row.batch) == ("Pharmacom", "UGL", "A123")


async def test_log_dose_without_amount_or_volume_raises(db_session):
    with pytest.raises(ValueError):
        await hrt_service.log_dose(
            db_session, compound_key="testosterone_enanthate",
            on_date=date(2026, 6, 1),
        )


async def test_log_dose_rejects_unknown_site(db_session):
    with pytest.raises(ValueError):
        await hrt_service.log_dose(
            db_session, compound_key="testosterone_enanthate",
            on_date=date(2026, 6, 1), dose=250, site="left_earlobe",
        )


async def test_log_dose_rejects_non_positive(db_session):
    with pytest.raises(ValueError):
        await hrt_service.log_dose(
            db_session, compound_key="oxandrolone",
            on_date=date(2026, 6, 1), dose=0,
        )


def test_site_frequency_counts_by_site():
    rows = [
        SimpleNamespace(site="glute_left"),
        SimpleNamespace(site="glute_left"),
        SimpleNamespace(site="delt_right"),
        SimpleNamespace(site=None),
    ]
    assert hrt_service.site_frequency(rows) == {"glute_left": 2, "delt_right": 1}


async def test_update_and_delete_dose(db_session):
    row = await hrt_service.log_dose(
        db_session, compound_key="oxandrolone", on_date=date(2026, 6, 1), dose=20, unit="mg",
    )
    await db_session.commit()
    updated = await hrt_service.update_dose(
        db_session, row.id, compound_key="oxandrolone",
        on_date=date(2026, 6, 2), dose=30, unit="mg",
    )
    assert updated.dose == 30 and updated.date == date(2026, 6, 2)
    assert await hrt_service.delete_dose(db_session, row.id) is True
    assert await hrt_service.delete_dose(db_session, row.id) is False


# ── Side effects ──────────────────────────────────────────────────────────────
async def test_side_effect_severity_bounds(db_session):
    ok = await hrt_service.log_side_effect(
        db_session, on_date=date(2026, 6, 1), effect_type="acne", severity=3,
    )
    await db_session.commit()
    assert ok.id is not None
    with pytest.raises(ValueError):
        await hrt_service.log_side_effect(
            db_session, on_date=date(2026, 6, 1), effect_type="acne", severity=9,
        )


# ── Conflict resolver ─────────────────────────────────────────────────────────
async def test_resolve_active_returns_recent_compound_class(db_session):
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    await hrt_service.log_dose(
        db_session, compound_key="oxandrolone", on_date=today_local(), dose=20, unit="mg",
    )
    await db_session.commit()
    items = await hrt_service.resolve_active(db_session)
    keys = {i["compound_key"]: i for i in items}
    assert "oxandrolone" in keys
    assert keys["oxandrolone"]["compound_class"] == "oral_aas"
    assert keys["oxandrolone"]["active"] is True


async def test_resolve_active_ignores_old_doses(db_session):
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    await hrt_service.log_dose(
        db_session, compound_key="oxandrolone", on_date=date(2020, 1, 1), dose=20, unit="mg",
    )
    await db_session.commit()
    assert await hrt_service.resolve_active(db_session) == []


# ── Catalog validation (pure, no DB) ──────────────────────────────────────────
_VALID_ENTRY = {
    "name": "X",
    "compound_class": "testosterone",
    "route": "intramuscular",
    "half_life_hours": 100,
    "active_fraction": 0.7,
}


def test_validate_entry_accepts_a_good_entry():
    # Must not raise; 'partial' is a legal tri-state for aromatizes.
    hrt_catalog._validate_entry("x", {**_VALID_ENTRY, "aromatizes": "partial"})


def test_validate_entry_rejects_bad_compound_class():
    with pytest.raises(ValueError):
        hrt_catalog._validate_entry("x", {**_VALID_ENTRY, "compound_class": "bogus"})


def test_validate_entry_rejects_bad_route():
    with pytest.raises(ValueError):
        hrt_catalog._validate_entry("x", {**_VALID_ENTRY, "route": "snorted"})


def test_validate_entry_rejects_bad_dose_unit():
    with pytest.raises(ValueError):
        hrt_catalog._validate_entry("x", {**_VALID_ENTRY, "dose_unit": "teaspoon"})


def test_validate_entry_rejects_missing_required():
    broken = {k: v for k, v in _VALID_ENTRY.items() if k != "route"}
    with pytest.raises(ValueError):
        hrt_catalog._validate_entry("x", broken)


def test_validate_entry_rejects_component_without_mg():
    with pytest.raises(ValueError):
        hrt_catalog._validate_entry(
            "x", {**_VALID_ENTRY, "components": [{"ester": "propionate"}]}
        )


# ── Compound catalog queries ──────────────────────────────────────────────────
async def test_sync_stamps_source_system(db_session):
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    row = await hrt_service.get_compound(db_session, "oxandrolone")
    assert row.source == "system"


async def test_list_compounds_filters_by_class(db_session):
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    ais = await hrt_service.list_compounds(db_session, compound_class="ai")
    keys = {c.key for c in ais}
    assert keys == {"anastrozole", "exemestane", "letrozole"}


async def test_set_compound_active_hides_from_active_list(db_session):
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    ana = await hrt_service.get_compound(db_session, "anastrozole")
    await hrt_service.set_compound_active(db_session, ana.id, active=False)
    await db_session.commit()
    active_ais = await hrt_service.list_compounds(db_session, compound_class="ai")
    assert "anastrozole" not in {c.key for c in active_ais}
    all_ais = await hrt_service.list_compounds(
        db_session, active_only=False, compound_class="ai"
    )
    assert "anastrozole" in {c.key for c in all_ais}


# ── Dose units (mg / IU / mcg) ────────────────────────────────────────────────
async def test_dose_unit_defaults_from_catalog_iu(db_session):
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    # Somatropin (GH) is dosed in IU — omitting unit must inherit it, not fall to mg.
    row = await hrt_service.log_dose(
        db_session, compound_key="somatropin", on_date=date(2026, 6, 1), dose=4,
    )
    await db_session.commit()
    assert row.unit == "iu"


async def test_dose_unit_defaults_from_catalog_mcg(db_session):
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    row = await hrt_service.log_dose(
        db_session, compound_key="bpc_157", on_date=date(2026, 6, 1), dose=250,
    )
    await db_session.commit()
    assert row.unit == "mcg"


async def test_dose_unit_is_normalized(db_session):
    row = await hrt_service.log_dose(
        db_session, compound_key="testosterone_enanthate",
        on_date=date(2026, 6, 1), dose=250, unit="  MG ",
    )
    await db_session.commit()
    assert row.unit == "mg"


async def test_dose_persists_volume_ml(db_session):
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    row = await hrt_service.log_dose(
        db_session, compound_key="testosterone_enanthate",
        on_date=date(2026, 6, 1), volume_ml=0.8,
    )
    await db_session.commit()
    assert row.volume_ml == pytest.approx(0.8)
    assert row.dose == pytest.approx(200.0)  # 0.8 ml × 250 mg/ml


async def test_dose_with_unknown_key_logs_without_compound_id(db_session):
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    # 'anavar' is an alias, not a catalog key (the key is 'oxandrolone'); the log
    # still records it as free text but links no catalog row.
    row = await hrt_service.log_dose(
        db_session, compound_key="anavar", on_date=date(2026, 6, 1), dose=20, unit="mg",
    )
    await db_session.commit()
    assert row.compound_id is None
    assert row.compound_key == "anavar"


# ── list_doses / side-effect list ─────────────────────────────────────────────
async def test_list_doses_date_range(db_session):
    for d in (date(2026, 6, 1), date(2026, 6, 10), date(2026, 6, 20)):
        await hrt_service.log_dose(
            db_session, compound_key="oxandrolone", on_date=d, dose=20, unit="mg",
        )
    await db_session.commit()
    rows = await hrt_service.list_doses(
        db_session, start=date(2026, 6, 5), end=date(2026, 6, 15)
    )
    assert [r.date for r in rows] == [date(2026, 6, 10)]


async def test_side_effect_list_and_delete(db_session):
    e = await hrt_service.log_side_effect(
        db_session, on_date=date(2026, 6, 1), effect_type="acne", severity=2,
    )
    await db_session.commit()
    assert len(await hrt_service.list_side_effects(db_session)) == 1
    assert await hrt_service.delete_side_effect(db_session, e.id) is True
    assert await hrt_service.list_side_effects(db_session) == []


async def test_resolve_active_dedupes_multiple_doses(db_session):
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    for _ in range(3):
        await hrt_service.log_dose(
            db_session, compound_key="oxandrolone", on_date=today_local(),
            dose=20, unit="mg",
        )
    await db_session.commit()
    items = await hrt_service.resolve_active(db_session)
    oxa = [i for i in items if i["compound_key"] == "oxandrolone"]
    assert len(oxa) == 1


# ── Dashboard route ───────────────────────────────────────────────────────────
async def test_hrt_dashboard_renders(auth_client, db_session):
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    r = await auth_client.get("/hrt")
    assert r.status_code == 200
    assert "ГЗТ" in r.text


async def test_hrt_log_dose_via_form(auth_client):
    r = await auth_client.post(
        "/hrt/dose",
        data={"date": "2026-06-01", "compound_key": "testosterone_enanthate",
              "dose": "250", "unit": "mg", "brand": "TestBrand"},
    )
    assert r.status_code == 303
    page = await auth_client.get("/hrt")
    assert "TestBrand" in page.text
