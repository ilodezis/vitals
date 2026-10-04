"""The station's state right now: latest reading, zone, trend and liveness.

The latest reading is served from Redis when the poller has put it there (the
screen asks every few seconds and shouldn't need the database for it) and from the
newest stored sample otherwise — a restart or a flushed cache must not blank the
screen. The trend always comes from stored samples, since it needs the last
fifteen minutes.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.config import load_config
from vitals.models.environment import EnvironmentSample
from vitals.services.environment import settings as env_settings
from vitals.services.environment.stats import SNAPSHOT_INTERVAL_S, slope_per_hour
from vitals.services.environment.types import (
    STATUS_OFFLINE,
    STATUS_ONLINE,
    STATUS_STALE,
    ZONE_BAD,
    ZONE_GOOD,
    ZONE_NONE,
    ZONE_OK,
    ZONE_WARN,
    LiveNow,
    LiveState,
    LiveStation,
)
from vitals.utils.timeutils import as_utc, now_utc

logger = logging.getLogger(__name__)

LIVE_TTL_S = 120
# A station that has been quiet this long is "offline" rather than "stale".
STALE_LIMIT_S = 300
TREND_WINDOW = timedelta(minutes=15)
TREND_MIN_POINTS = 6
# The trend is a statement about right now: if the newest reading is older than
# this, there is no trend to report.
TREND_MAX_AGE_S = 120


def live_key(station_id: str) -> str:
    return f"env:live:{station_id}"


def station_key(station_id: str) -> str:
    return f"env:station:{station_id}"


async def publish_live(redis: Optional[Redis], station_id: str, payload: dict[str, Any]) -> None:
    """Cache the newest reading. Best-effort: a Redis hiccup must never fail a poll."""
    if redis is None:
        return
    try:
        await redis.set(live_key(station_id), json.dumps(payload), ex=LIVE_TTL_S)
    except Exception:
        logger.warning("environment: could not cache the live reading", exc_info=True)


def co2_zone(co2: Optional[float], cfg: env_settings.EnvSettings) -> str:
    """good < ok_max <= ok < warn <= warn < bad <= bad."""
    if co2 is None:
        return ZONE_NONE
    if co2 < cfg.co2_ok_max:
        return ZONE_GOOD
    if co2 < cfg.co2_warn:
        return ZONE_OK
    if co2 < cfg.co2_bad:
        return ZONE_WARN
    return ZONE_BAD


def station_status(age_s: float, poll_seconds: int) -> str:
    """Online while the newest snapshot is at most three poll intervals old —
    counted against the station's own 10 s cadence when polling is faster, since
    polling every 5 s still only finds a new snapshot every 10 s. Stale up to five
    minutes, offline beyond."""
    online_limit = 3 * max(poll_seconds, SNAPSHOT_INTERVAL_S)
    if age_s <= online_limit:
        return STATUS_ONLINE
    if age_s <= STALE_LIMIT_S:
        return STATUS_STALE
    return STATUS_OFFLINE


def _from_row(row: EnvironmentSample) -> dict[str, Any]:
    extra = row.extra or {}
    return {
        "ts": as_utc(row.ts).isoformat(),
        "received_at": as_utc(row.received_at).isoformat(),
        "boot": row.boot_id,
        "seq": row.seq,
        "co2_ppm": row.co2_ppm,
        "temperature_c": row.temperature_c,
        "humidity_pct": row.humidity_pct,
        "lux": row.lux_avg,
        "rssi": extra.get("rssi"),
        "fw": extra.get("fw"),
    }


async def cached_reading(redis: Optional[Redis], station_id: str) -> Optional[dict[str, Any]]:
    if redis is None:
        return None
    try:
        raw = await redis.get(live_key(station_id))
        data = json.loads(raw) if raw else None
    except Exception:
        logger.warning("environment: live cache unreadable; reading the database", exc_info=True)
        return None
    if isinstance(data, dict) and data.get("received_at"):
        return data
    return None


async def _latest(session: AsyncSession, station_id: str) -> Optional[dict[str, Any]]:
    row = (
        await session.execute(
            select(EnvironmentSample)
            .where(EnvironmentSample.station_id == station_id)
            .order_by(EnvironmentSample.ts.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return _from_row(row) if row is not None else None


async def co2_trend(
    session: AsyncSession, station_id: str, *, now: datetime
) -> Optional[float]:
    """ppm per hour over the last 15 minutes (least squares), or ``None`` without
    at least six readings, the newest of them recent."""
    rows = (
        await session.execute(
            select(EnvironmentSample.ts, EnvironmentSample.co2_ppm)
            .where(
                EnvironmentSample.station_id == station_id,
                EnvironmentSample.ts >= now - TREND_WINDOW,
                EnvironmentSample.ts <= now,
                EnvironmentSample.co2_ppm.is_not(None),
            )
            .order_by(EnvironmentSample.ts)
        )
    ).all()
    points = [(as_utc(ts), float(v)) for ts, v in rows]
    if len(points) < TREND_MIN_POINTS:
        return None
    if (now - points[-1][0]).total_seconds() > TREND_MAX_AGE_S:
        return None
    slope = slope_per_hour(points)
    return None if slope is None else round(slope, 1)


async def get_live(
    session: AsyncSession,
    redis: Optional[Redis] = None,
    *,
    now: Optional[datetime] = None,
    station_id: Optional[str] = None,
) -> Optional[LiveState]:
    """The live state, or ``None`` while the station has never reported."""
    now = as_utc(now) if now else now_utc()
    config = load_config()
    station_id = station_id or config.env_station_id

    reading = await cached_reading(redis, station_id) or await _latest(session, station_id)
    if reading is None:
        return None

    cfg = await env_settings.get_settings(session)
    received = as_utc(datetime.fromisoformat(reading["received_at"]))
    age_s = max(0, int((now - received).total_seconds()))
    status = station_status(age_s, config.env_poll_seconds)

    co2 = reading.get("co2_ppm")
    return LiveState(
        station=LiveStation(
            status=status,
            last_seen_at=received,
            age_s=age_s,
            rssi=reading.get("rssi") if isinstance(reading.get("rssi"), int) else None,
            fw=reading.get("fw") if isinstance(reading.get("fw"), str) else None,
        ),
        now=LiveNow(
            co2_ppm=co2,
            temperature_c=reading.get("temperature_c"),
            humidity_pct=reading.get("humidity_pct"),
            lux=reading.get("lux"),
            co2_zone=co2_zone(co2, cfg),
            co2_trend_ppm_per_h=await co2_trend(session, station_id, now=now),
        ),
    )


__all__ = [
    "co2_trend",
    "cached_reading",
    "co2_zone",
    "get_live",
    "live_key",
    "publish_live",
    "station_key",
    "station_status",
]
