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
"""
from __future__ import annotations

from fastapi import Depends

from web.api import session
from web.api.errors import ApiRouter
from web.api.schemas.errors import NotFoundBody, UnauthenticatedBody
from web.deps import require_auth

api_router = ApiRouter(
    prefix="/api/v1",
    dependencies=[Depends(require_auth)],
    responses={401: {"model": UnauthenticatedBody}, 404: {"model": NotFoundBody}},
)

api_router.include_router(session.router)
