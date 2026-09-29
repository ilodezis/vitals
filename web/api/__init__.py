"""The JSON API the React app talks to, under ``/api/v1``.

Every route here sits behind the session guard (the router's own dependency), so
the app gains no anonymous surface. Endpoints only call ``vitals/services``; the
error bodies are one contract for the whole prefix (see ``web.api.errors``); the
typed schema for the client is dumped by ``scripts/dump_openapi.py`` — the app
itself publishes no schema.

A domain adds its router here. An optional module's router carries the same gate
the old pages get in ``web/main.py``, so a module switched off answers
``{"error": "module_disabled"}``::

    api_router.include_router(glp1.router, dependencies=[Depends(require_module("glp1"))])

A domain router also declares the session guard itself
(``ApiRouter(prefix=..., dependencies=[Depends(require_auth)])``). The guard on
``api_router`` is what answers 401 at runtime; the sweep in
``tests/test_anonymous_surface.py`` reads each route's own dependency tree, and a
guard held only by the parent router is not part of it.
"""
from __future__ import annotations

from fastapi import Depends

from web.api import (
    alerts,
    charts,
    garmin,
    genetics,
    glp1,
    hevy,
    hrt,
    interactions,
    labs,
    nutrition,
    reports,
    session,
    settings,
    share,
    signals,
    skincare,
    supplements,
    timeline,
    today,
    weight,
)
from web.api.errors import ApiRouter
from web.api.schemas.errors import NotFoundBody, UnauthenticatedBody
from web.deps import require_auth, require_module

api_router = ApiRouter(
    prefix="/api/v1",
    dependencies=[Depends(require_auth)],
    responses={401: {"model": UnauthenticatedBody}, 404: {"model": NotFoundBody}},
)

api_router.include_router(session.router)
api_router.include_router(today.router)
api_router.include_router(weight.router)
api_router.include_router(garmin.router)
api_router.include_router(hevy.router, dependencies=[Depends(require_module("hevy"))])
api_router.include_router(nutrition.router, dependencies=[Depends(require_module("nutrition"))])
api_router.include_router(glp1.router, dependencies=[Depends(require_module("glp1"))])
api_router.include_router(hrt.router, dependencies=[Depends(require_module("hrt"))])
api_router.include_router(labs.router, dependencies=[Depends(require_module("labs"))])
api_router.include_router(genetics.router, dependencies=[Depends(require_module("genetics"))])
api_router.include_router(supplements.router, dependencies=[Depends(require_module("supplements"))])
api_router.include_router(skincare.router, dependencies=[Depends(require_module("skincare"))])
api_router.include_router(interactions.router, dependencies=[Depends(require_module("interactions"))])
api_router.include_router(signals.router, dependencies=[Depends(require_module("signals"))])
api_router.include_router(timeline.router, dependencies=[Depends(require_module("timeline"))])
api_router.include_router(reports.router)
api_router.include_router(charts.router)
api_router.include_router(alerts.router)
api_router.include_router(share.router)
api_router.include_router(settings.router)

