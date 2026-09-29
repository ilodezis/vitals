"""``GET /api/v1/today``."""
from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.services import modules_service, today_service
from web.api.errors import ApiRouter
from web.api.schemas.today import TodayView
from web.deps import get_session, require_auth

router = ApiRouter(prefix="/today", dependencies=[Depends(require_auth)])


@router.get("", response_model=TodayView)
async def read_today(request: Request, db: AsyncSession = Depends(get_session)) -> TodayView:
    """The whole Today screen in one request: figures, the week's changes, the day's
    feed, what needs attention and the goal. A module that is switched off
    contributes nothing: no calories or meals without nutrition, no timeline rows
    without the timeline."""
    enabled = getattr(request.state, "enabled_modules", None) or dict(
        modules_service.DEFAULT_STATE
    )
    data = await today_service.collect(db, enabled_modules=enabled, weigh_ins=True)
    return TodayView.model_validate(data)
