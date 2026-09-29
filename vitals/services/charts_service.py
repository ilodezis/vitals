"""Charts service — custom metric charts and constructor."""
from __future__ import annotations

from typing import Any, Optional

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.services import chart_data_service, custom_charts_service


async def _overlays_by_chart(
    session: AsyncSession, charts: list[dict]
) -> dict[str, list[dict]]:
    """Manual Timeline flags for each saved chart — the union of its series'
    domains, deduped (a global flag would otherwise repeat once per domain)."""
    from vitals.services import timeline_service

    result: dict[str, list[dict]] = {}
    for c in charts:
        domains = {s.get("domain") for s in c.get("series", []) if s.get("domain")}
        seen: set[tuple] = set()
        merged: list[dict] = []
        for d in domains:
            for o in await timeline_service.overlays_for(session, domain=d):
                key = (o["start"], o["end"], o["label"])
                if key in seen:
                    continue
                seen.add(key)
                merged.append(o)
        result[c["id"]] = merged
    return result


async def collect(
    session: AsyncSession,
    redis: Optional[Redis] = None,
    enabled_modules: Optional[dict[str, bool]] = None,
    *,
    lang: str = "ru",
) -> dict[str, Any]:
    """Collect everything needed by the Charts dashboard in one round-trip."""
    enabled = enabled_modules or {}
    catalog = await chart_data_service.build_catalog(session, enabled, lang=lang)
    saved_charts = await custom_charts_service.list_charts(session, redis)

    chart_items: list[dict[str, Any]] = []
    overlays_map = (
        await _overlays_by_chart(session, saved_charts)
        if enabled.get("timeline", True)
        else {}
    )

    for c in saved_charts:
        series_data = await chart_data_service.resolve_chart_series(
            session, c, lang=lang
        )
        chart_items.append(
            {
                "id": c["id"],
                "name": c["name"],
                "normalize": c.get("normalize", False),
                "series": series_data,
                "overlays": overlays_map.get(c["id"], []),
            }
        )

    return {
        "charts": chart_items,
        "catalog": catalog,
        "count": len(chart_items),
        "empty": len(chart_items) == 0,
    }


async def create_chart(
    session: AsyncSession,
    *,
    name: str,
    series: list[dict[str, Any]],
    normalize: bool = False,
    redis: Optional[Redis] = None,
) -> dict[str, Any]:
    """Create a new custom chart configuration."""
    row = await custom_charts_service.create_chart(
        session, name=name, series=series, normalize=normalize, redis=redis
    )
    return row


async def delete_chart(
    session: AsyncSession,
    chart_id: str,
    redis: Optional[Redis] = None,
) -> bool:
    """Delete a saved custom chart."""
    return await custom_charts_service.delete_chart(session, chart_id, redis=redis)
