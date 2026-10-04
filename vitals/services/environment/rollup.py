"""Hourly rollup of ``environment_samples`` into ``environment_hourly``."""
from __future__ import annotations

from typing import Optional

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def environment_rollup_job(
    session_factory: async_sessionmaker[AsyncSession], redis: Optional[Redis] = None
) -> None:
    """Scheduler entry point (stub until the rollup lands)."""
    return None
