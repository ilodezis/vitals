"""UI language preference — stored in ``app_settings``, cached in Redis.

Mirrors the ``modules_service`` pattern exactly: DB is source of truth, Redis is a
read-through cache with 300 s TTL.  Supported codes: ``"en"`` (default), ``"ru"``.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.models.app_settings import AppSetting

logger = logging.getLogger(__name__)

SETTINGS_KEY = "ui_language"
REDIS_KEY = "settings:ui_language"
REDIS_TTL = 300
SUPPORTED = ("en", "ru")
DEFAULT = "en"


def _sanitize(raw: object) -> str:
    if isinstance(raw, str) and raw in SUPPORTED:
        return raw
    return DEFAULT


async def get_language(
    session: AsyncSession, redis: Optional[Redis] = None
) -> str:
    if redis is not None:
        try:
            cached = await redis.get(REDIS_KEY)
            if cached:
                return _sanitize(cached)
        except Exception:
            logger.warning("language: Redis read failed; falling through to DB", exc_info=True)

    try:
        row = await session.get(AppSetting, SETTINGS_KEY)
        if row is not None:
            lang = _sanitize(row.value)
            await prime_cache(redis, lang)
            return lang
        logger.debug("language: no app_settings row; using default '%s'", DEFAULT)
    except Exception:
        logger.warning("language: DB read failed; using default", exc_info=True)

    return DEFAULT


async def set_language(
    session: AsyncSession, lang: str, redis: Optional[Redis] = None
) -> str:
    lang = _sanitize(lang)
    row = await session.get(AppSetting, SETTINGS_KEY)
    if row is None:
        session.add(AppSetting(key=SETTINGS_KEY, value=lang))
    else:
        row.value = lang
    await session.flush()
    await prime_cache(redis, lang)
    return lang


async def prime_cache(redis: Optional[Redis], lang: str) -> None:
    if redis is None:
        return
    try:
        await redis.set(REDIS_KEY, lang, ex=REDIS_TTL)
    except Exception:
        logger.warning("language: Redis prime failed", exc_info=True)
