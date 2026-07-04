"""Custom chart builder — saved configurations.

Storage: one ``app_settings`` row, ``key='custom_charts'``, ``value`` a JSON
array of chart configs (not an object — this key just happens to hold a list).
Redis (``settings:custom_charts``) is a read-through cache; the DB is the
source of truth. Same shape as ``modules_service``/``ui_version_service``:
``_sanitize()`` never raises, projecting arbitrary stored data onto a clean
shape so a corrupt row degrades to an empty list instead of 500-ing.

A chart config::

    {
      "id": "9f3a1c2b7e4d",
      "name": "Вес и стресс",
      "normalize": false,
      "series": [
        {"domain": "weight", "metric_key": "weight.weight_kg", "param": null,
         "label": null, "color_slot": 0},
        ...
      ]
    }
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Optional

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.models.app_settings import AppSetting
from vitals.services.analytics import chart_registry

logger = logging.getLogger(__name__)

SETTINGS_KEY = "custom_charts"
REDIS_KEY = "settings:custom_charts"
REDIS_TTL = 300

MAX_SERIES_PER_CHART = 8   # matches the 8-slot categorical palette
MAX_CHARTS = 50


class ChartConfigError(ValueError):
    """Raised when a chart config fails validation (unknown metric, missing
    param, bad name/series count). Routers map this to a 4xx redirect."""


def _sanitize_series(raw: Any) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for i, item in enumerate(raw[:MAX_SERIES_PER_CHART]):
        if not isinstance(item, dict) or not item.get("metric_key"):
            continue
        out.append({
            "domain": item.get("domain"),
            "metric_key": item.get("metric_key"),
            "param": item.get("param"),
            "label": item.get("label"),
            "color_slot": item.get("color_slot") if isinstance(item.get("color_slot"), int) else i,
        })
    return out


def _sanitize(raw: Any) -> list[dict]:
    """Project arbitrary stored data onto a clean list of chart configs.

    Drops entries missing id/name/series, caps series-per-chart and
    charts-per-list. Unknown ``metric_key`` values are KEPT here (only
    resolution at read time drops them) so a disabled module's charts still
    list — they'll just resolve to fewer series."""
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw[:MAX_CHARTS]:
        if not isinstance(item, dict):
            continue
        chart_id = item.get("id")
        name = item.get("name")
        series = _sanitize_series(item.get("series"))
        if not chart_id or not name or not series:
            continue
        out.append({
            "id": str(chart_id),
            "name": str(name),
            "normalize": bool(item.get("normalize", False)),
            "series": series,
        })
    return out


async def list_charts(session: AsyncSession, redis: Optional[Redis] = None) -> list[dict]:
    """Resolve the saved chart list. Never raises — falls back to ``[]``.

    Order: Redis cache → DB (``app_settings``) → ``[]``.
    """
    if redis is not None:
        try:
            cached = await redis.get(REDIS_KEY)
            if cached:
                return _sanitize(json.loads(cached))
        except Exception:
            logger.warning(
                "custom_charts: Redis read failed; falling through to DB", exc_info=True
            )

    try:
        row = await session.get(AppSetting, SETTINGS_KEY)
        if row is not None:
            if isinstance(row.value, list):
                charts = _sanitize(row.value)
                await prime_cache(redis, charts)
                return charts
            logger.warning(
                "custom_charts: app_settings[%s] is not an array (%s); using []",
                SETTINGS_KEY,
                type(row.value).__name__,
            )
            return []
        logger.debug("custom_charts: no app_settings row; using []")
    except Exception:
        logger.warning("custom_charts: DB read failed; using []", exc_info=True)

    return []


async def get_chart(
    session: AsyncSession, chart_id: str, redis: Optional[Redis] = None
) -> Optional[dict]:
    charts = await list_charts(session, redis)
    for c in charts:
        if c["id"] == chart_id:
            return c
    return None


def _validate_series(series: list[dict]) -> None:
    if not series:
        raise ChartConfigError("a chart needs at least one series")
    if len(series) > MAX_SERIES_PER_CHART:
        raise ChartConfigError(f"a chart can have at most {MAX_SERIES_PER_CHART} series")
    for s in series:
        metric_key = s.get("metric_key")
        if not metric_key:
            raise ChartConfigError("every series needs a metric_key")
        try:
            field = chart_registry.get(metric_key)
        except KeyError:
            raise ChartConfigError(f"unknown metric_key '{metric_key}'") from None
        has_param = bool(s.get("param"))
        if field.param_kind != "none" and not has_param:
            raise ChartConfigError(f"metric '{metric_key}' requires a param")
        if field.param_kind == "none" and has_param:
            raise ChartConfigError(f"metric '{metric_key}' does not take a param")


async def create_chart(
    session: AsyncSession,
    *,
    name: str,
    series: list[dict],
    normalize: bool = False,
    redis: Optional[Redis] = None,
) -> dict:
    """Validate and append a new chart config. Flushes (caller commits).

    Raises ``ChartConfigError`` on any validation failure — nothing is
    persisted in that case."""
    name = (name or "").strip()
    if not name:
        raise ChartConfigError("chart name is required")
    if len(name) > 80:
        raise ChartConfigError("chart name must be at most 80 characters")
    _validate_series(series)

    row = await session.get(AppSetting, SETTINGS_KEY)
    current = _sanitize(row.value) if row is not None else []
    if len(current) >= MAX_CHARTS:
        raise ChartConfigError(f"at most {MAX_CHARTS} custom charts are allowed")

    new_chart = {
        "id": uuid.uuid4().hex[:12],
        "name": name,
        "normalize": bool(normalize),
        "series": [
            {
                "domain": s.get("domain"),
                "metric_key": s["metric_key"],
                "param": s.get("param"),
                "label": s.get("label"),
                "color_slot": idx,
            }
            for idx, s in enumerate(series[:MAX_SERIES_PER_CHART])
        ],
    }
    updated = [*current, new_chart]

    if row is None:
        session.add(AppSetting(key=SETTINGS_KEY, value=updated))
    else:
        # Reassign a NEW list so SQLAlchemy detects the change (plain JSON/JSONB
        # column, not a MutableList).
        row.value = updated

    await session.flush()
    await prime_cache(redis, updated)
    return new_chart


async def delete_chart(
    session: AsyncSession, chart_id: str, redis: Optional[Redis] = None
) -> bool:
    """Remove one chart by id. Returns False if it wasn't found."""
    row = await session.get(AppSetting, SETTINGS_KEY)
    if row is None:
        return False
    current = _sanitize(row.value)
    remaining = [c for c in current if c["id"] != chart_id]
    if len(remaining) == len(current):
        return False
    row.value = remaining
    await session.flush()
    await prime_cache(redis, remaining)
    return True


async def prime_cache(redis: Optional[Redis], charts: list[dict]) -> None:
    """Write-through the resolved list into Redis. Best-effort (logged on fail)."""
    if redis is None:
        return
    try:
        await redis.set(REDIS_KEY, json.dumps(_sanitize(charts)), ex=REDIS_TTL)
    except Exception:
        logger.warning("custom_charts: Redis prime failed", exc_info=True)
