"""Model Context Protocol (MCP) server integration for Vitals.

Exposes the app to Claude: everything the owner can do on a screen of the app,
Claude can do from a conversation, through the same services and the same
conflict checks. Read tools cover every domain plus the Today screen, the
settings, the photo galleries, saved charts and doctor reports; write tools
record, edit and delete across the domains (meals, weight, GLP-1, HRT, the
skincare catalog and its morning/evening ticks, supplements, measurements, body
scans, labs and their marker catalog, goals, timeline events, signals, notes)
and change what Settings changes (profile and nutrition goals, the bot's
schedule, the bedroom station's thresholds, module and conflict-rule switches).
Deliberately absent: credentials, password/2FA, backup import and the container
restart — a conversation must not be able to lock the owner out or overwrite
the lake. Two resources (``vitals://profile``, ``vitals://digest/latest``) and a
``weekly_review`` prompt round out the surface.

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

import asyncio
import functools
import importlib
import json
import logging
import os
from datetime import date as date_type, datetime, timedelta
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
    ProgressPhoto,
    SideEffect,
    Signal,
    SkincareCheck,
    SkincareLog,
    SkincareObservation,
    SkincarePhoto,
    SkincareProduct,
    Supplement,
    WeightLog,
    WeeklyDigest,
)
from vitals.services import conflict_engine, modules_service, photo_derivatives
from vitals.services.conflict_engine import ConflictBlocked
from vitals.utils.timeutils import format_iso, today_local
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
        if isinstance(val, datetime):
            d[column.name] = format_iso(val)
        elif hasattr(val, "isoformat"):
            d[column.name] = val.isoformat()
        else:
            d[column.name] = val
    if hasattr(row, "__tablename__") and row.__tablename__ == "meal_logs":
        if hasattr(row, "created_at") and row.created_at:
            d["logged_at"] = format_iso(row.created_at, is_utc=True)
        if "eaten_at" not in d:
            d["eaten_at"] = None
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
# switched-off module's tools from ``tools/list`` — the surface is over a hundred tools and
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
    """Returns the owner's profile as the Settings screen holds it — height, sex,
    age, timezone, goals, program — and the nutrition goals (protein target,
    calorie corridor). ``pending_restart`` lists any saved value the running app
    has not picked up yet: these settings live in ``.env`` and reach the
    computations (Navy body-fat, the nutrition corridor) on the next restart.
    READ tool; change them with ``update_user_profile``."""
    from web.services import profile_settings

    cfg = load_config()
    saved = {**profile_settings.read_profile(), **profile_settings.read_nutrition_goals()}

    def _num(raw: str, cast, fallback):
        try:
            return cast(raw)
        except (TypeError, ValueError):
            return fallback

    goals = [g.strip() for g in saved["user_goals"].split(",") if g.strip()] or cfg.user_goals
    profile = {
        "height_cm": _num(saved["height_cm"], float, cfg.height_cm),
        "sex": saved["sex"],
        "age": _num(saved["user_age"], int, cfg.user_age),
        "timezone": saved["timezone"],
        "goals": goals,
        "program": saved["user_program"] or cfg.user_program,
        "nutrition_goals": {
            "protein_target_g": _num(saved["nutrition_protein_target_g"], float, cfg.nutrition_protein_target_g),
            "calories_min": _num(saved["nutrition_calories_min"], int, cfg.nutrition_calories_min),
            "calories_max": _num(saved["nutrition_calories_max"], int, cfg.nutrition_calories_max),
        },
    }
    running = {
        "height_cm": cfg.height_cm, "sex": cfg.sex, "age": cfg.user_age,
        "timezone": str(cfg.timezone), "goals": cfg.user_goals, "program": cfg.user_program,
        "protein_target_g": cfg.nutrition_protein_target_g,
        "calories_min": cfg.nutrition_calories_min, "calories_max": cfg.nutrition_calories_max,
    }
    flat = {**{k: v for k, v in profile.items() if k != "nutrition_goals"}, **profile["nutrition_goals"]}
    pending = sorted(k for k, v in flat.items() if running[k] != v)
    if pending:
        profile["pending_restart"] = pending
    return profile


_HEIGHT_RANGE = (100.0, 250.0)
_AGE_RANGE = (10, 120)
_PROTEIN_RANGE = (0.0, 500.0)
_CALORIES_RANGE = (500, 8000)


@mcp.tool()
async def update_user_profile(
    height_cm: Optional[float] = None,
    age: Optional[int] = None,
    sex: Optional[str] = None,
    timezone: Optional[str] = None,
    program: Optional[str] = None,
    goals: Optional[list[str]] = None,
    protein_target_g: Optional[float] = None,
    calories_min: Optional[int] = None,
    calories_max: Optional[int] = None,
) -> dict:
    """Changes the owner's profile and nutrition goals — the same fields as the
    "About me" and nutrition cards in Settings, written the same way. Only the
    fields you pass change.

    ``sex`` is male or female (it switches the Navy body-fat formula);
    ``timezone`` an IANA name ("Europe/Chisinau"); ``goals`` the full new list
    (short phrases, no commas inside one); ``program`` one line describing the
    current program. ``calories_min`` / ``calories_max`` are the daily corridor
    the nutrition summary measures against; ``protein_target_g`` the daily
    protein goal.

    Like a save in Settings, this is stored at once but the running app applies
    it on its next restart — the result's ``pending_restart`` says what is
    waiting. WRITE tool. Returns the profile as now stored."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    from web.services import profile_settings

    def _bounded(name, value, bounds):
        low, high = bounds
        if value is not None and not low <= value <= high:
            raise ValueError(f"{name} must be between {low:g} and {high:g}")

    try:
        _bounded("height_cm", height_cm, _HEIGHT_RANGE)
        _bounded("age", age, _AGE_RANGE)
        _bounded("protein_target_g", protein_target_g, _PROTEIN_RANGE)
        _bounded("calories_min", calories_min, _CALORIES_RANGE)
        _bounded("calories_max", calories_max, _CALORIES_RANGE)
        if sex is not None and sex not in profile_settings.SEXES:
            raise ValueError(f"sex must be one of {', '.join(profile_settings.SEXES)}")
        if timezone is not None:
            try:
                ZoneInfo(timezone.strip())
            except (ZoneInfoNotFoundError, ValueError):
                raise ValueError(f"unknown timezone {timezone!r} — use an IANA name") from None
        if goals is not None and any("," in g for g in goals):
            raise ValueError("a goal cannot contain a comma — goals are stored comma-separated")
        stored = profile_settings.read_nutrition_goals()
        low = calories_min if calories_min is not None else int(float(stored["nutrition_calories_min"]))
        high = calories_max if calories_max is not None else int(float(stored["nutrition_calories_max"]))
        if low > high:
            raise ValueError(f"calories_min ({low}) is above calories_max ({high})")

        def _text(value):
            return None if value is None else f"{value:g}" if isinstance(value, float) else str(value)

        written = profile_settings.apply_profile(
            height_cm=_text(height_cm),
            sex=sex,
            user_age=_text(age),
            timezone=timezone,
            user_program=program,
            user_goals=None if goals is None else ", ".join(g.strip() for g in goals if g.strip()),
        )
        written.update(profile_settings.apply_nutrition_goals(
            protein_target_g=_text(protein_target_g),
            calories_min=_text(calories_min),
            calories_max=_text(calories_max),
        ))
    except ValueError as e:
        return {"error": str(e)}
    if not written:
        return {"error": "nothing to change — pass at least one field"}
    return await get_user_profile()


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
    """Retrieves the supplement catalog (taken and paused) with dosages and evidence
    tiers. ``periods`` is each one's start/stop history, oldest first: ``start``,
    ``end`` once stopped, ``inferred`` when the start was backfilled (may be later
    than the real one)."""
    from vitals.services import supplements_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(Supplement).order_by(Supplement.name)
        supps = (await session.execute(stmt)).scalars().all()
        history = await supplements_service.periods_by_supplement(session)
        out = []
        for s in supps:
            row = serialize_row(s)
            periods = supplements_service.periods_view(history.get(s.id, []))
            if periods:
                row["periods"] = periods
            out.append(row)
        return out


@mcp.tool()
async def get_skincare_logs(
    start_date: Optional[str] = None, end_date: Optional[str] = None, limit: int = 100
) -> dict:
    """The skincare *history* for a date range (YYYY-MM-DD), newest first, each
    series capped at ``limit`` rows (default 100):

      * ``checks`` — what was actually done: one row per product, slot (morning /
        evening) and day, the same ticks the app's checklist, the Telegram reminder
        and ``set_skincare_check`` write. ``product_id`` is null once the product
        was deleted from the catalog; ``product_name`` keeps the row readable.
      * ``observations`` — skin state: inflammation and PIH scores, zone, note.
      * ``day_flags`` — the day's actives as the conflict engine sees them
        (retinoid, azelaic, peel, …). Derived from the ticks; the rows from before
        the first tick are the old hand-filled checklist, and their ``note`` keeps
        what was written then.

    For the product catalog and what is planned today use
    ``get_skincare_routine``; to record a done product use ``set_skincare_check``.
    Face photos: ``list_photos(kind="face")``. READ tool."""
    from vitals.models import SkincareCheck

    session_factory = get_session_factory()
    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")

    def _ranged(stmt, model):
        if start:
            stmt = stmt.where(model.date >= start)
        if end:
            stmt = stmt.where(model.date <= end)
        return stmt

    async with session_factory() as session:
        checks = (await session.execute(
            _ranged(select(SkincareCheck), SkincareCheck)
            .order_by(SkincareCheck.date.desc(), SkincareCheck.slot, SkincareCheck.done_at)
            .limit(limit)
        )).scalars().all()
        observations = (await session.execute(
            _ranged(select(SkincareObservation), SkincareObservation)
            .order_by(SkincareObservation.date.desc()).limit(limit)
        )).scalars().all()
        logs = (await session.execute(
            _ranged(select(SkincareLog), SkincareLog)
            .order_by(SkincareLog.date.desc()).limit(limit)
        )).scalars().all()

        return {
            "checks": [serialize_row(c) for c in checks],
            "observations": [serialize_row(o) for o in observations],
            "day_flags": [serialize_row(l) for l in logs],
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
async def get_active_alerts(domain: Optional[str] = None) -> list[dict]:
    """Returns the currently active (unresolved) alerts — warnings, conflict
    blocks, overdue retests, the station's air — newest first, optionally for one
    ``domain``. ``override_at`` marks a block the owner already answered with
    "doing it anyway". The same list as the app's attention panel."""
    from vitals.services import alerts_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        alerts = await alerts_service.list_active(session, domain=domain)
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
async def resolve_all_alerts(domain: Optional[str] = None) -> dict:
    """Resolves every active alert at once — the app's "dismiss all" — or, with
    ``domain`` (e.g. "labs", "skincare", "environment"), every alert of that
    domain. Bulk and immediate: use it only when the owner asks to clear them
    all; for one alert use ``resolve_alert``. An alert whose cause is still there
    may be raised again by the next check. Returns how many were resolved.
    WRITE tool."""
    from vitals.services import alerts_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        count = len(await alerts_service.list_active(session, domain=domain))
        await alerts_service.resolve_all(session, domain=domain)
        await session.commit()
        return {"resolved": count, "domain": domain}


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
            {"key": key, "name": supplement_name, "active": True, "ref": f"supplement:{key}"},
        )
        return [_violation_view(v) for v in violations]


_VALID_CONFLICT_DOMAINS = {d.value for d in Domain}


def _violation_view(v) -> dict:
    """A dry-run violation plus the catalog entities the rule matched."""
    return {**v.to_dict(), "entities": list(v.entity_refs)}


@mcp.tool()
async def list_conflict_rules(
    domain: Optional[str] = None, category: Optional[str] = None
) -> list[dict]:
    """Lists the curated cross-domain conflict rules (vitals/data/conflict_rules.yaml),
    optionally filtered by ``domain`` (matches either side of the rule) and/or
    ``category`` (absorption, pharmacogenomics, dermatology, lab_safety, glp1,
    contraindication). ``active`` is the owner's on/off switch for the rule
    (``set_conflict_rule_active``); ``firing`` is true while the rule has an
    unresolved alert right now. Switched-off rules are included so the whole
    catalog is visible."""
    from vitals.models.conflict_rule import ConflictRule
    from vitals.services import conflict_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(ConflictRule)
        if category:
            stmt = stmt.where(ConflictRule.category == category)
        rows = (await session.execute(stmt)).scalars().all()
        if domain:
            rows = [r for r in rows if r.domain_a == domain or r.domain_b == domain]
        firing = await conflict_service.get_firing_rule_ids(session)
        return [{**serialize_row(r), "firing": r.id in firing} for r in rows]


@mcp.tool()
@gated("interactions")
async def set_conflict_rule_active(rule_id: int, active: bool) -> dict:
    """Switches one conflict rule on or off — the toggle on the app's
    Interactions screen. A rule switched off is never evaluated: its warnings and
    blocks stop for every write (the app's and yours) until it is switched back
    on. ``rule_id`` from ``list_conflict_rules``. Turning off a ``block`` rule
    removes a safety check, so do it only on the owner's explicit request, and
    say which rule it was. WRITE tool."""
    from vitals.services import conflict_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        row = await conflict_service.toggle_rule(session, rule_id, active)
        if row is None:
            return {"error": f"Conflict rule {rule_id} not found"}
        await session.commit()
        return await serialize_written(session, row)


@mcp.tool()
async def check_conflicts(domain: str, payload: dict) -> list[dict]:
    """Evaluates an arbitrary proposed state against the active conflict rules
    for ``domain`` (one of: weight, glp1, supplements, genetics, skincare,
    labs, nutrition, workouts, garmin, milestones, system, body_comp). E.g.
    ``check_conflicts("labs", {"marker": "Калий", "value": 5.5})`` or
    ``check_conflicts("supplements", {"key": "iron", "active": True})``.
    Read-only — never writes, never blocks; returns the violations the proposed
    item itself would take part in if saved (``key`` and ``active`` count: an
    inactive supplement clashes with nothing). Rules already true of the rest of
    the catalog are not repeated here — those are in ``get_active_alerts``.
    Each violation lists the catalog ``entities`` it matched."""
    if domain not in _VALID_CONFLICT_DOMAINS:
        return [{"error": f"Unknown domain '{domain}'. Use one of: {', '.join(sorted(_VALID_CONFLICT_DOMAINS))}"}]

    session_factory = get_session_factory()
    async with session_factory() as session:
        if (
            domain == Domain.SUPPLEMENTS.value
            and isinstance(payload, dict)
            and payload.get("key")
            and "ref" not in payload
        ):
            payload = {**payload, "ref": f"supplement:{payload['key']}"}
        violations = await conflict_engine.evaluate(session, domain, payload)
        return [_violation_view(v) for v in violations]


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
    Defaults: on_date = today, eaten_at = None (unspecified meal time). If a hard conflict rule
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
_MEAL_CLEARABLE = ("eaten_at", "calories", "protein_g", "fat_g", "carbs_g", "note")


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
    clear: Optional[list[str]] = None,
) -> dict:
    """Updates an existing meal by ID. Returns the updated meal or an error.

    Only the fields you pass are changed — anything left out keeps its stored
    value, including ``on_date``, which stays the meal's own date rather than
    moving the meal to today. To empty a field (an unknown macro, a wrong time,
    a note) name it in ``clear``: any of eaten_at, calories, protein_g, fat_g,
    carbs_g, note. WRITE tool — changes are saved immediately.
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
        unknown = sorted(set(clear or []) - set(_MEAL_CLEARABLE))
        if unknown:
            return {"error": f"cannot clear {unknown} — clearable: {', '.join(_MEAL_CLEARABLE)}"}
        for field in clear or []:
            merged[field] = None
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


@mcp.tool()
async def update_weight(
    log_id: int,
    weight_kg: Optional[float] = None,
    on_date: Optional[str] = None,
    note: Optional[str] = None,
    clear_note: bool = False,
    override: bool = False,
) -> dict:
    """Corrects a weight entry by ID (from ``get_weight_logs``) — a mistyped
    value, the wrong day, a note. Only what you pass changes; ``clear_note=True``
    empties the note. Moving it to another date re-ranks both days (the entry
    can outrank a Garmin import there, and the old day's next entry becomes
    active again). Runs the same conflict check as ``log_weight`` — a hard block
    returns ``{"blocked": true, ...}``; retry with ``override=True``. WRITE tool."""
    from vitals.services import weight_service

    parsed_date = _parse_date(on_date, field="on_date")
    session_factory = get_session_factory()
    async with session_factory() as session:
        row = await weight_service.get_weight_log(session, log_id)
        if row is None:
            return {"error": f"Weight log {log_id} not found"}
        try:
            updated = await weight_service.update_weight_log(
                session, log_id,
                on_date=parsed_date or row.date,
                weight_kg=weight_kg if weight_kg is not None else row.weight_kg,
                note=None if clear_note else (note if note is not None else row.note),
                override=override,
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
        except ValueError as e:
            return {"error": str(e)}
        await session.commit()
        return await serialize_written(session, updated)


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


# ── Skincare: the catalog, the day's plan and what was done ──────────────────
# The routine is the catalog read for a date: every product in use whose
# ``schedule_days`` include that weekday, in the slot(s) its ``default_time``
# names. A tick (``set_skincare_check``) is what records it as done — the same
# service call as a tap in the app or under the Telegram reminder, so it runs the
# same conflict check and sets the same day flags the engine reads.
SKINCARE_RANGE_MAX_DAYS = 31
_SKINCARE_TIMES = ("morning", "evening", "both")
_SKINCARE_CLEARABLE = (
    "active_ingredient", "description", "usage_instructions", "usage_morning",
    "usage_evening", "step", "active_flag",
)
_SKINCARE_STEP_RANGE = (1, 99)


def _skincare_schedule(
    default_time: Optional[str],
    schedule_days: Optional[list[int]],
    active_flag: Optional[str],
    step: Optional[int] = None,
) -> None:
    """Reject what the app's form can't produce: an unknown slot, a weekday
    outside 0..6, a conflict flag the engine has no rule key for, a step outside
    1..99."""
    from vitals.services import skincare_service

    low, high = _SKINCARE_STEP_RANGE
    if step is not None and not low <= step <= high:
        raise ValueError(f"step must be between {low} and {high}")

    if default_time is not None and default_time not in _SKINCARE_TIMES:
        raise ValueError(f"default_time must be one of {', '.join(_SKINCARE_TIMES)}")
    if schedule_days is not None and any(
        not isinstance(d, int) or isinstance(d, bool) or not 0 <= d <= 6 for d in schedule_days
    ):
        raise ValueError("schedule_days are weekday numbers 0..6 (Monday=1 … Saturday=6, Sunday=0)")
    if active_flag is not None and active_flag not in skincare_service.ACTIVE_FLAGS:
        raise ValueError(
            f"active_flag must be one of {', '.join(skincare_service.ACTIVE_FLAGS)} "
            "(or left out / cleared for a product no rule concerns)"
        )


@mcp.tool()
async def get_skincare_routine(
    start_date: Optional[str] = None, end_date: Optional[str] = None
) -> dict:
    """The skincare routine as the app runs it: the product catalog and the plan
    for a day or a range of days (YYYY-MM-DD, default today; ``start_date`` alone
    runs to today; at most 31 days), with what was ticked done. Call this first for anything about the routine —
    "what do I put on tonight", "did I do the morning", "add Х to Tuesdays".

    ``today`` is the owner's routine day, not the calendar: until the day ends
    (``day_end`` in the settings, 05:00 by default) it is still the evening before
    — at 01:00 "tonight" means the date ``today`` says.

    ``products`` — the whole catalog, products in use and switched off, in the
    order of application: ``id``, ``name``, ``type``, ``active_ingredient``,
    ``description``, ``usage_instructions`` (how to apply it) and
    ``usage_morning`` / ``usage_evening`` (how in that slot, when different),
    ``step`` (place in the order of application), ``default_time`` (morning /
    evening / both), ``schedule_days`` (weekday numbers: Monday=1 … Saturday=6,
    Sunday=0), ``active`` (false = switched off: kept in the catalog, never
    planned) and ``active_flag`` (the conflict-engine key ticking it sets — one of
    ``flags``; absent = a product no rule concerns, like a cleanser).

    ``days`` — newest first, each with ``morning`` and ``evening`` lists of
    ``{product_id, name, flag, how, planned, done, done_at}`` and ``notes``
    (``{slot: text}`` for the slots with a ``set_skincare_note``); ``planned:
    false`` marks a product ticked on a day it wasn't scheduled. The
    ``product_id`` here is what ``set_skincare_check`` and
    ``update_skincare_product`` take. READ tool."""
    from vitals.services import skincare_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        today = await skincare_service.today(session)
    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")
    if start is None and end is None:
        start = end = today
    elif end is None:  # "since Monday" reads up to today
        end = max(start, today)
    elif start is None:
        start = end
    if end < start:
        return {"error": "end_date is before start_date"}
    if (end - start).days >= SKINCARE_RANGE_MAX_DAYS:
        return {"error": f"at most {SKINCARE_RANGE_MAX_DAYS} days per call — narrow the range"}

    async with session_factory() as session:
        products = await skincare_service.list_products(session)
        return {
            "today": today.isoformat(),
            "products": [serialize_row(p) for p in products],
            "days": await skincare_service.plans_between(session, start, end),
            "flags": list(skincare_service.ACTIVE_FLAGS),
        }


@mcp.tool()
@gated("skincare")
async def add_skincare_product(
    name: str,
    type: str,
    default_time: str = "evening",
    schedule_days: Optional[list[int]] = None,
    active_ingredient: Optional[str] = None,
    active_flag: Optional[str] = None,
    description: Optional[str] = None,
    usage_instructions: Optional[str] = None,
    usage_morning: Optional[str] = None,
    usage_evening: Optional[str] = None,
    step: Optional[int] = None,
    active: bool = True,
) -> dict:
    """Adds a product to the skincare catalog — from then on it is planned on its
    days and shows on the checklist (app and Telegram).

    ``usage_instructions`` is how to apply it, one short line («горошина на сухую
    кожу, через 20 мин после умывания») — printed under the product in the
    reminder. ``usage_morning`` / ``usage_evening`` replace it in that slot for a
    product applied differently morning and evening. ``step`` is its place in
    the order of application, 1..99 (cleanser 1, active 2, cream 3).

    ``type`` is a short free-text kind ("Ретиноид", "Крем", "Умывалка").
    ``default_time`` is morning, evening or both. ``schedule_days`` are weekday
    numbers, Monday=1 … Saturday=6, Sunday=0; left out = every day.
    ``active_flag`` ties the product to the conflict rules — one of retinoid,
    azelaic, peel, niacinamide_spf, moisturizer, vitamin_c, benzoyl_peroxide; set
    it for anything containing that active (adapalene and tretinoin are
    ``retinoid``), leave it out for products no rule concerns. ``active=False``
    adds it switched off. WRITE tool — saved immediately."""
    from vitals.services import skincare_service

    name, type = (name or "").strip(), (type or "").strip()
    if not name or not type:
        return {"error": "name and type are required"}
    days = list(range(7)) if schedule_days is None else sorted(set(schedule_days))
    try:
        _skincare_schedule(default_time, days, active_flag, step)
    except ValueError as e:
        return {"error": str(e)}

    session_factory = get_session_factory()
    async with session_factory() as session:
        row = await skincare_service.add_product(
            session, name=name, type=type, active_ingredient=active_ingredient,
            description=description, usage_instructions=usage_instructions,
            usage_morning=usage_morning, usage_evening=usage_evening, step=step,
            default_time=default_time, schedule_days=days, active=active,
            active_flag=active_flag,
        )
        await session.commit()
        return await serialize_written(session, row)


@mcp.tool()
@gated("skincare")
async def update_skincare_product(
    product_id: int,
    name: Optional[str] = None,
    type: Optional[str] = None,
    default_time: Optional[str] = None,
    schedule_days: Optional[list[int]] = None,
    active_ingredient: Optional[str] = None,
    active_flag: Optional[str] = None,
    description: Optional[str] = None,
    usage_instructions: Optional[str] = None,
    usage_morning: Optional[str] = None,
    usage_evening: Optional[str] = None,
    step: Optional[int] = None,
    active: Optional[bool] = None,
    clear: Optional[list[str]] = None,
) -> dict:
    """Edits a catalog product by ``product_id`` (from ``get_skincare_routine``).
    Only the fields you pass change. Use it to reschedule (``schedule_days`` is
    the full new list, Monday=1 … Sunday=0; ``default_time`` morning / evening /
    both), to switch a product off or back on (``active=False`` / ``True`` — it
    stays in the catalog with its history, just is no longer planned; prefer this
    over deleting), to correct its conflict flag, or to say how and in what order
    it is applied: ``usage_instructions`` (one line, shown under it in the
    reminder), ``usage_morning`` / ``usage_evening`` (that slot only, when it
    differs), ``step`` (1..99, place in the order of application). For something
    about one day only («сегодня пропусти»), use ``set_skincare_note`` instead.

    To empty a field or remove the conflict flag, name it in ``clear`` (any of
    active_ingredient, description, usage_instructions, usage_morning,
    usage_evening, step, active_flag). Ticks already recorded keep the flag they
    were made with. WRITE tool."""
    from vitals.models import SkincareProduct
    from vitals.services import skincare_service

    clear = list(clear or [])
    unknown = sorted(set(clear) - set(_SKINCARE_CLEARABLE))
    if unknown:
        return {"error": f"cannot clear {unknown} — clearable: {', '.join(_SKINCARE_CLEARABLE)}"}
    days = sorted(set(schedule_days)) if schedule_days is not None else None
    try:
        _skincare_schedule(default_time, days, active_flag, step)
    except ValueError as e:
        return {"error": str(e)}
    if name is not None and not name.strip() or type is not None and not type.strip():
        return {"error": "name and type cannot be empty"}

    session_factory = get_session_factory()
    async with session_factory() as session:
        merged = await _merged(
            session, SkincareProduct, product_id,
            name=name.strip() if name else None, type=type.strip() if type else None,
            default_time=default_time, schedule_days=days,
            active_ingredient=active_ingredient, active_flag=active_flag,
            description=description, usage_instructions=usage_instructions,
            usage_morning=usage_morning, usage_evening=usage_evening, step=step, active=active,
        )
        if merged is None:
            return {"error": f"Skincare product {product_id} not found"}
        for field in clear:
            merged[field] = None
        merged["schedule_days"] = merged["schedule_days"] or []
        row = await skincare_service.update_product(session, product_id, **merged)
        await session.commit()
        return await serialize_written(session, row)


@mcp.tool()
@gated("skincare")
async def set_skincare_check(
    slot: str,
    product_id: Optional[int] = None,
    done: bool = True,
    on_date: Optional[str] = None,
    override: bool = False,
) -> dict:
    """Records that a skincare product was applied — or takes the mark back.
    The same tick as a tap on the app's checklist or the button under the Telegram
    reminder (a reminder already in the chat is redrawn to match). This is THE
    way to log skincare; it replaced the old seven-checkbox ``log_skincare``.

    ``slot`` is morning or evening. ``product_id`` comes from
    ``get_skincare_routine``; leave it out (with ``done=True``) to tick everything
    still open in that slot — the "all done" button. ``done=False`` unticks one
    product. ``on_date`` defaults to the routine day (at 01:00, the evening
    before); any past date works for catching up.
    A product can be ticked on a day it isn't scheduled — it then shows as
    ``planned: false``. Idempotent: ticking twice records one tick.

    Ticking a product whose conflict flag a blocking rule forbids (e.g. a
    retinoid and a peel the same evening) returns ``{"blocked": true, ...}`` and
    saves nothing; retry with ``override=True`` only when the owner confirms it
    was actually done. Returns the day's plan as it now stands plus any
    non-blocking ``warnings``. WRITE tool."""
    from vitals.services import skincare_service
    from vitals.services.proactive import channels
    from vitals.services.proactive import skincare as skincare_reminders

    if slot not in skincare_service.SLOTS:
        return {"error": f"slot must be one of {', '.join(skincare_service.SLOTS)}"}
    if product_id is None and not done:
        return {"error": "a whole slot can only be ticked, not unticked — pass product_id"}

    session_factory = get_session_factory()
    async with session_factory() as session:
        parsed_date = _parse_date(on_date, await skincare_service.today(session), field="on_date")
        try:
            if product_id is None:
                violations = await skincare_service.complete_slot(
                    session, on_date=parsed_date, slot=slot, override=override,
                    source=Source.MCP.value,
                )
            else:
                violations = await skincare_service.set_check(
                    session, on_date=parsed_date, product_id=product_id, slot=slot,
                    done=done, override=override, source=Source.MCP.value,
                )
        except ConflictBlocked as e:
            return _conflict_payload(e)
        except LookupError:
            return {"error": f"Skincare product {product_id} not found"}
        await session.commit()

        # Best-effort, as in the app: the tick is committed, and a slow or
        # refused Telegram edit must not turn it into an error.
        try:
            await skincare_reminders.sync_sent(
                session, channels.build_notifier(), parsed_date, slot
            )
        except Exception:  # noqa: BLE001
            logger.warning("mcp: could not sync the skincare reminder", exc_info=True)

        result = {
            "date": parsed_date.isoformat(),
            **await skincare_service.plan_for(session, parsed_date),
        }
        if violations:
            result["warnings"] = [v.to_dict() for v in violations]
        return result


@mcp.tool()
@gated("skincare")
async def set_skincare_note(slot: str, text: str, on_date: Optional[str] = None) -> dict:
    """Leaves a note on one slot of one day — what to do differently that time:
    «щёки раздражены — ретиноид только на лоб», «после пилинга без кислот». Shown
    above that slot's checklist in the app and at the top of its Telegram
    reminder (a reminder already sent is redrawn). One note per slot and day:
    writing again replaces it, empty ``text`` removes it. ``slot`` is morning or
    evening; ``on_date`` (YYYY-MM-DD) defaults to the routine day. How a product
    is applied every time belongs in its ``usage_instructions`` instead. WRITE
    tool. Returns the day's plan with its notes."""
    from vitals.services import skincare_service
    from vitals.services.proactive import channels
    from vitals.services.proactive import skincare as skincare_reminders

    if slot not in skincare_service.SLOTS:
        return {"error": f"slot must be one of {', '.join(skincare_service.SLOTS)}"}

    session_factory = get_session_factory()
    async with session_factory() as session:
        parsed_date = _parse_date(on_date, await skincare_service.today(session), field="on_date")
        try:
            await skincare_service.set_note(
                session, on_date=parsed_date, slot=slot, text=text, source=Source.MCP.value
            )
        except ValueError as e:
            return {"error": str(e)}
        await session.commit()

        try:
            await skincare_reminders.sync_sent(
                session, channels.build_notifier(), parsed_date, slot
            )
        except Exception:  # noqa: BLE001
            logger.warning("mcp: could not sync the skincare reminder", exc_info=True)

        return {
            "date": parsed_date.isoformat(),
            **await skincare_service.plan_for(session, parsed_date),
        }


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
# Every delete service takes ``(session, id)`` and reports whether there was a row —
# a bool, or for a photo the stored file's key (truthy) so the file can go once the
# row is committed. That shared shape is what lets a single tool stand in for the
# near-identical ones that used to live here, each differing only in the noun it
# echoed back. The tool list is re-read at the top of every conversation, so a
# fifth of it was spent spelling out delete_meal / delete_glp1 / delete_hrt_cycle_item.
_DELETE_TARGETS: dict[str, tuple[Optional[str], str, str]] = {
    "weight": (None, "weight_service", "delete_weight_log"),
    "measurement": (None, "weight_service", "delete_body_measurement"),
    "noise_marker": (None, "weight_service", "delete_noise_marker"),
    "progress_photo": (None, "weight_service", "delete_progress_photo"),
    "labs": (None, "labs_service", "delete_result"),
    "milestones": (None, "milestones_service", "delete_milestone"),
    "shared_report": (None, "share_service", "delete_report"),
    "nutrition": ("nutrition", "nutrition_service", "delete_meal"),
    "glp1": ("glp1", "glp1_service", "delete_injection"),
    "glp1_side_effect": ("glp1", "glp1_service", "delete_side_effect"),
    "glp1_dose_phase": ("glp1", "glp1_service", "delete_dose_phase"),
    "hrt_dose": ("hrt", "hrt_service", "delete_dose"),
    "hrt_cycle": ("hrt", "hrt_cycle_service", "delete_cycle"),
    "hrt_cycle_item": ("hrt", "hrt_cycle_service", "delete_cycle_item"),
    "body_comp": ("body_comp", "body_scan_service", "delete_scan"),
    "timeline": ("timeline", "timeline_service", "delete_annotation"),
    "skincare_product": ("skincare", "skincare_service", "delete_product"),
    "skincare_photo": ("skincare", "skincare_service", "delete_photo"),
    "skincare_observation": ("skincare", "skincare_service", "delete_observation"),
    "skincare_day_flags": ("skincare", "skincare_service", "delete_log"),
    "supplements": ("supplements", "supplements_service", "delete_supplement"),
    "genetics": ("genetics", "genetics_service", "delete_variant"),
    "signals": ("signals", "signals_service", "delete_signal"),
}

# The domains whose rows feed passive alerts: the app re-derives those alerts after
# a delete, so a removed out-of-range result can't leave its warning behind.
_DELETE_REFRESHES: dict[str, str] = {
    "labs": "labs_service",
    "body_comp": "body_scan_service",
}


def _remove_upload(rel_path: Optional[str]) -> None:
    """Delete a stored upload once its row is gone — best-effort, like the app."""
    from web.templating import STATIC_DIR

    if not rel_path:
        return
    path = os.path.join(STATIC_DIR, rel_path)
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass
    # A photo's tile and screen copies go with it; anything else has none.
    photo_derivatives.remove_derivatives(STATIC_DIR, rel_path)


@mcp.tool()
async def delete_record(domain: str, record_id: int) -> dict:
    """Deletes one record from any domain by its ID — permanently; there is no
    undo, so delete only what the owner asked to remove. WRITE tool — immediate.

    ``domain`` is one of: weight, measurement (body tape), noise_marker,
    progress_photo (a weight progress photo and its file), labs (one result),
    milestones (a goal card), shared_report (a doctor link's record — to only
    kill the link and keep the record use ``revoke_shared_report``), nutrition (a
    meal), glp1 (an injection), glp1_side_effect, glp1_dose_phase, hrt_dose,
    hrt_cycle (with its compound plans), hrt_cycle_item (one plan, cycle kept),
    body_comp (a scan with its metrics and file), timeline (a manual event),
    skincare_product (removes it from the catalog; past ticks keep its name —
    to stop using a product prefer ``update_skincare_product(active=False)``),
    skincare_photo (a face photo and its file), skincare_observation,
    skincare_day_flags (one day's conflict-flag row — the old hand-filled
    checklist; ticks are taken back with ``set_skincare_check(done=False)``,
    not here), supplements (a catalog entry), genetics (a variant), signals (one
    parsed signal — the raw message stays in the lake; for a whole batch parsed
    wrongly out of one message use ``mark_signal_misparse`` instead).

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
        upload = None
        if domain == "body_comp":
            # The scan's file key is relative to uploads/, unlike the photos'.
            scan = await session.get(BodyScan, record_id)
            upload = f"uploads/{scan.file_key}" if scan is not None and scan.file_key else None
        result = await getattr(service, fn_name)(session, record_id)
        if isinstance(result, str):  # a photo: the service hands back its file key
            upload = result
        refresher = _DELETE_REFRESHES.get(domain)
        if result and refresher:
            await importlib.import_module(f"vitals.services.{refresher}").refresh_alerts(session)
        await session.commit()
        if result:
            _remove_upload(upload)
        return {"deleted": bool(result), "domain": domain, "record_id": record_id}


# ── Photos: the weight's progress photos and the face diary ──────────────────
# Two galleries with one shape (a dated row + a file under static/uploads), so
# one set of tools serves both. ``get_photo`` hands the picture itself back as
# image content, scaled down: the model can look at it and compare, which a URL
# behind the owner's login never allowed.
_PHOTO_KINDS = ("face", "progress")
PHOTO_MAX_BYTES = 25 * 1024 * 1024  # the app's upload cap
PHOTOS_PER_LIST_MAX = 200
_PHOTO_FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}


def _photo_model(kind: str):
    from vitals.models import ProgressPhoto, SkincarePhoto

    return SkincarePhoto if kind == "face" else ProgressPhoto


async def _photo_kind_error(session, kind: str) -> Optional[dict]:
    """``None`` when ``kind`` is usable; the face diary belongs to skincare."""
    if kind not in _PHOTO_KINDS:
        return {"error": f"kind must be one of {', '.join(_PHOTO_KINDS)}"}
    if kind == "face" and not await _module_enabled(session, "skincare"):
        return {"error": "module 'skincare' is disabled"}
    return None


def _photo_row(row) -> dict:
    d = serialize_row(row)
    d.update(photo_derivatives.photo_urls(row.file_key))
    return d


@mcp.tool()
async def list_photos(
    kind: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """Lists photos from one of the app's two galleries, newest first:
    ``kind="face"`` — the face photo diary on the skincare screen;
    ``kind="progress"`` — the body progress photos on the weight screen.
    Each row is ``{id, date, note, url}`` (the url is a path behind the owner's
    login — to actually look at a photo call ``get_photo``). Optional
    YYYY-MM-DD range; most recent 50 by default. READ tool."""
    session_factory = get_session_factory()
    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")
    async with session_factory() as session:
        problem = await _photo_kind_error(session, kind)
        if problem:
            return [problem]
        model = _photo_model(kind)
        stmt = select(model)
        if start:
            stmt = stmt.where(model.date >= start)
        if end:
            stmt = stmt.where(model.date <= end)
        stmt = stmt.order_by(model.date.desc(), model.id.desc()).limit(
            max(1, min(limit, PHOTOS_PER_LIST_MAX))
        )
        return [_photo_row(r) for r in (await session.execute(stmt)).scalars().all()]


def _scaled_jpeg(path: str, max_px: int) -> bytes:
    """The stored photo, upright (EXIF orientation applied) and fitted inside
    ``max_px`` on its longer side, as a JPEG."""
    import io

    from PIL import Image as PilImage, ImageOps

    with PilImage.open(path) as img:
        img = ImageOps.exif_transpose(img)
        img.thumbnail((max_px, max_px))
        out = io.BytesIO()
        img.convert("RGB").save(out, "JPEG", quality=85)
        return out.getvalue()


@mcp.tool()
async def get_photo(kind: str, photo_id: int, max_px: int = 1024):
    """Shows one photo — returns its details and the image itself, so you can
    look at it: compare the face week to week (inflammation, marks, redness) or
    the body against an earlier progress photo. ``kind`` is "face" or
    "progress", ``photo_id`` from ``list_photos``. ``max_px`` bounds the longer
    side (default 1024, 256–2048): larger shows more detail but costs more of the
    conversation — ask for one or two photos at a time, not a whole gallery.
    READ tool."""
    import asyncio

    from fastmcp.tools import ToolResult
    from fastmcp.utilities.types import Image
    from mcp.types import TextContent

    from web.templating import STATIC_DIR

    session_factory = get_session_factory()
    async with session_factory() as session:
        problem = await _photo_kind_error(session, kind)
        if problem:
            return problem
        row = await session.get(_photo_model(kind), photo_id)
        if row is None:
            return {"error": f"{kind} photo {photo_id} not found"}
        meta = _photo_row(row)

    path = os.path.join(STATIC_DIR, row.file_key)
    if not os.path.exists(path):
        return {**meta, "error": "the file is missing on disk"}
    try:
        data = await asyncio.to_thread(_scaled_jpeg, path, max(256, min(int(max_px), 2048)))
    except Exception:  # noqa: BLE001 — HEIC without a decoder, a truncated file…
        logger.warning("mcp: cannot render photo %s", row.file_key, exc_info=True)
        return {**meta, "error": "this file can't be rendered here (unsupported or damaged image)"}
    return ToolResult(content=[
        TextContent(type="text", text=json.dumps(meta, ensure_ascii=False)),
        Image(data=data, format="jpeg").to_image_content(),
    ])


def _decode_image(image_base64: str) -> tuple[bytes, str]:
    """Base64 (optionally a ``data:`` URL) → ``(bytes, extension)``. The bytes are
    checked to be a JPEG, PNG or WebP image — whatever the caller claims."""
    import base64
    import binascii
    import io

    from PIL import Image as PilImage, UnidentifiedImageError

    raw = (image_base64 or "").strip()
    if raw.startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    if len(raw) * 3 // 4 > PHOTO_MAX_BYTES:
        raise ValueError(f"image too large (max {PHOTO_MAX_BYTES // (1024 * 1024)} MB)")
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("image_base64 is not valid base64") from None
    try:
        with PilImage.open(io.BytesIO(data)) as img:
            fmt = img.format
            img.verify()
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise ValueError("image_base64 does not decode to an image") from None
    ext = _PHOTO_FORMATS.get(fmt or "")
    if ext is None:
        raise ValueError(f"unsupported image format {fmt} — send JPEG, PNG or WebP")
    return data, ext


@mcp.tool()
async def add_photo(
    kind: str,
    image_base64: str,
    on_date: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    """Adds a photo to a gallery — ``kind="face"`` (the skincare face diary) or
    ``kind="progress"`` (body progress photos on the weight screen) — dated
    ``on_date`` (default today), with an optional note.

    ``image_base64`` is the file's bytes in base64 (a ``data:image/...;base64,``
    prefix is fine): JPEG, PNG or WebP, up to 25 MB. This only works where you
    actually hold the file's bytes (e.g. a client with file access). A photo the
    owner attached to a chat message is NOT available to you as bytes — don't
    try to re-create or describe it into this tool; ask the owner to upload it in
    the app instead. WRITE tool — saved immediately."""
    import uuid

    from vitals.services import skincare_service, weight_service
    from web.templating import STATIC_DIR
    from web.uploads import write_upload

    try:
        data, ext = _decode_image(image_base64)
    except ValueError as e:
        return {"error": str(e)}
    parsed_date = _parse_date(on_date, today_local(), field="on_date")
    note = (note or "").strip() or None

    session_factory = get_session_factory()
    async with session_factory() as session:
        problem = await _photo_kind_error(session, kind)
        if problem:
            return problem
        file_key = f"uploads/{uuid.uuid4().hex}{ext}"
        await write_upload(os.path.join(STATIC_DIR, file_key), data)
        # The same tile and screen copies an upload from the app gets.
        await asyncio.to_thread(photo_derivatives.make_derivatives, STATIC_DIR, file_key)
        add = skincare_service.add_photo if kind == "face" else weight_service.add_progress_photo
        row = await add(session, on_date=parsed_date, file_key=file_key, note=note)
        await session.commit()
        await session.refresh(row)
        return _photo_row(row)


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
        await body_scan_service.refresh_alerts(session)
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
    (YYYY-MM-DD). Defaults to the most recent 100 rows across all markers.
    ``flag`` is judged now against the result's own range (the catalog's when the
    lab printed none); ``suspect`` marks a value no person can have in that unit
    — a misread document, not a finding."""
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
        catalog = {m.name: m for m in await labs_service.list_markers(session)}
        out = []
        for r in results:
            ref_low, ref_high = labs_service.effective_range(r, catalog.get(r.marker))
            out.append({
                **serialize_row(r),
                "ref_low": ref_low,
                "ref_high": ref_high,
                "flag": labs_service.effective_flag(r, catalog.get(r.marker)),
            })
        return out


@mcp.tool()
async def get_lab_markers(marker: Optional[str] = None) -> dict:
    """The lab-marker catalog the alerts are computed from: per marker its
    ``unit``, reference range (``ref_low``/``ref_high``), ``category``, ``tier``
    (1 = key marker … 3), ``retest_interval_days`` (when an "overdue retest"
    alert fires) and ``defer_until`` (retest alert paused until then). With
    ``marker`` (any spelling — normalized like the results) it returns that one
    marker plus its full value history. READ tool; change with
    ``update_lab_marker``."""
    from vitals.services import labs_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        if marker is None:
            return {"markers": [serialize_row(m) for m in await labs_service.list_markers(session)]}
        row = await labs_service.get_marker(session, labs_service.normalize_marker(marker))
        if row is None:
            return {"error": f"No marker '{marker}' in the catalog"}
        return {
            **serialize_row(row),
            "history": await labs_service.marker_history(session, row.name),
        }


@mcp.tool()
async def update_lab_marker(
    marker: str,
    ref_low: Optional[float] = None,
    ref_high: Optional[float] = None,
    category: Optional[str] = None,
    tier: Optional[int] = None,
    retest_interval_days: Optional[int] = None,
    defer_until: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    """Edits a catalog marker — the marker card on the Labs screen. Only what you
    pass changes. ``ref_low``/``ref_high`` is the catalog's reference range (used
    when a result comes without one); ``tier`` 1–3; ``retest_interval_days``
    drives the "overdue retest" alert; ``defer_until`` (YYYY-MM-DD) is "remind me
    later": it pauses that alert until the date and closes the open one. Alerts
    are re-derived after the save. WRITE tool."""
    from vitals.services import labs_service

    parsed_defer = _parse_date(defer_until, field="defer_until")
    if tier is not None and not 1 <= tier <= 3:
        return {"error": "tier must be 1, 2 or 3"}
    if retest_interval_days is not None and retest_interval_days <= 0:
        return {"error": "retest_interval_days must be positive"}
    session_factory = get_session_factory()
    async with session_factory() as session:
        row = await labs_service.get_marker(session, labs_service.normalize_marker(marker))
        if row is None:
            return {"error": f"No marker '{marker}' in the catalog"}
        for field, value in {
            "ref_low": ref_low, "ref_high": ref_high, "category": category, "tier": tier,
            "retest_interval_days": retest_interval_days, "note": note,
        }.items():
            if value is not None:
                setattr(row, field, value)
        await session.flush()
        if parsed_defer is not None:
            await labs_service.defer_retest(session, row.name, until=parsed_defer)
        await labs_service.refresh_alerts(session)
        await session.commit()
        return await serialize_written(session, row)


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
        # The app re-derives the out-of-range / retest alerts after every save.
        await labs_service.refresh_alerts(session)
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
        await labs_service.refresh_alerts(session)
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
    clear: Optional[list[str]] = None,
) -> dict:
    """Updates a manual Timeline annotation by ID — the ``id`` of a row from
    ``get_timeline`` whose source is manual (derived events are computed and
    cannot be edited). Only the fields you pass are changed; everything left out
    keeps its stored value, including the event's own date. ``clear`` empties
    fields: ``end_date`` (a range back to a single day) and/or ``note``.
    WRITE tool."""
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
        unknown = sorted(set(clear or []) - {"end_date", "note"})
        if unknown:
            return {"error": f"cannot clear {unknown} — clearable: end_date, note"}
        for field in clear or []:
            merged[field] = None
        row = await timeline_service.update_annotation(
            session, event_id, on_date=merged.pop("date"), **merged
        )
        await session.commit()
        return await serialize_written(session, row)


# ── Cross-domain + whole-lake tools ──────────────────────────────────────────
DEFAULT_SNAPSHOT_SECTIONS = frozenset({"weight", "garmin", "nutrition", "hevy", "alerts", "glp1"})
ALL_OPTIONAL_SNAPSHOT_SECTIONS = frozenset({
    "labs", "body_comp", "genetics", "supplements", "skincare", "hrt",
    "signals", "milestones", "timeline", "environment",
})


@mcp.tool()
async def get_full_snapshot(
    on_date: Optional[str] = None,
    period_days: int = 7,
    sections: Optional[list[str]] = None,
) -> dict:
    """Returns context-v2 for a closed period (1..90 days).

    By default returns only sections that actively change over the period: weight,
    Garmin, nutrition, Hevy, active alerts, and GLP-1. Static or heavy sections
    (genetics, body_comp scans, labs, supplements catalog, skincare, hrt, signals,
    milestones, timeline, environment) are included only when explicitly requested
    via ``sections=[...]`` (e.g. ``sections=["weight", "labs", "body_comp"]`` or
    ``sections=["all"]`` for the unpruned full lake). Every dated fact is bounded
    by the effective period end."""
    from vitals.services import digest_service

    session_factory = get_session_factory()
    parsed_date = _parse_date(on_date, field="on_date")
    async with session_factory() as session:
        try:
            ctx = await digest_service.assemble_context(
                session, on_date=parsed_date, period_days=period_days
            )
        except ValueError as exc:
            return {"error": str(exc)}

        if sections is not None:
            sec_set = set(sections)
            if "all" not in sec_set:
                for k in ALL_OPTIONAL_SNAPSHOT_SECTIONS | DEFAULT_SNAPSHOT_SECTIONS:
                    if k not in sec_set and k in ctx:
                        ctx[k] = None
        else:
            for k in ALL_OPTIONAL_SNAPSHOT_SECTIONS:
                if k in ctx:
                    ctx[k] = None
        return ctx


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
        ("skincare_checks", SkincareCheck, SkincareCheck.date),
        ("skincare_logs", SkincareLog, SkincareLog.date),
        ("skincare_observations", SkincareObservation, SkincareObservation.date),
        ("skincare_photos", SkincarePhoto, SkincarePhoto.date),
        ("progress_photos", ProgressPhoto, ProgressPhoto.date),
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
        ("skincare_products", SkincareProduct),
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
                entry["last_updated"] = format_iso(row[3], is_utc=True) if row[3] else None
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

    if not (drug or "").strip():
        return {"error": "drug is required"}
    if dose_mg is None or dose_mg <= 0:
        return {"error": "dose_mg must be a positive number"}
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


@mcp.tool()
@gated("glp1")
async def close_dose_phase(
    phase_id: Optional[int] = None, end_date: Optional[str] = None
) -> dict:
    """Ends a GLP-1 dose phase — the "close" action on the GLP-1 screen: the
    phase gets ``end_date`` (default today) and stops being the current dose.
    Without ``phase_id`` it closes the phase covering today. Starting a new
    open-ended phase with ``add_dose_phase`` already closes the previous one, so
    this is for stopping (a pause, the end of the course). WRITE tool."""
    from vitals.services import glp1_service

    parsed_end = _parse_date(end_date, today_local(), field="end_date")
    session_factory = get_session_factory()
    async with session_factory() as session:
        if phase_id is not None:
            phase = await session.get(DosePhase, phase_id)
        else:
            phase = await glp1_service.active_dose_phase(session)
        if phase is None:
            return {"error": "No such dose phase" if phase_id else "No dose phase covers today"}
        if parsed_end < phase.start_date:
            return {"error": f"end_date is before the phase's start ({phase.start_date.isoformat()})"}
        phase.end_date = parsed_end
        await session.flush()
        await session.commit()
        return await serialize_written(session, phase)


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
    hyperpigmentation) scores, an optional face ``zone``, and a note: how the skin
    looks, not what was applied (that is ``set_skincare_check``). WRITE tool —
    saved immediately."""
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
                source=Source.MCP.value,
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
                session, supplement_id, key=key, override=override,
                source=Source.MCP.value, **merged,
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
    conflict check → ``{"blocked": true, ...}`` unless ``override=True``.
    Deactivating resolves the conflict alerts that no longer apply. WRITE tool."""
    from vitals.services import supplements_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            row = await supplements_service.set_active(
                session, supplement_id, active, override=override,
                source=Source.MCP.value,
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
    on_date: Optional[str] = None,
    neck_cm: Optional[float] = None,
    waist_cm: Optional[float] = None,
    hips_cm: Optional[float] = None,
    note: Optional[str] = None,
    override: bool = False,
) -> dict:
    """Edits a body-measurement row by ID (recomputes Navy body-fat % / LBM).
    Only the fields you pass change; ``on_date`` left out keeps the row's own
    date. On a hard block returns ``{"blocked": true, ...}``; retry with
    ``override=True``. WRITE tool."""
    from vitals.services import weight_service

    session_factory = get_session_factory()
    parsed_date = _parse_date(on_date, field="on_date")
    async with session_factory() as session:
        if parsed_date is None:
            existing = await session.get(BodyMeasurement, measurement_id)
            if existing is None:
                return {"error": f"Measurement {measurement_id} not found"}
            parsed_date = existing.date
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
    fit_window_days: Optional[int] = 56,
    exclude_noise: bool = True,
) -> dict:
    """Computes the trend for one metric instead of returning raw rows: linear slope
    (per day and per week), the latest rolling-mean value, and — if ``target`` is
    given — the projected date the trend reaches it. For weight metrics, noise-marked
    ranges are excluded (``exclude_noise``).

    ``fit_window_days`` (default 56 days / 8 weeks) bounds the linear regression fit
    to recent history so an ancient weight-loss rate does not distort the current trend.
    When ``target`` is given, the date is projected from the latest rolling mean.

    ``metric_key`` is a registry key such as ``weight.weight_kg``,
    ``weight.body_fat_pct``, ``garmin.hrv_avg``, ``nutrition.calories``, or a
    parametrized one: ``labs.marker`` (``param`` = marker name),
    ``hevy.working_weight`` (``param`` = exercise id), ``body_comp.metric``
    (``param`` = ``metric_key`` or ``metric_key:segment``). Read-only."""
    from vitals.services import chart_data_service, weight_service
    from vitals.services.analytics import exclude_ranges
    from vitals.services.analytics.regression import fit_trend
    from vitals.services.analytics.rolling import rolling_mean_by_date
    from vitals.services.analytics.chart_registry import get as get_metric

    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            field = get_metric(metric_key)
        except KeyError:
            from difflib import get_close_matches
            from vitals.services.analytics.chart_registry import REGISTRY
            available = sorted(REGISTRY.keys())
            matches = get_close_matches(metric_key, available, n=3, cutoff=0.4)
            hint = f" Did you mean: {', '.join(matches)}?" if matches else ""
            return {
                "error": f"Unknown metric '{metric_key}'.{hint}",
                "available_metrics": available,
            }
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

        fit_points = points
        if fit_window_days and len(points) > 1:
            end_date = points[-1][0]
            start_date = end_date - timedelta(days=fit_window_days)
            windowed = [p for p in points if p[0] >= start_date]
            if len(windowed) >= 2:
                fit_points = windowed

        trend = fit_trend(fit_points)
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
                "fit_window_days": fit_window_days,
            },
            "noise_excluded": noise_applied,
        }
        if target is not None:
            projection_date = None
            rolling_val = rolling[-1][1] if rolling else points[-1][1]
            last_date = points[-1][0]
            if trend and abs(trend.slope_per_day) >= 1e-9:
                slope = trend.slope_per_day
                moving_toward = (target < rolling_val and slope < 0) or (
                    target > rolling_val and slope > 0
                )
                if moving_toward:
                    days_needed = (target - rolling_val) / slope
                    if 0 < days_needed <= 3650:
                        projection_date = (last_date + timedelta(days=round(days_needed))).isoformat()
            result["projection"] = {
                "target": target,
                "projected_from": round(rolling_val, 3),
                "date": projection_date,
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
    explaining why the bot did or didn't say something. READ tool — change the
    settings with ``set_proactive_settings``, the week template with
    ``set_week_template``."""
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


# The host FastAPI app, handed over by ``get_mcp_app``: a proactive-settings save
# re-registers the jobs on its running scheduler, exactly like the Settings card.
_HOST_APP = None


@mcp.tool()
async def set_proactive_settings(
    brief_time: Optional[str] = None,
    evening_time: Optional[str] = None,
    skincare_morning_time: Optional[str] = None,
    skincare_evening_time: Optional[str] = None,
    quiet_start: Optional[str] = None,
    quiet_end: Optional[str] = None,
    daily_budget: Optional[int] = None,
    nudges: Optional[dict] = None,
    garmin_sync_hours: Optional[int] = None,
    garmin_weight_export_minutes: Optional[int] = None,
    garmin_weight_max_age_days: Optional[int] = None,
    pulse_seconds: Optional[int] = None,
    pulse_start_hour: Optional[int] = None,
    pulse_end_hour: Optional[int] = None,
) -> dict:
    """Changes how the Telegram bot behaves — the Notifications card in Settings,
    applied the same way (the scheduler is re-timed at once, no restart). Only
    the fields you pass change; read the current values with
    ``get_proactive_state``.

    Times are HH:MM local: ``brief_time`` (morning brief), ``evening_time``
    (evening block), ``skincare_morning_time`` / ``skincare_evening_time`` (the
    skincare checklist messages), ``quiet_start``–``quiet_end`` (no self-initiated
    messages). ``daily_budget`` caps self-initiated messages a day (1–12).
    ``nudges`` switches categories on/off, e.g. ``{"activity": false,
    "skincare": true}`` — categories: activity, nutrition, data, environment,
    skincare (only those you name change). Data freshness: ``garmin_sync_hours``
    (1–24), ``pulse_seconds`` (60–3600, 0 = light pulse off) within
    ``pulse_start_hour``–``pulse_end_hour``; Garmin weight export cadence
    ``garmin_weight_export_minutes`` (5–1440) and ``garmin_weight_max_age_days``
    (1–30). Out-of-range values are clamped, as in the app — ``adjusted: true``
    says the stored result differs from what was asked. Switching the whole bot
    off is the signals module (``set_module("signals", False)``). WRITE tool."""
    from vitals.services.proactive import prefs
    from web.api.settings import apply_schedule

    current = await _proactive_current()
    raw = dict(current)
    given = False
    for key, value in {
        "brief_time": brief_time, "evening_time": evening_time,
        "skincare_morning_time": skincare_morning_time,
        "skincare_evening_time": skincare_evening_time,
        "quiet_start": quiet_start, "quiet_end": quiet_end, "daily_budget": daily_budget,
        "garmin_sync_hours": garmin_sync_hours,
        "garmin_weight_export_minutes": garmin_weight_export_minutes,
        "garmin_weight_max_age_days": garmin_weight_max_age_days,
        "pulse_seconds": pulse_seconds, "pulse_start_hour": pulse_start_hour,
        "pulse_end_hour": pulse_end_hour,
    }.items():
        if value is not None:
            raw[key] = value
            given = True
    if nudges is not None:
        given = True
        unknown = sorted(set(nudges) - set(prefs.NUDGE_CATEGORIES))
        if unknown:
            return {"error": f"unknown nudge categories {unknown} — use {', '.join(prefs.NUDGE_CATEGORIES)}"}
        raw["nudges"] = {**current["nudges"], **{k: bool(v) for k, v in nudges.items()}}
    if not given:
        return {"error": "nothing to change — pass at least one field"}

    session_factory = get_session_factory()
    async with session_factory() as session:
        settings = await prefs.set_prefs(session, raw)
        await session.commit()
    if _HOST_APP is not None:
        apply_schedule(_HOST_APP, settings)
    return {"prefs": settings, "adjusted": raw != settings}


async def _proactive_current() -> dict:
    from vitals.services.proactive import prefs

    session_factory = get_session_factory()
    async with session_factory() as session:
        return await prefs.get_prefs(session)


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
    if summary.get("error") == garmin_service.SYNC_BUSY:
        return {"error": "A Garmin sync is already running — try again in a few minutes"}
    return summary


@mcp.tool()
@gated("hevy")
async def sync_hevy() -> dict:
    """Pulls the latest Hevy workouts now. Same rules as ``sync_garmin``: for a gap
    in the data, not for routine reads (the scheduler syncs every 6 hours), capped
    at 3 calls a day. Reads only what changed in Hevy since the last good sync (the
    first one reads the whole history). Returns ``{fetched, created, updated,
    deleted, skipped, full, total}`` — ``deleted`` counts workouts removed here
    because they were deleted in Hevy, ``total`` the workouts held afterwards."""
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
async def get_environment_vs_sleep(
    start_date: Optional[str] = None, end_date: Optional[str] = None
) -> dict:
    """One row per night (the date you woke up; YYYY-MM-DD, both ends inclusive,
    default the last 14, max 31): the bedroom's air — coverage_pct, CO2
    median/p90/max, minutes at or above the warn line, temperature range, mean
    humidity — next to that night's Garmin sleep: score, total/deep/REM minutes,
    awakenings, HRV, resting and sleeping HR, respiration. ``columns`` names the
    ``rows``; a missing side is null. Below 80% coverage the air numbers describe
    only part of the night. Same-night co-occurrence, not cause. Read-only."""
    from vitals.services import environment_context

    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")
    session_factory = get_session_factory()
    async with session_factory() as session:
        return await environment_context.nights_with_sleep(session, start=start, end=end)


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


@mcp.tool()
@gated("environment")
async def get_environment_settings() -> dict:
    """Returns the bedroom station's settings as the owner set them: the CO2
    zones (good < ``co2_ok_max`` ≤ ok < ``co2_warn`` ≤ warn < ``co2_bad`` ≤ bad,
    ppm), the day comfort and sleeping temperature ranges (°C), the humidity
    comfort band and the wider alert band (%), the ``night_window`` the night
    summaries use, and whether alerts fire at all (``alerts_enabled``) and go to
    Telegram (``alert_telegram``). Read-only; change with
    ``set_environment_settings``."""
    from vitals.services.environment import settings as env_settings

    session_factory = get_session_factory()
    async with session_factory() as session:
        return (await env_settings.get_settings(session)).to_dict()


@mcp.tool()
@gated("environment")
async def set_environment_settings(
    co2_ok_max: Optional[int] = None,
    co2_warn: Optional[int] = None,
    co2_bad: Optional[int] = None,
    temp_day_min: Optional[float] = None,
    temp_day_max: Optional[float] = None,
    temp_sleep_min: Optional[float] = None,
    temp_sleep_max: Optional[float] = None,
    rh_min: Optional[float] = None,
    rh_max: Optional[float] = None,
    rh_alert_low: Optional[float] = None,
    rh_alert_high: Optional[float] = None,
    night_start: Optional[str] = None,
    night_end: Optional[str] = None,
    alerts_enabled: Optional[bool] = None,
    alert_telegram: Optional[bool] = None,
) -> dict:
    """Changes the bedroom station's thresholds and alert switches — the
    station card in Settings. Only the fields you pass change (see
    ``get_environment_settings`` for their meaning; ``night_start`` /
    ``night_end`` are HH:MM). As in the app, out-of-range values are clamped and
    the zones kept in order (CO2 400–5000 ppm, temperature −10…45 °C, humidity
    0–100 %) rather than rejected — the result is what was actually stored.
    WRITE tool."""
    from vitals.services.environment import settings as env_settings

    patch = {k: v for k, v in {
        "co2_ok_max": co2_ok_max, "co2_warn": co2_warn, "co2_bad": co2_bad,
        "temp_day_min": temp_day_min, "temp_day_max": temp_day_max,
        "temp_sleep_min": temp_sleep_min, "temp_sleep_max": temp_sleep_max,
        "rh_min": rh_min, "rh_max": rh_max,
        "rh_alert_low": rh_alert_low, "rh_alert_high": rh_alert_high,
        "alerts_enabled": alerts_enabled, "alert_telegram": alert_telegram,
    }.items() if v is not None}
    window = {k: v for k, v in {"start": night_start, "end": night_end}.items() if v is not None}
    if window:
        patch["night_window"] = window
    if not patch:
        return {"error": "nothing to change — pass at least one field"}

    session_factory = get_session_factory()
    async with session_factory() as session:
        saved = await env_settings.set_settings(session, patch)
        await session.commit()
        return saved.to_dict()


# ── The Today screen ──────────────────────────────────────────────────────────
def _jsonable(value):
    """Dates, times and nested containers → plain JSON values."""
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, datetime):
        return format_iso(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


async def _enrich_sync_rows(session, sync_rows: list[dict], redis=None) -> list[dict]:
    """Enrich sync rows with separate last_data_date and last_sync_at fields (Convention C4)."""
    enriched = []
    for s in sync_rows:
        source = s.get("source")
        d = s.get("date")
        d_iso = d.isoformat() if hasattr(d, "isoformat") else str(d)
        last_sync = None
        if redis is not None:
            try:
                raw_ts = await redis.get(f"sync:last_success:{source.lower()}")
                if raw_ts:
                    from datetime import timezone
                    ts = datetime.fromtimestamp(int(raw_ts), tz=timezone.utc)
                    last_sync = format_iso(ts)
            except Exception:
                pass
        if last_sync is None:
            if source == "Garmin":
                max_updated = (await session.execute(select(func.max(GarminDaily.updated_at)))).scalar()
                if max_updated:
                    last_sync = format_iso(max_updated, is_utc=True)
            elif source == "Hevy":
                max_updated = (await session.execute(select(func.max(HevyWorkout.updated_at)))).scalar()
                if max_updated:
                    last_sync = format_iso(max_updated, is_utc=True)
        enriched.append({
            "source": source,
            "date": d,
            "last_data_date": d_iso,
            "last_sync_at": last_sync,
        })
    return enriched


@mcp.tool()
async def get_today() -> dict:
    """The app's Today screen as data — the same assembly the owner opens the app
    on: ``narrative`` (the morning brief's paragraph, or a computed sentence when
    there is none yet — ``narrative_source`` says which), ``figures`` (weight with
    its weekly trend, sleep score, HRV, Body Battery against the personal corridor,
    today's calories when nutrition is on), ``changes`` (this week vs last),
    ``feed`` (today's meals, signals, events, weigh-in), ``attention`` (active
    alerts and the recovery advice, most severe first), ``goal`` (the active goal
    with its forecast), and ``sync`` (when each source last delivered). Switched
    off modules contribute nothing, as on the screen. Use it for "как я сегодня" /
    "что у меня на сегодня" before drilling into a domain. READ tool."""
    from vitals.services import modules_service, today_service

    session_factory = get_session_factory()
    try:
        redis = get_redis_client()
    except Exception:
        redis = None
    async with session_factory() as session:
        enabled = await modules_service.get_enabled_modules(session)
        data = await today_service.collect(session, enabled_modules=enabled, weigh_ins=True)
        data["sync"] = await _enrich_sync_rows(session, data.get("sync") or [], redis=redis)
        return _jsonable(data)


# ── Doctor reports (shared links) ─────────────────────────────────────────────
@mcp.tool()
async def get_shared_reports() -> dict:
    """Lists the doctor reports the owner has published — the Share screen: each
    with ``id``, ``title``, ``domains``, the period, ``state`` (live / expired /
    revoked), ``expires_at``, how many times it was opened and when last, and its
    ``url`` (a path on the owner's Vitals host; the visitor also needs the
    password, which is shown only once, at creation, and is not stored). Also
    ``available_domains``, ``presets``, ``period_choices`` and ``expiry_choices``
    for ``create_shared_report``. READ tool."""
    from vitals.services import modules_service, share_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        enabled = await modules_service.get_enabled_modules(session)
        data = await share_service.collect(session, enabled)
        for r in data["reports"]:
            r.pop("token", None)  # the url carries it; once is enough
        return data


@mcp.tool()
async def create_shared_report(
    title: str,
    domains: Optional[list[str]] = None,
    preset: Optional[str] = None,
    period: str = "90",
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
    expires_days: int = 30,
    labs_flagged_only: bool = False,
    note: Optional[str] = None,
) -> dict:
    """Publishes a doctor report — a frozen, password-protected page with the
    chosen domains for a period, exactly like "New report" on the Share screen.
    OUTWARD-FACING: anyone holding the link and the password can read that
    medical data until it expires or is revoked. Create one only when the owner
    explicitly asks for it.

    ``domains`` from ``get_shared_reports().available_domains``, or a ``preset``
    from its ``presets`` instead. ``period`` is a number of days back ("30",
    "90", "180"), "all", or "custom" with ``period_start``/``period_end``
    (YYYY-MM-DD). ``expires_days`` — link lifetime (7, 30, 90).
    ``labs_flagged_only`` keeps only out-of-range lab results.

    Returns the ``url`` path and the ``password`` — the password exists only in
    this answer (only its hash is stored): give both to the owner right away.
    WRITE tool."""
    from vitals.i18n import t
    from vitals.services import modules_service, share_service

    title = (title or "").strip()
    if not title:
        return {"error": "title is required"}

    session_factory = get_session_factory()
    async with session_factory() as session:
        enabled = await modules_service.get_enabled_modules(session)
        wanted = list(domains or [])
        if preset:
            spec = share_service.PRESETS.get(preset)
            if spec is None:
                return {"error": f"unknown preset '{preset}' — use {', '.join(share_service.PRESETS)}"}
            wanted += list(spec["domains"])
            labs_flagged_only = labs_flagged_only or spec["labs_flagged_only"]
        chosen = share_service.resolve_domains(wanted, enabled)
        if not chosen:
            return {
                "error": "at least one available domain is required — choose from "
                + ", ".join(share_service.available_domains(enabled))
            }
        try:
            start, end = await share_service.resolve_period(
                session, period, period_start, period_end
            )
        except ValueError as e:
            return {"error": str(e)}
        row, password = await share_service.create_report(
            session, title=title, domains=chosen, period_start=start, period_end=end,
            expires_days=expires_days, note=note, labs_flagged_only=labs_flagged_only,
            preset=preset, enabled=enabled,
        )
        if not (row.snapshot or {}).get("blocks"):
            await session.rollback()
            return {"error": t("share.error.empty")}
        await session.commit()
        return {
            "id": row.id,
            "url": f"/r/{row.token}",
            "password": password,
            "domains": chosen,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "expires_at": format_iso(row.expires_at),
        }


@mcp.tool()
async def revoke_shared_report(report_id: int) -> dict:
    """Kills a doctor report's link now — it stops opening for anyone and its
    frozen copy of the data is erased; the record of what was shared, with whom
    and when stays on the Share screen. Irreversible: a revoked link can't be
    revived (publish a new one instead). To also remove the record use
    ``delete_record("shared_report", id)``. WRITE tool."""
    from vitals.services import share_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        row = await share_service.get_report(session, report_id)
        if row is None:
            return {"error": f"Shared report {report_id} not found"}
        if row.revoked_at is not None:
            return {"error": f"Shared report {report_id} is already revoked"}
        await share_service.revoke(session, report_id)
        await session.commit()
        return {"revoked": True, "id": report_id}


# ── Saved charts (the Charts screen) ──────────────────────────────────────────
@mcp.tool()
async def get_saved_charts(
    chart_id: Optional[str] = None, include_catalog: bool = False
) -> dict:
    """The owner's saved charts from the Charts screen. Without ``chart_id``:
    every chart's configuration — ``id``, ``name``, ``normalize`` and its
    ``series`` (``metric_key``, ``param``, ``label``). With ``chart_id``: that
    chart with its data resolved — each series' points ``{date, value}`` as the
    screen draws them, plus the timeline flags laid over it. ``include_catalog``
    adds the metric catalog (every ``metric_key`` a chart can plot, with the
    ``param`` it needs) — what ``create_saved_chart`` takes. READ tool."""
    from vitals.services import (
        chart_data_service, charts_service, custom_charts_service, language_service,
        modules_service,
    )

    redis = _redis_or_none()
    session_factory = get_session_factory()
    async with session_factory() as session:
        enabled = await modules_service.get_enabled_modules(session)
        lang = await language_service.get_language(session, redis)
        result: dict = {}
        if chart_id is None:
            result["charts"] = await custom_charts_service.list_charts(session, redis)
        else:
            chart = await custom_charts_service.get_chart(session, chart_id, redis)
            if chart is None:
                return {"error": f"Chart '{chart_id}' not found"}
            overlays = await charts_service._overlays_by_chart(
                session, [chart], with_supplements=bool(enabled.get("supplements"))
            ) if enabled.get("timeline") else {}
            result["chart"] = {
                "id": chart["id"],
                "name": chart["name"],
                "normalize": chart.get("normalize", False),
                "series": await chart_data_service.resolve_chart_series(session, chart, lang=lang),
                "overlays": overlays.get(chart["id"], []),
            }
        if include_catalog:
            result["catalog"] = await chart_data_service.build_catalog(session, enabled, lang=lang)
        return result


def _redis_or_none():
    """The shared Redis client, or ``None`` — the caches it serves only accelerate."""
    try:
        return get_redis_client()
    except Exception:
        return None


@mcp.tool()
async def create_saved_chart(
    name: str, series: list[dict], normalize: bool = False
) -> dict:
    """Saves a new chart on the Charts screen. ``series`` is 1–8 items of
    ``{"metric_key": str, "param": str?, "label": str?}`` — keys from
    ``get_saved_charts(include_catalog=True)`` (or the ``get_trend`` registry,
    e.g. ``weight.weight_kg``, ``garmin.hrv_avg``; ``labs.marker`` needs
    ``param`` = marker name). ``normalize=True`` draws every series on a shared
    0–100 scale, for comparing shapes of different units. WRITE tool."""
    from vitals.services import custom_charts_service
    from vitals.services.analytics import chart_registry

    clean = []
    for s in series or []:
        if not isinstance(s, dict) or not s.get("metric_key"):
            return {"error": "every series needs a metric_key"}
        try:
            domain = chart_registry.get(s["metric_key"]).domain
        except KeyError:
            return {"error": f"unknown metric_key '{s['metric_key']}'"}
        clean.append({
            "domain": s.get("domain") or domain, "metric_key": s["metric_key"],
            "param": s.get("param"), "label": s.get("label"),
        })

    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            chart = await custom_charts_service.create_chart(
                session, name=name, series=clean, normalize=normalize, redis=_redis_or_none()
            )
        except custom_charts_service.ChartConfigError as e:
            return {"error": str(e)}
        await session.commit()
        return chart


@mcp.tool()
async def delete_saved_chart(chart_id: str) -> dict:
    """Deletes a saved chart from the Charts screen (only the chart — the data it
    plots is untouched). Permanent. WRITE tool."""
    from vitals.services import custom_charts_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        ok = await custom_charts_service.delete_chart(session, chart_id, redis=_redis_or_none())
        await session.commit()
        return {"deleted": ok, "chart_id": chart_id}


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
    "get_skincare_routine": "skincare",
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


def get_mcp_app(host_app=None) -> tuple[object, object]:
    """Wraps the FastMCP Starlette app with Bearer authorization middleware.

    Returns ``(app, lifespan)``. Streamable HTTP builds its session manager inside
    the lifespan, and ``app.mount()`` does not run a sub-app's lifespan — so the
    caller must enter it explicitly or every request fails with "manager not
    initialized". See web/main.py. ``host_app`` is the app it is mounted on, for
    the tools that act on it (re-timing the scheduler).
    """
    from web.config import get_web_config

    global _HOST_APP
    _HOST_APP = host_app
    cfg = get_web_config()
    # Streamable HTTP (the SSE transport is deprecated in the MCP spec since
    # 2025-03). path="/" so that mounting on /mcp lands the endpoint on /mcp/
    # rather than /mcp/mcp — the library's own default path would be appended.
    raw_app = mcp.http_app(transport="http", path="/")
    return MCPAuthMiddleware(raw_app, client_id=cfg.mcp_client_id), raw_app.router.lifespan_context
