"""Data portability — full backup/restore + a curated LLM-ready export.

Two deliberately different shapes (they pull in opposite directions, so we don't
try to make one file serve both):

  * **Full backup** (:func:`export_full` / :func:`import_full`) — a faithful,
    machine-round-trippable snapshot of *every* table (including the ``raw_payloads``
    JSONB data-lake and internal ``id``s). Import runs **replace**: wipe every table
    and reload the file, preserving primary keys so foreign keys stay valid. The
    whole thing rides the request's single transaction — any error rolls the DB back
    to where it started (the router owns the commit; we only ``flush``).

  * **LLM export** (:func:`export_llm`) — a flat, human-readable digest the owner
    pastes straight into a chat (Claude/ChatGPT). No raw dumps, no ids, no service
    tables, no secrets, no superseded rows.

Design notes:
  * There are no per-table Pydantic schemas in this project, so the backup walks
    the ORM generically via ``Base.metadata.sorted_tables`` (already FK-ordered).
    That auto-captures every new metric as the schema grows — the maximal-capture
    principle. Only the ``metadata`` envelope gets a Pydantic model.
  * ``app_settings`` rows whose key looks like a credential are dropped from the
    backup so the file can't leak tokens. (Real secrets live in ``.env``, which the
    DB export never touches — this is defence in depth for any future token row.)
  * Photo binaries are *not* in the backup — ``progress_photos`` rows carry only the
    ``file_key`` reference (files live on disk). Restore brings back the rows, not
    the images.
"""
from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import Date, DateTime, Time, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from vitals.models.base import Base
from vitals.models.body_scan import BodyScan
from vitals.models.garmin import GarminActivity, GarminDaily
from vitals.models.genetics import GeneticVariant
from vitals.models.glp1 import DosePhase, Injection, SideEffect
from vitals.models.hevy import HevyExercise, HevySet, HevyWorkout
from vitals.models.hrt import HrtCycle, HrtCycleTemplate, HrtDose, HrtSideEffect
from vitals.models.labs import LabResult
from vitals.models.milestones import Milestone, WeeklyDigest
from vitals.models.nutrition import MealLog
from vitals.models.skincare import SkincareLog, SkincareObservation
from vitals.models.supplements import Supplement
from vitals.models.timeline import Annotation
from vitals.models.weight import BodyMeasurement, NoiseMarker, WeightLog
from vitals.i18n import t
from vitals.utils.timeutils import now_local

# Bump when the on-disk shape changes in a backward-incompatible way.
BACKUP_VERSION = "1.0"
KIND_FULL = "full_backup"
KIND_LLM = "llm_export"

# An ``app_settings`` key is treated as a secret (and dropped from the backup) when
# it contains any of these substrings — forward-looking guard for token rows.
_SECRET_KEY_MARKERS = ("token", "secret", "password", "api_key", "apikey", "credential")

_LABELED_TABLES = (
    "weight_logs", "body_measurements", "progress_photos", "hevy_workouts",
    "garmin_daily", "garmin_activities", "lab_results", "glp1_injections",
    "glp1_side_effects", "meal_logs", "supplements", "genetic_variants",
    "skincare_logs", "weekly_digests", "annotations",
    "hrt_doses", "hrt_cycles", "hrt_side_effects",
)


class PortabilityError(Exception):
    """Raised on a malformed/invalid backup file. The router turns it into a clean
    HTTP 400 (never a silent failure or a leaked DB error)."""


class BackupMetadata(BaseModel):
    """The backup envelope. Extra keys are ignored so older/newer files still load."""

    model_config = ConfigDict(extra="ignore")

    version: str
    kind: str | None = None
    exported_at: str | None = None
    timezone: str | None = None


@dataclass
class ImportStats:
    """Per-table row counts of what was loaded, for the success message."""

    counts: dict[str, int]

    def total(self) -> int:
        return sum(self.counts.values())

    def summary(self) -> str:
        parts: list[str] = []
        leftover = 0
        for table, count in self.counts.items():
            if count <= 0:
                continue
            if table in _LABELED_TABLES:
                parts.append(f"{count} {t('import.label.' + table)}")
            else:
                leftover += count
        if leftover:
            parts.append(t("import.summary_extra", n=leftover))
        if not parts:
            return t("import.summary_empty")
        return t("import.summary_prefix") + ", ".join(parts) + "."


# ── Value (de)serialization ────────────────────────────────────────────────────


def _serialize_value(value: Any) -> Any:
    """ORM value → JSON-safe value. ISO strings for temporals, float for Decimal;
    dicts/lists (JSONB) and scalars pass through."""
    # datetime must be checked before date (datetime subclasses date).
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _deserialize_value(col_type: Any, value: Any) -> Any:
    """JSON value → ORM value, driven by the column's SQLAlchemy type. Only temporal
    columns need coercing back from ISO strings; JSON/bool/number/text pass through."""
    if value is None:
        return None
    if isinstance(col_type, DateTime):
        return datetime.fromisoformat(value) if isinstance(value, str) else value
    if isinstance(col_type, Date):
        return date.fromisoformat(value) if isinstance(value, str) else value
    if isinstance(col_type, Time):
        return time.fromisoformat(value) if isinstance(value, str) else value
    return value


def _is_secret_setting_key(key: str) -> bool:
    low = str(key).lower()
    return any(marker in low for marker in _SECRET_KEY_MARKERS)


# ── Full backup: export ────────────────────────────────────────────────────────


async def export_full(session: AsyncSession) -> dict[str, Any]:
    """Snapshot every table into ``{table_name: [rows]}`` plus a ``metadata`` head.

    Tables are walked in FK order (``sorted_tables``); ``app_settings`` secret-ish
    rows are dropped. The result is a plain dict ready for ``json.dumps``.
    """
    out: dict[str, Any] = {
        "metadata": {
            "version": BACKUP_VERSION,
            "kind": KIND_FULL,
            "exported_at": now_local().isoformat(timespec="seconds"),
            "timezone": os.getenv("VITALS_TIMEZONE", "Europe/Chisinau"),
        }
    }

    for table in Base.metadata.sorted_tables:
        result = await session.execute(select(table))
        column_names = list(table.columns.keys())
        rows: list[dict[str, Any]] = []
        for mapping in result.mappings().all():
            if table.name == "app_settings" and _is_secret_setting_key(mapping.get("key")):
                continue
            rows.append({col: _serialize_value(mapping[col]) for col in column_names})
        out[table.name] = rows

    return out


# ── Full backup: import (replace) ──────────────────────────────────────────────


def _validate_payload(payload: Any) -> BackupMetadata:
    """Structural validation. Raises :class:`PortabilityError` with a clear message
    on anything malformed — no silent acceptance of junk."""
    if not isinstance(payload, dict):
        raise PortabilityError(t("import.error.not_json_obj"))
    if "metadata" not in payload:
        raise PortabilityError(t("import.error.no_metadata"))
    try:
        meta = BackupMetadata.model_validate(payload["metadata"])
    except ValidationError as exc:
        raise PortabilityError(t("import.error.bad_metadata", msg=exc.errors()[0].get("msg", exc)))

    known = set(Base.metadata.tables.keys())
    for key, value in payload.items():
        if key == "metadata":
            continue
        if key not in known:
            raise PortabilityError(t("import.error.unknown_table", key=key))
        if not isinstance(value, list):
            raise PortabilityError(t("import.error.not_list", key=key))
        for i, item in enumerate(value):
            if not isinstance(item, dict):
                raise PortabilityError(t("import.error.not_object", i=i, key=key))
    return meta


async def import_full(session: AsyncSession, payload: Any) -> ImportStats:
    """Replace the whole DB with the file's contents, in the caller's transaction.

    Deletes every table (children first), reloads each present table preserving
    primary keys (parents first), then fixes Postgres identity sequences. Only
    ``flush`` — the router commits, so any raised error rolls everything back.
    """
    _validate_payload(payload)

    try:
        # Wipe in reverse FK order so child rows go before the parents they reference.
        for table in reversed(Base.metadata.sorted_tables):
            await session.execute(table.delete())

        counts: dict[str, int] = {}
        # Reload in FK order, preserving ids and all columns.
        for table in Base.metadata.sorted_tables:
            rows = payload.get(table.name)
            if not rows:
                continue
            columns = table.columns
            records = [
                {
                    key: _deserialize_value(columns[key].type, val)
                    for key, val in row.items()
                    if key in columns  # tolerate columns dropped in a later schema
                }
                for row in rows
            ]
            await session.execute(table.insert(), records)
            counts[table.name] = len(records)

        await _reset_sequences(session)
        await session.flush()
    except PortabilityError:
        raise
    except SQLAlchemyError as exc:
        # Surface a clean message instead of a raw driver error; the transaction is
        # rolled back by the router's session dependency.
        raise PortabilityError(t("import.error.generic", exc=exc)) from exc

    return ImportStats(counts=counts)


async def _reset_sequences(session: AsyncSession) -> None:
    """Postgres only: after inserting explicit ids, advance each id sequence past the
    max id so the next normal insert doesn't collide. No-op on SQLite (tests)."""
    if session.bind is None or session.bind.dialect.name != "postgresql":
        return
    for table in Base.metadata.sorted_tables:
        if "id" not in table.columns:
            continue
        seq = (
            await session.execute(
                text("SELECT pg_get_serial_sequence(:tbl, 'id')"), {"tbl": table.name}
            )
        ).scalar()
        if not seq:
            continue
        max_id = (await session.execute(select(func.max(table.columns["id"])))).scalar()
        if max_id is not None:
            await session.execute(
                text("SELECT setval(:seq, :val, true)"), {"seq": seq, "val": int(max_id)}
            )


# ── LLM export ─────────────────────────────────────────────────────────────────


def _llm_profile() -> dict[str, Any]:
    """Owner context (from .env) so the LLM reads the data with the right frame."""
    return {
        "height_cm": os.getenv("VITALS_HEIGHT_CM") or "190",
        "sex": os.getenv("VITALS_SEX") or "male",
        "age": os.getenv("VITALS_USER_AGE") or "18",
        "program": os.getenv("VITALS_USER_PROGRAM") or "",
        "goals": os.getenv("VITALS_USER_GOALS") or "",
        "timezone": os.getenv("VITALS_TIMEZONE", "Europe/Chisinau"),
        "exported_at": now_local().isoformat(timespec="seconds"),
        "units": {"weight": "kg", "distance": "m", "energy": "kcal"},
        "note": (
            "Экспорт данных здоровья одного пользователя (Vitals) для анализа LLM. "
            "Даты в ISO 8601, вес в кг. Это навигатор для поддержки решений, не врач."
        ),
    }


def _compact(row: dict[str, Any]) -> dict[str, Any]:
    """Drop empty (None / "") fields so the digest stays terse for a chat window."""
    return {k: v for k, v in row.items() if v is not None and v != ""}


async def export_llm(session: AsyncSession) -> dict[str, Any]:
    """Curated, flat, secret-free digest grouped by domain — paste-into-chat ready."""
    out: dict[str, Any] = {"profile": _llm_profile()}

    # Weight — active rows only (superseded duplicates are noise for analysis).
    weights = (
        await session.execute(
            select(WeightLog).where(WeightLog.superseded.is_(False)).order_by(WeightLog.date)
        )
    ).scalars().all()
    out["weight_history"] = [
        _compact({"date": w.date.isoformat(), "weight_kg": w.weight_kg, "note": w.note})
        for w in weights
    ]

    measurements = (
        await session.execute(select(BodyMeasurement).order_by(BodyMeasurement.date))
    ).scalars().all()
    out["body_measurements"] = [
        _compact(
            {
                "date": m.date.isoformat(),
                "waist_cm": m.waist_cm,
                "neck_cm": m.neck_cm,
                "hips_cm": m.hips_cm,
                "body_fat_pct": m.body_fat_pct,
                "lbm_kg": m.lbm_kg,
            }
        )
        for m in measurements
    ]

    # Body composition — BIA/InBody scans with every captured metric per scan
    # (the body_comp domain; complements the Navy body_fat_pct/lbm above).
    scans = (
        await session.execute(
            select(BodyScan)
            .options(selectinload(BodyScan.metrics))
            .order_by(BodyScan.date, BodyScan.id)
        )
    ).scalars().all()
    out["body_scans"] = [
        _compact(
            {
                "date": s.date.isoformat(),
                "device": s.device,
                "note": s.note,
                "metrics": [
                    _compact(
                        {
                            "metric": m.metric_key,
                            "value": m.value,
                            "unit": m.unit,
                            "segment": m.segment,
                        }
                    )
                    for m in s.metrics
                ],
            }
        )
        for s in scans
    ]

    noise = (
        await session.execute(select(NoiseMarker).order_by(NoiseMarker.start_date))
    ).scalars().all()
    out["noise_periods"] = [
        _compact(
            {
                "start_date": n.start_date.isoformat(),
                "end_date": n.end_date.isoformat() if n.end_date else None,
                "reason": n.reason,
            }
        )
        for n in noise
    ]

    # GLP-1 protocol.
    injections = (
        await session.execute(select(Injection).order_by(Injection.date))
    ).scalars().all()
    out["glp1_injections"] = [
        _compact({"date": i.date.isoformat(), "drug": i.drug, "dose_mg": i.dose_mg, "site": i.site})
        for i in injections
    ]
    phases = (
        await session.execute(select(DosePhase).order_by(DosePhase.start_date))
    ).scalars().all()
    out["glp1_dose_phases"] = [
        _compact(
            {
                "start_date": p.start_date.isoformat(),
                "end_date": p.end_date.isoformat() if p.end_date else None,
                "drug": p.drug,
                "dose_mg": p.dose_mg,
            }
        )
        for p in phases
    ]
    effects = (
        await session.execute(select(SideEffect).order_by(SideEffect.date))
    ).scalars().all()
    out["glp1_side_effects"] = [
        _compact(
            {"date": e.date.isoformat(), "effect_type": e.effect_type, "severity": e.severity}
        )
        for e in effects
    ]

    # HRT / TRT protocol — doses (with grey-market provenance), cycles with their
    # per-compound plans, side effects, and the user's saved cycle templates.
    hrt_doses = (
        await session.execute(select(HrtDose).order_by(HrtDose.date, HrtDose.id))
    ).scalars().all()
    out["hrt_doses"] = [
        _compact(
            {
                "date": d.date.isoformat(),
                "compound": d.compound_key,
                "dose": d.dose,
                "unit": d.unit,
                "volume_ml": d.volume_ml,
                "brand": d.brand,
                "lab": d.lab,
                "batch": d.batch,
                "site": d.site,
                "note": d.note,
            }
        )
        for d in hrt_doses
    ]
    hrt_cycles = (
        await session.execute(
            select(HrtCycle)
            .options(selectinload(HrtCycle.items))
            .order_by(HrtCycle.start_date, HrtCycle.id)
        )
    ).scalars().all()
    out["hrt_cycles"] = [
        _compact(
            {
                "start_date": c.start_date.isoformat(),
                "end_date": c.end_date.isoformat() if c.end_date else None,
                "kind": c.kind,
                "name": c.name,
                "note": c.note,
                "items": [
                    _compact(
                        {
                            "compound": it.compound_key,
                            "unit": it.unit,
                            "start_offset_days": it.start_offset_days or None,
                            "schedule": it.schedule,
                        }
                    )
                    for it in c.items
                ],
            }
        )
        for c in hrt_cycles
    ]
    hrt_effects = (
        await session.execute(select(HrtSideEffect).order_by(HrtSideEffect.date))
    ).scalars().all()
    out["hrt_side_effects"] = [
        _compact(
            {"date": e.date.isoformat(), "effect_type": e.effect_type, "severity": e.severity}
        )
        for e in hrt_effects
    ]
    hrt_templates = (
        await session.execute(
            select(HrtCycleTemplate)
            .options(selectinload(HrtCycleTemplate.items))
            .order_by(HrtCycleTemplate.name)
        )
    ).scalars().all()
    out["hrt_cycle_templates"] = [
        _compact(
            {
                "name": tp.name,
                "kind": tp.kind,
                "note": tp.note,
                "items": [
                    _compact(
                        {
                            "compound": it.compound_key,
                            "unit": it.unit,
                            "start_offset_days": it.start_offset_days or None,
                            "schedule": it.schedule,
                        }
                    )
                    for it in tp.items
                ],
            }
        )
        for tp in hrt_templates
    ]

    # Labs.
    labs = (
        await session.execute(select(LabResult).order_by(LabResult.date, LabResult.marker))
    ).scalars().all()
    out["biomarkers"] = [
        _compact(
            {
                "date": r.date.isoformat(),
                "marker": r.marker,
                "value": r.value,
                "unit": r.unit,
                "ref_low": r.ref_low,
                "ref_high": r.ref_high,
                "flag": r.flag,
            }
        )
        for r in labs
    ]

    # Workouts — rebuild the Hevy tree (workout → exercises → sets) without ids.
    out["workouts"] = await _llm_workouts(session)

    # Garmin daily — wide recovery/activity row, compacted.
    garmin = (
        await session.execute(select(GarminDaily).order_by(GarminDaily.date))
    ).scalars().all()
    out["garmin_daily"] = [
        _compact(
            {
                "date": g.date.isoformat(),
                "sleep_score": g.sleep_score,
                "sleep_hours": round(g.sleep_seconds / 3600, 2) if g.sleep_seconds else None,
                "resting_hr": g.resting_hr,
                "hrv_avg": g.hrv_avg,
                "avg_stress": g.avg_stress,
                "body_battery_high": g.body_battery_high,
                "body_battery_low": g.body_battery_low,
                "steps": g.steps,
                "active_calories": g.active_calories,
                "total_calories": g.total_calories,
                "training_readiness": g.training_readiness,
                "vo2max": g.vo2max,
            }
        )
        for g in garmin
    ]
    activities = (
        await session.execute(select(GarminActivity).order_by(GarminActivity.date))
    ).scalars().all()
    out["garmin_activities"] = [
        _compact(
            {
                "date": a.date.isoformat(),
                "type": a.activity_type,
                "name": a.name,
                "duration_min": round(a.duration_seconds / 60, 1) if a.duration_seconds else None,
                "distance_m": a.distance_m,
                "calories": a.calories,
                "avg_hr": a.avg_hr,
            }
        )
        for a in activities
    ]

    # Nutrition.
    meals = (
        await session.execute(select(MealLog).order_by(MealLog.date))
    ).scalars().all()
    out["nutrition"] = [
        _compact(
            {
                "date": m.date.isoformat(),
                "name": m.name,
                "calories": m.calories,
                "protein_g": m.protein_g,
                "fat_g": m.fat_g,
                "carbs_g": m.carbs_g,
            }
        )
        for m in meals
    ]

    # Reference catalogs.
    supplements = (
        await session.execute(select(Supplement).order_by(Supplement.name))
    ).scalars().all()
    out["supplements"] = [
        _compact(
            {
                "name": s.name,
                "dose": s.dose,
                "timing": s.timing,
                "evidence": s.evidence,
                "active": s.active,
                "contraindications": s.contraindications,
            }
        )
        for s in supplements
    ]
    variants = (
        await session.execute(select(GeneticVariant).order_by(GeneticVariant.gene))
    ).scalars().all()
    out["genetics"] = [
        _compact(
            {
                "gene": v.gene,
                "rsid": v.rsid,
                "genotype": v.genotype,
                "impact": v.impact,
                "interpretation": v.interpretation,
            }
        )
        for v in variants
    ]

    # Skincare logs + observations.
    sk_logs = (
        await session.execute(select(SkincareLog).order_by(SkincareLog.date))
    ).scalars().all()
    out["skincare_logs"] = [
        _compact(
            {
                "date": s.date.isoformat(),
                "retinoid": s.retinoid,
                "azelaic": s.azelaic,
                "peel": s.peel,
                "niacinamide_spf": s.niacinamide_spf,
                "moisturizer": s.moisturizer,
                "vitamin_c": s.vitamin_c,
                "benzoyl_peroxide": s.benzoyl_peroxide,
            }
        )
        for s in sk_logs
    ]
    sk_obs = (
        await session.execute(select(SkincareObservation).order_by(SkincareObservation.date))
    ).scalars().all()
    out["skincare_observations"] = [
        _compact(
            {
                "date": o.date.isoformat(),
                "inflammation": o.inflammation,
                "pih": o.pih,
                "zone": o.zone,
            }
        )
        for o in sk_obs
    ]

    # Goals + generated narratives.
    milestones = (
        await session.execute(select(Milestone).order_by(Milestone.id))
    ).scalars().all()
    out["milestones"] = [
        _compact(
            {
                "name": m.name,
                "domain": m.domain,
                "target_value": m.target_value,
                "target_unit": m.target_unit,
                "deadline": m.deadline.isoformat() if m.deadline else None,
                "status": m.status,
            }
        )
        for m in milestones
    ]
    digests = (
        await session.execute(select(WeeklyDigest).order_by(WeeklyDigest.date))
    ).scalars().all()
    out["weekly_digests"] = [
        _compact({"date": d.date.isoformat(), "content": d.content}) for d in digests
    ]

    # Timeline — manual annotations (derived events already surface through
    # their own domain's block above, so they aren't repeated here).
    annotations = (
        await session.execute(select(Annotation).order_by(Annotation.date))
    ).scalars().all()
    out["timeline_annotations"] = [
        _compact(
            {
                "date": a.date.isoformat(),
                "end_date": a.end_date.isoformat() if a.end_date else None,
                "domain": a.domain,
                "kind": a.kind,
                "title": a.title,
                "note": a.note,
            }
        )
        for a in annotations
    ]

    return out


async def _llm_workouts(session: AsyncSession) -> list[dict[str, Any]]:
    """Assemble Hevy workouts with their exercises and sets, id-free, in two passes
    (no N+1): load all rows, then group children by parent in Python."""
    workouts = (
        await session.execute(select(HevyWorkout).order_by(HevyWorkout.date))
    ).scalars().all()
    exercises = (
        await session.execute(
            select(HevyExercise).order_by(HevyExercise.workout_id, HevyExercise.exercise_index)
        )
    ).scalars().all()
    sets = (
        await session.execute(
            select(HevySet).order_by(HevySet.exercise_id, HevySet.set_index)
        )
    ).scalars().all()

    sets_by_exercise: dict[int, list] = defaultdict(list)
    for s in sets:
        sets_by_exercise[s.exercise_id].append(s)
    exercises_by_workout: dict[int, list] = defaultdict(list)
    for e in exercises:
        exercises_by_workout[e.workout_id].append(e)

    result: list[dict[str, Any]] = []
    for w in workouts:
        result.append(
            _compact(
                {
                    "date": w.date.isoformat(),
                    "title": w.title,
                    "program": w.program,
                    "duration_min": round(w.duration_seconds / 60, 1)
                    if w.duration_seconds
                    else None,
                    "exercises": [
                        _compact(
                            {
                                "title": ex.title,
                                "sets": [
                                    _compact(
                                        {
                                            "weight_kg": st.weight_kg,
                                            "reps": st.reps,
                                            "rpe": st.rpe,
                                            "set_type": st.set_type
                                            if st.set_type != "normal"
                                            else None,
                                        }
                                    )
                                    for st in sets_by_exercise.get(ex.id, [])
                                ],
                            }
                        )
                        for ex in exercises_by_workout.get(w.id, [])
                    ],
                }
            )
        )
    return result
