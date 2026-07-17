"""Tests for the data-portability service + settings routes.

Round-trip fidelity (export → wipe+import → export gives the same snapshot),
idempotency, FK integrity across the Hevy tree, strict validation (clean errors,
no silent failures), secret exclusion, and the curated LLM export shape. The
Postgres sequence-reset behaviour is an ``@pytest.mark.integration`` test (SQLite
can't exercise it).
"""
import json
from datetime import date, datetime

import pytest

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
    r = await auth_client.get("/settings/export")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    assert "vitals_backup_" in r.headers["content-disposition"]
    data = r.json()
    assert data["metadata"]["kind"] == "full_backup"
    assert "weight_logs" in data


async def test_export_llm_endpoint_downloads_digest(auth_client, db_session):
    await _seed(db_session)
    r = await auth_client.get("/settings/export-llm")
    assert r.status_code == 200
    assert "vitals_llm_" in r.headers["content-disposition"]
    data = r.json()
    assert "profile" in data
    assert "raw_payloads" not in data


async def test_import_endpoint_restores_and_reports(auth_client, db_session):
    await _seed(db_session)
    snap = await export_full(db_session)
    files = {"backup_file": ("backup.json", json.dumps(snap).encode(), "application/json")}
    r = await auth_client.post("/settings/import", files=files)
    assert r.status_code == 200
    assert "Импортировано" in r.text


async def test_import_endpoint_rejects_bad_json(auth_client):
    files = {"backup_file": ("bad.json", b"{not valid json", "application/json")}
    r = await auth_client.post("/settings/import", files=files)
    assert r.status_code == 400
    assert "JSON" in r.json()["detail"]


async def test_import_endpoint_rejects_wrong_extension(auth_client):
    files = {"backup_file": ("data.csv", b"a,b,c", "text/csv")}
    r = await auth_client.post("/settings/import", files=files)
    assert r.status_code == 415
