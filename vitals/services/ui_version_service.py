"""UI version preference — stored in ``app_settings``, cached in Redis.

Mirrors ``language_service`` exactly: DB is source of truth, Redis is a
read-through cache with 300 s TTL.  Supported values: ``"classic"`` (default),
``"masthead"``.  Switching is instant, needs no migration, and never touches
domain data — a missing row simply resolves to the ``"classic"`` default so the
chrome always renders.
"""
from __future__ import annotations

import logging
from typing import Optional

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.models.app_settings import AppSetting

logger = logging.getLogger(__name__)

SETTINGS_KEY = "ui_version"
REDIS_KEY = "settings:ui_version"
REDIS_TTL = 300
SUPPORTED = ("classic", "masthead")
DEFAULT = "classic"


def _sanitize(raw: object) -> str:
    if isinstance(raw, str) and raw in SUPPORTED:
        return raw
    return DEFAULT


async def get_ui_version(
    session: AsyncSession, redis: Optional[Redis] = None
) -> str:
    if redis is not None:
        try:
            cached = await redis.get(REDIS_KEY)
            if cached:
                return _sanitize(cached)
        except Exception:
            logger.warning("ui_version: Redis read failed; falling through to DB", exc_info=True)

    try:
        row = await session.get(AppSetting, SETTINGS_KEY)
        if row is not None:
            value = _sanitize(row.value)
            await prime_cache(redis, value)
            return value
        logger.debug("ui_version: no app_settings row; using default '%s'", DEFAULT)
    except Exception:
        logger.warning("ui_version: DB read failed; using default", exc_info=True)

    return DEFAULT


async def set_ui_version(
    session: AsyncSession, value: str, redis: Optional[Redis] = None
) -> str:
    value = _sanitize(value)
    row = await session.get(AppSetting, SETTINGS_KEY)
    if row is None:
        session.add(AppSetting(key=SETTINGS_KEY, value=value))
    else:
        row.value = value
    await session.flush()
    await prime_cache(redis, value)
    return value


async def prime_cache(redis: Optional[Redis], value: str) -> None:
    if redis is None:
        return
    try:
        await redis.set(REDIS_KEY, value, ex=REDIS_TTL)
    except Exception:
        logger.warning("ui_version: Redis prime failed", exc_info=True)
