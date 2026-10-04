"""Reads over the stored samples: chart series and the night / day summaries.

Three resolutions, one rule per range so a screen and the connector see the same
numbers: ``raw`` is the samples themselves, ``minute`` buckets them in Python (the
same result on SQLite and Postgres — no ``date_trunc``), and ``hour`` reads the
rollup table. Minute buckets are only built for up to 48 hours; beyond that the
rollup is the source. The newest two hours always come from the samples through the
rollup's own aggregation, because the rollup row of the hour in progress is
still being filled.
"""
from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, time as time_type, timedelta
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.config import load_config
from vitals.models.environment import EnvironmentHourly
from vitals.services.environment import settings as env_settings
from vitals.services.environment import stats
from vitals.services.environment.rollup import (
    HOUR,
    HourStats,
    SampleRow,
    aggregate_hours,
    floor_hour,
    load_rows,
)
from vitals.services.environment.types import (
    Co2Stats,
    DaySummary,
    NightSummary,
    PeriodSummary,
    Point,
    RangeStats,
    Resolution,
    Window,
)
from vitals.utils.timeutils import as_utc, local_naive_to_utc, now_utc

DEFAULT_STATION = "bedroom"

# Raw samples are only worth drawing for a short window; minutes are built in
# Python only up to this long.
RAW_MAX_HOURS = 3
MINUTE_MAX_HOURS = 48
# The newest hours are recomputed from samples instead of read from the rollup.
LIVE_HOURS = 2


def _station(station_id: Optional[str]) -> str:
    return station_id or load_config().env_station_id or DEFAULT_STATION


def effective_resolution(
    start: datetime, end: datetime, requested: Resolution
) -> Resolution:
    """The resolution a range can be served at: raw up to 3 h, minutes up to 48 h,
    hours beyond. A coarser request is always honoured."""
    span_h = (end - start).total_seconds() / 3600
    if requested == "hour" or span_h > MINUTE_MAX_HOURS:
        return "hour"
    if requested == "minute" or span_h > RAW_MAX_HOURS:
        return "minute"
    return "raw"


# ── Hours (rollup table + the live tail) ──────────────────────────────────────
def _hour_stats_from_row(row: EnvironmentHourly) -> HourStats:
    return HourStats(
        hour_start=as_utc(row.hour_start),
        sample_count=row.sample_count,
        coverage_pct=row.coverage_pct,
        co2_mean=row.co2_mean,
        co2_min=row.co2_min,
        co2_max=row.co2_max,
        co2_p90=row.co2_p90,
        temp_mean=row.temp_mean,
        temp_min=row.temp_min,
        temp_max=row.temp_max,
        rh_mean=row.rh_mean,
        rh_min=row.rh_min,
        rh_max=row.rh_max,
        lux_mean=row.lux_mean,
        lux_max=row.lux_max,
    )


async def hour_stats(
    session: AsyncSession, start: datetime, end: datetime, *, station_id: Optional[str] = None
) -> list[HourStats]:
    """One :class:`HourStats` per hour with data, for hours starting in
    ``[floor_hour(start), end)``, oldest first."""
    station_id = _station(station_id)
    first = floor_hour(start)
    end = as_utc(end)
    live_from = max(first, floor_hour(end) - (LIVE_HOURS - 1) * HOUR)

    older: dict[datetime, HourStats] = {}
    if first < live_from:
        table_rows = (
            await session.execute(
                select(EnvironmentHourly).where(
                    EnvironmentHourly.station_id == station_id,
                    EnvironmentHourly.hour_start >= first,
                    EnvironmentHourly.hour_start < live_from,
                )
            )
        ).scalars().all()
        older = {as_utc(r.hour_start): _hour_stats_from_row(r) for r in table_rows}
        if not older:
            # The rollup has not run over this range (a fresh install, or the job
            # was off): serve it from the samples rather than show a hole.
            older = aggregate_hours(await load_rows(session, station_id, first, live_from))

    recent = aggregate_hours(await load_rows(session, station_id, live_from, end))
    merged = {**older, **recent}
    return [merged[h] for h in sorted(merged)]


def _hour_point(hs: HourStats) -> Point:
    return Point(
        ts=hs.hour_start,
        co2_ppm=hs.co2_mean,
        temperature_c=hs.temp_mean,
        humidity_pct=hs.rh_mean,
        lux=hs.lux_mean,
        co2_max=hs.co2_max,
        co2_min=hs.co2_min,
    )


# ── Series ────────────────────────────────────────────────────────────────────
def _minute_points(rows: Sequence[SampleRow]) -> list[Point]:
    buckets: dict[datetime, list[SampleRow]] = {}
    for row in rows:
        buckets.setdefault(row.ts.replace(second=0, microsecond=0), []).append(row)

    def avg(values: list[float], digits: int) -> Optional[float]:
        mean = stats.mean(values)
        return None if mean is None else round(mean, digits)

    return [
        Point(
            ts=minute,
            co2_ppm=avg([r.co2 for r in group if r.co2 is not None], 1),
            temperature_c=avg([r.temp for r in group if r.temp is not None], 2),
            humidity_pct=avg([r.rh for r in group if r.rh is not None], 2),
            lux=avg([r.lux for r in group if r.lux is not None], 2),
        )
        for minute, group in sorted(buckets.items())
    ]


def _raw_points(rows: Sequence[SampleRow]) -> list[Point]:
    return [
        Point(
            ts=r.ts,
            co2_ppm=r.co2,
            temperature_c=r.temp,
            humidity_pct=r.rh,
            lux=r.lux,
        )
        for r in rows
    ]


async def series(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    *,
    resolution: Resolution,
    station_id: Optional[str] = None,
) -> list[Point]:
    """Points for ``[start, end]`` at ``resolution``. ``minute`` over more than 48
    hours is served as ``hour`` (see :func:`effective_resolution`); ask for the
    effective resolution first when the caller must know."""
    station_id = _station(station_id)
    start, end = as_utc(start), as_utc(end)
    resolution = effective_resolution(start, end, resolution)

    if resolution == "hour":
        hours = await hour_stats(session, start, end, station_id=station_id)
        return [_hour_point(h) for h in hours if h.hour_start < end]

    rows = await load_rows(session, station_id, start, end + timedelta(microseconds=1))
    return _raw_points(rows) if resolution == "raw" else _minute_points(rows)


async def coverage_pct(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    *,
    station_id: Optional[str] = None,
) -> float:
    """Share of ``[start, end]`` the station actually reported (0-100). Counted
    from the real gaps between snapshots for up to 48 hours, from the hourly
    rollup beyond."""
    station_id = _station(station_id)
    start, end = as_utc(start), as_utc(end)
    span = (end - start).total_seconds()
    if span <= 0:
        return 0.0

    if span / 3600 <= MINUTE_MAX_HOURS:
        rows = await load_rows(session, station_id, start, end)
        return round(min(100.0, stats.covered_seconds([r.ts for r in rows], start, end) / span * 100), 1)

    hours = await hour_stats(session, start, end, station_id=station_id)
    # An hour with no row at all counts as zero, so weight by the window's hours.
    total_hours = span / 3600
    return round(min(100.0, sum(h.coverage_pct for h in hours) / total_hours), 1)


# ── Night / day summaries ─────────────────────────────────────────────────────
def night_window(on_date: date_type, cfg: env_settings.EnvSettings) -> tuple[datetime, datetime]:
    """The night that ends on ``on_date`` as a UTC range. A window that wraps
    midnight (22:00-07:00) starts the evening before."""
    start_t, end_t = cfg.night_times()
    start_day = on_date if start_t < end_t else on_date - timedelta(days=1)
    return (
        local_naive_to_utc(datetime.combine(start_day, start_t)),
        local_naive_to_utc(datetime.combine(on_date, end_t)),
    )


def day_window(on_date: date_type) -> tuple[datetime, datetime]:
    """A local calendar day as a UTC range."""
    midnight = time_type(0, 0)
    return (
        local_naive_to_utc(datetime.combine(on_date, midnight)),
        local_naive_to_utc(datetime.combine(on_date + timedelta(days=1), midnight)),
    )


def _range(values: list[float]) -> RangeStats:
    if not values:
        return RangeStats()
    return RangeStats(
        min=round(min(values), 1), mean=round(sum(values) / len(values), 1), max=round(max(values), 1)
    )


def summarize(
    rows: Sequence[SampleRow],
    on_date: date_type,
    window: tuple[datetime, datetime],
    cfg: env_settings.EnvSettings,
    *,
    now: datetime,
) -> PeriodSummary:
    """The numbers of one window. A window still running is measured against the
    part of it that has elapsed, so an unfinished night isn't "half uncovered"."""
    start, end = window
    elapsed_end = min(end, now)
    timestamps = [r.ts for r in rows]

    span = (elapsed_end - start).total_seconds()
    coverage = (
        round(min(100.0, stats.covered_seconds(timestamps, start, elapsed_end) / span * 100), 1)
        if span > 0
        else 0.0
    )

    co2 = [float(r.co2) for r in rows if r.co2 is not None]
    co2_stats = Co2Stats()
    if co2:
        co2_stats = Co2Stats(
            median=round(stats.percentile(co2, 50), 1),
            p90=round(stats.percentile(co2, 90), 1),
            max=max(co2),
            minutes_above_warn=round(
                stats.seconds_where(
                    timestamps, [r.co2 is not None and r.co2 >= cfg.co2_warn for r in rows], start, end
                ) / 60.0,
                1,
            ),
            minutes_above_bad=round(
                stats.seconds_where(
                    timestamps, [r.co2 is not None and r.co2 >= cfg.co2_bad for r in rows], start, end
                ) / 60.0,
                1,
            ),
        )

    return PeriodSummary(
        date=on_date,
        window=Window(start=start, end=end),
        samples=len(rows),
        coverage_pct=coverage,
        co2=co2_stats,
        temperature=_range([r.temp for r in rows if r.temp is not None]),
        humidity=_range([r.rh for r in rows if r.rh is not None]),
    )


async def _summary(
    session: AsyncSession,
    on_date: date_type,
    window: tuple[datetime, datetime],
    station_id: Optional[str],
    now: Optional[datetime],
) -> PeriodSummary:
    cfg = await env_settings.get_settings(session)
    rows = await load_rows(session, _station(station_id), *window)
    return summarize(rows, on_date, window, cfg, now=as_utc(now) if now else now_utc())


async def night_summary(
    session: AsyncSession,
    on_date: date_type,
    *,
    station_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> NightSummary:
    """The night that ended on ``on_date`` (the date you woke up)."""
    cfg = await env_settings.get_settings(session)
    return await _summary(session, on_date, night_window(on_date, cfg), station_id, now)


async def day_summary(
    session: AsyncSession,
    on_date: date_type,
    *,
    station_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> DaySummary:
    """A whole local calendar day."""
    return await _summary(session, on_date, day_window(on_date), station_id, now)
