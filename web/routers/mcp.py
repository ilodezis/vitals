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
  * A delete — ``{"deleted": <bool>, "domain": <str>, "record_id": <id>}``
    (one ``delete_record`` tool serves every domain; see ``_DELETE_TARGETS``).
  * A write to a switched-off optional domain — ``{"error": "module '<key>' is
    disabled"}``; ``get_modules`` says which are on.
"""
from __future__ import annotations

import functools
import importlib
import logging
import os
from datetime import date as date_type, timedelta
from typing import Optional

from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from vitals.config import load_config
from vitals.enums import Domain, MilestoneStatus, Source
from vitals.models import (
    Annotation,
    BodyMeasurement,
    BodyScan,
    DayContext,
    DosePhase,
    EnvironmentHourly,
    EnvironmentSample,
    GarminActivity,
    GarminDaily,
    GarminIntraday,
    GeneticVariant,
    HevyExercise,
    HevyWorkout,
    HrtCycle,
    HrtDose,
    HrtSideEffect,
    Injection,
    LabResult,
    MealLog,
    Milestone,
    NoiseMarker,
    SideEffect,
    Signal,
    SkincareLog,
    SkincareObservation,
    Supplement,
    SystemAlert,
    WeightLog,
    WeeklyDigest,
)
from vitals.services import conflict_engine, modules_service
from vitals.services.conflict_engine import ConflictBlocked
from vitals.utils.timeutils import today_local
from web.deps import get_redis_client, get_session_factory

logger = logging.getLogger(__name__)

mcp = FastMCP("Vitals")


# Columns every row carries and no tool ever accepts back: bookkeeping the model
# cannot act on. Dropped from serialized rows along with every ``None`` value —
# at a hundred rows per read the key names alone outweigh the data. ``id`` and
# ``date`` stay (edits and deletes address rows by id); ``source`` stays (weight
# priority and provenance are answers in their own right).
_ROW_NOISE = frozenset({"domain", "created_at", "updated_at", "raw_payload_id"})


def serialize_row(row) -> dict:
    """Helper to convert any SQLAlchemy model instance into a JSON-serializable dict.

    Omits bookkeeping columns (``_ROW_NOISE``) and unset fields: an absent key and
    a ``null`` one read the same to the model, and the null costs tokens per row.
    """
    if row is None:
        return {}
    d = {}
    for column in row.__table__.columns:
        if column.name in _ROW_NOISE:
            continue
        val = getattr(row, column.name)
        if val is None:
            continue
        d[column.name] = val.isoformat() if hasattr(val, "isoformat") else val
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


def _parse_date(value: Optional[str], default=None, *, field: str):
    """Parse a ``YYYY-MM-DD`` tool argument, falling back to ``default`` when omitted.

    A model writes dates the way a person says them ("вчера", "01.07.2026"), and
    the stdlib answers with "Invalid isoformat string: ..." — which names neither
    the argument nor the shape expected, so the model can't fix its own call.
    """
    if value is None:
        return default
    try:
        return date_type.fromisoformat(value)
    except (ValueError, TypeError):
        raise ValueError(f"{field} must be a YYYY-MM-DD date, got {value!r}") from None


def _parse_time(value: Optional[str], *, field: str):
    """Same as ``_parse_date`` for an ``HH:MM`` argument."""
    from datetime import time as time_type

    if value is None:
        return None
    try:
        return time_type.fromisoformat(value)
    except (ValueError, TypeError):
        raise ValueError(f"{field} must be an HH:MM time, got {value!r}") from None


async def _merged(session, model, record_id: int, **fields) -> Optional[dict]:
    """Fill a partial tool edit in from the stored row: a field left ``None`` keeps
    its current value. Keys are column names on ``model``; ``None`` if the row is gone.

    The update services replace every field they are handed, because the web forms
    post the whole form and clearing an input there has to clear the column. A tool
    call carries only what the conversation mentioned, so the same call would blank
    everything the model didn't repeat — a rename would cost the meal its calories.
    """
    row = await session.get(model, record_id)
    if row is None:
        return None
    return {k: (getattr(row, k) if v is None else v) for k, v in fields.items()}


async def _module_enabled(session, key: str) -> bool:
    """True when an optional module is on (write tools honour the toggle)."""
    from vitals.services import modules_service

    state = await modules_service.get_enabled_modules(session)
    return bool(state.get(key))


# tool name → the optional module it belongs to. Writes register themselves through
# ``gated``; the reads of those same domains are listed below. Used only to hide a
# switched-off module's tools from ``tools/list`` — the surface is 75 tools and
# their schemas are re-sent with every message of every conversation, so a domain
# the owner does not track is pure weight. Reads stay callable if invoked directly:
# hiding them is a budget decision, not a permission one.
TOOL_MODULES: dict[str, str] = {}


def gated(module_key: str):
    """Refuse a write when its optional module is switched off.

    Turning a module off in settings is the owner saying "I don't track this" —
    the web routes honour it (``require_module``), and until now the tool surface
    honoured it on three writes out of forty, so a conversation could refill a
    domain the owner had just emptied out of the UI. One decorator per write tool
    of an optional domain; ``tests/test_mcp_module_gate.py`` holds the full list,
    so a new tool has to be classified rather than quietly ungated."""
    def decorator(fn):
        TOOL_MODULES[fn.__name__] = module_key

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            session_factory = get_session_factory()
            async with session_factory() as session:
                if not await _module_enabled(session, module_key):
                    return {"error": f"module '{module_key}' is disabled"}
            return await fn(*args, **kwargs)

        return wrapper

    return decorator


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
    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")

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
    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")

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

# The two per-night timelines on a daily row: a hypnogram is ~30 intervals and the
# breathing spans a handful more, so together they are ~70% of the row's JSON and
# ride along on every read of the last hundred nights. Replaced by a breadcrumb
# unless asked for — hiding the data outright would read as "there are no sleep
# stages" and the model would stop asking.
_SLEEP_DETAIL_COLUMNS = ("sleep_stages", "breathing_events")


def _fold_sleep_detail(row: dict) -> dict:
    """Swap each present sleep-detail column for a count + how to get the real thing."""
    for name in _SLEEP_DETAIL_COLUMNS:
        value = row.get(name)
        if value:
            row[name] = f"{len(value)} entries — call again with sleep_detail=True"
    return row


@mcp.tool()
async def get_garmin_metrics(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 100,
    intraday: bool = False,
    sleep_detail: bool = False,
) -> dict:
    """Retrieves daily Garmin recovery/sleep scores and recorded activity sessions.
    Each series defaults to the most recent 100 rows.

    Set ``intraday=True`` to also get the curves behind the daily summaries, as
    ``intraday: {series_type: [{ts, value}]}``. Two families of series:

      * the whole day — ``stress``, ``body_battery``, ``heart_rate`` (a sample
        every ~2–3 minutes, so ~480 points per series per day);
      * the night — ``sleep_hr``, ``sleep_spo2``, ``sleep_respiration``,
        ``sleep_stress``, ``sleep_bb``, ``sleep_hrv``, ``sleep_movement``
        (~2000 points across the seven).

    A night's samples are dated to the daily row they belong to (the morning of
    waking), including the ones recorded the previous evening, so one night reads
    as one date.

    Off by default because it is orders of magnitude more data than the daily
    rows: use it to answer *when* something happened (a stress spike, a Body
    Battery drain, an SpO2 dip and which sleep stage it fell in), always with a
    narrow start_date/end_date window. The response caps at 5000 points and sets
    ``intraday_truncated`` to true when the window held more than that.

    The night's *stage* timeline is not a series — it's ``sleep_stages`` on the
    daily row (``[{start, end, stage}]``, stage being deep/light/rem/awake), next
    to ``breathing_events``. Both are folded to a count by default and returned in
    full with ``sleep_detail=True`` — a separate switch from ``intraday`` so that
    reading one night's hypnogram doesn't drag every curve along with it. Ask for
    it with a narrow window when the question is about the shape of a night.
    """
    session_factory = get_session_factory()
    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")

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

        rows = [serialize_row(d) for d in daily]
        if not sleep_detail:
            rows = [_fold_sleep_detail(r) for r in rows]
        result = {
            "daily_recovery": rows,
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
    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")

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
    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")

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
async def get_genetics_snps(
    gene: Optional[str] = None, rsid: Optional[str] = None, limit: int = 100
) -> list[dict]:
    """Retrieves digitized SNPs (genetic variants) with a description of their effect.
    Filter by ``gene`` ("MTHFR") or ``rsid`` ("rs1801133") — both match regardless of
    case. Unfiltered it returns the first ``limit`` variants in (gene, rsid) order;
    a whole-genome import is far larger than that, so ask for the marker you mean.
    READ tool."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(GeneticVariant)
        if gene:
            stmt = stmt.where(func.lower(GeneticVariant.gene) == gene.strip().lower())
        if rsid:
            stmt = stmt.where(func.lower(GeneticVariant.rsid) == rsid.strip().lower())
        stmt = stmt.order_by(GeneticVariant.gene, GeneticVariant.rsid).limit(limit)
        variants = (await session.execute(stmt)).scalars().all()
        return [serialize_row(v) for v in variants]


@mcp.tool()
@gated("genetics")
async def upsert_genetic_variant(
    gene: str,
    rsid: str,
    genotype: Optional[str] = None,
    marker: Optional[str] = None,
    impact: Optional[str] = None,
    impact_domain: Optional[str] = None,
    interpretation: Optional[str] = None,
    action_notes: Optional[str] = None,
) -> dict:
    """Adds or updates one genetic variant, keyed by ``rsid`` — restating a known
    rsid edits that row instead of duplicating it. ``marker`` is the slug the
    conflict rules match on (e.g. "mthfr_c677t_tt"); without one the variant is
    reference-only. Fields left out keep their stored value. WRITE tool."""
    from vitals.services import genetics_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        # upsert_by_rsid replaces the genotype unconditionally — the VCF importer
        # always has one. A conversation adding just an interpretation does not,
        # and must not blank the genotype the import wrote.
        if genotype is None:
            existing = (
                await session.execute(
                    select(GeneticVariant).where(GeneticVariant.rsid == rsid)
                )
            ).scalar_one_or_none()
            genotype = existing.genotype if existing is not None else None
        row = await genetics_service.upsert_by_rsid(
            session,
            gene=gene,
            rsid=rsid,
            genotype=genotype,
            marker=marker,
            impact=impact,
            impact_domain=impact_domain,
            interpretation=interpretation,
            action_notes=action_notes,
            source=Source.MCP.value,
        )
        await session.commit()
        return await serialize_written(session, row)


@mcp.tool()
async def get_active_alerts() -> list[dict]:
    """Returns currently active warning alerts and conflict notifications."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(SystemAlert).where(SystemAlert.resolved_at.is_(None)).order_by(SystemAlert.created_at.desc())
        alerts = (await session.execute(stmt)).scalars().all()
        return [serialize_row(a) for a in alerts]


@mcp.tool()
async def resolve_alert(alert_id: int) -> dict:
    """Marks one alert resolved — it disappears from ``get_active_alerts`` and
    from the dashboard. Use it once the thing the alert is about has actually been
    dealt with in the conversation, so the discussion and the closing are the same
    step instead of leaving the owner a button to press afterwards. WRITE tool."""
    from vitals.services import alerts_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        row = await alerts_service.resolve_alert(session, alert_id)
        if row is None:
            return {"error": f"Alert {alert_id} not found"}
        await session.commit()
        return await serialize_written(session, row)


@mcp.tool()
async def override_alert(alert_id: int) -> dict:
    """Marks a blocking alert overridden — "noted, doing it anyway". The alert
    stays active and visible; only the block it represents stops being treated as
    unanswered. For resolving it instead, use ``resolve_alert``. WRITE tool."""
    from vitals.services import alerts_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        row = await alerts_service.override_alert(session, alert_id)
        if row is None:
            return {"error": f"Alert {alert_id} not found"}
        await session.commit()
        return await serialize_written(session, row)


@mcp.tool()
async def get_weekly_digests(limit: int = 5) -> list[dict]:
    """Retrieves historical Claude-generated weekly summaries for continuity."""
    from vitals.services import digest_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        # Through the service, so this stays weekly-only: the same table now also
        # holds the daily Telegram briefs.
        digests = await digest_service.list_digests(session, limit=limit)
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
@gated("nutrition")
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
    parsed_date = _parse_date(on_date, today_local(), field="on_date")
    parsed_time = _parse_time(eaten_at, field="eaten_at")

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
                source=Source.MCP.value,
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

    start = _parse_date(start_date, today, field="start_date")
    end = _parse_date(end_date, today, field="end_date")

    if start == end:
        async with session_factory() as session:
            return await nutrition_service.daily_summary(session, start, cfg)
    else:
        async with session_factory() as session:
            return await nutrition_service.nutrition_summary(session, start, end, cfg)


# ── Meal CRUD tools ─────────────────────────────────────────────────────────

@mcp.tool()
@gated("nutrition")
async def update_meal(
    meal_id: int,
    name: Optional[str] = None,
    calories: Optional[float] = None,
    protein_g: Optional[float] = None,
    fat_g: Optional[float] = None,
    carbs_g: Optional[float] = None,
    eaten_at: Optional[str] = None,
    note: Optional[str] = None,
    on_date: Optional[str] = None,
) -> dict:
    """Updates an existing meal by ID. Returns the updated meal or an error.

    Only the fields you pass are changed — anything left out keeps its stored
    value, including ``on_date``, which stays the meal's own date rather than
    moving the meal to today. WRITE tool — changes are saved immediately.
    """
    from vitals.services import nutrition_service

    session_factory = get_session_factory()
    parsed_date = _parse_date(on_date, field="on_date")
    parsed_time = _parse_time(eaten_at, field="eaten_at")

    async with session_factory() as session:
        merged = await _merged(
            session,
            MealLog,
            meal_id,
            date=parsed_date,
            name=name,
            eaten_at=parsed_time,
            calories=calories,
            protein_g=protein_g,
            fat_g=fat_g,
            carbs_g=carbs_g,
            note=note,
        )
        if merged is None:
            return {"error": f"Meal {meal_id} not found"}
        row = await nutrition_service.update_meal(
            session, meal_id, on_date=merged.pop("date"), **merged
        )
        await session.commit()
        return await serialize_written(session, row)


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
    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")

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
    parsed_date = _parse_date(on_date, today_local(), field="on_date")

    async with session_factory() as session:
        try:
            row = await weight_service.log_weight(
                session, on_date=parsed_date, weight_kg=weight_kg, note=note,
                source=Source.MCP.value, override=override,
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
        except ValueError as e:
            return {"error": str(e)}
        await session.commit()
        return await serialize_written(session, row)


# ── GLP-1 tools ─────────────────────────────────────────────────────────────

@mcp.tool()
@gated("glp1")
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
    parsed_date = _parse_date(on_date, today_local(), field="on_date")

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
    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")

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
@gated("hrt")
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
    parsed_date = _parse_date(on_date, today_local(), field="on_date")

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
@gated("hrt")
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
    start = _parse_date(start_date, today_local(), field="start_date")
    end = _parse_date(end_date, field="end_date")

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
@gated("hrt")
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
@gated("hrt")
async def update_hrt_dose(
    dose_id: int,
    compound_key: Optional[str] = None,
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
    """Updates a recorded HRT/TRT administration by ID. Only the fields you pass are
    changed; everything left out keeps its stored value, including the dose's own
    date. A new ``volume_ml`` or ``concentration_mg_ml`` without a ``dose`` recomputes
    the mg. WRITE tool — on a hard block returns ``{"blocked": true, ...}``; retry
    with ``override=True``."""
    from vitals.services import hrt_service

    session_factory = get_session_factory()
    parsed_date = _parse_date(on_date, field="on_date")

    async with session_factory() as session:
        merged = await _merged(
            session,
            HrtDose,
            dose_id,
            compound_key=compound_key,
            date=parsed_date,
            dose=dose,
            unit=unit,
            volume_ml=volume_ml,
            concentration_mg_ml=concentration_mg_ml,
            brand=brand,
            lab=lab,
            batch=batch,
            site=site,
            note=note,
        )
        if merged is None:
            return {"error": f"HRT dose {dose_id} not found"}
        # A new volume or concentration is a request to recompute the mg, and an
        # explicit dose wins over both — so carrying the stored one forward here
        # would silently ignore what the call actually changed.
        if dose is None and (volume_ml is not None or concentration_mg_ml is not None):
            merged["dose"] = None
        try:
            row = await hrt_service.update_dose(
                session, dose_id, on_date=merged.pop("date"), override=override, **merged
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
        except ValueError as e:
            return {"error": str(e)}
        await session.commit()
        return await serialize_written(session, row)


@mcp.tool()
@gated("hrt")
async def log_hrt_side_effect(
    effect_type: str,
    severity: int,
    on_date: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    """Records an HRT/TRT side effect (e.g. "акне", "отёки") with a severity 1–5 for
    a date (default today). Distinct from ``log_side_effect``, which belongs to
    GLP-1. WRITE tool — saved immediately."""
    from vitals.services import hrt_service
    from vitals.utils.timeutils import today_local

    session_factory = get_session_factory()
    parsed_date = _parse_date(on_date, today_local(), field="on_date")

    async with session_factory() as session:
        try:
            row = await hrt_service.log_side_effect(
                session, on_date=parsed_date, effect_type=effect_type,
                severity=severity, note=note,
            )
        except ValueError as e:
            return {"error": str(e)}
        await session.commit()
        return await serialize_written(session, row)


@mcp.tool()
@gated("hrt")
async def close_hrt_cycle(cycle_id: int, end_date: Optional[str] = None) -> dict:
    """Closes an HRT cycle by giving it an end date (default today). WRITE tool."""
    from vitals.services import hrt_cycle_service
    from vitals.utils.timeutils import today_local

    session_factory = get_session_factory()
    end = _parse_date(end_date, today_local(), field="end_date")

    async with session_factory() as session:
        try:
            cycle = await hrt_cycle_service.close_cycle(session, cycle_id, end_date=end)
        except ValueError as e:
            return {"error": str(e)}
        if cycle is None:
            return {"error": f"cycle {cycle_id} not found"}
        await session.commit()
        return await serialize_written(session, cycle)


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
@gated("skincare")
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
    parsed_date = _parse_date(on_date, today_local(), field="on_date")

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
    parsed_date = _parse_date(on_date, today_local(), field="on_date")

    async with session_factory() as session:
        try:
            row = await weight_service.upsert_body_measurement(
                session, on_date=parsed_date, neck_cm=neck_cm, waist_cm=waist_cm,
                hips_cm=hips_cm, note=note, override=override,
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
        except ValueError as e:
            return {"error": str(e)}
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
    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")

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
    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")

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


# ── Deletion (one tool, every domain) ─────────────────────────────────────────

# domain → (module key gating the write, service module, delete function).
# Every delete service happens to share one signature — ``(session, id) -> bool`` —
# which is what lets a single tool stand in for the eighteen near-identical ones
# that used to live here, each differing only in the noun it echoed back. The tool
# list is re-read at the top of every conversation, so a fifth of it was spent
# spelling out delete_meal / delete_glp1 / delete_hrt_cycle_item.
_DELETE_TARGETS: dict[str, tuple[Optional[str], str, str]] = {
    "weight": (None, "weight_service", "delete_weight_log"),
    "measurement": (None, "weight_service", "delete_body_measurement"),
    "noise_marker": (None, "weight_service", "delete_noise_marker"),
    "labs": (None, "labs_service", "delete_result"),
    "milestones": (None, "milestones_service", "delete_milestone"),
    "nutrition": ("nutrition", "nutrition_service", "delete_meal"),
    "glp1": ("glp1", "glp1_service", "delete_injection"),
    "glp1_side_effect": ("glp1", "glp1_service", "delete_side_effect"),
    "glp1_dose_phase": ("glp1", "glp1_service", "delete_dose_phase"),
    "hrt_dose": ("hrt", "hrt_service", "delete_dose"),
    "hrt_cycle": ("hrt", "hrt_cycle_service", "delete_cycle"),
    "hrt_cycle_item": ("hrt", "hrt_cycle_service", "delete_cycle_item"),
    "body_comp": ("body_comp", "body_scan_service", "delete_scan"),
    "timeline": ("timeline", "timeline_service", "delete_annotation"),
    "skincare_observation": ("skincare", "skincare_service", "delete_observation"),
    "supplements": ("supplements", "supplements_service", "delete_supplement"),
    "genetics": ("genetics", "genetics_service", "delete_variant"),
    "signals": ("signals", "signals_service", "delete_signal"),
}


@mcp.tool()
async def delete_record(domain: str, record_id: int) -> dict:
    """Deletes one record from any domain by its ID. WRITE tool — immediate.

    ``domain`` is one of: weight, measurement (body tape), noise_marker, labs (one
    result), milestones (a goal card), nutrition (a meal), glp1 (an injection),
    glp1_side_effect, glp1_dose_phase, hrt_dose, hrt_cycle (with its compound
    plans), hrt_cycle_item (one plan, cycle kept), body_comp (a scan with its
    metrics), timeline (a manual event), skincare_observation, supplements (a
    catalog entry), genetics (a variant), signals (one parsed signal — the raw
    message stays in the lake; for a whole batch parsed wrongly out of one message
    use ``mark_signal_misparse`` instead).

    Deleting a weight log reactivates the next-highest-priority log for that date.
    Returns ``{"deleted": false, ...}`` when nothing has that id."""
    target = _DELETE_TARGETS.get(domain)
    if target is None:
        return {"error": f"Unknown domain '{domain}'. Use: {', '.join(_DELETE_TARGETS)}"}
    module_key, service_name, fn_name = target

    session_factory = get_session_factory()
    async with session_factory() as session:
        if module_key and not await _module_enabled(session, module_key):
            return {"error": f"module '{module_key}' is disabled"}
        service = importlib.import_module(f"vitals.services.{service_name}")
        ok = await getattr(service, fn_name)(session, record_id)
        await session.commit()
        return {"deleted": ok, "domain": domain, "record_id": record_id}


# ── Body composition tools (InBody / МедАсс — optional module) ────────────────
def _serialize_scan(scan: BodyScan) -> dict:
    """A scan plus its metrics nested (relationship must be loaded already)."""
    d = serialize_row(scan)
    d["metrics"] = [serialize_row(m) for m in scan.metrics]
    return d


@mcp.tool()
async def get_body_scans(
    start_date: Optional[str] = None, end_date: Optional[str] = None, limit: int = 100
) -> list[dict]:
    """Retrieves body-composition scans (InBody / МедАсс) with every parsed metric
    (skeletal muscle, body water, visceral fat, segmental analysis, phase angle…).
    Defaults to the most recent 100 scans."""
    session_factory = get_session_factory()
    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")

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
    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")
    async with session_factory() as session:
        return await body_scan_service.metric_history(
            session, metric_key, segment=segment, start=start, end=end
        )


@mcp.tool()
@gated("body_comp")
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
    parsed_date = _parse_date(on_date, today_local(), field="on_date")

    async with session_factory() as session:
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
        except ValueError as e:
            return {"error": str(e)}
        await session.commit()
        full = await body_scan_service.get_scan(session, scan.id)
        return _serialize_scan(full) if full else {"scan_id": scan.id}


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
    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")

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
    override: bool = False,
) -> dict:
    """Records a single lab marker value (one biomarker from a blood/urine test).
    The out-of-range flag is computed automatically; a range left out here falls
    back to the marker's catalog range if one is already on file. WRITE tool —
    saved immediately. Defaults: on_date = today. A hard conflict rule (e.g. a
    hyperkalemic potassium result while a potassium supplement is active) returns
    ``{"blocked": true, ...}``; retry with ``override=True`` to save anyway."""
    from vitals.services import labs_service
    from vitals.utils.timeutils import today_local

    session_factory = get_session_factory()
    parsed_date = _parse_date(on_date, today_local(), field="on_date")

    async with session_factory() as session:
        try:
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
                source=Source.MCP.value,
                override=override,
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
        except ValueError as e:
            return {"error": str(e)}
        await session.commit()
        return await serialize_written(session, row)


@mcp.tool()
async def update_lab_result(
    result_id: int,
    value: Optional[float] = None,
    marker: Optional[str] = None,
    on_date: Optional[str] = None,
    unit: Optional[str] = None,
    ref_low: Optional[float] = None,
    ref_high: Optional[float] = None,
    lab_name: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    """Corrects an existing lab result by ID — a mistyped value, a range read off
    the wrong column. Only the fields you pass are changed; the out-of-range flag
    is recomputed and the alerts derived from it refreshed. Use this instead of
    delete + re-add: a measurement is never thrown away here. WRITE tool."""
    from vitals.services import labs_service

    session_factory = get_session_factory()
    parsed_date = _parse_date(on_date, field="on_date")

    async with session_factory() as session:
        try:
            row = await labs_service.update_result(
                session,
                result_id,
                on_date=parsed_date,
                marker=marker,
                value=value,
                unit=unit,
                ref_low=ref_low,
                ref_high=ref_high,
                lab_name=lab_name,
                note=note,
            )
        except ValueError as e:
            return {"error": str(e)}
        if row is None:
            return {"error": f"Lab result {result_id} not found"}
        await session.commit()
        return await serialize_written(session, row)


@mcp.tool()
async def log_lab_results(
    results: list[dict],
    on_date: Optional[str] = None,
    lab_name: Optional[str] = None,
    override: bool = False,
) -> dict:
    """Records every marker from one lab report at once (e.g. a full blood panel
    read from a photo/PDF shared in the conversation) — the natural way to push a
    whole report in one call instead of calling log_lab_result per marker.

    Each item in ``results`` is ``{"marker": str, "value": number, "unit": str?,
    "ref_low": number?, "ref_high": number?}``. Identical (date, marker, value)
    rows are deduped, so retrying a call is safe. The verbatim payload is kept in
    raw_payloads, same as a document uploaded through the web UI. WRITE tool —
    saved immediately. Defaults: on_date = today. A hard conflict rule on any
    marker in the panel returns ``{"blocked": true, ...}`` and saves nothing;
    retry with ``override=True`` to save the whole panel anyway."""
    from vitals.services import labs_service
    from vitals.utils.timeutils import today_local

    session_factory = get_session_factory()
    parsed_date = _parse_date(on_date, today_local(), field="on_date")

    async with session_factory() as session:
        extracted = {
            "date": parsed_date.isoformat(),
            "lab_name": lab_name,
            "results": results,
        }
        try:
            summary = await labs_service.ingest_extracted(
                session, extracted, override=override
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
        await session.commit()
        return {
            "created": summary["created"],
            "skipped": summary["skipped"],
            "results": [await serialize_written(session, r) for r in summary["results"]],
        }


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
    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")
    domains = [domain] if domain else None

    async with session_factory() as session:
        events = await timeline_service.list_events(
            session, domains=domains, start=start, end=end, limit=limit
        )
        return [e.to_dict() for e in events]


@mcp.tool()
@gated("timeline")
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
    parsed_date = _parse_date(on_date, today_local(), field="on_date")
    parsed_end = _parse_date(end_date, field="end_date")

    async with session_factory() as session:
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


@mcp.tool()
@gated("timeline")
async def update_event(
    event_id: int,
    title: Optional[str] = None,
    on_date: Optional[str] = None,
    end_date: Optional[str] = None,
    kind: Optional[str] = None,
    domain: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    """Updates a manual Timeline annotation by ID — the ``id`` of a row from
    ``get_timeline`` whose source is manual (derived events are computed and
    cannot be edited). Only the fields you pass are changed; everything left out
    keeps its stored value, including the event's own date. WRITE tool."""
    from vitals.services import timeline_service

    session_factory = get_session_factory()
    parsed_date = _parse_date(on_date, field="on_date")
    parsed_end = _parse_date(end_date, field="end_date")

    async with session_factory() as session:
        merged = await _merged(
            session,
            Annotation,
            event_id,
            title=title,
            date=parsed_date,
            end_date=parsed_end,
            kind=kind,
            domain=domain,
            note=note,
        )
        if merged is None:
            return {"error": f"Event {event_id} not found"}
        row = await timeline_service.update_annotation(
            session, event_id, on_date=merged.pop("date"), **merged
        )
        await session.commit()
        return await serialize_written(session, row)


# ── Cross-domain + whole-lake tools ──────────────────────────────────────────
@mcp.tool()
async def get_full_snapshot(
    on_date: Optional[str] = None,
    period_days: int = 7,
) -> dict:
    """Returns context-v2 for a closed period (1..90 days): profile, coverage,
    weight/body composition, GLP-1/HRT plans and facts, every lab result in the
    period, Garmin recovery and activities, Hevy, nutrition, skincare, signals,
    timeline and active goals. Every dated fact is bounded by the effective
    period end. When ``on_date`` is today the closed period ends yesterday."""
    from vitals.services import digest_service

    session_factory = get_session_factory()
    parsed_date = _parse_date(on_date, field="on_date")
    async with session_factory() as session:
        try:
            return await digest_service.assemble_context(
                session, on_date=parsed_date, period_days=period_days
            )
        except ValueError as exc:
            return {"error": str(exc)}


EXPORT_DEFAULT_DAYS = 90


@mcp.tool()
async def export_everything(
    domains: Optional[list[str]] = None, since: Optional[str] = None
) -> dict:
    """Returns the health history as one compact, secret-free, LLM-ready export
    grouped by domain (weight, measurements, body scans, GLP-1, HRT, labs, Garmin,
    workouts, nutrition, skincare, supplements, genetics, signals, day context,
    milestones, timeline, and the bedroom's air as ``environment_nights`` —
    one summary per night — and ``environment_hours``, the hourly means as
    parallel arrays per day). This is the way to read long-term history in a single
    call rather than paging each domain's newest-100 read tool. Read-only.

    Defaults to the **last 90 days**: the whole lake is years of daily Garmin rows
    with per-minute sleep and would fill the conversation before the question is
    asked. Widen deliberately — ``since="2020-01-01"`` (any early date) for the
    entire history, and/or ``domains=["biomarkers", "weight_history"]`` to pull a
    couple of areas in full instead of everything. Unknown domain names are
    rejected with the list of valid ones."""
    from vitals.services import data_portability_service
    from vitals.utils.timeutils import today_local

    default_since = today_local() - timedelta(days=EXPORT_DEFAULT_DAYS)
    cutoff = _parse_date(since, default_since, field="since")

    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            return await data_portability_service.export_llm(
                session, domains=domains, since=cutoff
            )
        except ValueError as e:
            return {"error": str(e)}


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
        ("signals", Signal, Signal.date),
        ("day_context", DayContext, DayContext.date),
        ("hrt_doses", HrtDose, HrtDose.date),
        ("hrt_side_effects", HrtSideEffect, HrtSideEffect.date),
        ("hrt_cycles", HrtCycle, HrtCycle.start_date),
        ("environment_samples", EnvironmentSample, EnvironmentSample.date),
        ("environment_hourly", EnvironmentHourly, EnvironmentHourly.date),
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
    parsed_deadline = _parse_date(deadline, field="deadline")
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
            kwargs["deadline"] = _parse_date(deadline, field="deadline")
        if status is not None:
            kwargs["status"] = status
        if note is not None:
            kwargs["note"] = note
        row = await milestones_service.update_milestone(session, milestone_id, **kwargs)
        if row is None:
            return {"error": f"Milestone {milestone_id} not found"}
        await session.commit()
        return await serialize_written(session, row)


# ── GLP-1 write completeness (edit/delete injection, side effects, phases) ────
@mcp.tool()
@gated("glp1")
async def update_glp1(
    injection_id: int,
    drug: Optional[str] = None,
    dose_mg: Optional[float] = None,
    on_date: Optional[str] = None,
    site: Optional[str] = None,
    note: Optional[str] = None,
    override: bool = False,
) -> dict:
    """Edits an existing GLP-1 injection by ID. Only the fields you pass are
    changed; ``on_date`` left out keeps the injection's own date. Runs the same
    conflict gate as a fresh log — on a hard block returns ``{"blocked": true,
    ...}``; retry with ``override=True``. WRITE tool."""
    from vitals.services import glp1_service

    session_factory = get_session_factory()
    parsed_date = _parse_date(on_date, field="on_date")
    async with session_factory() as session:
        merged = await _merged(
            session, Injection, injection_id,
            date=parsed_date, drug=drug, dose_mg=dose_mg, site=site, note=note,
        )
        if merged is None:
            return {"error": f"Injection {injection_id} not found"}
        try:
            row = await glp1_service.update_injection(
                session, injection_id, on_date=merged.pop("date"),
                override=override, **merged,
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
        except ValueError as e:
            return {"error": str(e)}
        await session.commit()
        return await serialize_written(session, row)


@mcp.tool()
@gated("glp1")
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
    parsed_date = _parse_date(on_date, today_local(), field="on_date")
    async with session_factory() as session:
        row = await glp1_service.log_side_effect(
            session, on_date=parsed_date, effect_type=effect_type,
            severity=severity, note=note,
        )
        await session.commit()
        return await serialize_written(session, row)


@mcp.tool()
@gated("glp1")
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
    parsed_start = _parse_date(start_date, field="start_date")
    parsed_end = _parse_date(end_date, field="end_date")
    async with session_factory() as session:
        row = await glp1_service.add_dose_phase(
            session, start_date=parsed_start, drug=drug, dose_mg=dose_mg,
            end_date=parsed_end, note=note,
        )
        await session.commit()
        return await serialize_written(session, row)


# ── Skincare observations ─────────────────────────────────────────────────────
@mcp.tool()
@gated("skincare")
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
    parsed_date = _parse_date(on_date, today_local(), field="on_date")
    async with session_factory() as session:
        row = await skincare_service.add_observation(
            session, on_date=parsed_date, inflammation=inflammation,
            pih=pih, zone=zone, note=note,
        )
        await session.commit()
        return await serialize_written(session, row)


# ── Supplements catalog CRUD ──────────────────────────────────────────────────
@mcp.tool()
@gated("supplements")
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
@gated("supplements")
async def update_supplement(
    supplement_id: int,
    name: Optional[str] = None,
    key: Optional[str] = None,
    dose: Optional[str] = None,
    timing: Optional[str] = None,
    evidence: Optional[str] = None,
    active: Optional[bool] = None,
    contraindications: Optional[str] = None,
    note: Optional[str] = None,
    override: bool = False,
) -> dict:
    """Updates a catalog supplement by ID. Only the fields you pass are changed —
    a rename does not clear the dose or switch a paused supplement back on; use
    ``set_supplement_active`` (or pass ``active``) for that. Same conflict gate as
    add — a hard block returns ``{"blocked": true, ...}``; retry with
    ``override=True``. WRITE tool."""
    from vitals.services import supplements_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        merged = await _merged(
            session, Supplement, supplement_id,
            name=name, dose=dose, timing=timing, evidence=evidence,
            active=active, contraindications=contraindications, note=note,
        )
        if merged is None:
            return {"error": f"Supplement {supplement_id} not found"}
        try:
            # ``key`` stays as passed: left out, the service re-derives the
            # conflict-matching slug from the (possibly new) name, same as add.
            row = await supplements_service.update_supplement(
                session, supplement_id, key=key, override=override, **merged,
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
        await session.commit()
        return await serialize_written(session, row)


@mcp.tool()
@gated("supplements")
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
    parsed_date = _parse_date(on_date, field="on_date")
    async with session_factory() as session:
        try:
            row = await weight_service.update_body_measurement(
                session, measurement_id, on_date=parsed_date, neck_cm=neck_cm,
                waist_cm=waist_cm, hips_cm=hips_cm, note=note, override=override,
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
        except ValueError as e:
            return {"error": str(e)}
        if row is None:
            return {"error": f"Measurement {measurement_id} not found"}
        await session.commit()
        return await serialize_written(session, row)


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
    parsed_start = _parse_date(start_date, field="start_date")
    parsed_end = _parse_date(end_date, field="end_date")
    async with session_factory() as session:
        row = await weight_service.add_noise_marker(
            session, start_date=parsed_start, end_date=parsed_end,
            reason=reason, direction=direction,
        )
        await session.commit()
        return await serialize_written(session, row)


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
        except ValueError as exc:
            return {"error": str(exc)}
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


# ── Signals tools (free-text capture — optional module) ───────────────────────
@mcp.tool()
async def get_signals(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    kind: Optional[str] = None,
    key: Optional[str] = None,
    limit: int = 200,
) -> list[dict]:
    """Retrieves signals — the owner's own words about how a day felt, parsed into
    rows: states ("энергии ноль"), symptoms ("голова раскалывается"), exposures
    ("кофе в 22"). This is the domain that *explains* the Garmin numbers. Filter by
    ``kind`` (state/symptom/exposure) and/or ``key`` (matches every stored spelling
    that folds to it, e.g. ``sleepiness`` also finds ``sleepy_af``). Rows the owner
    flagged as misparsed are excluded. Newest first, most recent 200 by default."""
    from vitals.services import signals_service

    session_factory = get_session_factory()
    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")

    async with session_factory() as session:
        rows = await signals_service.list_signals(
            session, key=key, kind=kind, start=start, end=end, limit=limit
        )
        return [serialize_row(r) for r in rows]


@mcp.tool()
@gated("signals")
async def log_signal(
    key: str,
    kind: str,
    value_num: Optional[float] = None,
    unit: Optional[str] = None,
    note: Optional[str] = None,
    at_time: Optional[str] = None,
    on_date: Optional[str] = None,
) -> dict:
    """Records one signal — a state, symptom or exposure the owner mentioned in
    conversation. ``kind`` must be state, symptom or exposure; ``key`` is a short
    slug (``headache``, ``caffeine_late``); ``value_num`` is intensity 1-5 for
    state/symptom or an amount for exposure; ``at_time`` is HH:MM (matters for
    exposures — "кофе в 22" only means something with the hour attached).
    WRITE tool — saved immediately."""
    from vitals.services import signals_service
    from vitals.utils.timeutils import today_local

    session_factory = get_session_factory()
    parsed_date = _parse_date(on_date, today_local(), field="on_date")

    async with session_factory() as session:
        rows = await signals_service.create_signals(
            session,
            items=[{
                "kind": kind, "key": key, "value_num": value_num,
                "unit": unit, "note": note, "at_time": at_time,
            }],
            on_date=parsed_date,
            source=Source.MCP.value,
        )
        # create_signals drops unusable rows silently (it batch-parses LLM output,
        # where one bad fact must not cost the message). A single-row tool call has
        # no such batch to protect — an empty result means this call was rejected.
        if not rows:
            return {"error": "kind must be state, symptom or exposure, and key must be non-empty"}
        await session.commit()
        return await serialize_written(session, rows[0])


@mcp.tool()
@gated("signals")
async def mark_signal_misparse(batch_id: str) -> dict:
    """Flags every signal parsed out of one message as misparsed — the "не то"
    button. The rows and the raw text stay, they just drop out of ``get_signals``
    and out of the charts. ``batch_id`` is the field shared by all rows from the
    same message. WRITE tool — immediate."""
    from vitals.services import signals_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        marked = await signals_service.mark_misparse(session, batch_id)
        await session.commit()
        return {"marked": marked, "batch_id": batch_id}


@mcp.tool()
async def get_day_context(
    start_date: Optional[str] = None, end_date: Optional[str] = None, limit: int = 100
) -> list[dict]:
    """Retrieves per-day context — what kind of day it was (remote/office, gym or
    not, workload), as answered by the owner or guessed by the week template
    (``planned``). One row per date, newest first. Read this before explaining a
    day's Garmin numbers: a heavy office day and a rest day at home look the same
    in the metrics and mean opposite things."""
    session_factory = get_session_factory()
    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")

    async with session_factory() as session:
        stmt = select(DayContext)
        if start:
            stmt = stmt.where(DayContext.date >= start)
        if end:
            stmt = stmt.where(DayContext.date <= end)
        stmt = stmt.order_by(DayContext.date.desc()).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        return [serialize_row(r) for r in rows]


@mcp.tool()
@gated("signals")
async def log_day_context(answers: dict, on_date: Optional[str] = None) -> dict:
    """Records what kind of day it was — the same answers the owner taps in
    Telegram, when he says them here instead ("сегодня удалёнка, зала не будет").
    Keys: ``where`` (office/remote/off), ``gym`` (true/false), ``load``
    (light/normal/heavy — about a day already spent, not a plan). Only the keys
    you pass are changed, and the week template's own guess is kept beside the
    answer rather than overwritten. ``on_date`` defaults to today. WRITE tool."""
    from vitals.services.proactive import day_plan
    from vitals.utils.timeutils import today_local

    session_factory = get_session_factory()
    parsed_date = _parse_date(on_date, today_local(), field="on_date")

    legal = "; ".join(f"{q.key}: {list(q.labels)}" for q in day_plan.QUESTIONS)
    if not answers:
        return {"error": f"answers must contain at least one of — {legal}"}
    for key, value in answers.items():
        question = day_plan.QUESTIONS_BY_KEY.get(key)
        # Validated before anything is written: half-applied answers would leave
        # the day in a state neither the owner nor the template ever produced.
        if question is None or value not in question.labels:
            return {"error": f"{key}={value!r} is not a day-context answer — {legal}"}

    async with session_factory() as session:
        for key, value in answers.items():
            row = await day_plan.record_answer(session, parsed_date, key, value)
        await session.commit()
        return await serialize_written(session, row)


@mcp.tool()
async def get_proactive_state(limit: int = 10) -> dict:
    """Retrieves the state of the proactive Telegram layer: whether it is on, its
    settings (message times, daily budget, which nudge categories are allowed), the
    week template (what each weekday is assumed to be until the owner says
    otherwise), and the last messages the bot actually sent. Read this before
    explaining why the bot did or didn't say something. READ tool — the settings are
    read-only here; retiming or muting the bot is done in Settings, by the owner."""
    from vitals.models.proactive import Notification
    from vitals.services.proactive import day_plan, prefs

    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(Notification).order_by(Notification.sent_at.desc()).limit(limit)
        sent = (await session.execute(stmt)).scalars().all()
        return {
            "enabled": await prefs.bot_enabled(session),
            "prefs": await prefs.get_prefs(session),
            "week_template": await day_plan.get_week_template(session),
            "recent_notifications": [serialize_row(n) for n in sent],
        }


@mcp.tool()
@gated("signals")
async def set_week_template(template: dict) -> dict:
    """Stores the week template — what each weekday is assumed to be until the owner
    answers otherwise ("по вторникам я всегда на удалёнке"). Keys are "mon".."sun",
    each a dict of ``where`` (office/remote/off) and ``gym`` (true/false). Only the
    weekdays and keys you pass are changed; the rest keep their stored values. How
    heavy a day is can't be predicted from a weekday, so it isn't part of the
    template. WRITE tool — returns the full stored template."""
    from vitals.services.proactive import day_plan

    legal = "/".join(day_plan.WEEKDAYS)
    if not isinstance(template, dict) or not template:
        return {"error": f"template must be a dict of weekday → answers ({legal})"}
    unknown = sorted(k for k in template if k not in day_plan.WEEKDAYS)
    if unknown:
        return {"error": f"unknown weekday(s) {unknown} — use {legal}"}

    session_factory = get_session_factory()
    async with session_factory() as session:
        # Merged onto the stored template, per day: the sanitizer fills an absent
        # weekday (and an absent key within one) from the neutral default, so a call
        # naming only Tuesday would otherwise reset the other six.
        merged = await day_plan.get_week_template(session)
        for day, values in template.items():
            if not isinstance(values, dict):
                return {"error": f"{day} must be a dict of answers, got {values!r}"}
            merged[day] = {**merged[day], **values}
        clean = await day_plan.set_week_template(session, merged)
        await session.commit()
        return clean


# ── Sync tools (pull from Garmin / Hevy on demand) ────────────────────────────
# A sync is an outbound call to someone else's API — Garmin's in particular
# throttles logins — and the scheduler already polls both several times a day.
# These exist for the gap case ("the last two days are empty"), so three calls a
# day each is plenty. Counter is per calendar day, in Redis; fail-open like
# web/ratelimit.py — a counter must never be the reason a sync can't run.
SYNC_DAILY_LIMIT = 3


async def _spend_sync_quota(bucket: str, limit: int = SYNC_DAILY_LIMIT) -> Optional[dict]:
    """Count one call against today's quota. Returns an error dict once it's spent."""
    key = f"mcp:sync_quota:{bucket}:{today_local().isoformat()}"
    try:
        redis = get_redis_client()
        used = await redis.incr(key)
        if used == 1:
            await redis.expire(key, 86400)
    except Exception:
        logger.warning("sync quota backend unavailable for %s; allowing", bucket, exc_info=True)
        return None
    if used > limit:
        return {
            "error": f"{bucket} has already run {limit} times today, which is the daily "
                     "cap for on-demand syncs. The scheduled sync keeps running regardless; "
                     "the quota resets at midnight."
        }
    return None


@mcp.tool()
async def sync_garmin(days: int = 2) -> dict:
    """Pulls fresh Garmin data now — daily metrics plus activities for the last
    ``days`` (default 2: yesterday and today; up to 30 to fill a longer gap).

    Use it when the data looks stale or a day is missing, not before every read:
    the scheduler already polls several times a day. Capped at 3 calls a day.
    Returns ``{days, activities, error}``; an auth/MFA/throttle failure comes back
    as ``error`` (and raises an alert) rather than as an exception."""
    from vitals.services import garmin_service

    spent = await _spend_sync_quota("sync_garmin")
    if spent:
        return spent

    summary = await garmin_service.sync_job(
        get_session_factory(), get_redis_client(), days=max(1, min(int(days), 30))
    )
    if summary is None:
        return {"error": "Garmin is not configured — no credentials in settings"}
    return summary


@mcp.tool()
@gated("hevy")
async def sync_hevy() -> dict:
    """Pulls the latest Hevy workouts now. Same rules as ``sync_garmin``: for a gap
    in the data, not for routine reads (the scheduler syncs every 6 hours), capped
    at 3 calls a day. Returns ``{fetched, created, updated, skipped}``."""
    from vitals.integrations.hevy_client import HevyAPIError, HevyNotConfigured
    from vitals.services import hevy_service

    spent = await _spend_sync_quota("sync_hevy")
    if spent:
        return spent

    try:
        summary = await hevy_service.sync_job(get_session_factory(), get_redis_client())
    except (HevyNotConfigured, HevyAPIError) as e:
        return {"error": f"Hevy sync failed: {e}"}
    if summary is None:
        return {"error": "Hevy is not configured — no API key in settings"}
    return summary


# ── Environment tools (the bedroom's air — optional module) ───────────────────
# Reads only, from a CO2 / temperature / humidity station that measures around the
# clock. Gated like the optional domains' writes: with the module off they refuse
# and are not listed. The shaping (local times, rounding, honest truncation) lives in
# ``environment_context`` so the weekly report and the exports read the same numbers.
@mcp.tool()
@gated("environment")
async def get_environment_live() -> dict:
    """Returns what the bedroom station reads right now: CO2 (ppm), temperature,
    humidity, the CO2 zone (good/ok/warn/bad), the CO2 trend in ppm per hour, and
    whether the station is online, stale, offline or has never reported — plus the
    owner's thresholds. Times are local. Read-only."""
    from vitals.services import environment_context

    try:
        redis = get_redis_client()
    except Exception:
        redis = None  # the cache only accelerates; the database still answers
    session_factory = get_session_factory()
    async with session_factory() as session:
        return await environment_context.live_view(session, redis)


@mcp.tool()
@gated("environment")
async def get_environment(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    granularity: str = "hour",
    limit: int = 800,
) -> dict:
    """Retrieves the bedroom's air — CO2 (ppm), temperature (°C), humidity (%) —
    over whole local days (YYYY-MM-DD, both ends inclusive), as ``columns`` plus
    ``rows``. ``granularity`` is ``hour`` (up to 31 days; default the last 7; each
    hour also carries its CO2 min and max) or ``minute`` (up to 2 days; default
    today). A longer window or more than ``limit`` points (default 800, max 3000)
    is cut to its FIRST part and flagged with ``truncated`` and a ``hint`` — narrow
    the dates to see the rest. Raw 10-second samples are not exposed. Includes
    ``coverage_pct`` (how much of the window the station was actually reporting)
    and the owner's thresholds. For the night's summary use
    ``get_environment_night``. Times are local. Read-only."""
    from vitals.services import environment_context

    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")
    session_factory = get_session_factory()
    async with session_factory() as session:
        return await environment_context.history_view(
            session, start=start, end=end, granularity=granularity, limit=limit
        )


@mcp.tool()
@gated("environment")
async def get_environment_night(on_date: Optional[str] = None) -> dict:
    """Returns one night of the bedroom's air: the window 00:00–12:00 local of
    ``on_date`` (default today — which is *last night*, the one that ended this
    morning), with CO2 median / p90 / max, the minutes spent at or above the warn
    and bad lines, temperature and humidity ranges, and ``coverage_pct`` — how much
    of the window the station reported; a low value is a gap in the data, not a
    clean night. Includes the owner's sleeping thresholds. A night with no station
    data comes back with ``samples: 0`` and a note. Read-only."""
    from vitals.services import environment_context
    from vitals.utils.timeutils import today_local

    parsed = _parse_date(on_date, today_local(), field="on_date")
    session_factory = get_session_factory()
    async with session_factory() as session:
        return await environment_context.night_view(session, parsed)


@mcp.tool()
@gated("environment")
async def get_environment_alerts(hours: int = 24) -> dict:
    """Returns the bedroom-air alerts that fired in the last ``hours`` (default 24,
    max 168) — too stuffy, too hot or cold, too dry or humid, station silent — each
    with its key, when it started and ended (``ongoing`` if still open), how long it
    lasted, and the peak the reading reached. Newest first; ``active`` counts the
    ones still open. Read-only."""
    from vitals.services import environment_context

    session_factory = get_session_factory()
    async with session_factory() as session:
        return await environment_context.alerts_view(session, hours=hours)


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


# The read side of the same map (the writes registered themselves via ``gated``).
# ``tests/test_mcp_tool_budget.py`` checks every name here is a real tool, so a
# rename can't quietly leave a domain's reads visible forever.
TOOL_MODULES.update({
    "get_glp1_logs": "glp1",
    "get_hevy_workouts": "hevy",
    "get_supplements_catalog": "supplements",
    "get_skincare_logs": "skincare",
    "get_genetics_snps": "genetics",
    "get_hrt_logs": "hrt",
    "get_hrt_cycles": "hrt",
    "get_nutrition_summary": "nutrition",
    "search_meals": "nutrition",
    "get_body_scans": "body_comp",
    "get_body_scan": "body_comp",
    "get_body_metric_history": "body_comp",
    "get_timeline": "timeline",
    "get_signals": "signals",
    "get_day_context": "signals",
    "get_proactive_state": "signals",
})


class ModuleVisibilityMiddleware(Middleware):
    """Hide a switched-off module's tools from ``tools/list``.

    They already refuse the call ("module '<key>' is disabled") — listing them only
    spends the conversation's budget on schemas for domains the owner does not
    track, and invites the model to try them. Resolved per request rather than
    latched at import, so flipping a toggle in Settings takes effect on the next
    reconnect without a restart. Fails open: if the module state can't be read, the
    full surface is listed rather than an empty one.
    """

    async def on_list_tools(self, context, call_next):
        tools = await call_next(context)
        try:
            session_factory = get_session_factory()
            async with session_factory() as session:
                enabled = await modules_service.get_enabled_modules(session)
        except Exception:
            logger.warning("mcp: module state unavailable; listing every tool", exc_info=True)
            return tools
        return [t for t in tools if enabled.get(TOOL_MODULES.get(t.name, ""), True)]


mcp.add_middleware(ModuleVisibilityMiddleware())


def _www_authenticate(scope) -> bytes:
    """The 401 challenge, pointing at this resource's metadata (RFC 9728 §5.1).

    A bare ``Bearer`` leaves a fresh client guessing where tokens come from; the
    ``resource_metadata`` link is how it finds the authorization server. Built from
    the request's own host so it stays right behind the reverse proxy (uvicorn runs
    with --forwarded-allow-ips, so the scheme is the external one)."""
    from web.routers.oauth import PROTECTED_RESOURCE_PATH

    host = dict(scope.get("headers", [])).get(b"host", b"").decode("utf-8", "ignore")
    if not host:
        return b"Bearer"
    url = f"{scope.get('scheme', 'https')}://{host}{PROTECTED_RESOURCE_PATH}"
    return f'Bearer resource_metadata="{url}"'.encode("utf-8")


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
            # No access-control-allow-origin: the actual MCP responses carry no CORS
            # headers, so a wildcard here grants nothing. Claude.ai's connector is
            # server-side (not a browser), so it never sends a preflight anyway.
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"access-control-allow-methods", b"GET, POST, DELETE, OPTIONS"),
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
                    (b"www-authenticate", _www_authenticate(scope)),
                ]
            })
            await send({
                "type": "http.response.body",
                "body": response_body,
                "more_body": False
            })
            return

        # Track whether the downstream app already began the response, so on a
        # mid-stream failure we don't try to start a second one (that would raise).
        response_started = False
        response_done = False

        async def _send(message):
            nonlocal response_started, response_done
            if response_done:
                return
            if message["type"] == "http.response.start":
                if response_started:
                    # A streaming endpoint can emit a second response start after
                    # the stream is over (e.g. an empty Response() once the client
                    # hangs up). Forwarding it trips an assertion inside the
                    # BaseHTTPMiddleware wrappers from web/csrf.py and logs a
                    # traceback on every connector reconnect. Drop it and anything
                    # after it — the response is finished either way.
                    response_done = True
                    return
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, _send)
        except TypeError:
            logger.exception("MCP app raised TypeError handling %s", scope.get("path"))
            if not response_started:
                body = b'{"detail":"Internal server error in MCP handler."}'
                await send({
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("utf-8")),
                    ],
                })
                await send({
                    "type": "http.response.body",
                    "body": body,
                    "more_body": False,
                })


def get_mcp_app() -> tuple[object, object]:
    """Wraps the FastMCP Starlette app with Bearer authorization middleware.

    Returns ``(app, lifespan)``. Streamable HTTP builds its session manager inside
    the lifespan, and ``app.mount()`` does not run a sub-app's lifespan — so the
    caller must enter it explicitly or every request fails with "manager not
    initialized". See web/main.py.
    """
    from web.config import get_web_config
    cfg = get_web_config()
    # Streamable HTTP (the SSE transport is deprecated in the MCP spec since
    # 2025-03). path="/" so that mounting on /mcp lands the endpoint on /mcp/
    # rather than /mcp/mcp — the library's own default path would be appended.
    raw_app = mcp.http_app(transport="http", path="/")
    return MCPAuthMiddleware(raw_app, client_id=cfg.mcp_client_id), raw_app.router.lifespan_context
