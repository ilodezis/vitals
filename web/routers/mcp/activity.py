"""Garmin metrics, Hevy workouts and on-demand syncs."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from vitals.models import (
    GarminActivity, GarminDaily, GarminIntraday, HevyExercise, HevyWorkout,
)
from vitals.utils.timeutils import today_local
from web.routers.mcp._core import (
    READ, WRITE, _parse_date, _pkg, gated, get_redis_client, get_session_factory, logger,
    dispatch, serialize_row, tool,
)

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
    """Swap each present sleep-detail column for an integer count."""
    for name in _SLEEP_DETAIL_COLUMNS:
        value = row.pop(name, None)
        if value is not None:
            row[f"{name}_count"] = len(value) if isinstance(value, list) else 0
    return row


@tool(READ)
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
        else:
            for r in rows:
                for name in _SLEEP_DETAIL_COLUMNS:
                    if name in r and r[name] is not None:
                        r[f"{name}_count"] = len(r[name]) if isinstance(r[name], list) else 0

        today_iso = today_local().isoformat()
        for r in rows:
            r["is_partial_day"] = (r.get("date") == today_iso)
            if "sleep_need_actual" in r:
                r["sleep_need_minutes"] = r.pop("sleep_need_actual")

        result = {
            "daily_recovery": rows,
            "activities": [serialize_row(a) for a in activities],
        }

        if intraday:
            # Grouped per series and trimmed to {ts, value} rather than run through
            # serialize_row: at thousands of rows the per-row id/domain/source/
            # timestamps would dwarf the actual curve. Fetch one over the cap to
            # tell "exactly full" from "truncated".
            cap = _pkg().INTRADAY_POINT_CAP
            i_stmt = select(GarminIntraday)
            if start:
                i_stmt = i_stmt.where(GarminIntraday.date >= start)
            if end:
                i_stmt = i_stmt.where(GarminIntraday.date <= end)
            i_stmt = i_stmt.order_by(GarminIntraday.ts).limit(cap + 1)
            points = (await session.execute(i_stmt)).scalars().all()
            result["intraday_truncated"] = len(points) > cap
            series: dict[str, list[dict]] = {}
            for p in points[:cap]:
                series.setdefault(p.series_type, []).append(
                    {"ts": p.ts.isoformat(), "value": p.value}
                )
            result["intraday"] = series

        return result


@tool(READ, module='hevy')
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
            w_dict.pop("id", None)
            w_dict["exercises"] = []
            for e in w.exercises:
                e_dict = serialize_row(e)
                e_dict.pop("id", None)
                e_dict.pop("workout_id", None)
                sets = []
                for s in e.sets:
                    s_dict = serialize_row(s)
                    s_dict.pop("id", None)
                    s_dict.pop("exercise_id", None)
                    sets.append(s_dict)
                e_dict["sets"] = sets
                w_dict["exercises"].append(e_dict)
            serialized.append(w_dict)
        return serialized


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


# ── Consolidated sync tool ───────────────────────────────────────────────────
_SYNC_SOURCES = {
    ("garmin", False): (sync_garmin, None),
    ("hevy", False): (sync_hevy, None),
}


@tool(WRITE, idempotent=True, open_world=True)
async def sync_data(source: str = "garmin", days: Optional[int] = None) -> dict:
    """Pulls fresh data from an external service now, for a gap or stale data —
    not before routine reads (the scheduler already polls Garmin several times a
    day and Hevy every 6 hours). Each source is capped at 3 calls a day.

    ``source="garmin"``: daily metrics plus activities for the last ``days``
    (default 2: yesterday and today; max 30). Returns ``{days, activities, error}``;
    an auth/MFA/throttle failure comes back as ``error`` and raises an alert.
    ``source="hevy"``: the latest workouts (takes no ``days``)."""
    return await dispatch("sync_data", "source", source, _SYNC_SOURCES, dict(days=days))
