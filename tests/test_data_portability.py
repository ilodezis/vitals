"""Tests for the data-portability service + settings routes.

Round-trip fidelity (export → wipe+import → export gives the same snapshot),
idempotency, FK integrity across the Hevy tree, strict validation (clean errors,
no silent failures), secret exclusion, and the curated LLM export shape. The
Postgres sequence-reset behaviour is an ``@pytest.mark.integration`` test (SQLite
can't exercise it).
"""
import json
from datetime import date, datetime, timedelta, timezone

import pytest

from vitals.enums import Domain
from vitals.models.app_settings import AppSetting
from vitals.models.garmin import GarminActivity, GarminDaily, GarminIntraday
from vitals.models.glp1 import Injection
from vitals.models.hevy import HevyExercise, HevySet, HevyWorkout
from vitals.models.labs import LabResult
from vitals.models.raw_payload import RawPayload
from vitals.models.supplements import Supplement
from vitals.models.weight import BodyMeasurement, WeightLog
from vitals.services.data_portability_service import (
    PortabilityError,
    export_full,
    export_llm,
    import_full,
)


async def _seed(session) -> None:
    """Populate a few rows across domains, including a raw payload + FK link, a
    superseded weight, the Hevy tree, and a secret-looking app setting."""
    rp = RawPayload(domain="garmin", source="garmin_api", external_id="g1", payload={"steps": 8000})
    session.add(rp)
    await session.flush()  # need rp.id for the FK link below

    session.add_all(
        [
            # Two weights on one date: a superseded Garmin row + the active manual one.
            WeightLog(
                date=date(2026, 4, 29), domain="weight", source="garmin_api",
                weight_kg=119.1, raw_payload_id=rp.id, superseded=True,
            ),
            WeightLog(
                date=date(2026, 4, 29), domain="weight", source="manual",
                weight_kg=118.5, superseded=False, note="утро",
            ),
            BodyMeasurement(
                date=date(2026, 4, 29), domain="weight", source="manual",
                waist_cm=100.0, neck_cm=42.0,
            ),
            Injection(
                date=date(2026, 4, 28), domain="glp1", source="manual",
                drug="tirzepatide", dose_mg=5.0, site="abdomen_left",
            ),
            GarminDaily(
                date=date(2026, 4, 29), domain="garmin", source="garmin_api",
                raw_payload_id=rp.id, steps=8000, sleep_seconds=27000,
                sleep_score=80, resting_hr=55,
                # The night's interval series — JSONB round-trip stability.
                sleep_stages=[
                    {"start": "2026-04-28T23:00:00", "end": "2026-04-28T23:30:00", "stage": "light"},
                    {"start": "2026-04-28T23:30:00", "end": "2026-04-29T01:00:00", "stage": "deep"},
                ],
                breathing_events=[
                    {"start": "2026-04-28T23:00:00", "end": "2026-04-29T01:00:00", "value": 0},
                ],
            ),
            # Per-activity detail — exercises JSONB round-trip stability.
            GarminActivity(
                date=date(2026, 4, 29), domain="garmin", source="garmin_api",
                external_id="act1", activity_type="running", name="Run",
                elevation_gain_m=42.0, training_effect_aerobic=3.4,
                hr_zone_seconds=[{"zone": 1, "secs": 120.0, "low_hr": 101}],
                splits=[{"index": 1, "distance_m": 1000.0, "avg_hr": 150}],
            ),
            # Intraday samples — the tall series table backing the daily scalars.
            GarminIntraday(
                date=date(2026, 4, 29), domain="garmin", source="garmin_api",
                raw_payload_id=rp.id, series_type="stress",
                ts=datetime(2026, 4, 29, 8, 0), value=43.0,
            ),
            GarminIntraday(
                date=date(2026, 4, 29), domain="garmin", source="garmin_api",
                raw_payload_id=rp.id, series_type="body_battery",
                ts=datetime(2026, 4, 29, 8, 0), value=72.0,
            ),
            # A nightly series, timestamped the evening before the date it's filed
            # under — the backup must not "helpfully" re-date it.
            GarminIntraday(
                date=date(2026, 4, 29), domain="garmin", source="garmin_api",
                raw_payload_id=rp.id, series_type="sleep_hr",
                ts=datetime(2026, 4, 28, 23, 10), value=58.0,
            ),
            LabResult(
                date=date(2026, 4, 1), domain="labs", source="lab_parser",
                marker="glucose", value=5.1, unit="mmol/L", ref_low=3.9, ref_high=5.5,
                flag="normal",
            ),
            Supplement(
                domain="supplements", source="manual", name="Omega-3", key="omega3",
                dose="2g", evidence="A", active=True,
            ),
            AppSetting(key="ui_pref", value={"theme": "dim"}),
            AppSetting(key="garmin_oauth_token", value="super-secret-xyz"),
        ]
    )
    await session.flush()

    w = HevyWorkout(
        date=date(2026, 4, 27), domain="workouts", source="hevy_api",
        external_id="w1", title="Push", program="A", duration_seconds=3600,
    )
    session.add(w)
    await session.flush()
    ex = HevyExercise(workout_id=w.id, exercise_index=0, title="Bench Press", exercise_template_id="bp")
    session.add(ex)
    await session.flush()
    session.add_all(
        [
            HevySet(exercise_id=ex.id, set_index=0, set_type="normal", weight_kg=80.0, reps=8, rpe=8.0),
            HevySet(exercise_id=ex.id, set_index=1, set_type="normal", weight_kg=80.0, reps=7),
        ]
    )
    await session.commit()


def _normalize(snapshot: dict) -> dict:
    """Snapshot minus the (timestamped) metadata, with each table's rows sorted so
    the comparison is order-insensitive."""
    out = {}
    for key, rows in snapshot.items():
        if key == "metadata":
            continue
        out[key] = sorted(rows, key=lambda r: json.dumps(r, sort_keys=True, default=str))
    return out


# ── Full backup round-trip ─────────────────────────────────────────────────────


async def test_full_roundtrip_replace_is_stable(db_session):
    await _seed(db_session)
    snap1 = await export_full(db_session)

    # Replace the whole DB from the snapshot, then re-export.
    stats = await import_full(db_session, snap1)
    await db_session.flush()
    snap2 = await export_full(db_session)

    assert _normalize(snap1) == _normalize(snap2)
    assert snap1["metadata"]["kind"] == "full_backup"
    # Both weight rows survive (active + superseded); the Hevy tree is intact.
    assert stats.counts["weight_logs"] == 2
    assert stats.counts["hevy_exercises"] == 1
    assert stats.counts["hevy_sets"] == 2
    # The intraday series is in the backup (it rides the generic sorted_tables
    # walk, so this guards the walk actually reaching new tables) — whole-day and
    # nightly series alike.
    assert stats.counts["garmin_intraday"] == 3
    assert {r["series_type"] for r in snap1["garmin_intraday"]} == {
        "stress", "body_battery", "sleep_hr",
    }
    # The night's interval series survive as structure, not as a stringified blob.
    daily = snap1["garmin_daily"][0]
    assert [s["stage"] for s in daily["sleep_stages"]] == ["light", "deep"]
    assert daily["breathing_events"][0]["value"] == 0


async def test_import_is_idempotent(db_session):
    await _seed(db_session)
    snap = await export_full(db_session)

    await import_full(db_session, snap)
    await db_session.flush()
    await import_full(db_session, snap)  # second run must not duplicate or fail
    await db_session.flush()

    after = await export_full(db_session)
    assert _normalize(snap) == _normalize(after)


async def test_import_preserves_fk_links(db_session):
    await _seed(db_session)
    snap = await export_full(db_session)
    await import_full(db_session, snap)
    await db_session.flush()

    # The Hevy set → exercise → workout chain and the weight → raw_payload link
    # must still resolve after the id-preserving restore.
    from sqlalchemy import select

    sets = (await db_session.execute(select(HevySet))).scalars().all()
    exercises = {e.id for e in (await db_session.execute(select(HevyExercise))).scalars().all()}
    workouts = {w.id for w in (await db_session.execute(select(HevyWorkout))).scalars().all()}
    assert sets and all(s.exercise_id in exercises for s in sets)

    exrows = (await db_session.execute(select(HevyExercise))).scalars().all()
    assert all(e.workout_id in workouts for e in exrows)

    raw_ids = {r.id for r in (await db_session.execute(select(RawPayload))).scalars().all()}
    linked = (
        await db_session.execute(select(WeightLog).where(WeightLog.raw_payload_id.isnot(None)))
    ).scalars().all()
    assert linked and all(w.raw_payload_id in raw_ids for w in linked)


# ── Validation (clean 400s, never silent) ──────────────────────────────────────


async def test_import_rejects_non_object(db_session):
    with pytest.raises(PortabilityError):
        await import_full(db_session, ["not", "a", "dict"])


async def test_import_rejects_missing_metadata(db_session):
    with pytest.raises(PortabilityError, match="metadata"):
        await import_full(db_session, {"weight_logs": []})


async def test_import_rejects_unknown_table(db_session):
    payload = {"metadata": {"version": "1.0"}, "not_a_real_table": [{"x": 1}]}
    with pytest.raises(PortabilityError, match="(Неизвестн|Unknown)"):
        await import_full(db_session, payload)


async def test_import_rejects_non_list_section(db_session):
    payload = {"metadata": {"version": "1.0"}, "weight_logs": {"oops": True}}
    with pytest.raises(PortabilityError, match="(списком|list)"):
        await import_full(db_session, payload)


# ── Secret exclusion ───────────────────────────────────────────────────────────


async def test_export_excludes_secret_settings(db_session):
    await _seed(db_session)
    snap = await export_full(db_session)
    keys = {row["key"] for row in snap["app_settings"]}
    assert "ui_pref" in keys
    assert "garmin_oauth_token" not in keys  # dropped by the secret guard


# ── LLM export shape ───────────────────────────────────────────────────────────


async def test_llm_export_is_clean(db_session):
    await _seed(db_session)
    out = await export_llm(db_session)

    # No raw dumps, no service tables.
    assert "raw_payloads" not in out
    assert "system_alerts" not in out
    # Profile header present.
    assert "profile" in out and "exported_at" in out["profile"]
    # Only the active weight (superseded row excluded), and no internal ids leak.
    assert len(out["weight_history"]) == 1
    assert out["weight_history"][0]["weight_kg"] == 118.5
    assert all("id" not in row for row in out["weight_history"])
    # Biomarkers + nested workouts present.
    assert out["biomarkers"][0]["marker"] == "glucose"
    assert out["workouts"][0]["exercises"][0]["title"] == "Bench Press"
    assert out["workouts"][0]["exercises"][0]["sets"][0]["weight_kg"] == 80.0
    # body_comp key always present (empty here — the seed has no scan).
    assert out["body_scans"] == []


async def test_llm_export_includes_full_garmin_rows(db_session):
    """The Garmin blocks used to be a hand-picked dozen fields out of ~45, so sleep
    phases, HR zones and splits never reached the AI export. Both rows now go out
    whole — minus ids/plumbing."""
    await _seed(db_session)
    out = await export_llm(db_session)

    daily = out["garmin_daily"][0]
    assert daily["date"] == "2026-04-29"
    assert daily["sleep_seconds"] == 27000
    assert [s["stage"] for s in daily["sleep_stages"]] == ["light", "deep"]
    assert daily["breathing_events"][0]["value"] == 0
    # Plumbing stays out.
    assert not {"id", "raw_payload_id", "domain", "source"} & set(daily)

    act = out["garmin_activities"][0]
    assert act["activity_type"] == "running"
    assert act["elevation_gain_m"] == 42.0
    assert act["training_effect_aerobic"] == 3.4
    assert act["hr_zone_seconds"][0]["secs"] == 120.0
    assert act["splits"][0]["distance_m"] == 1000.0
    assert not {"id", "external_id", "raw_payload_id"} & set(act)


async def test_llm_export_includes_body_scans(db_session):
    """D3: the body_comp domain (BIA/InBody scans + every captured metric) must
    appear in the curated LLM export — previously it was dropped entirely."""
    from vitals.models.body_scan import BodyScan, BodyScanMetric

    scan = BodyScan(
        date=date(2026, 4, 20), domain="body_comp", source="body_scan", device="InBody 770"
    )
    db_session.add(scan)
    await db_session.flush()
    db_session.add_all(
        [
            BodyScanMetric(
                scan_id=scan.id, metric_key="body_fat_pct", label="Percent Body Fat",
                value=18.5, unit="%", category="composition",
            ),
            BodyScanMetric(
                scan_id=scan.id, metric_key="skeletal_muscle_mass", label="SMM",
                value=42.0, unit="кг", category="composition",
            ),
        ]
    )
    await db_session.commit()

    out = await export_llm(db_session)
    assert len(out["body_scans"]) == 1
    block = out["body_scans"][0]
    assert block["date"] == "2026-04-20"
    assert block["device"] == "InBody 770"
    metrics = {m["metric"]: m["value"] for m in block["metrics"]}
    assert metrics == {"body_fat_pct": 18.5, "skeletal_muscle_mass": 42.0}


async def test_llm_export_since_keeps_open_periods_and_catalogs(db_session):
    """``since`` narrows the digest for the MCP tool. Two things must survive the cut
    regardless of when they started: a period still running today (an open dose
    phase), and the catalogs, which are current state rather than history."""
    from vitals.services import glp1_service, supplements_service

    await glp1_service.add_dose_phase(
        db_session, start_date=date(2020, 1, 1), drug="semaglutide", dose_mg=1.0
    )
    await glp1_service.add_dose_phase(
        db_session, start_date=date(2019, 1, 1), end_date=date(2019, 6, 1),
        drug="semaglutide", dose_mg=0.5,
    )
    await supplements_service.add_supplement(db_session, name="Creatine")
    await db_session.commit()

    out = await export_llm(db_session, since=date(2026, 1, 1))
    assert [p["dose_mg"] for p in out["glp1_dose_phases"]] == [1.0]  # open phase kept
    assert [s["name"] for s in out["supplements"]] == ["Creatine"]

    # And with no arguments the export is still the whole history (the web download).
    full = await export_llm(db_session)
    assert len(full["glp1_dose_phases"]) == 2


# ── Every domain reaches the LLM export ────────────────────────────────────────
#
# ``export_llm`` is a long hand-written function, and its real failure mode isn't
# its length — it's that a new domain gets added to ``Domain`` and nobody
# remembers to give it a block, so the AI report silently loses a whole module.
# The map below is the contract: every enum member names the export key(s) it must
# fill. Adding a Domain member without touching this map fails immediately.

DOMAIN_EXPORT_KEYS: dict[Domain, tuple[str, ...]] = {
    Domain.WEIGHT: ("weight_history", "body_measurements", "noise_periods"),
    Domain.BODY_COMPOSITION: ("body_scans",),
    Domain.GLP1: ("glp1_injections", "glp1_dose_phases", "glp1_side_effects"),
    Domain.HRT: ("hrt_doses", "hrt_cycles", "hrt_side_effects", "hrt_cycle_templates"),
    Domain.LABS: ("biomarkers",),
    Domain.WORKOUTS: ("workouts",),
    Domain.GARMIN: ("garmin_daily", "garmin_activities"),
    Domain.NUTRITION: ("nutrition",),
    Domain.SUPPLEMENTS: ("supplements",),
    Domain.GENETICS: ("genetics",),
    Domain.SKINCARE: ("skincare_logs", "skincare_observations"),
    Domain.MILESTONES: ("milestones", "weekly_digests"),
    Domain.TIMELINE: ("timeline_annotations",),
    Domain.SIGNALS: ("signals", "day_context"),
    Domain.ENVIRONMENT: ("environment_nights", "environment_hours"),
    # Infra/alert rows — deliberately excluded from a digest meant for a chat
    # window (test_llm_export_is_clean pins that they stay out).
    Domain.SYSTEM: (),
}


def test_every_domain_is_mapped_to_export_keys():
    """A new Domain member must be given an export block (or an explicit empty
    tuple saying it's intentionally not exported)."""
    assert set(DOMAIN_EXPORT_KEYS) == set(Domain)


async def _seed_every_domain(session) -> None:
    """One row per domain — the domains _seed/_seed_hrt don't already cover."""
    from vitals.models.body_scan import BodyScan, BodyScanMetric
    from vitals.models.environment import EnvironmentHourly, EnvironmentSample
    from vitals.models.genetics import GeneticVariant
    from vitals.models.glp1 import DosePhase, SideEffect
    from vitals.models.milestones import Milestone, WeeklyDigest
    from vitals.models.nutrition import MealLog
    from vitals.models.signals import DayContext, Signal
    from vitals.models.skincare import SkincareLog, SkincareObservation
    from vitals.models.timeline import Annotation
    from vitals.models.weight import NoiseMarker

    await _seed(session)
    await _seed_hrt(session)

    d = date(2026, 4, 25)
    scan = BodyScan(date=d, domain="body_comp", source="body_scan", device="InBody 770")
    session.add(scan)
    await session.flush()
    session.add_all(
        [
            BodyScanMetric(
                scan_id=scan.id, metric_key="body_fat_pct", label="Percent Body Fat",
                value=18.5, unit="%", category="composition",
            ),
            NoiseMarker(
                domain="weight", source="manual", start_date=d, reason="креатин",
            ),
            DosePhase(
                domain="glp1", source="manual", start_date=d, drug="tirzepatide", dose_mg=5.0,
            ),
            SideEffect(
                date=d, domain="glp1", source="manual", effect_type="nausea", severity=1,
            ),
            GeneticVariant(
                domain="genetics", source="vcf_import", gene="MTHFR", rsid="rs1801133",
                genotype="CT", impact="Фолатный цикл", impact_domain="supplements",
            ),
            SkincareLog(date=d, domain="skincare", source="manual", retinoid=True),
            SkincareObservation(
                date=d, domain="skincare", source="manual", inflammation=2, zone="лоб",
            ),
            MealLog(
                date=d, domain="nutrition", source="manual", name="Курица с рисом",
                calories=520, protein_g=45,
            ),
            Milestone(domain="weight", name="100 кг", target_value=100.0, target_unit="кг"),
            WeeklyDigest(
                date=d, domain="milestones", source="manual", content="Неделя прошла ровно.",
            ),
            Annotation(
                date=d, domain="timeline", source="manual", kind="travel", title="Поездка",
            ),
            Signal(
                date=d, domain="signals", source="telegram", kind="symptom",
                key="head_ache", value_num=4, batch_id="b1", note="голова раскалывается",
            ),
            DayContext(
                date=d, domain="signals", source="manual", answers={"remote": True},
            ),
            EnvironmentSample(
                date=d, domain="environment", source="esphome", station_id="bedroom", boot_id="b0",
                seq=1, ts=datetime(2026, 4, 24, 23, 0, tzinfo=timezone.utc),  # 02:00 local on d
                received_at=datetime(2026, 4, 24, 23, 0, 2, tzinfo=timezone.utc), co2_ppm=900,
            ),
            EnvironmentHourly(
                date=d, domain="environment", source="esphome", station_id="bedroom",
                hour_start=datetime(2026, 4, 24, 23, 0, tzinfo=timezone.utc), sample_count=360,
                coverage_pct=100.0, co2_mean=900.0,
            ),
        ]
    )
    await session.commit()


async def test_llm_export_covers_every_domain(db_session, monkeypatch):
    """With one row seeded per domain, every mapped export key must be non-empty —
    the test that fails when a domain is added but never wired into export_llm."""
    from vitals.services.environment import queries
    from vitals.services.environment.types import Co2Stats, NightSummary, Window

    # The storage layer's own night summary is tested with it; here it only has to
    # find the seeded night so the export's wiring is what is being checked.
    async def one_night(session, on_date, *, station_id="bedroom"):
        stamp = datetime(on_date.year, on_date.month, on_date.day, tzinfo=timezone.utc)
        return NightSummary(
            date=on_date, window=Window(start=stamp, end=stamp), samples=1, co2=Co2Stats(max=900.0)
        )

    monkeypatch.setattr(queries, "night_summary", one_night)
    await _seed_every_domain(db_session)
    out = await export_llm(db_session)

    empty = [
        key
        for domain, keys in DOMAIN_EXPORT_KEYS.items()
        for key in keys
        if not out.get(key)
    ]
    assert not empty, f"domains missing from the LLM export: {empty}"


async def test_llm_export_folds_signal_key_aliases(db_session):
    """The export ships canonical keys — otherwise the model sees 'head_ache' and
    'headache' as two unrelated things and the correlation is split in half."""
    from vitals.models.signals import Signal

    d = date(2026, 4, 25)
    db_session.add_all([
        Signal(date=d, domain="signals", source="telegram", kind="symptom",
               key="head_ache", batch_id="b1"),
        Signal(date=d, domain="signals", source="telegram", kind="symptom",
               key="headache", batch_id="b2"),
        # A cancelled batch stays out of the export entirely.
        Signal(date=d, domain="signals", source="telegram", kind="state",
               key="sleepiness", batch_id="b3", misparse=True),
    ])
    await db_session.commit()

    out = await export_llm(db_session)
    assert [s["key"] for s in out["signals"]] == ["headache", "headache"]


# ── Postgres sequence reset (real DB only) ─────────────────────────────────────


@pytest.mark.integration
async def test_import_resets_postgres_sequences(db_session):
    await _seed(db_session)
    snap = await export_full(db_session)
    await import_full(db_session, snap)
    await db_session.flush()

    # After restoring rows with explicit ids, a normal insert (no id) must get a
    # fresh id past the restored max — i.e. the identity sequence was advanced.
    db_session.add(
        WeightLog(date=date(2099, 1, 1), domain="weight", source="manual", weight_kg=100.0)
    )
    await db_session.flush()  # would raise duplicate-PK without the sequence reset


# ── Web routes ─────────────────────────────────────────────────────────────────


async def test_export_endpoint_downloads_backup(auth_client, db_session):
    await _seed(db_session)
    r = await auth_client.get("/api/v1/settings/export")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    assert "vitals_backup_" in r.headers["content-disposition"]
    data = r.json()
    assert data["metadata"]["kind"] == "full_backup"
    assert "weight_logs" in data


async def test_export_llm_endpoint_downloads_digest(auth_client, db_session):
    await _seed(db_session)
    r = await auth_client.get("/api/v1/settings/export-llm")
    assert r.status_code == 200
    assert "vitals_llm_" in r.headers["content-disposition"]
    data = r.json()
    assert "profile" in data
    assert "raw_payloads" not in data


async def test_import_endpoint_restores_and_reports(auth_client, db_session):
    await _seed(db_session)
    snap = await export_full(db_session)
    files = {"backup_file": ("backup.json", json.dumps(snap).encode(), "application/json")}
    r = await auth_client.post("/api/v1/settings/import", files=files)
    assert r.status_code == 200
    body = r.json()
    assert body["restored"] is True
    assert "Импортировано" in body["summary"]


async def test_import_endpoint_rejects_bad_json(auth_client):
    files = {"backup_file": ("bad.json", b"{not valid json", "application/json")}
    r = await auth_client.post("/api/v1/settings/import", files=files)
    assert r.status_code == 400
    assert "JSON" in r.json()["detail"]


async def test_import_endpoint_rejects_wrong_extension(auth_client):
    files = {"backup_file": ("data.csv", b"a,b,c", "text/csv")}
    r = await auth_client.post("/api/v1/settings/import", files=files)
    assert r.status_code == 415


# ── HRT in the exports (PR #7 review item) ────────────────────────────────────
async def _seed_hrt(session):
    from vitals.services import hrt_catalog, hrt_cycle_service, hrt_service, hrt_template_service
    from vitals.utils.timeutils import today_local

    await hrt_catalog.sync_catalog(session)
    await hrt_service.log_dose(
        session, compound_key="testosterone_enanthate", on_date=today_local(),
        dose=250, unit="mg", brand="TestBrand", lab="UGL",
    )
    await hrt_service.log_side_effect(
        session, on_date=today_local(), effect_type="acne", severity=2,
    )
    cycle = await hrt_cycle_service.add_cycle(
        session, kind="course", start_date=today_local(), name="Cut",
    )
    await hrt_cycle_service.add_cycle_item(
        session, cycle.id, compound_key="stanozolol_oral",
        schedule=[{"dose": 30, "interval_days": 1, "duration_days": 28}],
        start_offset_days=28,
    )
    await hrt_template_service.save_cycle_as_template(session, cycle.id, name="Cut tpl")
    await session.commit()


async def test_llm_export_includes_hrt(db_session):
    await _seed_hrt(db_session)
    out = await export_llm(db_session)
    assert out["hrt_doses"][0]["compound"] == "testosterone_enanthate"
    assert out["hrt_doses"][0]["brand"] == "TestBrand"
    assert out["hrt_side_effects"][0]["effect_type"] == "acne"
    cycle = out["hrt_cycles"][0]
    assert cycle["kind"] == "course"
    assert cycle["items"][0]["start_offset_days"] == 28
    tpl = out["hrt_cycle_templates"][0]
    assert tpl["name"] == "Cut tpl" and tpl["items"][0]["compound"] == "stanozolol_oral"


async def test_full_backup_round_trips_hrt(db_session):
    """The generic full backup must carry every HRT table through wipe+restore."""
    from sqlalchemy import func, select
    from vitals.models.hrt import HrtCycle, HrtCycleItem, HrtCycleTemplate, HrtDose

    await _seed_hrt(db_session)
    snapshot = await export_full(db_session)
    for table in ("hrt_doses", "hrt_cycles", "hrt_cycle_items",
                  "hrt_side_effects", "hrt_cycle_templates", "hrt_cycle_template_items"):
        assert snapshot.get(table), f"{table} missing from full backup"

    stats = await import_full(db_session, snapshot)  # wipe + reload
    await db_session.commit()
    assert stats.counts["hrt_doses"] == 1
    dose = (await db_session.execute(select(HrtDose))).scalars().one()
    assert dose.brand == "TestBrand"
    item = (await db_session.execute(select(HrtCycleItem))).scalars().one()
    assert item.start_offset_days == 28 and item.schedule[0]["dose"] == 30
    assert (await db_session.execute(select(func.count(HrtCycle.id)))).scalar() == 1
    assert (await db_session.execute(select(func.count(HrtCycleTemplate.id)))).scalar() == 1


def test_import_summary_labels_signals_and_friends():
    """The newer domains must be named in the summary, not swallowed by the
    anonymous "and N more" tail."""
    from vitals.i18n import t
    from vitals.services.data_portability_service import ImportStats

    stats = ImportStats(counts={
        "signals": 3, "day_context": 2, "body_scans": 1,
        "milestones": 4, "noise_markers": 5,
    })
    summary = stats.summary()
    for table in ("signals", "day_context", "body_scans", "milestones", "noise_markers"):
        assert t("import.label." + table) in summary
    assert t("import.summary_extra", n=15) not in summary


@pytest.mark.asyncio
async def test_backup_neither_carries_nor_resurrects_shared_reports(db_session):
    """A published doctor report is an outward-facing artifact, not data to
    round-trip. The export must not carry its password hash and its full copy of
    the record, and — the half that is easy to forget — the import must not wipe
    or recreate one, or restoring a backup would republish links the owner had
    already revoked."""
    from sqlalchemy import select as sa_select

    from vitals.models.share import SharedReport
    from vitals.utils.timeutils import now_local

    db_session.add(
        SharedReport(
            token="tok-abc", password_hash="$2b$04$hash", title="Endocrinologist",
            domains=["labs"], period_start=date(2026, 3, 1), period_end=date(2026, 3, 30),
            snapshot={"blocks": {"labs": {"markers": [{"marker": "Ферритин"}]}}},
            expires_at=now_local() + timedelta(days=30),
        )
    )
    await db_session.commit()

    snapshot = await export_full(db_session)
    assert "shared_reports" not in snapshot
    assert "$2b$04$hash" not in json.dumps(snapshot, ensure_ascii=False)

    # An import wipes everything else; this row survives untouched.
    await import_full(db_session, snapshot)
    await db_session.commit()
    rows = (await db_session.execute(sa_select(SharedReport))).scalars().all()
    assert len(rows) == 1 and rows[0].token == "tok-abc"

    # And a file that *claims* to carry one plants nothing.
    forged = dict(snapshot)
    forged["shared_reports"] = [
        {
            "id": 999, "token": "planted", "password_hash": "x", "title": "planted",
            "domains": [], "period_start": "2026-01-01", "period_end": "2026-01-02",
            "labs_flagged_only": False, "snapshot": None,
            "expires_at": "2030-01-01T00:00:00", "opened_count": 0,
        }
    ]
    await import_full(db_session, forged)
    await db_session.commit()
    tokens = {
        r.token for r in (await db_session.execute(sa_select(SharedReport))).scalars().all()
    }
    assert tokens == {"tok-abc"}
