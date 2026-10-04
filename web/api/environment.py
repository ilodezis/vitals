"""``/api/v1/environment`` — the bedroom's air: live reading, curves, night/day
summaries, thresholds and a connection check."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from fastapi import Depends, Query
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.config import load_config
from vitals.services.environment import ingest, live, queries
from vitals.services.environment import settings as env_settings
from vitals.services.environment.types import LiveState, PeriodSummary
from vitals.utils.timeutils import now_utc
from web.api.errors import ApiRouter
from web.api.schemas.environment import (
    EnvSettings,
    EnvSettingsPatch,
    LiveView,
    PeriodView,
    Resolution,
    SeriesView,
    StationCheck,
    Thresholds,
)
from web.deps import get_redis, get_session, require_auth

router = ApiRouter(prefix="/environment", dependencies=[Depends(require_auth)])


def _thresholds(cfg: env_settings.EnvSettings) -> Thresholds:
    return Thresholds(**cfg.thresholds_dict())


async def _redis_or_none(redis: Redis = Depends(get_redis)) -> Optional[Redis]:
    return redis


@router.get("/live", response_model=LiveView)
async def read_environment_live(
    db: AsyncSession = Depends(get_session),
    redis: Optional[Redis] = Depends(_redis_or_none),
) -> LiveView:
    """The latest reading with its zone and trend, the station's liveness and the
    thresholds the screen draws against."""
    cfg = await env_settings.get_settings(db)
    state = await live.get_live(db, redis) or LiveState()
    return LiveView.model_validate(
        {
            "configured": bool(load_config().env_station_url),
            **state.to_dict(),
            "thresholds": cfg.thresholds_dict(),
        }
    )


@router.get("/series", response_model=SeriesView)
async def read_environment_series(
    hours: int = Query(24, ge=1, le=168),
    resolution: Resolution = "minute",
    db: AsyncSession = Depends(get_session),
) -> SeriesView:
    """The last ``hours`` hours as points. The resolution actually returned can be
    coarser than asked (a week of minutes is 10 000 points): ``resolution`` in the
    response says which one it is."""
    cfg = await env_settings.get_settings(db)
    end = now_utc()
    start = end - dt.timedelta(hours=hours)
    effective = queries.effective_resolution(start, end, resolution)
    points = await queries.series(db, start, end, resolution=effective)
    return SeriesView.model_validate(
        {
            "points": [p.to_dict() for p in points],
            "resolution": effective,
            "coverage_pct": await queries.coverage_pct(db, start, end),
            "thresholds": cfg.thresholds_dict(),
            "window": {"start": start, "end": end},
        }
    )


async def _period_view(
    db: AsyncSession, summary: PeriodSummary, cfg: env_settings.EnvSettings
) -> PeriodView:
    points = await queries.series(
        db, summary.window.start, summary.window.end, resolution="minute"
    )
    return PeriodView.model_validate(
        {
            "summary": summary.to_dict(),
            "series": [p.to_dict() for p in points],
            "thresholds": cfg.thresholds_dict(),
        }
    )


@router.get("/day/{on_date}", response_model=PeriodView)
async def read_environment_day(on_date: dt.date, db: AsyncSession = Depends(get_session)) -> PeriodView:
    """A calendar day (local time): its summary and minute curve."""
    cfg = await env_settings.get_settings(db)
    return await _period_view(db, await queries.day_summary(db, on_date), cfg)


@router.get("/night/{on_date}", response_model=PeriodView)
async def read_environment_night(on_date: dt.date, db: AsyncSession = Depends(get_session)) -> PeriodView:
    """The night that ended on ``on_date`` (the date you woke up): its summary and
    minute curve."""
    cfg = await env_settings.get_settings(db)
    return await _period_view(db, await queries.night_summary(db, on_date), cfg)


@router.get("/settings", response_model=EnvSettings)
async def read_environment_settings(db: AsyncSession = Depends(get_session)) -> EnvSettings:
    return EnvSettings.model_validate((await env_settings.get_settings(db)).to_dict())


@router.put("/settings", response_model=EnvSettings)
async def write_environment_settings(
    body: EnvSettingsPatch, db: AsyncSession = Depends(get_session)
) -> EnvSettings:
    """Partial update; out-of-range values are clamped and the saved result is
    returned."""
    saved = await env_settings.set_settings(db, body.model_dump(exclude_unset=True))
    return EnvSettings.model_validate(saved.to_dict())


@router.post("/station/check", response_model=StationCheck)
async def check_environment_station(
    db: AsyncSession = Depends(get_session),
    redis: Optional[Redis] = Depends(_redis_or_none),
) -> StationCheck:
    """Ask the station for a snapshot right now and report how it went."""
    return StationCheck.model_validate(await ingest.check_station(db, redis))
