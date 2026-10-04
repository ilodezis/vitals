"""Reads over the stored samples: chart series and the night / day summaries."""
from __future__ import annotations

from datetime import date as date_type
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from vitals.services.environment.types import (
    DaySummary,
    NightSummary,
    Point,
    Resolution,
    Window,
)

DEFAULT_STATION = "bedroom"


def effective_resolution(
    start: datetime, end: datetime, requested: Resolution
) -> Resolution:
    """The resolution a range can be served at: raw up to 3 h, minutes up to 48 h,
    hours beyond. A coarser request is always honoured."""
    span_h = (end - start).total_seconds() / 3600
    if requested == "hour" or span_h > 48:
        return "hour"
    if requested == "minute" or span_h > 3:
        return "minute"
    return "raw"


async def coverage_pct(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    *,
    station_id: str = DEFAULT_STATION,
) -> float:
    """Stub until the reads land."""
    return 0.0


async def series(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    *,
    resolution: Resolution,
    station_id: str = DEFAULT_STATION,
) -> list[Point]:
    """Stub until the reads land: no points."""
    return []


async def night_summary(
    session: AsyncSession, on_date: date_type, *, station_id: str = DEFAULT_STATION
) -> NightSummary:
    """Stub until the reads land: an empty window."""
    start = datetime.combine(on_date, datetime.min.time())
    return NightSummary(date=on_date, window=Window(start=start, end=start))


async def day_summary(
    session: AsyncSession, on_date: date_type, *, station_id: str = DEFAULT_STATION
) -> DaySummary:
    """Stub until the reads land: an empty window."""
    start = datetime.combine(on_date, datetime.min.time())
    return DaySummary(date=on_date, window=Window(start=start, end=start))
