"""Hourly rollup of ``environment_samples`` into ``environment_hourly``.

A week of 10-second samples is ~60 000 rows; the same week by the hour is 168. The
rollup job keeps that table current, so long charts read the small one.

``aggregate_hours`` is a pure function over sample rows and is the one definition
of an hour's numbers: the job stores its result, and the chart reads of the most
recent hours (not yet rolled up, or still changing) compute it on the fly through
the same function — so the two can never disagree.

The job is idempotent and cheap: each run recomputes only the hours from just
before the newest stored one onward, so late samples of the previous hour are
picked up and nothing is ever double counted.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Sequence

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from vitals.config import load_config
from vitals.enums import Source
from vitals.models.environment import DOMAIN, EnvironmentHourly, EnvironmentSample
from vitals.services import modules_service
from vitals.services.environment import stats
from vitals.utils.timeutils import as_utc, now_utc, to_local_naive

logger = logging.getLogger(__name__)

HOUR = timedelta(hours=1)
# A first run over a long history is done in slices so no single run holds the
# lock or the transaction for long; the next tick carries on.
CHUNK_HOURS = 72
MAX_CHUNKS_PER_RUN = 10


@dataclass(frozen=True)
class SampleRow:
    """The columns of a sample the numbers are built from (``ts`` aware UTC)."""

    ts: datetime
    co2: Optional[int]
    temp: Optional[float]
    rh: Optional[float]
    lux: Optional[float]
    lux_max: Optional[float]


@dataclass(frozen=True)
class HourStats:
    hour_start: datetime
    sample_count: int
    coverage_pct: float
    co2_mean: Optional[float] = None
    co2_min: Optional[int] = None
    co2_max: Optional[int] = None
    co2_p90: Optional[float] = None
    temp_mean: Optional[float] = None
    temp_min: Optional[float] = None
    temp_max: Optional[float] = None
    rh_mean: Optional[float] = None
    rh_min: Optional[float] = None
    rh_max: Optional[float] = None
    lux_mean: Optional[float] = None
    lux_max: Optional[float] = None


def floor_hour(ts: datetime) -> datetime:
    return as_utc(ts).replace(minute=0, second=0, microsecond=0)


def _r(value: Optional[float], digits: int) -> Optional[float]:
    return None if value is None else round(value, digits)


def aggregate_hours(rows: Sequence[SampleRow]) -> dict[datetime, HourStats]:
    """Rows (sorted by ``ts``) → one :class:`HourStats` per clock hour that has any."""
    by_hour: dict[datetime, list[SampleRow]] = {}
    for row in rows:
        by_hour.setdefault(floor_hour(row.ts), []).append(row)
    covered = stats.covered_by_hour([r.ts for r in rows])

    out: dict[datetime, HourStats] = {}
    for hour, group in by_hour.items():
        co2 = [r.co2 for r in group if r.co2 is not None]
        temp = [r.temp for r in group if r.temp is not None]
        rh = [r.rh for r in group if r.rh is not None]
        lux = [r.lux for r in group if r.lux is not None]
        lux_peaks = [r.lux_max for r in group if r.lux_max is not None] or lux
        out[hour] = HourStats(
            hour_start=hour,
            sample_count=len(group),
            coverage_pct=round(min(100.0, covered.get(hour, 0.0) / 3600.0 * 100.0), 1),
            co2_mean=_r(stats.mean(co2), 1),
            co2_min=min(co2) if co2 else None,
            co2_max=max(co2) if co2 else None,
            co2_p90=_r(stats.percentile(co2, 90), 1),
            temp_mean=_r(stats.mean(temp), 2),
            temp_min=min(temp) if temp else None,
            temp_max=max(temp) if temp else None,
            rh_mean=_r(stats.mean(rh), 2),
            rh_min=min(rh) if rh else None,
            rh_max=max(rh) if rh else None,
            lux_mean=_r(stats.mean(lux), 2),
            lux_max=max(lux_peaks) if lux_peaks else None,
        )
    return out


async def load_rows(
    session: AsyncSession, station_id: str, start: datetime, end: datetime
) -> list[SampleRow]:
    """Samples with ``start <= ts < end``, oldest first."""
    result = await session.execute(
        select(
            EnvironmentSample.ts,
            EnvironmentSample.co2_ppm,
            EnvironmentSample.temperature_c,
            EnvironmentSample.humidity_pct,
            EnvironmentSample.lux_avg,
            EnvironmentSample.lux_max,
        )
        .where(
            EnvironmentSample.station_id == station_id,
            EnvironmentSample.ts >= as_utc(start),
            EnvironmentSample.ts < as_utc(end),
        )
        .order_by(EnvironmentSample.ts)
    )
    return [SampleRow(as_utc(ts), *rest) for ts, *rest in result.all()]


async def rollup_range(
    session: AsyncSession, station_id: str, start_hour: datetime, end_hour: datetime
) -> int:
    """Recompute the hourly rows for hours in ``[start_hour, end_hour)``. Returns
    how many rows exist for them afterwards. Flushes; the caller commits."""
    start_hour, end_hour = floor_hour(start_hour), floor_hour(end_hour)
    # Read a minute past the range so the last sample's gap to its successor is
    # measured, not assumed — otherwise every chunk edge would under-report coverage.
    rows = await load_rows(
        session, station_id, start_hour, end_hour + timedelta(seconds=stats.GAP_CAP_S)
    )
    computed = {
        hour: hs for hour, hs in aggregate_hours(rows).items() if start_hour <= hour < end_hour
    }
    if not computed:
        return 0

    existing_rows = (
        await session.execute(
            select(EnvironmentHourly).where(
                EnvironmentHourly.station_id == station_id,
                EnvironmentHourly.hour_start >= start_hour,
                EnvironmentHourly.hour_start < end_hour,
            )
        )
    ).scalars().all()
    existing = {floor_hour(row.hour_start): row for row in existing_rows}

    for hour, hs in computed.items():
        fields = {
            "sample_count": hs.sample_count,
            "coverage_pct": hs.coverage_pct,
            "co2_mean": hs.co2_mean,
            "co2_min": hs.co2_min,
            "co2_max": hs.co2_max,
            "co2_p90": hs.co2_p90,
            "temp_mean": hs.temp_mean,
            "temp_min": hs.temp_min,
            "temp_max": hs.temp_max,
            "rh_mean": hs.rh_mean,
            "rh_min": hs.rh_min,
            "rh_max": hs.rh_max,
            "lux_mean": hs.lux_mean,
            "lux_max": hs.lux_max,
        }
        row = existing.get(hour)
        if row is None:
            session.add(
                EnvironmentHourly(
                    station_id=station_id,
                    hour_start=hour,
                    date=to_local_naive(hour).date(),
                    domain=DOMAIN,
                    source=Source.ESPHOME.value,
                    **fields,
                )
            )
        else:
            for name, value in fields.items():
                if getattr(row, name) != value:
                    setattr(row, name, value)
    await session.flush()
    return len(computed)


async def environment_rollup_job(
    session_factory: async_sessionmaker[AsyncSession], redis: Optional[Redis] = None
) -> None:
    """Scheduler entry point: bring ``environment_hourly`` up to date. Returns on
    its first line without a configured station or with the module off."""
    config = load_config()
    if not config.env_station_url:
        return
    station_id = config.env_station_id
    async with session_factory() as session:
        enabled = await modules_service.get_enabled_modules(session, redis)
        if not enabled.get("environment"):
            return

        last = (
            await session.execute(
                select(func.max(EnvironmentHourly.hour_start)).where(
                    EnvironmentHourly.station_id == station_id
                )
            )
        ).scalar_one_or_none()
        if last is not None:
            start = floor_hour(last) - HOUR  # one back: late samples of the last hour
        else:
            first = (
                await session.execute(
                    select(func.min(EnvironmentSample.ts)).where(
                        EnvironmentSample.station_id == station_id
                    )
                )
            ).scalar_one_or_none()
            if first is None:
                return
            start = floor_hour(first)

        end = floor_hour(now_utc()) + HOUR
        for _ in range(MAX_CHUNKS_PER_RUN):
            if start >= end:
                break
            chunk_end = min(end, start + timedelta(hours=CHUNK_HOURS))
            await rollup_range(session, station_id, start, chunk_end)
            await session.commit()
            start = chunk_end
