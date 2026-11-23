"""Cross-domain reads: Today, snapshot, export, coverage and trends."""
from __future__ import annotations

from datetime import date as date_type, datetime, timedelta
from typing import Optional

from sqlalchemy import func, select

from vitals.models import (
    Annotation, BodyMeasurement, BodyScan, DayContext, DosePhase, EnvironmentHourly,
    EnvironmentSample, GarminActivity, GarminDaily, GarminIntraday, GeneticVariant,
    HevyWorkout, HrtCycle, HrtDose, HrtSideEffect, Injection, LabResult,
    MealLog, Milestone, NoiseMarker, ProgressPhoto, SideEffect, Signal, SkincareCheck,
    SkincareLog, SkincareObservation, SkincarePhoto, SkincareProduct, Supplement,
    WeightLog, WeeklyDigest,
)
from vitals.services import modules_service
from vitals.utils.timeutils import format_iso, today_local
from web.routers.mcp._core import (
    READ, _parse_date, get_redis_client, get_session_factory, dispatch, tool,
)

# ── Cross-domain + whole-lake tools ──────────────────────────────────────────
DEFAULT_SNAPSHOT_SECTIONS = frozenset({"weight", "garmin", "nutrition", "hevy", "alerts", "glp1"})
ALL_OPTIONAL_SNAPSHOT_SECTIONS = frozenset({
    "labs", "body_comp", "genetics", "supplements", "skincare", "hrt",
    "signals", "milestones", "timeline", "environment",
})


@tool(READ)
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


async def export_everything(
    domains: Optional[list[str]] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> dict:
    """Returns the health history as one compact, secret-free, LLM-ready export
    grouped by domain (weight, measurements, body scans, GLP-1, HRT, labs, Garmin,
    workouts, nutrition, skincare, supplements, genetics, signals, day context,
    milestones, timeline, and the bedroom's air as ``environment_nights`` —
    one summary per night — and ``environment_hours``, the hourly means as
    parallel arrays per day). This is the way to read long-term history in a single
    call rather than paging each domain's newest-100 read tool. Read-only.

    WARNING: Heavy response payload. Do NOT call this tool 'just in case' or for
    casual status queries; use ``get_data_overview``, ``get_today``, or domain-specific
    query tools instead. Data is returned directly in the response payload (not written
    to disk).

    Defaults to the **last 90 days**: the whole lake is years of daily Garmin rows
    with per-minute sleep and would fill the conversation before the question is
    asked. Widen or slice deliberately — ``since="2020-01-01"`` (any early date)
    for the entire history, ``since`` + ``until`` (both inclusive ``YYYY-MM-DD``)
    for an exact period, and/or ``domains=["biomarkers", "weight_history"]`` to
    pull a couple of areas in full instead of everything. Unknown domain names are
    rejected with the list of valid ones."""
    from vitals.services import data_portability_service

    end = _parse_date(until, None, field="until")
    anchor = end or today_local()
    default_since = anchor - timedelta(days=EXPORT_DEFAULT_DAYS)
    cutoff = _parse_date(since, default_since, field="since")

    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            return await data_portability_service.export_llm(
                session, domains=domains, since=cutoff, until=end
            )
        except ValueError as e:
            return {"error": str(e)}


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
            stmt = select(*cols)
            if name == "weekly_digests":
                from vitals.enums import DigestKind
                stmt = stmt.where(model.kind == DigestKind.WEEKLY.value)
            row = (await session.execute(stmt)).one()
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


# ── Trend analytics ───────────────────────────────────────────────────────────
@tool(READ)
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


def _clean_today_for_mcp(data: dict) -> dict:
    """Trim empty boilerplate and null fields from today figures and feed (Convention C5, Item 18/19)."""
    if "figures" in data and isinstance(data["figures"], list):
        cleaned_figures = []
        for f in data["figures"]:
            c = {}
            for k, v in f.items():
                if k == "value":
                    c[k] = v
                elif v is not None and v != "":
                    c[k] = v
            if c.get("key") == "weight" and c.get("trend") is not None:
                c["trend_unit"] = "kg/week"
            cleaned_figures.append(c)
        data["figures"] = cleaned_figures

    if "feed" in data and isinstance(data["feed"], list):
        cleaned_feed = []
        for item in data["feed"]:
            if item.get("kind") == "brief" and not item.get("text") and item.get("value") is None:
                continue
            c = {}
            for k, v in item.items():
                if v is not None and v != "":
                    c[k] = v
                elif k == "value" and v is not None:
                    c[k] = v
            cleaned_feed.append(c)
        data["feed"] = cleaned_feed

    return data


@tool(READ)
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
    from vitals.i18n import current_lang
    from vitals.services import language_service, today_service

    session_factory = get_session_factory()
    try:
        redis = get_redis_client()
    except Exception:
        redis = None
    async with session_factory() as session:
        current_lang.set(await language_service.get_language(session, redis))
        enabled = await modules_service.get_enabled_modules(session)
        data = await today_service.collect(session, enabled_modules=enabled, weigh_ins=True)
        data = _clean_today_for_mcp(data)
        data["sync"] = await _enrich_sync_rows(session, data.get("sync") or [], redis=redis)
        return _jsonable(data)


# ── Consolidated overview / export tool ──────────────────────────────────────
_EXPORT_MODES = {
    ("overview", False): (get_data_overview, None),
    ("export", False): (export_everything, None),
}


@tool(READ)
async def export_data(
    mode: str = "overview",
    domains: Optional[list[str]] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> dict:
    """Data coverage map or full LLM-ready export.

    ``mode``:
      * ``overview`` (default) — per-domain row count, earliest/latest date and
        last-updated timestamp. Call this first to orient before querying a
        domain, so you don't page blindly through empty windows.
      * ``export`` — compact, secret-free health history grouped by domain for
        long-term cross-domain analysis. WARNING: heavy payload — do NOT call
        for casual status checks (use ``get_today`` or ``get_full_snapshot``).
        Defaults to the last 90 days; pass ``since``/``until`` (YYYY-MM-DD, both
        inclusive) and/or ``domains=[...]`` to slice deliberately."""
    args = dict(domains=domains, since=since, until=until)
    return await dispatch("export_data", "mode", mode, _EXPORT_MODES, args)
