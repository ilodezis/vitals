"""What the screens' endpoints say when there is nothing to say: a missing figure is ``null``, a
label follows the language, a code is a code — never a stand-in that reads like data."""
from __future__ import annotations

import datetime as dt
from datetime import timedelta

import pytest

from vitals.enums import AnnotationKind, Domain, Drug, Source
from vitals.i18n import STRINGS
from vitals.models.conflict_rule import ConflictRule
from vitals.models.garmin import DOMAIN as GARMIN_DOMAIN, GarminDaily
from vitals.services import (
    glp1_service,
    hrt_catalog,
    language_service,
    milestones_service,
    modules_service,
    skincare_service,
    weight_service,
)
from vitals.services.analytics import body_metrics
from vitals.services.today_service import _whole
from vitals.utils.timeutils import today_local

WEIGHT = "/api/v1/weight"
GLP1 = "/api/v1/glp1"
HRT = "/api/v1/hrt"
RECOVERY = "/api/v1/recovery"
SUPPLEMENTS = "/api/v1/supplements"


async def _english(db_session, redis):
    await language_service.set_language(db_session, "en", redis)
    await db_session.commit()


# ── /api/v1/weight ───────────────────────────────────────────────────────────


async def test_weight_pace_goal_follows_the_active_weight_goal(auth_client, db_session):
    today = today_local()
    for days_ago, kg in ((14, 90.0), (7, 89.0), (0, 88.0)):
        await weight_service.log_weight(db_session, on_date=today - timedelta(days=days_ago), weight_kg=kg)
    await db_session.commit()

    without = (await auth_client.get(WEIGHT)).json()
    assert without["pace"]["goal"] is None

    await milestones_service.create_milestone(
        db_session,
        name="Target 80 kg",
        domain=Domain.WEIGHT.value,
        target_value=80.0,
        target_unit="kg",
        deadline=today + timedelta(days=90),
    )
    await db_session.commit()

    goal = (await auth_client.get(WEIGHT)).json()["pace"]["goal"]
    assert goal is not None
    assert goal["target_kg"] == pytest.approx(80.0)
    assert goal["weeks"] is None or goal["weeks"] > 0


async def test_weight_dose_change_is_unknown_after_a_single_weighing(auth_client, db_session):
    today = today_local()
    await glp1_service.add_dose_phase(
        db_session, start_date=today - timedelta(days=5), drug=Drug.SEMAGLUTIDE.value, dose_mg=0.5
    )
    await weight_service.log_weight(db_session, on_date=today, weight_kg=88.0)
    await db_session.commit()

    dose = (await auth_client.get(WEIGHT)).json()["pace"]["dose"]

    assert dose is not None
    assert dose["delta_kg"] is None  # one reading is no change: never "0" or a made-up one
    assert dose["drug"] == Drug.SEMAGLUTIDE.value
    assert dose["dose_mg"] == pytest.approx(0.5)
    # The screen words the drug and the dose in its own language: the API sends no ready label.
    assert "label" not in dose


async def test_weight_dose_change_is_real_with_two_weighings(auth_client, db_session):
    today = today_local()
    await glp1_service.add_dose_phase(
        db_session, start_date=today - timedelta(days=5), drug=Drug.SEMAGLUTIDE.value, dose_mg=0.5
    )
    await weight_service.log_weight(db_session, on_date=today - timedelta(days=5), weight_kg=89.0)
    await weight_service.log_weight(db_session, on_date=today, weight_kg=88.0)
    await db_session.commit()

    dose = (await auth_client.get(WEIGHT)).json()["pace"]["dose"]

    assert dose["delta_kg"] == pytest.approx(-1.0)


async def test_last_scan_units_follow_the_language(auth_client, db_session, redis):
    state = await modules_service.set_module_enabled(db_session, key="body_comp", enabled=True)
    await db_session.commit()
    await modules_service.prime_cache(redis, state)
    await _english(db_session, redis)
    payload = {
        "date": today_local().isoformat(),
        "device": "InBody 770",
        "override": False,
        "metrics": [
            {"metric_key": "skeletal_muscle_mass", "label": "Скелетная масса", "value": 39.0, "unit": "кг", "category": "composition"},
            {"metric_key": "visceral_fat_area", "label": "Висцеральный жир", "value": 90.0, "unit": "см²", "category": "composition"},
        ],
    }
    assert (await auth_client.post(f"{WEIGHT}/body-scans/confirm", json=payload)).status_code == 200

    rows = (await auth_client.get(WEIGHT)).json()["last_scan"]["rows"]
    units = {r["label"]: r["unit"] for r in rows}

    assert units["Visceral Fat Area"] == "cm²"


def test_display_unit_reads_in_the_screens_language_whatever_the_device_printed():
    assert body_metrics.display_unit("skeletal_muscle_mass", "en") == "kg"
    assert body_metrics.display_unit("skeletal_muscle_mass", "ru") == "кг"
    assert body_metrics.display_unit("visceral_fat_area", "en") == "cm²"
    assert body_metrics.display_unit("visceral_fat_area", "ru") == "см²"
    # A stored row carries the unit its sheet printed; either spelling maps onto one key.
    assert body_metrics.display_unit(None, "en", "кг") == "kg"
    assert body_metrics.display_unit(None, "ru", "kg") == "кг"
    assert body_metrics.display_unit(None, "en", "л") == "l"
    assert body_metrics.display_unit(None, "en", "кг/м²") == "kg/m²"
    assert body_metrics.display_unit(None, "en", "ккал/м²") == "kcal/m²"
    assert body_metrics.display_unit(None, "ru", "%") == "%"


def test_display_unit_leaves_a_device_specific_unit_as_it_is_and_says_nothing_without_one():
    assert body_metrics.display_unit("body_fat_pct", "en", "ур.") == "ур."
    assert body_metrics.display_unit(None, "en") == ""
    assert body_metrics.display_unit("no_such_metric", "en") == ""


# ── /api/v1/glp1 ─────────────────────────────────────────────────────────────


async def test_glp1_says_nothing_until_an_injection_is_logged(auth_client):
    data = (await auth_client.get(GLP1)).json()

    assert data["drug"] is None
    assert data["doseMg"] is None
    assert data["sinceIso"] is None
    assert data["dayOnDose"] is None
    assert data["deltaOnDoseKg"] is None
    assert data["cycle"]["nextIso"] is None
    assert data["cycle"]["daysToNext"] is None
    assert "summary" not in data


async def test_glp1_site_names_follow_the_language(auth_client, db_session, redis):
    await _english(db_session, redis)

    labels = (await auth_client.get(GLP1)).json()["siteLabels"]

    assert labels["shoulder_left"] == "Shoulder L"
    assert labels["abdomen_right"] == "Abdomen R"


# ── /api/v1/hrt ──────────────────────────────────────────────────────────────


async def test_hrt_labels_follow_the_language(auth_client, db_session, redis):
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    await _english(db_session, redis)
    await auth_client.post(
        f"{HRT}/doses",
        json={"date": today_local().isoformat(), "compoundKey": "testosterone_enanthate", "dose": 250.0, "unit": "mg", "site": "delt_left"},
    )

    data = (await auth_client.get(HRT)).json()

    assert data["siteLabels"]["delt_left"] == "Delt L"
    assert data["siteLabels"]["ventroglute_right"] == "Ventrogluteal R"
    assert data["siteLabels"]["vastus_lateralis_left"] == "VL L"
    assert not any(ord(ch) > 0x400 for ch in "".join(data["siteLabels"].values()))
    name = data["doses"][0]["name"]
    assert name.isascii(), f"English screen got a non-English compound name: {name!r}"


async def test_hrt_labels_are_russian_in_russian(auth_client, db_session, redis):
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()

    data = (await auth_client.get(HRT)).json()

    assert data["siteLabels"]["delt_left"] == "Дельта Л"
    assert data["siteLabels"]["vastus_lateralis_right"] == "ВЛБ П"


# ── /api/v1/recovery ─────────────────────────────────────────────────────────


def _day(resting_hr: int | None) -> GarminDaily:
    return GarminDaily(
        date=today_local(),
        domain=GARMIN_DOMAIN,
        source=Source.GARMIN_API.value,
        sleep_score=85,
        hrv_avg=55.0,
        resting_hr=resting_hr,
    )


async def _seed_history(db_session) -> None:
    """Twenty earlier days whose own corridors come out as sleep 80–90, HRV 50–60
    and resting pulse 48–58 (mean give or take one deviation)."""
    for i in range(1, 21):
        low = i % 2 == 1
        db_session.add(
            GarminDaily(
                date=today_local() - timedelta(days=i),
                domain=GARMIN_DOMAIN,
                source=Source.GARMIN_API.value,
                sleep_score=80 if low else 90,
                hrv_avg=50.0 if low else 60.0,
                resting_hr=48 if low else 58,
            )
        )
    await db_session.commit()


async def test_recovery_norm_units_are_codes(auth_client, db_session):
    await _seed_history(db_session)
    norms = (await auth_client.get(RECOVERY)).json()["norms"]

    assert norms["hrv"]["unit"] == "ms"
    assert norms["rhr"]["unit"] == "bpm"
    assert norms["sleep"]["unit"] == ""


@pytest.mark.parametrize(
    ("resting_hr", "note"),
    [(52, "normal"), (56, "upper"), (62, "above"), (44, "below"), (None, "")],
)
async def test_recovery_resting_pulse_note_is_a_code(auth_client, db_session, resting_hr, note):
    await _seed_history(db_session)
    db_session.add(_day(resting_hr))
    await db_session.commit()

    assert (await auth_client.get(RECOVERY)).json()["headline"]["rhr_note"] == note


async def test_recovery_invents_no_bedtime(auth_client, db_session):
    row = _day(52)
    row.sleep_seconds = 7 * 3600  # slept, but the watch did not say when
    db_session.add(row)
    await db_session.commit()

    night = (await auth_client.get(RECOVERY)).json()["night"]

    assert night["start"] == ""
    assert night["end"] == ""


# ── /api/v1/supplements ──────────────────────────────────────────────────────


async def test_supplement_slots_follow_the_language(auth_client, db_session, redis):
    await auth_client.post(SUPPLEMENTS, json={"name": "Creatine", "dose": "5 g", "timing": "morning", "active": True})

    ru = {g["key"]: g for g in (await auth_client.get(SUPPLEMENTS)).json()["groups"]}
    assert ru["morning"]["label"] == "Утро"
    assert ru["morning"]["sub"] == "с первым приёмом пищи"
    assert ru["evening"]["sub"] == "перед сном"

    await _english(db_session, redis)
    en = {g["key"]: g for g in (await auth_client.get(SUPPLEMENTS)).json()["groups"]}
    assert en["morning"]["label"] == "Morning"
    assert en["morning"]["sub"] == "with the first meal"
    assert en["day"]["sub"] == "through the day"
    assert en["evening"]["sub"] == "before bed"


# ── the header of "Today", and the dictionary behind the timeline ────────────


def test_the_calories_of_the_header_are_said_the_way_the_tile_shows_them():
    assert _whole(1316.5) == "1 317"
    assert _whole(1316.4) == "1 316"
    assert _whole(950) == "950"
    assert _whole(0) == "0"
    assert _whole("n/a") == "n/a"


@pytest.mark.parametrize("lang", sorted(STRINGS))
@pytest.mark.parametrize("kind", [k.value for k in AnnotationKind])
def test_every_annotation_kind_has_its_name_in_both_languages(kind, lang):
    assert f"app.timeline.kind.{kind}" in STRINGS[lang]


# ── /api/v1/skincare ─────────────────────────────────────────────────────────


async def test_a_rule_without_a_category_is_filed_under_a_code_not_a_russian_word(db_session):
    db_session.add(
        ConflictRule(
            rule_type="hard_block",
            domain_a="skincare",
            condition_a={},
            domain_b="skincare",
            condition_b={},
            severity="block",
            message="Not together.",
            category=None,
            active=True,
        )
    )
    await db_session.commit()

    rules = (await skincare_service.collect(db_session))["rules"]

    assert [r["kind"] for r in rules] == ["other"]
    assert f"app.rule_cat.{rules[0]['kind']}" in STRINGS["ru"]
    assert f"app.rule_cat.{rules[0]['kind']}" in STRINGS["en"]
