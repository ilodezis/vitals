"""``/api/v1/charts`` — Custom metric charts endpoints."""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, Request, Response, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.services import charts_service
from web.api.errors import ApiRouter, not_found
from web.api.schemas.charts import ChartCreateRequest, ChartCreated, ChartsView
from web.deps import get_redis, get_session, require_auth

router = ApiRouter(prefix="/charts", dependencies=[Depends(require_auth)])


@router.get("", response_model=ChartsView)
async def read_charts(
    request: Request,
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> ChartsView:
    """The charts gallery: saved custom charts with resolved data series, plus metric catalog."""
    lang = getattr(request.state, "lang", "ru")
    enabled = getattr(request.state, "enabled_modules", None) or {}

    data = await charts_service.collect(db, redis, enabled, lang=lang)
    return ChartsView.model_validate(data)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ChartCreated,
)
async def create_chart(
    body: ChartCreateRequest,
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> ChartCreated:
    """Create a new custom chart configuration."""
    if not body.name or not body.name.strip():
        raise ValueError("name is required")
    if not body.series:
        raise ValueError("at least one series is required")

    series_dicts = [
        {
            "domain": s.domain,
            "metric_key": s.metric_key,
            "param": s.param,
            "label": s.label,
        }
        for s in body.series
        if s.metric_key
    ]

    res = await charts_service.create_chart(
        db,
        name=body.name.strip(),
        series=series_dicts,
        normalize=body.normalize,
        redis=redis,
    )
    await db.commit()
    return ChartCreated(id=res["id"])


@router.delete("/{chart_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chart(
    chart_id: str,
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
):
    """Delete a saved custom chart."""
    if not await charts_service.delete_chart(db, chart_id, redis=redis):
        return not_found()
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
