"""Pulling snapshots from the station into ``environment_samples``."""
from __future__ import annotations

from typing import Optional

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def environment_poll_job(
    session_factory: async_sessionmaker[AsyncSession], redis: Optional[Redis] = None
) -> None:
    """Scheduler entry point (stub until the poller lands)."""
    return None


async def check_station(session: AsyncSession, redis: Optional[Redis] = None) -> dict:
    """Poll the station right now and say how it went (stub until the poller lands)."""
    return {"ok": False, "status": "never", "error": "not_configured"}
