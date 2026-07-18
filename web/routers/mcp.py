"""Model Context Protocol (MCP) server integration for Vitals.

Exposes access to all health domains using FastMCP and standard SQLAlchemy
preloading patterns. Read tools cover every domain; write tools let Claude
record and edit meals, weight, GLP-1, skincare, supplements, measurements,
body scans, labs, goals, timeline events and notes directly from the
conversation. Two resources (``vitals://profile``, ``vitals://digest/latest``)
and a ``weekly_review`` prompt round out the surface.

Response conventions (a stable contract the model can rely on):
  * Success — the tool's normal payload (a dict, or a list of dicts).
  * A recoverable problem (bad id, unknown key, missing dependency) — a dict
    ``{"error": "<human message>"}`` (list-returning tools wrap it: ``[{"error": ...}]``).
  * A hard conflict block on a write — a dict ``{"blocked": true, "violations":
    [...], "message": ..., "hint": ...}`` (see ``_conflict_payload``); the model
    can retry the same call with ``override=True``.
  * A delete — ``{"deleted": <bool>, "<entity>_id": <id>}``.
"""
from __future__ import annotations

import logging
import os
from datetime import date as date_type
from typing import Optional

from fastmcp import FastMCP
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from vitals.config import load_config
from vitals.enums import Domain, MilestoneStatus, Source
from vitals.models import (
    Annotation,
    BodyMeasurement,
    BodyScan,
    DosePhase,
    GarminActivity,
    GarminDaily,
    GarminIntraday,
    GeneticVariant,
    HevyExercise,
    HevyWorkout,
    Injection,
    LabResult,
    MealLog,
    Milestone,
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
from vitals.services.conflict_engine import ConflictBlocked
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


def _conflict_payload(exc: ConflictBlocked) -> dict:
    """Structured result for a write blocked by a hard conflict rule.

    The HTML UI gets a 409 + violations and renders "Save anyway (Override)".
    A tool call has no HTTP status the model can act on, so we return the same
    violation list as a plain dict instead of letting the exception escape as an
    opaque 500 — the model can inspect the block and retry the call with
    ``override=True`` (the MCP equivalent of the override button)."""
    return {
        "blocked": True,
        "message": str(exc),
        "violations": [v.to_dict() for v in exc.violations],
        "hint": "Retry the same call with override=True to save anyway.",
    }


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
    from vitals.services import weight_service

    session_factory = get_session_factory()
    start = date_type.fromisoformat(start_date) if start_date else None
    end = date_type.fromisoformat(end_date) if end_date else None

    async with session_factory() as session:
        # Weight logs — the "active weight" invariant (superseded filter, source
        # priority) lives in weight_service; call it instead of re-encoding the
        # rule here, then apply this tool's newest-first, most-recent-`limit`
        # contract on top (the service returns all matching rows, ascending).
        weights = await weight_service.list_active_weights(session, start=start, end=end)
        weights = sorted(weights, key=lambda w: w.date, reverse=True)[:limit]

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


# Ceiling on intraday points in one get_garmin_metrics response (~5 days of a
# single series at Garmin's 3-minute cadence). The table is the densest in the
# project — a year is ~350k rows — so an unbounded read would blow the context.
INTRADAY_POINT_CAP = 5000


@mcp.tool()
async def get_garmin_metrics(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 100,
    intraday: bool = False,
) -> dict:
    """Retrieves daily Garmin recovery/sleep scores and recorded activity sessions.
    Each series defaults to the most recent 100 rows.

    Set ``intraday=True`` to also get the curves behind the daily summaries, as
    ``intraday: {series_type: [{ts, value}]}``. Two families of series:

      * the whole day — ``stress``, ``body_battery`` (a sample every ~3 minutes,
        so ~480 points per series per day);
      * the night — ``sleep_hr``, ``sleep_spo2``, ``sleep_respiration``,
        ``sleep_stress``, ``sleep_bb``, ``sleep_hrv``, ``sleep_movement``
        (~2000 points across the seven).

    A night's samples are dated to the daily row they belong to (the morning of
    waking), including the ones recorded the previous evening, so one night reads
    as one date. The night's *stage* timeline is not a series — it's
    ``sleep_stages`` on the daily row (``[{start, end, stage}]``, stage being
    deep/light/rem/awake), next to ``breathing_events``.

    Off by default because it is orders of magnitude more data than the daily
    rows: use it to answer *when* something happened (a stress spike, a Body
    Battery drain, an SpO2 dip and which sleep stage it fell in), always with a
    narrow start_date/end_date window. The response caps at 5000 points and sets
    ``intraday_truncated`` to true when the window held more than that.
    """
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

        result = {
            "daily_recovery": [serialize_row(d) for d in daily],
            "activities": [serialize_row(a) for a in activities],
        }

        if intraday:
            # Grouped per series and trimmed to {ts, value} rather than run through
            # serialize_row: at thousands of rows the per-row id/domain/source/
            # timestamps would dwarf the actual curve. Fetch one over the cap to
            # tell "exactly full" from "truncated".
            i_stmt = select(GarminIntraday)
            if start:
                i_stmt = i_stmt.where(GarminIntraday.date >= start)
            if end:
                i_stmt = i_stmt.where(GarminIntraday.date <= end)
            i_stmt = i_stmt.order_by(GarminIntraday.ts).limit(INTRADAY_POINT_CAP + 1)
            points = (await session.execute(i_stmt)).scalars().all()
            result["intraday_truncated"] = len(points) > INTRADAY_POINT_CAP
            series: dict[str, list[dict]] = {}
            for p in points[:INTRADAY_POINT_CAP]:
                series.setdefault(p.series_type, []).append(
                    {"ts": p.ts.isoformat(), "value": p.value}
                )
            result["intraday"] = series

        return result


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
    """Retrieves digitized SNPs (genetic variants) with a description of their effect.
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
    """Evaluates a proposed supplement (by free-text name) against the curated
    conflict-rule catalog — active supplements, genetics, skincare routine,
    labs, and GLP-1 state. The name is normalized to the same stable ``key``
    the catalog matches rules on (e.g. "Железо" -> "iron"), so this works
    regardless of spelling/language. Read-only — never writes, never blocks."""
    from vitals.services import conflict_catalog

    session_factory = get_session_factory()
    key = conflict_catalog.normalize_ingredient(supplement_name)
    async with session_factory() as session:
        violations = await conflict_engine.evaluate(
            session,
            Domain.SUPPLEMENTS.value,
            {"key": key, "name": supplement_name, "active": True},
        )
        return [v.to_dict() for v in violations]


_VALID_CONFLICT_DOMAINS = {d.value for d in Domain}


@mcp.tool()
async def list_conflict_rules(
    domain: Optional[str] = None, category: Optional[str] = None
) -> list[dict]:
    """Lists the curated cross-domain conflict rules (vitals/data/conflict_rules.yaml),
    optionally filtered by ``domain`` (matches either side of the rule) and/or
    ``category`` (absorption, pharmacogenomics, dermatology, lab_safety, glp1,
    contraindication). Only ``active`` rules are meaningful for evaluation, but
    inactive ones are included too so a caller can see the full catalog."""
    from vitals.models.conflict_rule import ConflictRule

    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(ConflictRule)
        if category:
            stmt = stmt.where(ConflictRule.category == category)
        rows = (await session.execute(stmt)).scalars().all()
        if domain:
            rows = [r for r in rows if r.domain_a == domain or r.domain_b == domain]
        return [serialize_row(r) for r in rows]


@mcp.tool()
async def check_conflicts(domain: str, payload: dict) -> list[dict]:
    """Evaluates an arbitrary proposed state against the active conflict rules
    for ``domain`` (one of: weight, glp1, supplements, genetics, skincare,
    labs, nutrition, workouts, garmin, milestones, system, body_comp). E.g.
    ``check_conflicts("labs", {"marker": "Калий", "value": 5.5})`` or
    ``check_conflicts("supplements", {"key": "iron", "active": True})``.
    Read-only — never writes, never blocks; returns the violations that would
    fire if this state were saved."""
    if domain not in _VALID_CONFLICT_DOMAINS:
        return [{"error": f"Unknown domain '{domain}'. Use one of: {', '.join(sorted(_VALID_CONFLICT_DOMAINS))}"}]

    session_factory = get_session_factory()
    async with session_factory() as session:
        violations = await conflict_engine.evaluate(session, domain, payload)
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
    override: bool = False,
) -> dict:
    """Records a meal or snack with optional macros (KCAL, protein, fat, carbs).

    This is a WRITE tool — the meal is saved to the database immediately.
    Defaults: on_date = today, eaten_at = current time. If a hard conflict rule
    blocks the save, returns ``{"blocked": true, "violations": [...]}`` instead
    of saving; call again with ``override=True`` to save anyway.
    """
    from datetime import time as time_type
    from vitals.services import nutrition_service
    from vitals.utils.timeutils import today_local

    session_factory = get_session_factory()
    parsed_date = date_type.fromisoformat(on_date) if on_date else today_local()
    parsed_time = time_type.fromisoformat(eaten_at) if eaten_at else None

    async with session_factory() as session:
        try:
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
                override=override,
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
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
    override: bool = False,
) -> dict:
    """Records a manual weight entry (kg). One active weight per date — manual
    entries override Garmin imports. WRITE tool — saved immediately. If a hard
    conflict rule blocks the save, returns ``{"blocked": true, ...}``; call again
    with ``override=True`` to save anyway."""
    from vitals.services import weight_service
    from vitals.utils.timeutils import today_local

    session_factory = get_session_factory()
    parsed_date = date_type.fromisoformat(on_date) if on_date else today_local()

    async with session_factory() as session:
        try:
            row = await weight_service.log_weight(
                session, on_date=parsed_date, weight_kg=weight_kg, note=note,
                override=override,
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
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
    override: bool = False,
) -> dict:
    """Records a GLP-1 injection (drug name, dose in mg, optional injection site).
    WRITE tool — saved immediately. If a hard conflict rule blocks the save,
    returns ``{"blocked": true, ...}``; call again with ``override=True`` to save
    anyway."""
    from vitals.services import glp1_service
    from vitals.utils.timeutils import today_local

    session_factory = get_session_factory()
    parsed_date = date_type.fromisoformat(on_date) if on_date else today_local()

    async with session_factory() as session:
        try:
            row = await glp1_service.log_injection(
                session, on_date=parsed_date, drug=drug, dose_mg=dose_mg,
                site=site, note=note, override=override,
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
        except ValueError as e:
            # An LLM bypasses the HTML form, so bad input (dose_mg<=0, garbage site)
            # comes back as a clean error instead of an opaque DB failure.
            return {"error": str(e)}
        await session.commit()
        return await serialize_written(session, row)


# ── HRT / TRT tools ─────────────────────────────────────────────────────────

@mcp.tool()
async def get_hrt_logs(
    start_date: Optional[str] = None, end_date: Optional[str] = None, limit: int = 100
) -> dict:
    """Retrieves HRT/TRT dose administrations, side effects, and the active cycle
    with its per-compound plan. Doses/side effects default to the most recent 100.
    READ tool."""
    from vitals.models.hrt import HrtDose, HrtSideEffect
    from vitals.services import hrt_cycle_service

    session_factory = get_session_factory()
    start = date_type.fromisoformat(start_date) if start_date else None
    end = date_type.fromisoformat(end_date) if end_date else None

    async with session_factory() as session:
        d_stmt = select(HrtDose)
        if start:
            d_stmt = d_stmt.where(HrtDose.date >= start)
        if end:
            d_stmt = d_stmt.where(HrtDose.date <= end)
        d_stmt = d_stmt.order_by(HrtDose.date.desc()).limit(limit)
        doses = (await session.execute(d_stmt)).scalars().all()

        s_stmt = select(HrtSideEffect).order_by(HrtSideEffect.date.desc()).limit(limit)
        effects = (await session.execute(s_stmt)).scalars().all()

        active = await hrt_cycle_service.active_cycle(session)
        active_cycle = None
        if active is not None:
            active_cycle = serialize_row(active)
            active_cycle["items"] = [serialize_row(it) for it in active.items]

        return {
            "doses": [serialize_row(d) for d in doses],
            "side_effects": [serialize_row(e) for e in effects],
            "active_cycle": active_cycle,
        }


@mcp.tool()
async def log_hrt_dose(
    compound_key: str,
    dose: Optional[float] = None,
    unit: Optional[str] = None,
    volume_ml: Optional[float] = None,
    concentration_mg_ml: Optional[float] = None,
    on_date: Optional[str] = None,
    brand: Optional[str] = None,
    lab: Optional[str] = None,
    batch: Optional[str] = None,
    site: Optional[str] = None,
    note: Optional[str] = None,
    override: bool = False,
) -> dict:
    """Records an HRT/TRT administration. ``compound_key`` is a catalog slug (e.g.
    'testosterone_enanthate'). Give either ``dose`` (in ``unit`` — mg/iu/mcg) or a
    ``volume_ml`` with ``concentration_mg_ml`` (or the catalog concentration) to
    compute mg. Grey-market ``brand``/``lab``/``batch`` are optional. WRITE tool —
    on a hard block returns ``{"blocked": true, ...}``; retry with
    ``override=True``."""
    from vitals.services import hrt_service
    from vitals.utils.timeutils import today_local

    session_factory = get_session_factory()
    parsed_date = date_type.fromisoformat(on_date) if on_date else today_local()

    async with session_factory() as session:
        try:
            row = await hrt_service.log_dose(
                session, compound_key=compound_key, on_date=parsed_date, dose=dose,
                unit=unit, volume_ml=volume_ml, concentration_mg_ml=concentration_mg_ml,
                brand=brand, lab=lab, batch=batch, site=site, note=note, override=override,
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
        except ValueError as e:
            return {"error": str(e)}
        await session.commit()
        return await serialize_written(session, row)


@mcp.tool()
async def add_hrt_cycle(
    kind: str,
    start_date: Optional[str] = None,
    name: Optional[str] = None,
    end_date: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    """Starts an HRT cycle (``kind``: course | pct — put nuance like TRT/blast/
    cruise in ``name``). An open-ended cycle closes the previous open one. WRITE
    tool. Add compounds with ``add_hrt_cycle_item``."""
    from vitals.services import hrt_cycle_service
    from vitals.utils.timeutils import today_local

    session_factory = get_session_factory()
    start = date_type.fromisoformat(start_date) if start_date else today_local()
    end = date_type.fromisoformat(end_date) if end_date else None

    async with session_factory() as session:
        try:
            cycle = await hrt_cycle_service.add_cycle(
                session, kind=kind, start_date=start, name=name, end_date=end, note=note,
            )
        except ValueError as e:
            return {"error": str(e)}
        await session.commit()
        return await serialize_written(session, cycle)


@mcp.tool()
async def add_hrt_cycle_item(
    cycle_id: int,
    compound_key: str,
    schedule: Optional[list] = None,
    dose: Optional[float] = None,
    interval_days: Optional[float] = None,
    duration_days: Optional[int] = None,
    start_offset_days: Optional[int] = None,
    unit: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    """Adds a compound plan to a cycle. Pass a full ``schedule`` (a list of
    segments — flat ``{dose, interval_days, duration_days}`` or a linear ramp
    ``{dose_start, dose_end, step, step_every_days, interval_days, duration_days}``)
    for titration/ramps, or the simple ``dose``+``interval_days`` for one flat
    segment. ``start_offset_days`` delays the compound's grid relative to the
    cycle start (week 5 → 28) for staggered courses. WRITE tool."""
    from vitals.services import hrt_cycle_service

    if not schedule:
        if dose is None or interval_days is None:
            return {"error": "provide schedule, or both dose and interval_days"}
        segment: dict = {"dose": dose, "interval_days": interval_days}
        if duration_days:
            segment["duration_days"] = int(duration_days)
        schedule = [segment]

    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            item = await hrt_cycle_service.add_cycle_item(
                session, cycle_id, compound_key=compound_key, schedule=schedule,
                unit=unit, start_offset_days=int(start_offset_days or 0), note=note,
            )
        except ValueError as e:
            return {"error": str(e)}
        if item is None:
            return {"error": f"cycle {cycle_id} not found"}
        await session.commit()
        return await serialize_written(session, item)


@mcp.tool()
async def get_hrt_cycles() -> dict:
    """Lists all HRT cycles (newest first) with their per-compound plans. READ tool."""
    from vitals.services import hrt_cycle_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        cycles = await hrt_cycle_service.list_cycles(session)
        out = []
        for c in cycles:
            row = serialize_row(c)
            row["items"] = [serialize_row(it) for it in c.items]
            out.append(row)
        return {"cycles": out}


# ── Skincare tools ──────────────────────────────────────────────────────────

@mcp.tool()
async def log_skincare(
    on_date: Optional[str] = None,
    retinoid: bool = False,
    azelaic: bool = False,
    peel: bool = False,
    niacinamide_spf: bool = False,
    moisturizer: bool = False,
    vitamin_c: bool = False,
    benzoyl_peroxide: bool = False,
    note: Optional[str] = None,
    override: bool = False,
) -> dict:
    """Records or updates the daily skincare routine checklist (one per day, upsert).
    Boolean flags indicate which products were applied. WRITE tool — saved
    immediately. If a hard conflict rule blocks the save, returns
    ``{"blocked": true, ...}``; call again with ``override=True`` to save anyway."""
    from vitals.services import skincare_service
    from vitals.utils.timeutils import today_local

    session_factory = get_session_factory()
    parsed_date = date_type.fromisoformat(on_date) if on_date else today_local()

    async with session_factory() as session:
        try:
            row = await skincare_service.upsert_log(
                session, on_date=parsed_date, retinoid=retinoid, azelaic=azelaic,
                peel=peel, niacinamide_spf=niacinamide_spf, moisturizer=moisturizer,
                vitamin_c=vitamin_c, benzoyl_peroxide=benzoyl_peroxide,
                note=note, override=override,
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
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
    override: bool = False,
) -> dict:
    """Records body circumference measurements (neck, waist, hips in cm). Upserts
    per date. Auto-computes Navy body-fat % and LBM if weight exists for the date.
    WRITE tool — saved immediately. If a hard conflict rule blocks the save,
    returns ``{"blocked": true, ...}``; call again with ``override=True``."""
    from vitals.services import weight_service
    from vitals.utils.timeutils import today_local

    session_factory = get_session_factory()
    parsed_date = date_type.fromisoformat(on_date) if on_date else today_local()

    async with session_factory() as session:
        try:
            row = await weight_service.upsert_body_measurement(
                session, on_date=parsed_date, neck_cm=neck_cm, waist_cm=waist_cm,
                hips_cm=hips_cm, note=note, override=override,
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
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

# Domains whose per-row ``note`` field the note tools can read/write, mapped to
# their model. Single source of truth for both log_note and get_notes so the two
# never drift out of sync.
_NOTE_MODELS = {
    "weight": WeightLog,
    "nutrition": MealLog,
    "glp1": Injection,
    "skincare": SkincareLog,
    "measurement": BodyMeasurement,
    "body_comp": BodyScan,
    "labs": LabResult,
}


@mcp.tool()
async def log_note(
    domain: str,
    record_id: int,
    note: str,
) -> dict:
    """Adds or updates the note field on any domain record by its ID.
    Supported domains: weight, nutrition, glp1, skincare, measurement, body_comp, labs.
    WRITE tool — saved immediately."""
    model = _NOTE_MODELS.get(domain)
    if model is None:
        return {"error": f"Unknown domain '{domain}'. Use: {', '.join(_NOTE_MODELS)}"}

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
    if domain and domain not in _NOTE_MODELS:
        return [{"error": f"Unknown domain '{domain}'. Use: {', '.join(_NOTE_MODELS)}"}]

    targets = {domain: _NOTE_MODELS[domain]} if domain else _NOTE_MODELS
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
    override: bool = False,
) -> dict:
    """Records a body-composition scan from structured metrics (no photo needed).

    Each metric is ``{"label" or "metric_key": str, "value": number, "unit": str?,
    "ref_low": number?, "ref_high": number?, "segment": str?}``. The scan's weight /
    body-fat% / LBM are bridged into the weight domain. WRITE tool — saved
    immediately. No-op with an error if the body_comp module is disabled. If a hard
    conflict rule blocks the save, returns ``{"blocked": true, ...}``; call again
    with ``override=True``."""
    from vitals.services import body_scan_service
    from vitals.utils.timeutils import today_local

    session_factory = get_session_factory()
    parsed_date = date_type.fromisoformat(on_date) if on_date else today_local()

    async with session_factory() as session:
        if not await _module_enabled(session, "body_comp"):
            return {"error": "module 'body_comp' is disabled"}
        try:
            scan = await body_scan_service.save_scan(
                session,
                on_date=parsed_date,
                device=device,
                metrics=metrics,
                note=note,
                source=Source.BODY_SCAN.value,
                override=override,
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
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


# ── Timeline tools ───────────────────────────────────────────────────────────
@mcp.tool()
async def get_timeline(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    domain: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    """Retrieves the cross-domain event feed — manual annotations (trips,
    illness, protocol changes) plus derived events (GLP-1 dose changes, lab
    draws, BIA scans, achieved milestones, noisy weight periods), newest first.
    Optionally filtered by date range (YYYY-MM-DD) and/or domain (weight, glp1,
    garmin, workouts, labs, nutrition, skincare, supplements, genetics,
    body_comp, or "timeline" for global flags)."""
    from vitals.services import timeline_service

    session_factory = get_session_factory()
    start = date_type.fromisoformat(start_date) if start_date else None
    end = date_type.fromisoformat(end_date) if end_date else None
    domains = [domain] if domain else None

    async with session_factory() as session:
        events = await timeline_service.list_events(
            session, domains=domains, start=start, end=end, limit=limit
        )
        return [e.to_dict() for e in events]


@mcp.tool()
async def log_event(
    title: str,
    on_date: Optional[str] = None,
    end_date: Optional[str] = None,
    kind: str = "note",
    domain: str = "timeline",
    note: Optional[str] = None,
) -> dict:
    """Records a manual Timeline annotation — a flag shown on every chart and
    in the event feed (a trip, an illness, a protocol change, a free-form
    note). ``kind`` is one of: life_event, illness, travel, protocol_change,
    note. ``domain`` scopes the flag to one chart (weight, glp1, ...) or
    "timeline" (default) to show it on every chart. ``end_date`` makes it a
    range (e.g. a week-long trip); omit it for a single-day event. WRITE tool —
    saved immediately. No-op with an error if the timeline module is disabled."""
    from vitals.services import timeline_service
    from vitals.utils.timeutils import today_local

    session_factory = get_session_factory()
    parsed_date = date_type.fromisoformat(on_date) if on_date else today_local()
    parsed_end = date_type.fromisoformat(end_date) if end_date else None

    async with session_factory() as session:
        if not await _module_enabled(session, "timeline"):
            return {"error": "module 'timeline' is disabled"}
        row = await timeline_service.create_annotation(
            session,
            title=title,
            on_date=parsed_date,
            end_date=parsed_end,
            kind=kind,
            domain=domain,
            note=note,
        )
        await session.commit()
        return await serialize_written(session, row)


# ── Cross-domain + whole-lake tools ──────────────────────────────────────────
@mcp.tool()
async def get_full_snapshot(
    on_date: Optional[str] = None,
    period_days: int = 7,
) -> dict:
    """Returns one structured cross-domain snapshot for a point in time — the same
    context the weekly digest is built from: profile, weight trend (noise-excluded
    MA7 + slope), GLP-1 state, recent labs, activity/recovery, workouts, nutrition,
    skincare and active goals, all aligned to ``on_date`` (default today) over a
    ``period_days`` window. Use this instead of calling each per-domain read tool
    separately when you want the whole picture / cross-domain correlations."""
    from vitals.services import digest_service

    session_factory = get_session_factory()
    parsed_date = date_type.fromisoformat(on_date) if on_date else None
    async with session_factory() as session:
        return await digest_service.assemble_context(
            session, on_date=parsed_date, period_days=period_days
        )


@mcp.tool()
async def export_everything() -> dict:
    """Returns the entire health history as one compact, secret-free, LLM-ready
    export grouped by domain (weight, measurements, body scans, GLP-1, labs,
    Garmin, workouts, nutrition, skincare, supplements, genetics, milestones,
    timeline). This is the way to read the full long-term history in a single
    call rather than paging each domain's newest-100 read tool. Read-only."""
    from vitals.services import data_portability_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        return await data_portability_service.export_llm(session)


@mcp.tool()
async def get_data_overview() -> dict:
    """Returns a per-domain map of what data exists: row count, earliest and latest
    date, and last-updated timestamp for each domain. Call this first to orient —
    it tells you the real date coverage and density before you query a domain, so
    you don't page blindly through empty or out-of-range windows. Read-only."""
    # Dated log/metric tables: report count + min/max of their date column.
    dated = [
        ("weight", WeightLog, WeightLog.date),
        ("measurements", BodyMeasurement, BodyMeasurement.date),
        ("body_scans", BodyScan, BodyScan.date),
        ("glp1_injections", Injection, Injection.date),
        ("side_effects", SideEffect, SideEffect.date),
        ("garmin_daily", GarminDaily, GarminDaily.date),
        ("garmin_activities", GarminActivity, GarminActivity.date),
        ("garmin_intraday", GarminIntraday, GarminIntraday.date),
        ("workouts", HevyWorkout, HevyWorkout.date),
        ("labs", LabResult, LabResult.date),
        ("nutrition", MealLog, MealLog.date),
        ("skincare_logs", SkincareLog, SkincareLog.date),
        ("skincare_observations", SkincareObservation, SkincareObservation.date),
        ("weekly_digests", WeeklyDigest, WeeklyDigest.date),
        ("timeline", Annotation, Annotation.date),
        ("noise_markers", NoiseMarker, NoiseMarker.start_date),
    ]
    # Config/catalog tables have no per-day date — report count only.
    count_only = [
        ("supplements", Supplement),
        ("genetics", GeneticVariant),
        ("milestones", Milestone),
        ("dose_phases", DosePhase),
    ]

    session_factory = get_session_factory()
    overview: dict = {}
    async with session_factory() as session:
        for name, model, date_col in dated:
            cols = [func.count(), func.min(date_col), func.max(date_col)]
            updated_col = getattr(model, "updated_at", None)
            if updated_col is not None:
                cols.append(func.max(updated_col))
            row = (await session.execute(select(*cols))).one()
            entry = {
                "count": row[0],
                "earliest": row[1].isoformat() if row[1] else None,
                "latest": row[2].isoformat() if row[2] else None,
            }
            if updated_col is not None:
                entry["last_updated"] = row[3].isoformat() if row[3] else None
            overview[name] = entry

        for name, model in count_only:
            count = (await session.execute(select(func.count()).select_from(model))).scalar_one()
            overview[name] = {"count": count}

    return overview


# ── Milestones / goals tools ──────────────────────────────────────────────────
_MILESTONE_STATUSES = {s.value for s in MilestoneStatus}


@mcp.tool()
async def get_milestones(status: Optional[str] = None) -> list[dict]:
    """Returns goal cards with live progress (current value, remaining, days left)
    computed for weight/body-comp goals. Optionally filtered by ``status`` (active,
    achieved, missed, paused). Read-only."""
    from vitals.services import milestones_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        rows = await milestones_service.list_milestones(session, status=status)
        return [await milestones_service.progress(session, m) for m in rows]


@mcp.tool()
async def create_milestone(
    name: str,
    domain: str = Domain.WEIGHT.value,
    target_value: Optional[float] = None,
    target_unit: Optional[str] = None,
    deadline: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    """Creates a goal card (e.g. "reach 85 kg by 2026-12-31"). ``domain`` is the
    related health area (weight, glp1, labs, body_comp, ...); ``deadline`` is
    YYYY-MM-DD. WRITE tool — saved immediately."""
    from vitals.services import milestones_service

    session_factory = get_session_factory()
    parsed_deadline = date_type.fromisoformat(deadline) if deadline else None
    async with session_factory() as session:
        row = await milestones_service.create_milestone(
            session, name=name, domain=domain, target_value=target_value,
            target_unit=target_unit, deadline=parsed_deadline, note=note,
        )
        await session.commit()
        return await serialize_written(session, row)


@mcp.tool()
async def update_milestone(
    milestone_id: int,
    name: Optional[str] = None,
    domain: Optional[str] = None,
    target_value: Optional[float] = None,
    target_unit: Optional[str] = None,
    deadline: Optional[str] = None,
    status: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    """Updates a goal card by ID. Only the fields you pass are changed. Use
    ``status`` to mark a goal achieved/missed/paused/active. WRITE tool."""
    from vitals.services import milestones_service

    if status is not None and status not in _MILESTONE_STATUSES:
        return {"error": f"Unknown status '{status}'. Use: {', '.join(sorted(_MILESTONE_STATUSES))}"}

    session_factory = get_session_factory()
    async with session_factory() as session:
        kwargs: dict = {}
        if name is not None:
            kwargs["name"] = name
        if domain is not None:
            kwargs["domain"] = domain
        if target_value is not None:
            kwargs["target_value"] = target_value
        if target_unit is not None:
            kwargs["target_unit"] = target_unit
        if deadline is not None:
            kwargs["deadline"] = date_type.fromisoformat(deadline)
        if status is not None:
            kwargs["status"] = status
        if note is not None:
            kwargs["note"] = note
        row = await milestones_service.update_milestone(session, milestone_id, **kwargs)
        if row is None:
            return {"error": f"Milestone {milestone_id} not found"}
        await session.commit()
        return await serialize_written(session, row)


@mcp.tool()
async def delete_milestone(milestone_id: int) -> dict:
    """Deletes a goal card by ID. WRITE tool — deletion is immediate."""
    from vitals.services import milestones_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        ok = await milestones_service.delete_milestone(session, milestone_id)
        await session.commit()
        return {"deleted": ok, "milestone_id": milestone_id}


# ── GLP-1 write completeness (edit/delete injection, side effects, phases) ────
@mcp.tool()
async def update_glp1(
    injection_id: int,
    drug: str,
    dose_mg: float,
    on_date: Optional[str] = None,
    site: Optional[str] = None,
    note: Optional[str] = None,
    override: bool = False,
) -> dict:
    """Edits an existing GLP-1 injection by ID. Runs the same conflict gate as a
    fresh log — on a hard block returns ``{"blocked": true, ...}``; retry with
    ``override=True``. WRITE tool."""
    from vitals.services import glp1_service
    from vitals.utils.timeutils import today_local

    session_factory = get_session_factory()
    parsed_date = date_type.fromisoformat(on_date) if on_date else today_local()
    async with session_factory() as session:
        try:
            row = await glp1_service.update_injection(
                session, injection_id, on_date=parsed_date, drug=drug,
                dose_mg=dose_mg, site=site, note=note, override=override,
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
        except ValueError as e:
            return {"error": str(e)}
        if row is None:
            return {"error": f"Injection {injection_id} not found"}
        await session.commit()
        return await serialize_written(session, row)


@mcp.tool()
async def delete_glp1(injection_id: int) -> dict:
    """Deletes a GLP-1 injection by ID. WRITE tool — deletion is immediate."""
    from vitals.services import glp1_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        ok = await glp1_service.delete_injection(session, injection_id)
        await session.commit()
        return {"deleted": ok, "injection_id": injection_id}


@mcp.tool()
async def log_side_effect(
    effect_type: str,
    severity: int,
    on_date: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    """Records a GLP-1 side effect (e.g. "nausea") with a severity 1–5 for a date
    (default today). WRITE tool — saved immediately."""
    from vitals.services import glp1_service
    from vitals.utils.timeutils import today_local

    session_factory = get_session_factory()
    parsed_date = date_type.fromisoformat(on_date) if on_date else today_local()
    async with session_factory() as session:
        row = await glp1_service.log_side_effect(
            session, on_date=parsed_date, effect_type=effect_type,
            severity=severity, note=note,
        )
        await session.commit()
        return await serialize_written(session, row)


@mcp.tool()
async def delete_side_effect(effect_id: int) -> dict:
    """Deletes a GLP-1 side-effect entry by ID. WRITE tool."""
    from vitals.services import glp1_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        ok = await glp1_service.delete_side_effect(session, effect_id)
        await session.commit()
        return {"deleted": ok, "effect_id": effect_id}


@mcp.tool()
async def add_dose_phase(
    start_date: str,
    drug: str,
    dose_mg: float,
    end_date: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    """Adds a GLP-1 dose phase (a period on a given drug + dose, overlaid on the
    weight chart). An open-ended phase (no ``end_date``) auto-closes any other
    still-open phase the day before it starts. WRITE tool."""
    from vitals.services import glp1_service

    session_factory = get_session_factory()
    parsed_start = date_type.fromisoformat(start_date)
    parsed_end = date_type.fromisoformat(end_date) if end_date else None
    async with session_factory() as session:
        row = await glp1_service.add_dose_phase(
            session, start_date=parsed_start, drug=drug, dose_mg=dose_mg,
            end_date=parsed_end, note=note,
        )
        await session.commit()
        return await serialize_written(session, row)


@mcp.tool()
async def delete_dose_phase(phase_id: int) -> dict:
    """Deletes a GLP-1 dose phase by ID. WRITE tool."""
    from vitals.services import glp1_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        ok = await glp1_service.delete_dose_phase(session, phase_id)
        await session.commit()
        return {"deleted": ok, "phase_id": phase_id}


# ── Skincare observations ─────────────────────────────────────────────────────
@mcp.tool()
async def log_skincare_observation(
    on_date: Optional[str] = None,
    inflammation: Optional[int] = None,
    pih: Optional[int] = None,
    zone: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    """Records a skin-status observation — inflammation and PIH (post-inflammatory
    hyperpigmentation) scores, an optional face ``zone``, and a note. Distinct from
    the daily routine checklist (log_skincare). WRITE tool — saved immediately."""
    from vitals.services import skincare_service
    from vitals.utils.timeutils import today_local

    session_factory = get_session_factory()
    parsed_date = date_type.fromisoformat(on_date) if on_date else today_local()
    async with session_factory() as session:
        row = await skincare_service.add_observation(
            session, on_date=parsed_date, inflammation=inflammation,
            pih=pih, zone=zone, note=note,
        )
        await session.commit()
        return await serialize_written(session, row)


@mcp.tool()
async def delete_skincare_observation(observation_id: int) -> dict:
    """Deletes a skin-status observation by ID. WRITE tool."""
    from vitals.services import skincare_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        ok = await skincare_service.delete_observation(session, observation_id)
        await session.commit()
        return {"deleted": ok, "observation_id": observation_id}


# ── Supplements catalog CRUD ──────────────────────────────────────────────────
@mcp.tool()
async def add_supplement(
    name: str,
    key: Optional[str] = None,
    dose: Optional[str] = None,
    timing: Optional[str] = None,
    evidence: Optional[str] = None,
    active: bool = True,
    contraindications: Optional[str] = None,
    note: Optional[str] = None,
    override: bool = False,
) -> dict:
    """Adds a supplement to the catalog (reference, not a daily log). ``key`` is the
    stable conflict-matching slug — omit it and it's derived from ``name`` (RU/EN
    aware). ``evidence`` is tier A/B/C. Activating a contraindicated supplement can
    hard-block → ``{"blocked": true, ...}``; retry with ``override=True``. WRITE tool."""
    from vitals.services import supplements_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            row = await supplements_service.add_supplement(
                session, name=name, key=key, dose=dose, timing=timing,
                evidence=evidence, active=active,
                contraindications=contraindications, note=note, override=override,
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
        await session.commit()
        return await serialize_written(session, row)


@mcp.tool()
async def update_supplement(
    supplement_id: int,
    name: str,
    key: Optional[str] = None,
    dose: Optional[str] = None,
    timing: Optional[str] = None,
    evidence: Optional[str] = None,
    active: bool = True,
    contraindications: Optional[str] = None,
    note: Optional[str] = None,
    override: bool = False,
) -> dict:
    """Updates a catalog supplement by ID (full replace of its fields). Same
    conflict gate as add — a hard block returns ``{"blocked": true, ...}``; retry
    with ``override=True``. WRITE tool."""
    from vitals.services import supplements_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            row = await supplements_service.update_supplement(
                session, supplement_id, name=name, key=key, dose=dose,
                timing=timing, evidence=evidence, active=active,
                contraindications=contraindications, note=note, override=override,
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
        if row is None:
            return {"error": f"Supplement {supplement_id} not found"}
        await session.commit()
        return await serialize_written(session, row)


@mcp.tool()
async def set_supplement_active(
    supplement_id: int, active: bool, override: bool = False
) -> dict:
    """Toggles a supplement's active flag. Activating a contraindicated one runs the
    conflict check → ``{"blocked": true, ...}`` unless ``override=True``. WRITE tool."""
    from vitals.services import supplements_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            row = await supplements_service.set_active(
                session, supplement_id, active, override=override
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
        if row is None:
            return {"error": f"Supplement {supplement_id} not found"}
        await session.commit()
        return await serialize_written(session, row)


@mcp.tool()
async def delete_supplement(supplement_id: int) -> dict:
    """Deletes a supplement from the catalog by ID. WRITE tool."""
    from vitals.services import supplements_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        ok = await supplements_service.delete_supplement(session, supplement_id)
        await session.commit()
        return {"deleted": ok, "supplement_id": supplement_id}


# ── Body measurement edit/delete + noise markers ──────────────────────────────
@mcp.tool()
async def update_measurement(
    measurement_id: int,
    on_date: str,
    neck_cm: Optional[float] = None,
    waist_cm: Optional[float] = None,
    hips_cm: Optional[float] = None,
    note: Optional[str] = None,
    override: bool = False,
) -> dict:
    """Edits a body-measurement row by ID (recomputes Navy body-fat % / LBM). On a
    hard block returns ``{"blocked": true, ...}``; retry with ``override=True``.
    WRITE tool."""
    from vitals.services import weight_service

    session_factory = get_session_factory()
    parsed_date = date_type.fromisoformat(on_date)
    async with session_factory() as session:
        try:
            row = await weight_service.update_body_measurement(
                session, measurement_id, on_date=parsed_date, neck_cm=neck_cm,
                waist_cm=waist_cm, hips_cm=hips_cm, note=note, override=override,
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
        if row is None:
            return {"error": f"Measurement {measurement_id} not found"}
        await session.commit()
        return await serialize_written(session, row)


@mcp.tool()
async def delete_measurement(measurement_id: int) -> dict:
    """Deletes a body-measurement row by ID. WRITE tool."""
    from vitals.services import weight_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        ok = await weight_service.delete_body_measurement(session, measurement_id)
        await session.commit()
        return {"deleted": ok, "measurement_id": measurement_id}


@mcp.tool()
async def add_noise_marker(
    start_date: str,
    reason: str,
    end_date: Optional[str] = None,
    direction: Optional[str] = None,
) -> dict:
    """Marks a date range as noisy so it's excluded from the weight moving average
    and trend (e.g. "sick week", "creatine loading"). ``direction`` is up (scale
    inflated), down (scale deflated), or neutral. Omit ``end_date`` for a single
    day. WRITE tool — the weight trend recomputes without this range."""
    from vitals.services import weight_service

    session_factory = get_session_factory()
    parsed_start = date_type.fromisoformat(start_date)
    parsed_end = date_type.fromisoformat(end_date) if end_date else None
    async with session_factory() as session:
        row = await weight_service.add_noise_marker(
            session, start_date=parsed_start, end_date=parsed_end,
            reason=reason, direction=direction,
        )
        await session.commit()
        return await serialize_written(session, row)


@mcp.tool()
async def delete_noise_marker(marker_id: int) -> dict:
    """Deletes a noise marker by ID — its date range re-enters the weight trend.
    WRITE tool."""
    from vitals.services import weight_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        ok = await weight_service.delete_noise_marker(session, marker_id)
        await session.commit()
        return {"deleted": ok, "marker_id": marker_id}


# ── Modules (optional-domain toggles) ─────────────────────────────────────────
@mcp.tool()
async def get_modules() -> dict:
    """Returns which optional domains are enabled, plus which module keys are core
    (always-on, locked) vs optional (toggleable). Check this before calling a
    module-gated write tool (log_body_scan, log_event) so you know if it's on."""
    from vitals.services import modules_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        enabled = await modules_service.get_enabled_modules(session)
    return {
        "enabled": enabled,
        "core": sorted(modules_service.CORE_KEYS),
        "optional": sorted(modules_service.OPTIONAL_KEYS),
    }


@mcp.tool()
async def set_module(key: str, enabled: bool) -> dict:
    """Enables or disables an optional module (e.g. body_comp, timeline, glp1,
    nutrition). Core modules are locked and return an error. WRITE tool — returns
    the new enabled-module map."""
    from vitals.services import modules_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            state = await modules_service.set_module_enabled(
                session, key=key, enabled=enabled
            )
        except modules_service.ModuleToggleError as e:
            return {"error": str(e)}
        await session.commit()
        return {"enabled": state}


# ── Weekly digest generation ──────────────────────────────────────────────────
@mcp.tool()
async def generate_digest_now(period_days: int = 7) -> dict:
    """Generates a fresh weekly AI digest right now (assembles the cross-domain
    context, asks the configured LLM for the narrative, saves it) and returns it.
    Errors cleanly if no OpenRouter key is configured. WRITE tool."""
    from vitals.integrations.llm_client import LLMClient, LLMNotConfigured
    from vitals.services import digest_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            row = await digest_service.generate_digest(
                session, LLMClient(), period_days=period_days
            )
        except LLMNotConfigured:
            return {"error": "LLM not configured — set VITALS_OPENROUTER_API_KEY"}
        await session.commit()
        return await serialize_written(session, row)


# ── Trend analytics ───────────────────────────────────────────────────────────
@mcp.tool()
async def get_trend(
    metric_key: str,
    param: Optional[str] = None,
    target: Optional[float] = None,
    rolling_window_days: int = 7,
    exclude_noise: bool = True,
) -> dict:
    """Computes the trend for one metric instead of returning raw rows: linear slope
    (per day and per week), the latest rolling-mean value, and — if ``target`` is
    given — the projected date the trend reaches it. For weight metrics, noise-marked
    ranges are excluded (``exclude_noise``).

    ``metric_key`` is a registry key such as ``weight.weight_kg``,
    ``weight.body_fat_pct``, ``garmin.hrv_avg``, ``nutrition.calories``, or a
    parametrized one: ``labs.marker`` (``param`` = marker name),
    ``hevy.working_weight`` (``param`` = exercise id), ``body_comp.metric``
    (``param`` = ``metric_key`` or ``metric_key:segment``). Read-only."""
    from vitals.services import chart_data_service, weight_service
    from vitals.services.analytics import exclude_ranges
    from vitals.services.analytics.regression import fit_trend, project_date_for_value
    from vitals.services.analytics.rolling import rolling_mean_by_date
    from vitals.services.analytics.chart_registry import get as get_metric

    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            field = get_metric(metric_key)
        except KeyError:
            return {"error": f"Unknown metric '{metric_key}'"}
        try:
            raw = await chart_data_service.series_for(
                session, metric_key=metric_key, param=param
            )
        except ValueError as e:
            return {"error": str(e)}

        points = [(date_type.fromisoformat(p["date"]), float(p["value"])) for p in raw]

        noise_applied = False
        if exclude_noise and field.domain == "weight":
            markers = await weight_service.list_noise_markers(session)
            ranges = [(m.start_date, m.end_date) for m in markers]
            if ranges:
                points = exclude_ranges(points, ranges)
                noise_applied = True

        points = sorted(points, key=lambda p: p[0])
        if not points:
            return {"metric_key": metric_key, "param": param, "unit": field.unit, "points": 0}

        trend = fit_trend(points)
        rolling = rolling_mean_by_date(points, window_days=rolling_window_days)
        result: dict = {
            "metric_key": metric_key,
            "param": param,
            "unit": field.unit,
            "points": len(points),
            "first": {"date": points[0][0].isoformat(), "value": points[0][1]},
            "last": {"date": points[-1][0].isoformat(), "value": points[-1][1]},
            "rolling_mean": {
                "window_days": rolling_window_days,
                "last": {"date": rolling[-1][0].isoformat(), "value": rolling[-1][1]},
            },
            "trend": None if trend is None else {
                "slope_per_day": round(trend.slope_per_day, 5),
                "slope_per_week": round(trend.slope_per_week, 4),
                "n": trend.n,
            },
            "noise_excluded": noise_applied,
        }
        if target is not None:
            crossing = project_date_for_value(points, target)
            result["projection"] = {
                "target": target,
                "date": crossing.isoformat() if crossing else None,
            }
        return result


# ── Resources & prompts ───────────────────────────────────────────────────────
@mcp.resource("vitals://profile")
async def profile_resource() -> dict:
    """The user's physical profile, goals, and program — attachable as lightweight
    context without spending a tool call."""
    return await get_user_profile()


@mcp.resource("vitals://digest/latest")
async def latest_digest_resource() -> dict:
    """The most recent weekly AI digest (narrative + date) for conversation
    continuity."""
    from vitals.services import digest_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        row = await digest_service.latest_digest(session)
        if row is None:
            return {"error": "No digests yet"}
        return {"date": row.date.isoformat(), "content": row.content, "model": row.model}


@mcp.prompt()
async def weekly_review() -> str:
    """A ready-made prompt that drives a full cross-domain weekly review."""
    return (
        "Review my last 7 days across every domain. First call get_full_snapshot "
        "for the aligned cross-domain picture (weight trend, GLP-1 state, recent "
        "labs, activity/recovery, workouts, nutrition, skincare, goals). Then pull "
        "get_trend for weight and any lab marker that looks off. Summarize what "
        "changed, call out cross-domain correlations (e.g. sleep vs training load, "
        "dose changes vs side effects), surface anything from get_active_alerts, and "
        "give at most three concrete, non-alarmist suggestions. This is decision "
        "support, not medical advice."
    )


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

        # Bearer header ONLY. We deliberately do not accept the token via a query
        # param (?token=/?access_token=): query strings leak into reverse-proxy
        # access logs, browser history and Referer headers, and this token is
        # long-lived. Claude.ai's connector sends the Authorization header.
        token = None
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:]

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

