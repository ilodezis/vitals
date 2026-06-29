"""Model Context Protocol (MCP) server integration for Vitals.

Exposes access to all health domains using FastMCP and standard SQLAlchemy
preloading patterns. Read tools cover every domain; write tools let Claude
record meals, weight, GLP-1 injections, skincare logs, body measurements,
and notes directly from the conversation.
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
from vitals.enums import Domain
from vitals.models import (
    BodyMeasurement,
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
async def get_weight_logs(start_date: Optional[str] = None, end_date: Optional[str] = None) -> dict:
    """Retrieves active weight logs, body measurements, and noise markers for a date range (YYYY-MM-DD)."""
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
        w_stmt = w_stmt.order_by(WeightLog.date.desc())
        weights = (await session.execute(w_stmt)).scalars().all()

        # Body measurements
        m_stmt = select(BodyMeasurement)
        if start:
            m_stmt = m_stmt.where(BodyMeasurement.date >= start)
        if end:
            m_stmt = m_stmt.where(BodyMeasurement.date <= end)
        m_stmt = m_stmt.order_by(BodyMeasurement.date.desc())
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
async def get_glp1_logs(start_date: Optional[str] = None, end_date: Optional[str] = None) -> dict:
    """Retrieves GLP-1 injection logs, active dosage phases, and recorded side effects."""
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
        i_stmt = i_stmt.order_by(Injection.date.desc())
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
        s_stmt = s_stmt.order_by(SideEffect.date.desc())
        effects = (await session.execute(s_stmt)).scalars().all()

        return {
            "injections": [serialize_row(i) for i in injections],
            "dose_phases": [serialize_row(p) for p in phases],
            "side_effects": [serialize_row(s) for s in effects],
        }


@mcp.tool()
async def get_garmin_metrics(start_date: Optional[str] = None, end_date: Optional[str] = None) -> dict:
    """Retrieves daily Garmin recovery/sleep scores and recorded activity sessions."""
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
        d_stmt = d_stmt.order_by(GarminDaily.date.desc())
        daily = (await session.execute(d_stmt)).scalars().all()

        # Activities
        a_stmt = select(GarminActivity)
        if start:
            a_stmt = a_stmt.where(GarminActivity.date >= start)
        if end:
            a_stmt = a_stmt.where(GarminActivity.date <= end)
        a_stmt = a_stmt.order_by(GarminActivity.date.desc(), GarminActivity.start_time.desc())
        activities = (await session.execute(a_stmt)).scalars().all()

        return {
            "daily_recovery": [serialize_row(d) for d in daily],
            "activities": [serialize_row(a) for a in activities],
        }


@mcp.tool()
async def get_hevy_workouts(start_date: Optional[str] = None, end_date: Optional[str] = None) -> list[dict]:
    """Retrieves Hevy strength training workouts, including exercises, sets, weights, and reps."""
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
        stmt = stmt.order_by(HevyWorkout.date.desc())
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
async def get_skincare_logs(start_date: Optional[str] = None, end_date: Optional[str] = None) -> dict:
    """Retrieves skincare routine application logs and skin status observations."""
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
        l_stmt = l_stmt.order_by(SkincareLog.date.desc())
        logs = (await session.execute(l_stmt)).scalars().all()

        # Observations
        o_stmt = select(SkincareObservation)
        if start:
            o_stmt = o_stmt.where(SkincareObservation.date >= start)
        if end:
            o_stmt = o_stmt.where(SkincareObservation.date <= end)
        o_stmt = o_stmt.order_by(SkincareObservation.date.desc())
        observations = (await session.execute(o_stmt)).scalars().all()

        return {
            "logs": [serialize_row(l) for l in logs],
            "observations": [serialize_row(o) for o in observations],
        }


@mcp.tool()
async def get_lab_results() -> list[dict]:
    """Retrieves medical laboratory test reports and all parsed biomarkers/ranges."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(LabResult).order_by(LabResult.date.desc())
        results = (await session.execute(stmt)).scalars().all()
        return [serialize_row(r) for r in results]


@mcp.tool()
async def get_genetics_snps() -> list[dict]:
    """Retrieves oцифрованные SNPs (генетические варианты) с описанием их влияния."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(GeneticVariant).order_by(GeneticVariant.gene, GeneticVariant.rsid)
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
) -> list[dict]:
    """Retrieves body measurements (neck, waist, hips, body-fat %, LBM) for a date range."""
    session_factory = get_session_factory()
    start = date_type.fromisoformat(start_date) if start_date else None
    end = date_type.fromisoformat(end_date) if end_date else None

    async with session_factory() as session:
        stmt = select(BodyMeasurement)
        if start:
            stmt = stmt.where(BodyMeasurement.date >= start)
        if end:
            stmt = stmt.where(BodyMeasurement.date <= end)
        stmt = stmt.order_by(BodyMeasurement.date.desc())
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
    Supported domains: weight, nutrition, glp1, skincare, measurement.
    WRITE tool — saved immediately."""
    from vitals.models.glp1 import Injection
    from vitals.models.skincare import SkincareLog

    model_map = {
        "weight": WeightLog,
        "nutrition": MealLog,
        "glp1": Injection,
        "skincare": SkincareLog,
        "measurement": BodyMeasurement,
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
    and date range. Returns records from: weight, nutrition, glp1, skincare, measurement."""
    from vitals.models.glp1 import Injection
    from vitals.models.skincare import SkincareLog

    model_map = {
        "weight": WeightLog,
        "nutrition": MealLog,
        "glp1": Injection,
        "skincare": SkincareLog,
        "measurement": BodyMeasurement,
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
            from web.auth import _get_serializer
            from itsdangerous import SignatureExpired, BadSignature
            serializer = _get_serializer()
            try:
                # Validate access token with 1 year TTL limit
                payload = serializer.loads(token, max_age=31536000)
                if payload.get("type") == "mcp_access_token" and payload.get("client_id") == self.client_id:
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
            pass


def get_mcp_app() -> object:
    """Wraps the FastMCP Starlette app with Bearer authorization middleware."""
    from web.config import get_web_config
    cfg = get_web_config()
    raw_app = mcp.sse_app()
    return MCPAuthMiddleware(raw_app, client_id=cfg.mcp_client_id)

