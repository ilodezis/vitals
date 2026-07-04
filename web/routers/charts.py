"""Custom chart builder — a Core, cross-domain utility (not gated by any single
Optional module, since it exists specifically to overlay metrics *across*
domains)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.services import chart_data_service, custom_charts_service
from vitals.services.custom_charts_service import ChartConfigError
from web.deps import get_redis, get_session, require_auth
from web.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/charts", tags=["charts"])


@router.get("", response_class=HTMLResponse)
async def charts_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    username: str = Depends(require_auth),
):
    lang = getattr(request.state, "lang", "ru")
    enabled = getattr(request.state, "enabled_modules", None) or {}

    catalog = await chart_data_service.build_catalog(db, enabled, lang=lang)
    charts = await custom_charts_service.list_charts(db, redis)
    resolved = {
        c["id"]: await chart_data_service.resolve_chart_series(db, c, lang=lang)
        for c in charts
    }

    return templates.TemplateResponse(
        request,
        "charts/index.html",
        {
            "username": username,
            "catalog": catalog,
            "charts": charts,
            "resolved": resolved,
            "error": request.query_params.get("error"),
        },
    )


@router.post("")
async def create_chart(
    request: Request,
    name: str = Form(...),
    domain: list[str] = Form([]),
    metric_key: list[str] = Form([]),
    param: list[str] = Form([]),
    normalize: bool = Form(False),
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    username: str = Depends(require_auth),
):
    series = [
        {"domain": d, "metric_key": mk, "param": (p.strip() or None)}
        for d, mk, p in zip(domain, metric_key, param)
        if mk
    ]
    try:
        await custom_charts_service.create_chart(
            db, name=name.strip(), series=series, normalize=normalize, redis=redis
        )
        await db.commit()
    except ChartConfigError as e:
        logger.warning("custom chart rejected: %s", e)
        return _redirect(request, "?error=invalid")
    return _redirect(request)


@router.post("/{chart_id}/delete")
async def delete_chart_entry(
    request: Request,
    chart_id: str,
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    username: str = Depends(require_auth),
):
    await custom_charts_service.delete_chart(db, chart_id, redis=redis)
    await db.commit()
    return _redirect(request)


def _redirect(request: Request, suffix: str = "") -> RedirectResponse:
    url = f"/charts{suffix}"
    response = RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)
    if "hx-request" in request.headers:
        response.headers["HX-Redirect"] = url
    return response
