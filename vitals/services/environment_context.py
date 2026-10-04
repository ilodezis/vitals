"""What the environment domain hands to the surfaces that read the whole lake: the
MCP tools, the AI digest and the exports.

The storage layer (``services/environment``) answers in its own result types, with
instants in UTC. A model reading the answer has none of that context and reasons in
the owner's wall clock, so everything leaving here is shaped for a reader: local
times, nulls pruned, numbers rounded to what a sensor can claim, and any cut made
to keep an answer small said out loud (``truncated`` plus how to ask for the rest).

One place for it, so the same night reads the same number in a tool call, in the
weekly report and in an export.
"""
from __future__ import annotations

import logging
from datetime import date as date_type
from datetime import datetime, time as time_type, timedelta
from typing import Any, Optional, Sequence

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.config import load_config
from vitals.enums import Domain
from vitals.models import SystemAlert
from vitals.models.environment import EnvironmentHourly, EnvironmentSample
from vitals.services.environment import live as env_live
from vitals.services.environment import queries
from vitals.services.environment import settings as env_settings
from vitals.services.environment.queries import DEFAULT_STATION
from vitals.services.environment.types import LiveState, NightSummary
from vitals.utils import timeutils

logger = logging.getLogger(__name__)

# Nights a report carries — the current period and the one before it.
NIGHTS_LIMIT = 62

# How far one history call may reach, by granularity (days), and how many points.
HISTORY_DAYS = {"hour": 31, "minute": 2}
HISTORY_DEFAULT_DAYS = {"hour": 7, "minute": 1}
MAX_POINTS = 3000

ALERT_HOURS_MAX = 168


# ── shaping ──────────────────────────────────────────────────────────────────


def prune(value: Any) -> Any:
    """Drop nulls and groups that end up empty — an absent field is cheaper to read
    than a null, and says the same. Zero and the empty string are values."""
    if isinstance(value, dict):
        cleaned = {k: prune(v) for k, v in value.items()}
        return {k: v for k, v in cleaned.items() if v is not None and v != {}}
    if isinstance(value, list):
        return [prune(v) for v in value]
    return value


def _int(value: Optional[float]) -> Optional[int]:
    return None if value is None else int(round(value))


def _r1(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 1)


def _local_iso(value: Optional[datetime], *, seconds: bool = False) -> Optional[str]:
    if value is None:
        return None
    return timeutils.to_local_naive(value).isoformat(timespec="seconds" if seconds else "minutes")


def _timezone() -> str:
    return load_config().timezone


def _local_midnight_utc(day: date_type) -> datetime:
    return timeutils.local_naive_to_utc(datetime.combine(day, time_type.min))


def night_thresholds(settings: env_settings.EnvSettings) -> dict[str, Any]:
    """The owner's own lines a night is read against."""
    full = settings.thresholds_dict()
    keys = ("co2_ok_max", "co2_warn", "co2_bad", "temp_sleep_min", "temp_sleep_max", "rh_min", "rh_max")
    return {k: full[k] for k in keys}


def night_dict(summary: NightSummary) -> dict[str, Any]:
    """One night as the surfaces show it. A night with no readings is just its date,
    window and a zero — not a column of zeros that reads as a measured, clean night."""
    window = {"start": _local_iso(summary.window.start), "end": _local_iso(summary.window.end)}
    if not summary.samples:
        return {"date": summary.date.isoformat(), "window": window, "samples": 0}

    def spread(r) -> dict[str, Any]:
        return {"min": _r1(r.min), "mean": _r1(r.mean), "max": _r1(r.max)}

    return prune({
        "date": summary.date.isoformat(),
        "window": window,
        "samples": summary.samples,
        "coverage_pct": _r1(summary.coverage_pct),
        "co2": {
            "median": _int(summary.co2.median),
            "p90": _int(summary.co2.p90),
            "max": _int(summary.co2.max),
            "minutes_above_warn": _r1(summary.co2.minutes_above_warn),
            "minutes_above_bad": _r1(summary.co2.minutes_above_bad),
        },
        "temperature": spread(summary.temperature),
        "humidity": spread(summary.humidity),
    })


# ── live ─────────────────────────────────────────────────────────────────────


async def live_view(session: AsyncSession, redis=None) -> dict[str, Any]:
    prefs = await env_settings.get_settings(session)
    try:
        state = await env_live.get_live(session, redis)
    except Exception:
        # The cache is an accelerator, not the source of truth: with it down the
        # database still knows the latest reading.
        if redis is None:
            raise
        logger.warning("environment: live cache unavailable; reading the database", exc_info=True)
        state = await env_live.get_live(session, None)

    state = state or LiveState()
    station = state.to_dict()["station"]
    station["last_seen_at"] = _local_iso(state.station.last_seen_at, seconds=True)
    return {
        **prune({"station": station, "now": state.to_dict()["now"]}),
        "thresholds": prefs.thresholds_dict(),
        "timezone": _timezone(),
    }


# ── history ──────────────────────────────────────────────────────────────────


async def history_view(
    session: AsyncSession,
    *,
    start: Optional[date_type],
    end: Optional[date_type],
    granularity: str,
    limit: int,
) -> dict[str, Any]:
    """Hourly or per-minute means for whole local days (both ends inclusive).

    Raw 10-second samples are not exposed: a day of them is 8640 rows and nothing a
    conversation needs. A window or a point count beyond what an answer should carry
    is cut to its *first* part and reported — ``truncated`` with a hint — never
    silently shortened.
    """
    if granularity not in HISTORY_DAYS:
        return {"error": f"granularity must be 'hour' or 'minute', got {granularity!r} (raw samples are not exposed)"}

    end = end or timeutils.today_local()
    start = start or end - timedelta(days=HISTORY_DEFAULT_DAYS[granularity] - 1)
    if start > end:
        return {"error": "start_date is after end_date"}

    hints: list[str] = []
    max_days = HISTORY_DAYS[granularity]
    if (end - start).days + 1 > max_days:
        end = start + timedelta(days=max_days - 1)
        hints.append(
            f"{granularity} granularity covers at most {max_days} days: the window was cut to its "
            f"first {max_days} — call again with a later start_date for the rest."
        )

    limit = max(1, min(int(limit), MAX_POINTS))
    start_utc, end_utc = _local_midnight_utc(start), _local_midnight_utc(end + timedelta(days=1))

    prefs = await env_settings.get_settings(session)
    points = list(await queries.series(session, start_utc, end_utc, resolution=granularity))
    available = len(points)
    if available > limit:
        points = points[:limit]
        hints.append(
            f"Returned the first {limit} of {available} points — narrow start_date/end_date or raise "
            f"limit (max {MAX_POINTS})."
        )

    columns, rows = _columnar(points, granularity)
    out: dict[str, Any] = {
        "granularity": granularity,
        "timezone": _timezone(),
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "columns": columns,
        "rows": rows,
        "count": len(rows),
        "coverage_pct": _r1(await queries.coverage_pct(session, start_utc, end_utc)),
        "truncated": bool(hints),
        "thresholds": prefs.thresholds_dict(),
    }
    if available > len(rows):
        out["available"] = available
    if hints:
        out["hint"] = " ".join(hints)
    return out


def _columnar(points: Sequence, granularity: str) -> tuple[list[str], list[list[Any]]]:
    """Points as a header plus rows: the same fields as objects would repeat their
    names a thousand times. Optional columns (an hour's CO2 extremes, light) appear
    only when something filled them."""
    spec: list[tuple[str, Any, bool]] = [
        ("ts", lambda p: _local_iso(p.ts), True),
        ("co2_ppm", lambda p: _int(p.co2_ppm), True),
        ("co2_max", lambda p: _int(p.co2_max), granularity == "hour"),
        ("co2_min", lambda p: _int(p.co2_min), granularity == "hour"),
        ("temperature_c", lambda p: _r1(p.temperature_c), True),
        ("humidity_pct", lambda p: _r1(p.humidity_pct), True),
        ("lux", lambda p: _r1(p.lux), False),
    ]
    core = {"ts", "co2_ppm", "temperature_c", "humidity_pct"}
    table = [[get(p) for _, get, _ in spec] for p in points]
    keep = [
        i for i, (name, _, wanted) in enumerate(spec)
        if wanted and (name in core or any(row[i] is not None for row in table))
        or (not wanted and any(row[i] is not None for row in table))
    ]
    return [spec[i][0] for i in keep], [[row[i] for i in keep] for row in table]


# ── nights ───────────────────────────────────────────────────────────────────


async def night_view(session: AsyncSession, on_date: date_type) -> dict[str, Any]:
    prefs = await env_settings.get_settings(session)
    summary = await queries.night_summary(session, on_date)
    out = {**night_dict(summary), "thresholds": night_thresholds(prefs), "timezone": _timezone()}
    if not summary.samples:
        out["note"] = "No station readings for this night window."
    return out


async def nights(
    session: AsyncSession,
    start: Optional[date_type],
    end: Optional[date_type],
    *,
    limit: Optional[int] = NIGHTS_LIMIT,
    station_id: str = DEFAULT_STATION,
) -> tuple[list[NightSummary], bool]:
    """Summaries of the nights between ``start`` and ``end`` (either may be open)
    that have station data, oldest first. With more than ``limit``, the newest are
    kept and the second element says so."""
    stmt = (
        select(EnvironmentSample.date)
        .where(EnvironmentSample.station_id == station_id)
        .distinct()
        .order_by(EnvironmentSample.date)
    )
    if start is not None:
        stmt = stmt.where(EnvironmentSample.date >= start)
    if end is not None:
        stmt = stmt.where(EnvironmentSample.date <= end)
    days = list((await session.execute(stmt)).scalars().all())

    truncated = limit is not None and len(days) > limit
    if truncated:
        days = days[-limit:]
    found: list[NightSummary] = []
    for day in days:
        summary = await queries.night_summary(session, day, station_id=station_id)
        # A date with samples only in the afternoon has no night to report.
        if summary.samples:
            found.append(summary)
    return found, truncated


# ── hours (exports) ──────────────────────────────────────────────────────────


async def hours_by_day(
    session: AsyncSession,
    start: Optional[date_type],
    end: Optional[date_type],
    *,
    station_id: str = DEFAULT_STATION,
) -> list[dict[str, Any]]:
    """The hourly rollup as one entry per local day, the hours as parallel arrays.

    A row per hour repeats its field names 24 times a day; ninety days of that is
    longer than everything else in an export together. ``hours`` labels the arrays
    (local hour), and keeps a repeated label on the day the clocks go back rather
    than guessing which one a reader meant.
    """
    stmt = (
        select(EnvironmentHourly)
        .where(EnvironmentHourly.station_id == station_id)
        .order_by(EnvironmentHourly.hour_start)
    )
    if start is not None:
        stmt = stmt.where(EnvironmentHourly.date >= start)
    if end is not None:
        stmt = stmt.where(EnvironmentHourly.date <= end)

    days: dict[date_type, dict[str, Any]] = {}
    for row in (await session.execute(stmt)).scalars().all():
        day = days.setdefault(row.date, {
            "date": row.date.isoformat(), "hours": [], "coverage_pct": [], "co2_mean": [],
            "co2_max": [], "temperature_mean": [], "humidity_mean": [],
        })
        day["hours"].append(f"{timeutils.to_local_naive(row.hour_start).hour:02d}")
        day["coverage_pct"].append(_int(row.coverage_pct))
        day["co2_mean"].append(_int(row.co2_mean))
        day["co2_max"].append(_int(row.co2_max))
        day["temperature_mean"].append(_r1(row.temp_mean))
        day["humidity_mean"].append(_r1(row.rh_mean))
    return list(days.values())


async def export_blocks(
    session: AsyncSession,
    *,
    since: Optional[date_type],
    blocks: Sequence[str] = ("environment_nights", "environment_hours"),
) -> dict[str, list]:
    """The export's environment blocks, only the ones asked for — the nights are a
    query each and not worth running for a caller who wanted the hours."""
    out: dict[str, list] = {}
    if "environment_nights" in blocks:
        found, _ = await nights(session, since, None, limit=None)
        out["environment_nights"] = [night_dict(n) for n in found]
    if "environment_hours" in blocks:
        out["environment_hours"] = await hours_by_day(session, since, None)
    return out


# ── alerts ───────────────────────────────────────────────────────────────────

# Which reading an alert is about, found from its key so the view does not depend on
# how the rules spell their prefix: (column, name in the answer, wants the maximum).
def _peak_spec(key: str):
    k = key.lower()
    if "co2" in k:
        return EnvironmentSample.co2_ppm, "co2_ppm", True
    if "temp" in k:
        return EnvironmentSample.temperature_c, "temperature_c", "low" not in k
    if "rh" in k or "humid" in k:
        return EnvironmentSample.humidity_pct, "humidity_pct", "low" not in k
    return None


async def _peak(session: AsyncSession, key: str, start: datetime, end: datetime, station_id: str):
    spec = _peak_spec(key)
    if spec is None:
        return None
    column, metric, highest = spec
    row = (
        await session.execute(
            select(EnvironmentSample.ts, column)
            .where(
                EnvironmentSample.station_id == station_id,
                EnvironmentSample.ts >= timeutils.local_naive_to_utc(start),
                EnvironmentSample.ts <= timeutils.local_naive_to_utc(end),
                column.is_not(None),
            )
            .order_by(column.desc() if highest else column.asc(), EnvironmentSample.ts)
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    value = _int(row[1]) if metric == "co2_ppm" else _r1(row[1])
    return {"metric": metric, "value": value, "at": _local_iso(row[0], seconds=True)}


async def alerts_view(
    session: AsyncSession,
    *,
    hours: int = 24,
    now: Optional[datetime] = None,
    station_id: str = DEFAULT_STATION,
) -> dict[str, Any]:
    """The environment alerts that were open at any point in the last ``hours``:
    when each started and ended and how far the reading went. The peak is read off
    the samples of the episode, so it does not depend on the wording of a message."""
    hours = max(1, min(int(hours), ALERT_HOURS_MAX))
    now = now or timeutils.now_local()
    since = now - timedelta(hours=hours)

    rows = (
        await session.execute(
            select(SystemAlert)
            .where(
                SystemAlert.domain == Domain.ENVIRONMENT.value,
                or_(
                    SystemAlert.created_at >= since,
                    SystemAlert.resolved_at.is_(None),
                    SystemAlert.resolved_at >= since,
                ),
            )
            .order_by(SystemAlert.created_at.desc(), SystemAlert.id.desc())
        )
    ).scalars().all()

    alerts = []
    for row in rows:
        ended = row.resolved_at
        until = ended or now
        alerts.append(prune({
            "key": row.alert_key,
            "severity": row.severity,
            "message": row.message,
            "started_at": row.created_at.isoformat(timespec="seconds"),
            "ended_at": ended.isoformat(timespec="seconds") if ended else None,
            "ongoing": ended is None,
            "minutes": int(round((until - row.created_at).total_seconds() / 60)),
            "peak": await _peak(session, row.alert_key, row.created_at, until, station_id),
        }))
    return {
        "hours": hours,
        "alerts": alerts,
        "active": sum(1 for a in alerts if a["ongoing"]),
        "timezone": _timezone(),
    }
