"""Dashboard modularity — which optional domains are visible.

Single source of truth for the **module registry** (Core vs Optional) and a
fail-safe service to read/write the enabled set.

Storage: one ``app_settings`` row, ``key='enabled_modules'``, ``value`` a JSON
object ``{"hevy": true, ...}``. Redis (``settings:enabled_modules``) is a
read-through cache; the DB is the source of truth.

Manifest — **Zero Silent Errors**: every fallback path is *logged*, never
swallowed. ``get_enabled_modules`` NEVER raises: on a broken/empty/corrupt config
it returns the safe default (Core → True, Optional → False) so the UI degrades to
"core only" instead of 500-ing.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.models.app_settings import AppSetting

logger = logging.getLogger(__name__)

SETTINGS_KEY = "enabled_modules"          # app_settings.key
REDIS_KEY = "settings:enabled_modules"    # cache key
REDIS_TTL = 300                           # seconds


class ModuleToggleError(ValueError):
    """Raised when a caller tries to toggle a non-existent or Core (locked)
    module. The router maps this to HTTP 400."""


@dataclass(frozen=True)
class ModuleSpec:
    key: str
    label: str          # Russian nav label
    category: str       # "core" | "optional"
    route: str          # URL prefix / nav href


# Ordered registry. ``key`` == route name == nav anchor. Order = render order.
MODULE_REGISTRY: dict[str, ModuleSpec] = {
    m.key: m
    for m in (
        # ── Core — always on, toggle locked ──────────────────────────────────
        ModuleSpec("weight", "Вес", "core", "/weight"),
        ModuleSpec("garmin", "Организм", "core", "/garmin"),
        ModuleSpec("labs", "Анализы", "core", "/labs"),
        ModuleSpec("reports", "Отчёты", "core", "/reports"),
        ModuleSpec("charts", "Графики", "core", "/charts"),
        # ── Optional — user-toggleable ───────────────────────────────────────
        ModuleSpec("timeline", "Хронология", "optional", "/timeline"),
        ModuleSpec("glp1", "GLP-1", "optional", "/glp1"),
        ModuleSpec("hevy", "Тренировки", "optional", "/hevy"),
        ModuleSpec("supplements", "Добавки", "optional", "/supplements"),
        ModuleSpec("genetics", "Генетика", "optional", "/genetics"),
        ModuleSpec("skincare", "Кожа", "optional", "/skincare"),
        ModuleSpec("nutrition", "Питание", "optional", "/nutrition"),
        ModuleSpec("interactions", "Взаимодействия", "optional", "/interactions"),
        # Body composition (InBody / МедАсс) — a tab inside /weight, not its own
        # nav item; the toggle just shows/hides that tab and its routes.
        ModuleSpec("body_comp", "Состав тела", "optional", "/weight"),
    )
}

CORE_KEYS: frozenset[str] = frozenset(
    k for k, s in MODULE_REGISTRY.items() if s.category == "core"
)
OPTIONAL_KEYS: frozenset[str] = frozenset(
    k for k, s in MODULE_REGISTRY.items() if s.category == "optional"
)

# Safe fallback set: Core on, Optional off. Used ONLY when config is missing or
# unreadable — not what the migration seeds (it seeds optional ON).
DEFAULT_STATE: dict[str, bool] = {
    **{k: True for k in CORE_KEYS},
    **{k: False for k in OPTIONAL_KEYS},
}


def _sanitize(raw: Any) -> dict[str, bool]:
    """Project arbitrary stored data onto the registry.

    Core keys are forced True; Optional keys take ``bool(raw[key])`` when present
    else their default (False); unknown keys are dropped. Resilient to schema
    drift and to a non-dict ``raw`` (returns clean defaults).
    """
    state = dict(DEFAULT_STATE)
    if isinstance(raw, dict):
        for key in OPTIONAL_KEYS:
            if key in raw:
                state[key] = bool(raw[key])
    for key in CORE_KEYS:
        state[key] = True
    return state


async def get_enabled_modules(
    session: AsyncSession, redis: Optional[Redis] = None
) -> dict[str, bool]:
    """Resolve the enabled-module map. Never raises — falls back to safe defaults.

    Order: Redis cache → DB (``app_settings``) → ``DEFAULT_STATE``.
    """
    # 1) Redis read-through cache.
    if redis is not None:
        try:
            cached = await redis.get(REDIS_KEY)
            if cached:
                return _sanitize(json.loads(cached))
        except Exception:
            logger.warning(
                "modules: Redis read failed; falling through to DB", exc_info=True
            )

    # 2) Database (source of truth).
    try:
        row = await session.get(AppSetting, SETTINGS_KEY)
        if row is not None:
            if isinstance(row.value, dict):
                state = _sanitize(row.value)
                await prime_cache(redis, state)
                return state
            logger.warning(
                "modules: app_settings[%s] is not an object (%s); using defaults",
                SETTINGS_KEY,
                type(row.value).__name__,
            )
            return dict(DEFAULT_STATE)
        # Empty config is normal on a fresh DB — debug, not a warning.
        logger.debug("modules: no app_settings row; using defaults")
    except Exception:
        logger.warning(
            "modules: DB read failed; using safe defaults", exc_info=True
        )

    # 3) Safe fallback.
    return dict(DEFAULT_STATE)


async def set_module_enabled(
    session: AsyncSession, *, key: str, enabled: bool
) -> dict[str, bool]:
    """Toggle an Optional module. Flushes (caller commits). Returns the new state.

    Raises ``ModuleToggleError`` for unknown keys or Core (locked) modules.
    """
    if key not in MODULE_REGISTRY:
        raise ModuleToggleError(f"unknown module '{key}'")
    if key in CORE_KEYS:
        raise ModuleToggleError(f"module '{key}' is core and cannot be disabled")

    # Lock the settings row FOR UPDATE so concurrent toggles serialize on it.
    # This is a read-modify-write (read the JSON map, flip one key, write it back);
    # without the row lock two near-simultaneous toggles both read the old map and
    # the second write silently drops the first one's change (lost update). On
    # SQLite (fast test path) with_for_update is a no-op, but there is no real
    # concurrency there; the guarantee that matters is on Postgres in prod.
    row = (
        await session.execute(
            select(AppSetting)
            .where(AppSetting.key == SETTINGS_KEY)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        state = dict(DEFAULT_STATE)
        state[key] = bool(enabled)
        session.add(AppSetting(key=SETTINGS_KEY, value=state))
    else:
        current = row.value if isinstance(row.value, dict) else {}
        # Reassign a NEW dict so SQLAlchemy detects the change (column is plain
        # JSON/JSONB, not a MutableDict).
        row.value = {**_sanitize(current), key: bool(enabled)}

    await session.flush()
    new_state = await session.get(AppSetting, SETTINGS_KEY)
    return _sanitize(new_state.value if new_state else None)


async def prime_cache(redis: Optional[Redis], state: dict[str, bool]) -> None:
    """Write-through the resolved state into Redis. Best-effort (logged on fail)."""
    if redis is None:
        return
    try:
        await redis.set(REDIS_KEY, json.dumps(_sanitize(state)), ex=REDIS_TTL)
    except Exception:
        logger.warning("modules: Redis prime failed", exc_info=True)
