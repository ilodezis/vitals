"""Model Context Protocol (MCP) server integration for Vitals.

Exposes access to all health domains using FastMCP and standard SQLAlchemy
preloading patterns. Read tools cover every domain; write tools let Claude
record meals, weight, GLP-1 injections, skincare logs, body measurements,
lab results, and notes directly from the conversation.
"""
from __future__ import annotations

import logging
import os
from datetime import date as date_type
from typing import Optional

from fastmcp import FastMCP
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from vitals.config import load_config
from vitals.enums import Domain, Source
from vitals.models import (
    BodyMeasurement,
    BodyScan,
    DosePhase,
    GarminActivity,
    GarminDaily,
    GeneticVariant,
    HevyExercise,
    HevyWorkout,
    Injection,
    LabResult,
    MealLog,
    NoiseMarker,
    SideEffect,
    SkincareLog,
    SkincareObservation,
    Supplement,
    SystemAlert,
    WeightLog,
    WeeklyDigest,
)
from vitals.services import conflict_engine
from web.deps import get_session_factory

logger = logging.getLogger(__name__)

# Initialize FastMCP in stateless mode for cloud/OAuth deployment compatibility
mcp = FastMCP("Vitals")


def serialize_row(row) -> dict:
    """Helper to convert any SQLAlchemy model instance into a JSON-serializable dict."""
    if row is None:
        return {}
    d = {}
    for column in row.__table__.columns:
        val = getattr(row, column.name)
        if hasattr(val, "isoformat"):
            d[column.name] = val.isoformat()
        else:
            d[column.name] = val
    return d


async def serialize_written(session, row) -> dict:
    """Serialize a row that was just written. After an UPDATE flush, server-side
    ``onupdate``/``server_default`` columns (e.g. ``updated_at``) are *expired*;
    reading them in the sync ``serialize_row`` would trigger a lazy SELECT outside
    the async greenlet and fail with ``greenlet_spawn has not been called``. An
    explicit ``await session.refresh`` reloads them inside the async context first.
    """
    if row is None:
        return {}
    await session.refresh(row)
    return serialize_row(row)


# ── Tool Definitions ─────────────────────────────────────────────────────────

@mcp.tool()
async def get_user_profile() -> dict:
    """Returns the user's physical profile, active goals, and program overview."""
    cfg = load_config()
    return {
        "height_cm": cfg.height_cm,
        "sex": cfg.sex,
        "age": cfg.user_age,
        "timezone": str(cfg.timezone),
        "goals": cfg.user_goals,
        "program": cfg.user_program,
    }


@mcp.tool()
async def get_weight_logs(
    start_date: Optional[str] = None, end_date: Optional[str] = None, limit: int = 100
) -> dict:
    """Retrieves active weight logs, body measurements, and noise markers for a
    date range (YYYY-MM-DD). Weights/measurements default to the most recent 100."""
    session_factory = get_session_factory()
    start = date_type.fromisoformat(start_date) if start_date else None
    end = date_type.fromisoformat(end_date) if end_date else None

    async with session_factory() as session:
        # Weight logs
        w_stmt = select(WeightLog).where(WeightLog.superseded.is_(False))
        if start:
            w_stmt = w_stmt.where(WeightLog.date >= start)
        if end:
            w_stmt = w_stmt.where(WeightLog.date <= end)
        w_stmt = w_stmt.order_by(WeightLog.date.desc()).limit(limit)
        weights = (await session.execute(w_stmt)).scalars().all()

        # Body measurements
        m_stmt = select(BodyMeasurement)
        if start:
            m_stmt = m_stmt.where(BodyMeasurement.date >= start)
        if end:
            m_stmt = m_stmt.where(BodyMeasurement.date <= end)
        m_stmt = m_stmt.order_by(BodyMeasurement.date.desc()).limit(limit)
        measurements = (await session.execute(m_stmt)).scalars().all()

        # Noise markers
        n_stmt = select(NoiseMarker).order_by(NoiseMarker.start_date.desc())
        noise = (await session.execute(n_stmt)).scalars().all()

        return {
            "weights": [serialize_row(w) for w in weights],
            "measurements": [serialize_row(m) for m in measurements],
            "noise_markers": [serialize_row(n) for n in noise],
        }


@mcp.tool()
async def get_glp1_logs(
    start_date: Optional[str] = None, end_date: Optional[str] = None, limit: int = 100
) -> dict:
    """Retrieves GLP-1 injection logs, active dosage phases, and recorded side
    effects. Injections/side effects default to the most recent 100."""
    session_factory = get_session_factory()
    start = date_type.fromisoformat(start_date) if start_date else None
    end = date_type.fromisoformat(end_date) if end_date else None

    async with session_factory() as session:
        # Injections
        i_stmt = select(Injection)
        if start:
            i_stmt = i_stmt.where(Injection.date >= start)
        if end:
            i_stmt = i_stmt.where(Injection.date <= end)
        i_stmt = i_stmt.order_by(Injection.date.desc()).limit(limit)
        injections = (await session.execute(i_stmt)).scalars().all()

        # Dose phases
        p_stmt = select(DosePhase).order_by(DosePhase.start_date.desc())
        phases = (await session.execute(p_stmt)).scalars().all()

        # Side effects
        s_stmt = select(SideEffect)
        if start:
            s_stmt = s_stmt.where(SideEffect.date >= start)
        if end:
            s_stmt = s_stmt.where(SideEffect.date <= end)
        s_stmt = s_stmt.order_by(SideEffect.date.desc()).limit(limit)
        effects = (await session.execute(s_stmt)).scalars().all()

        return {
            "injections": [serialize_row(i) for i in injections],
            "dose_phases": [serialize_row(p) for p in phases],
            "side_effects": [serialize_row(s) for s in effects],
        }


@mcp.tool()
async def get_garmin_metrics(
    start_date: Optional[str] = None, end_date: Optional[str] = None, limit: int = 100
) -> dict:
    """Retrieves daily Garmin recovery/sleep scores and recorded activity sessions.
    Each series defaults to the most recent 100 rows."""
    session_factory = get_session_factory()
    start = date_type.fromisoformat(start_date) if start_date else None
    end = date_type.fromisoformat(end_date) if end_date else None

    async with session_factory() as session:
        # Daily metrics
        d_stmt = select(GarminDaily)
        if start:
            d_stmt = d_stmt.where(GarminDaily.date >= start)
        if end:
            d_stmt = d_stmt.where(GarminDaily.date <= end)
        d_stmt = d_stmt.order_by(GarminDaily.date.desc()).limit(limit)
        daily = (await session.execute(d_stmt)).scalars().all()

        # Activities
        a_stmt = select(GarminActivity)
        if start:
            a_stmt = a_stmt.where(GarminActivity.date >= start)
        if end:
            a_stmt = a_stmt.where(GarminActivity.date <= end)
        a_stmt = a_stmt.order_by(GarminActivity.date.desc(), GarminActivity.start_time.desc()).limit(limit)
        activities = (await session.execute(a_stmt)).scalars().all()

        return {
            "daily_recovery": [serialize_row(d) for d in daily],
            "activities": [serialize_row(a) for a in activities],
        }


@mcp.tool()
async def get_hevy_workouts(
    start_date: Optional[str] = None, end_date: Optional[str] = None, limit: int = 100
) -> list[dict]:
    """Retrieves Hevy strength training workouts, including exercises, sets,
    weights, and reps. Defaults to the most recent 100 workouts."""
    session_factory = get_session_factory()
    start = date_type.fromisoformat(start_date) if start_date else None
    end = date_type.fromisoformat(end_date) if end_date else None

    async with session_factory() as session:
        stmt = select(HevyWorkout)
        if start:
            stmt = stmt.where(HevyWorkout.date >= start)
        if end:
            stmt = stmt.where(HevyWorkout.date <= end)
        stmt = stmt.options(selectinload(HevyWorkout.exercises).selectinload(HevyExercise.sets))
        stmt = stmt.order_by(HevyWorkout.date.desc()).limit(limit)
        workouts = (await session.execute(stmt)).scalars().all()

        serialized = []
        for w in workouts:
            w_dict = serialize_row(w)
            w_dict["exercises"] = []
            for e in w.exercises:
                e_dict = serialize_row(e)
                e_dict["sets"] = [serialize_row(s) for s in e.sets]
                w_dict["exercises"].append(e_dict)
            serialized.append(w_dict)
        return serialized


@mcp.tool()
async def get_supplements_catalog() -> list[dict]:
    """Retrieves the active supplement catalog, including dosages and evidence tiers."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(Supplement).order_by(Supplement.name)
        supps = (await session.execute(stmt)).scalars().all()
        return [serialize_row(s) for s in supps]


@mcp.tool()
async def get_skincare_logs(
    start_date: Optional[str] = None, end_date: Optional[str] = None, limit: int = 100
) -> dict:
    """Retrieves skincare routine application logs and skin status observations.
    Each series defaults to the most recent 100 rows."""
    session_factory = get_session_factory()
    start = date_type.fromisoformat(start_date) if start_date else None
    end = date_type.fromisoformat(end_date) if end_date else None

    async with session_factory() as session:
        # Routine logs
        l_stmt = select(SkincareLog)
        if start:
            l_stmt = l_stmt.where(SkincareLog.date >= start)
        if end:
            l_stmt = l_stmt.where(SkincareLog.date <= end)
        l_stmt = l_stmt.order_by(SkincareLog.date.desc()).limit(limit)
        logs = (await session.execute(l_stmt)).scalars().all()

        # Observations
        o_stmt = select(SkincareObservation)
        if start:
            o_stmt = o_stmt.where(SkincareObservation.date >= start)
        if end:
            o_stmt = o_stmt.where(SkincareObservation.date <= end)
        o_stmt = o_stmt.order_by(SkincareObservation.date.desc()).limit(limit)
        observations = (await session.execute(o_stmt)).scalars().all()

        return {
            "logs": [serialize_row(l) for l in logs],
            "observations": [serialize_row(o) for o in observations],
        }


@mcp.tool()
async def get_genetics_snps(limit: int = 100) -> list[dict]:
    """Retrieves oцифрованные SNPs (генетические варианты) с описанием их влияния.
    Defaults to the first 100 variants (gene, rsid order)."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = (
            select(GeneticVariant)
            .order_by(GeneticVariant.gene, GeneticVariant.rsid)
            .limit(limit)
        )
        variants = (await session.execute(stmt)).scalars().all()
        return [serialize_row(v) for v in variants]


@mcp.tool()
async def get_active_alerts() -> list[dict]:
    """Returns currently active warning alerts and conflict notifications."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(SystemAlert).where(SystemAlert.resolved_at.is_(None)).order_by(SystemAlert.created_at.desc())
        alerts = (await session.execute(stmt)).scalars().all()
        return [serialize_row(a) for a in alerts]


@mcp.tool()
async def get_weekly_digests(limit: int = 5) -> list[dict]:
    """Retrieves historical Claude-generated weekly summaries for continuity."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(WeeklyDigest).order_by(WeeklyDigest.date.desc()).limit(limit)
        digests = (await session.execute(stmt)).scalars().all()
        return [serialize_row(d) for d in digests]


@mcp.tool()
async def check_supplement_conflicts(supplement_name: str) -> list[dict]:
    """Evaluates a proposed supplement name against active supplements, skincare routines, and genetics."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        violations = await conflict_engine.evaluate(
            session,
            Domain.SUPPLEMENTS.value,
            {"name": supplement_name}
        )
        return [v.to_dict() for v in violations]


# ── Nutrition tools ──────────────────────────────────────────────────────────

@mcp.tool()
async def log_meal(
    name: str,
    calories: Optional[float] = None,
    protein_g: Optional[float] = None,
    fat_g: Optional[float] = None,
    carbs_g: Optional[float] = None,
    eaten_at: Optional[str] = None,
    note: Optional[str] = None,
    on_date: Optional[str] = None,
) -> dict:
    """Records a meal or snack with optional macros (KCAL, protein, fat, carbs).

    This is a WRITE tool — the meal is saved to the database immediately.
    Defaults: on_date = today, eaten_at = current time.
    """
    from datetime import time as time_type
    from vitals.services import nutrition_service
    from vitals.utils.timeutils import today_local

    session_factory = get_session_factory()
    parsed_date = date_type.fromisoformat(on_date) if on_date else today_local()
    parsed_time = time_type.fromisoformat(eaten_at) if eaten_at else None

    async with session_factory() as session:
        row = await nutrition_service.log_meal(
            session,
            on_date=parsed_date,
            name=name,
            eaten_at=parsed_time,
            calories=calories,
            protein_g=protein_g,
            fat_g=fat_g,
            carbs_g=carbs_g,
            note=note,
        )
        await session.commit()
        return await serialize_written(session, row)


@mcp.tool()
async def get_nutrition_summary(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    """Returns a nutrition summary with total KCAL/protein/fat/carbs, meal counts,
    per-day breakdown, and goal tracking. Defaults to today if no dates given."""
    from vitals.services import nutrition_service
    from vitals.utils.timeutils import today_local

    cfg = load_config()
    session_factory = get_session_factory()
    today = today_local()

    start = date_type.fromisoformat(start_date) if start_date else today
    end = date_type.fromisoformat(end_date) if end_date else today

    if start == end:
        async with session_factory() as session:
            return await nutrition_service.daily_summary(session, start, cfg)
    else:
        async with session_factory() as session:
            return await nutrition_service.nutrition_summary(session, start, end, cfg)


# ── Meal CRUD tools ─────────────────────────────────────────────────────────

@mcp.tool()
async def update_meal(
    meal_id: int,
    name: str,
    calories: Optional[float] = None,
    protein_g: Optional[float] = None,
    fat_g: Optional[float] = None,
    carbs_g: Optional[float] = None,
    eaten_at: Optional[str] = None,
    note: Optional[str] = None,
    on_date: Optional[str] = None,
) -> dict:
    """Updates an existing meal by ID. Returns the updated meal or an error.

    WRITE tool — changes are saved immediately.
    """
    from datetime import time as time_type
    from vitals.services import nutrition_service
    from vitals.utils.timeutils import today_local

    session_factory = get_session_factory()
    parsed_date = date_type.fromisoformat(on_date) if on_date else today_local()
    parsed_time = time_type.fromisoformat(eaten_at) if eaten_at else None

    async with session_factory() as session:
        row = await nutrition_service.update_meal(
            session,
            meal_id,
            on_date=parsed_date,
            name=name,
            eaten_at=parsed_time,
            calories=calories,
            protein_g=protein_g,
            fat_g=fat_g,
            carbs_g=carbs_g,
            note=note,
        )
        if row is None:
            return {"error": f"Meal {meal_id} not found"}
        await session.commit()
        return await serialize_written(session, row)


@mcp.tool()
async def delete_meal(meal_id: int) -> dict:
    """Deletes a meal by ID. WRITE tool — deletion is immediate."""
    from vitals.services import nutrition_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        ok = await nutrition_service.delete_meal(session, meal_id)
        await session.commit()
        return {"deleted": ok, "meal_id": meal_id}


@mcp.tool()
async def search_meals(
    query: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """Searches meals by name substring and/or date range. Returns matching meals
    ordered by date descending."""
    session_factory = get_session_factory()
    start = date_type.fromisoformat(start_date) if start_date else None
    end = date_type.fromisoformat(end_date) if end_date else None

    async with session_factory() as session:
        stmt = select(MealLog)
        if query:
            stmt = stmt.where(MealLog.name.ilike(f"%{query}%"))
        if start:
            stmt = stmt.where(MealLog.date >= start)
        if end:
            stmt = stmt.where(MealLog.date <= end)
        stmt = stmt.order_by(MealLog.date.desc(), MealLog.eaten_at.desc().nulls_last())
        stmt = stmt.limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        return [serialize_row(r) for r in rows]


# ── Weight tools ────────────────────────────────────────────────────────────

@mcp.tool()
async def log_weight(
    weight_kg: float,
    on_date: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    """Records a manual weight entry (kg). One active weight per date — manual
    entries override Garmin imports. WRITE tool — saved immediately."""
    from vitals.services import weight_service
    from vitals.utils.timeutils import today_local

    session_factory = get_session_factory()
    parsed_date = date_type.fromisoformat(on_date) if on_date else today_local()

    async with session_factory() as session:
        row = await weight_service.log_weight(
            session, on_date=parsed_date, weight_kg=weight_kg, note=note,
        )
        await session.commit()
        return await serialize_written(session, row)


@mcp.tool()
async def delete_weight(weight_id: int) -> dict:
    """Deletes a weight log by ID. If it was the active entry, the next highest
    priority log for that date is reactivated. WRITE tool."""
    from vitals.services import weight_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        ok = await weight_service.delete_weight_log(session, weight_id)
        await session.commit()
        return {"deleted": ok, "weight_id": weight_id}


# ── GLP-1 tools ─────────────────────────────────────────────────────────────

@mcp.tool()
async def log_glp1(
    drug: str,
    dose_mg: float,
    on_date: Optional[str] = None,
    site: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    """Records a GLP-1 injection (drug name, dose in mg, optional injection site).
    WRITE tool — saved immediately."""
    from vitals.services import glp1_service
    from vitals.utils.timeutils import today_local

    session_factory = get_session_factory()
    parsed_date = date_type.fromisoformat(on_date) if on_date else today_local()

    async with session_factory() as session:
        row = await glp1_service.log_injection(
            session, on_date=parsed_date, drug=drug, dose_mg=dose_mg,
            site=site, note=note,
        )
        await session.commit()
        return await serialize_written(session, row)


# ── Skincare tools ──────────────────────────────────────────────────────────

@mcp.tool()
async def log_skincare(
    on_date: Optional[str] = None,
    retinoid: bool = False,
    azelaic: bool = False,
    peel: bool = False,
    niacinamide_spf: bool = False,
    moisturizer: bool = False,
    note: Optional[str] = None,
) -> dict:
    """Records or updates the daily skincare routine checklist (one per day, upsert).
    Boolean flags indicate which products were applied. WRITE tool — saved immediately."""
    from vitals.services import skincare_service
    from vitals.utils.timeutils import today_local

    session_factory = get_session_factory()
    parsed_date = date_type.fromisoformat(on_date) if on_date else today_local()

    async with session_factory() as session:
        row = await skincare_service.upsert_log(
            session, on_date=parsed_date, retinoid=retinoid, azelaic=azelaic,
            peel=peel, niacinamide_spf=niacinamide_spf, moisturizer=moisturizer,
            note=note,
        )
        await session.commit()
        return await serialize_written(session, row)


# ── Body measurement tools ──────────────────────────────────────────────────

@mcp.tool()
async def log_measurement(
    on_date: Optional[str] = None,
    neck_cm: Optional[float] = None,
    waist_cm: Optional[float] = None,
    hips_cm: Optional[float] = None,
    note: Optional[str] = None,
) -> dict:
    """Records body circumference measurements (neck, waist, hips in cm). Upserts
    per date. Auto-computes Navy body-fat % and LBM if weight exists for the date.
    WRITE tool — saved immediately."""
    from vitals.services import weight_service
    from vitals.utils.timeutils import today_local

    session_factory = get_session_factory()
    parsed_date = date_type.fromisoformat(on_date) if on_date else today_local()

    async with session_factory() as session:
        row = await weight_service.upsert_body_measurement(
            session, on_date=parsed_date, neck_cm=neck_cm, waist_cm=waist_cm,
            hips_cm=hips_cm, note=note,
        )
        await session.commit()
        return await serialize_written(session, row)


@mcp.tool()
async def get_measurements(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    """Retrieves body measurements (neck, waist, hips, body-fat %, LBM) for a date
    range. Defaults to the most recent 100 rows."""
    session_factory = get_session_factory()
    start = date_type.fromisoformat(start_date) if start_date else None
    end = date_type.fromisoformat(end_date) if end_date else None

    async with session_factory() as session:
        stmt = select(BodyMeasurement)
        if start:
            stmt = stmt.where(BodyMeasurement.date >= start)
        if end:
            stmt = stmt.where(BodyMeasurement.date <= end)
        stmt = stmt.order_by(BodyMeasurement.date.desc()).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        return [serialize_row(r) for r in rows]


# ── Notes tools ─────────────────────────────────────────────────────────────

@mcp.tool()
async def log_note(
    domain: str,
    record_id: int,
    note: str,
) -> dict:
    """Adds or updates the note field on any domain record by its ID.
    Supported domains: weight, nutrition, glp1, skincare, measurement, body_comp, labs.
    WRITE tool — saved immediately."""
    from vitals.models.glp1 import Injection
    from vitals.models.skincare import SkincareLog

    model_map = {
        "weight": WeightLog,
        "nutrition": MealLog,
        "glp1": Injection,
        "skincare": SkincareLog,
        "measurement": BodyMeasurement,
        "body_comp": BodyScan,
        "labs": LabResult,
    }
    model = model_map.get(domain)
    if model is None:
        return {"error": f"Unknown domain '{domain}'. Use: {', '.join(model_map)}"}

    session_factory = get_session_factory()
    async with session_factory() as session:
        row = await session.get(model, record_id)
        if row is None:
            return {"error": f"{domain} record {record_id} not found"}
        row.note = note
        await session.flush()
        await session.commit()
        return await serialize_written(session, row)


@mcp.tool()
async def get_notes(
    domain: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """Retrieves records that have non-empty notes, optionally filtered by domain
    and date range. Returns records from: weight, nutrition, glp1, skincare,
    measurement, body_comp, labs."""
    from vitals.models.glp1 import Injection
    from vitals.models.skincare import SkincareLog

    model_map = {
        "weight": WeightLog,
        "nutrition": MealLog,
        "glp1": Injection,
        "skincare": SkincareLog,
        "measurement": BodyMeasurement,
        "body_comp": BodyScan,
        "labs": LabResult,
    }

    if domain and domain not in model_map:
        return [{"error": f"Unknown domain '{domain}'. Use: {', '.join(model_map)}"}]

    targets = {domain: model_map[domain]} if domain else model_map
    session_factory = get_session_factory()
    start = date_type.fromisoformat(start_date) if start_date else None
    end = date_type.fromisoformat(end_date) if end_date else None

    results = []
    async with session_factory() as session:
        for d_name, model in targets.items():
            stmt = select(model).where(model.note.isnot(None), model.note != "")
            if start:
                stmt = stmt.where(model.date >= start)
            if end:
                stmt = stmt.where(model.date <= end)
            stmt = stmt.order_by(model.date.desc()).limit(limit)
            rows = (await session.execute(stmt)).scalars().all()
            for r in rows:
                entry = serialize_row(r)
                entry["_domain"] = d_name
                results.append(entry)

    results.sort(key=lambda x: x.get("date", ""), reverse=True)
    return results[:limit]


# ── Body composition tools (InBody / МедАсс — optional module) ────────────────
def _serialize_scan(scan: BodyScan) -> dict:
    """A scan plus its metrics nested (relationship must be loaded already)."""
    d = serialize_row(scan)
    d["metrics"] = [serialize_row(m) for m in scan.metrics]
    return d


async def _module_enabled(session, key: str) -> bool:
    """True when an optional module is on (write tools honour the toggle)."""
    from vitals.services import modules_service

    state = await modules_service.get_enabled_modules(session)
    return bool(state.get(key))


@mcp.tool()
async def get_body_scans(
    start_date: Optional[str] = None, end_date: Optional[str] = None, limit: int = 100
) -> list[dict]:
    """Retrieves body-composition scans (InBody / МедАсс) with every parsed metric
    (skeletal muscle, body water, visceral fat, segmental analysis, phase angle…).
    Defaults to the most recent 100 scans."""
    session_factory = get_session_factory()
    start = date_type.fromisoformat(start_date) if start_date else None
    end = date_type.fromisoformat(end_date) if end_date else None

    async with session_factory() as session:
        stmt = select(BodyScan).options(selectinload(BodyScan.metrics))
        if start:
            stmt = stmt.where(BodyScan.date >= start)
        if end:
            stmt = stmt.where(BodyScan.date <= end)
        stmt = stmt.order_by(BodyScan.date.desc(), BodyScan.id.desc()).limit(limit)
        scans = (await session.execute(stmt)).scalars().all()
        return [_serialize_scan(s) for s in scans]


@mcp.tool()
async def get_body_scan(scan_id: int) -> dict:
    """Retrieves a single body-composition scan with its full metric sheet."""
    from vitals.services import body_scan_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        scan = await body_scan_service.get_scan(session, scan_id)
        if scan is None:
            return {"error": f"Body scan {scan_id} not found"}
        return _serialize_scan(scan)


@mcp.tool()
async def get_body_metric_history(
    metric_key: str,
    segment: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> list[dict]:
    """Time series for one body-composition metric (e.g. ``skeletal_muscle_mass``,
    ``phase_angle``, ``visceral_fat_area``), optionally for a single body segment."""
    from vitals.services import body_scan_service

    session_factory = get_session_factory()
    start = date_type.fromisoformat(start_date) if start_date else None
    end = date_type.fromisoformat(end_date) if end_date else None
    async with session_factory() as session:
        return await body_scan_service.metric_history(
            session, metric_key, segment=segment, start=start, end=end
        )


@mcp.tool()
async def log_body_scan(
    metrics: list[dict],
    on_date: Optional[str] = None,
    device: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    """Records a body-composition scan from structured metrics (no photo needed).

    Each metric is ``{"label" or "metric_key": str, "value": number, "unit": str?,
    "ref_low": number?, "ref_high": number?, "segment": str?}``. The scan's weight /
    body-fat% / LBM are bridged into the weight domain. WRITE tool — saved
    immediately. No-op with an error if the body_comp module is disabled."""
    from vitals.services import body_scan_service
    from vitals.utils.timeutils import today_local

    session_factory = get_session_factory()
    parsed_date = date_type.fromisoformat(on_date) if on_date else today_local()

    async with session_factory() as session:
        if not await _module_enabled(session, "body_comp"):
            return {"error": "module 'body_comp' is disabled"}
        scan = await body_scan_service.save_scan(
            session,
            on_date=parsed_date,
            device=device,
            metrics=metrics,
            note=note,
            source=Source.BODY_SCAN.value,
        )
        await session.commit()
        full = await body_scan_service.get_scan(session, scan.id)
        return _serialize_scan(full) if full else {"scan_id": scan.id}


@mcp.tool()
async def delete_body_scan(scan_id: int) -> dict:
    """Deletes a body-composition scan and its metrics. WRITE tool. No-op with an
    error if the body_comp module is disabled."""
    from vitals.services import body_scan_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        if not await _module_enabled(session, "body_comp"):
            return {"error": "module 'body_comp' is disabled"}
        ok = await body_scan_service.delete_scan(session, scan_id)
        await session.commit()
        return {"deleted": ok, "scan_id": scan_id}


# ── Labs tools ──────────────────────────────────────────────────────────────
@mcp.tool()
async def get_lab_results(
    marker: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    """Retrieves lab results (biomarker, value, unit, reference range, computed
    out-of-range flag), optionally filtered by marker name and/or date range
    (YYYY-MM-DD). Defaults to the most recent 100 rows across all markers."""
    from vitals.services import labs_service

    session_factory = get_session_factory()
    start = date_type.fromisoformat(start_date) if start_date else None
    end = date_type.fromisoformat(end_date) if end_date else None

    async with session_factory() as session:
        stmt = select(LabResult)
        if marker:
            stmt = stmt.where(LabResult.marker == labs_service.normalize_marker(marker))
        if start:
            stmt = stmt.where(LabResult.date >= start)
        if end:
            stmt = stmt.where(LabResult.date <= end)
        stmt = stmt.order_by(LabResult.date.desc(), LabResult.id.desc()).limit(limit)
        results = (await session.execute(stmt)).scalars().all()
        return [serialize_row(r) for r in results]


@mcp.tool()
async def log_lab_result(
    marker: str,
    value: float,
    on_date: Optional[str] = None,
    unit: Optional[str] = None,
    ref_low: Optional[float] = None,
    ref_high: Optional[float] = None,
    lab_name: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    """Records a single lab marker value (one biomarker from a blood/urine test).
    The out-of-range flag is computed automatically; a range left out here falls
    back to the marker's catalog range if one is already on file. WRITE tool —
    saved immediately. Defaults: on_date = today."""
    from vitals.services import labs_service
    from vitals.utils.timeutils import today_local

    session_factory = get_session_factory()
    parsed_date = date_type.fromisoformat(on_date) if on_date else today_local()

    async with session_factory() as session:
        row = await labs_service.add_result(
            session,
            on_date=parsed_date,
            marker=marker,
            value=value,
            unit=unit,
            ref_low=ref_low,
            ref_high=ref_high,
            lab_name=lab_name,
            note=note,
        )
        await session.commit()
        return await serialize_written(session, row)


@mcp.tool()
async def log_lab_results(
    results: list[dict],
    on_date: Optional[str] = None,
    lab_name: Optional[str] = None,
) -> dict:
    """Records every marker from one lab report at once (e.g. a full blood panel
    read from a photo/PDF shared in the conversation) — the natural way to push a
    whole report in one call instead of calling log_lab_result per marker.

    Each item in ``results`` is ``{"marker": str, "value": number, "unit": str?,
    "ref_low": number?, "ref_high": number?}``. Identical (date, marker, value)
    rows are deduped, so retrying a call is safe. The verbatim payload is kept in
    raw_payloads, same as a document uploaded through the web UI. WRITE tool —
    saved immediately. Defaults: on_date = today."""
    from vitals.services import labs_service
    from vitals.utils.timeutils import today_local

    session_factory = get_session_factory()
    parsed_date = date_type.fromisoformat(on_date) if on_date else today_local()

    async with session_factory() as session:
        extracted = {
            "date": parsed_date.isoformat(),
            "lab_name": lab_name,
            "results": results,
        }
        summary = await labs_service.ingest_extracted(session, extracted)
        await session.commit()
        return {
            "created": summary["created"],
            "skipped": summary["skipped"],
            "results": [await serialize_written(session, r) for r in summary["results"]],
        }


@mcp.tool()
async def delete_lab_result(result_id: int) -> dict:
    """Deletes a lab result by ID. WRITE tool — deletion is immediate."""
    from vitals.services import labs_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        ok = await labs_service.delete_result(session, result_id)
        await session.commit()
        return {"deleted": ok, "result_id": result_id}


class MCPAuthMiddleware:
    """ASGI middleware that intercepts all requests to the MCP application

    and validates the signed Bearer access token in the Authorization header.
    """
    def __init__(self, app, client_id: str):
        self.app = app
        self.client_id = client_id

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if scope.get("method") == "OPTIONS":
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"access-control-allow-origin", b"*"),
                    (b"access-control-allow-methods", b"GET, POST, OPTIONS"),
                    (b"access-control-allow-headers", b"Authorization, Content-Type"),
                    (b"content-length", b"0"),
                ]
            })
            await send({
                "type": "http.response.body",
                "body": b"",
                "more_body": False
            })
            return

        # Check Authorization header
        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode("utf-8")

        token = None
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:]
        else:
            # Fallback to query params
            from urllib.parse import parse_qs
            query_string = scope.get("query_string", b"").decode("utf-8")
            params = parse_qs(query_string)
            token_list = params.get("token") or params.get("access_token")
            if token_list:
                token = token_list[0]

        authenticated = False
        if token:
            from web.auth import _get_mcp_serializer
            from itsdangerous import SignatureExpired, BadSignature
            serializer = _get_mcp_serializer()
            try:
                # Validate access token with 1 year TTL limit
                payload = serializer.loads(token, max_age=31536000)
                if (
                    isinstance(payload, dict)
                    and payload.get("type") == "mcp_access_token"
                    and payload.get("client_id") == self.client_id
                ):
                    authenticated = True
            except (SignatureExpired, BadSignature):
                pass

        if not authenticated:
            response_body = b'{"detail":"Unauthorized. Invalid or missing MCP access token."}'
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(response_body)).encode("utf-8")),
                    (b"www-authenticate", b"Bearer"),
                ]
            })
            await send({
                "type": "http.response.body",
                "body": response_body,
                "more_body": False
            })
            return

        try:
            await self.app(scope, receive, send)
        except TypeError:
            logger.exception("MCP app raised TypeError handling %s", scope.get("path"))


def get_mcp_app() -> object:
    """Wraps the FastMCP Starlette app with Bearer authorization middleware."""
    from web.config import get_web_config
    cfg = get_web_config()
    raw_app = mcp.sse_app()
    return MCPAuthMiddleware(raw_app, client_id=cfg.mcp_client_id)

