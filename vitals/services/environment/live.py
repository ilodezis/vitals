"""The station's state right now: latest reading, zone, trend and liveness."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.services.environment.types import LiveState


async def get_live(
    session: AsyncSession, redis: Optional[Redis] = None, *, now: Optional[datetime] = None
) -> Optional[LiveState]:
    """``None`` while the station has never reported (stub until ingest lands)."""
    return None
