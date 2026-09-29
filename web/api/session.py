"""``GET /api/v1/session``."""
from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.services import modules_service, nav_status_service
from web.api.errors import ApiRouter
from web.api.schemas.session import Nav, NavItem, NavSlot, RailStat, SessionView
from web.deps import get_session, require_auth

router = ApiRouter()


@router.get("/session", response_model=SessionView)
async def read_session(
    request: Request,
    username: str = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> SessionView:
    """Who is signed in, the UI language, and everything the shell draws from: the
    module switches, the navigation built from them, the rail's status card."""
    # The module map and the language are the ones the app already resolved for
    # this request (``load_enabled_modules`` / ``load_language``): nothing is read
    # twice.
    enabled = getattr(request.state, "enabled_modules", None) or dict(
        modules_service.DEFAULT_STATE
    )
    return SessionView(
        username=username,
        lang=getattr(request.state, "lang", "en"),
        enabled_modules=enabled,
        nav=Nav(
            items=[NavItem.model_validate(s) for s in modules_service.nav_modules(enabled)],
            bottom_slots=[
                NavSlot.model_validate(s) for s in modules_service.bottom_slots(enabled)
            ],
            more_rubrics=modules_service.more_rubrics(enabled),
            more_routes=list(modules_service.more_routes(enabled)),
        ),
        rail=[
            RailStat.model_validate(s)
            for s in await nav_status_service.rail_stats_raw(db, enabled)
        ],
    )
