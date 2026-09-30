"""The React app's HTML shell, served on the site's own paths behind the login.

Vite builds into ``web/static/app``. The hashed JS/CSS/fonts it emits ride the
existing public ``/static`` mount (their year-long cache is set in
``web/csrf.py``), so the app adds no anonymous surface of its own. Only the shell
is served here, for every screen's address, so a deep link or a reload lands on the
client router instead of a 404. Like every page it depends on ``require_auth``: a
stranger's browser is sent to ``/login?next=...`` by the ``NotAuthenticated``
handler in ``web/main.py``.

A screen of an optional module is gated like the module's API: while the module is
off the address behaves as if absent (``ModuleDisabled`` sends the browser to Today).

Addresses the app used to live at (``/app/...``, ``/garmin``, ``/hevy``) are
permanent redirects, so a bookmark or an installed app's saved page keeps working.
"""
from __future__ import annotations

import os
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse

from web.deps import require_auth, require_module
from web.templating import STATIC_DIR

# Read on every request, not at import: a rebuild is picked up without a restart.
SPA_INDEX = os.path.join(STATIC_DIR, "app", "index.html")

# Every address the client router owns, with the module that switches it on (``None``: always
# there). Keep in step with ``SCREEN_PATH`` in ``frontend/src/components/shell/nav.ts``.
SPA_SCREENS: tuple[tuple[str, Optional[str]], ...] = (
    ("/today", None),
    ("/more", None),
    ("/weight", None),
    ("/weight/measures", None),
    ("/recovery", None),
    ("/recovery/sleep", None),
    ("/recovery/sleep/{on_date}", None),
    ("/recovery/nights", None),
    ("/recovery/activities", None),
    ("/workouts", "hevy"),
    ("/nutrition", "nutrition"),
    ("/glp1", "glp1"),
    ("/hrt", "hrt"),
    ("/labs", None),
    ("/genetics", "genetics"),
    ("/supplements", "supplements"),
    ("/skincare", "skincare"),
    ("/interactions", "interactions"),
    ("/signals", "signals"),
    ("/timeline", "timeline"),
    ("/reports", None),
    ("/charts", None),
    ("/share", None),
    ("/settings", None),
)

router = APIRouter(dependencies=[Depends(require_auth)])


def _serve_shell():
    if not os.path.isfile(SPA_INDEX):
        return PlainTextResponse("frontend not built", status_code=503)
    # The shell names the current asset hashes; a cached copy would boot a build
    # whose files are already gone.
    return FileResponse(SPA_INDEX, media_type="text/html", headers={"Cache-Control": "no-store"})


def _register_screen(path: str, module: Optional[str]) -> None:
    dependencies = [] if module is None else [Depends(require_module(module))]

    async def shell():
        return _serve_shell()

    router.add_api_route(path, shell, methods=["GET"], include_in_schema=False, dependencies=dependencies)


for _path, _module in SPA_SCREENS:
    _register_screen(_path, _module)


# ── Old addresses ────────────────────────────────────────────────────────────


def _moved(request: Request, path: str) -> RedirectResponse:
    target = path if not request.url.query else f"{path}?{request.url.query}"
    return RedirectResponse(url=target, status_code=301)


@router.get("/app", include_in_schema=False)
@router.get("/app/", include_in_schema=False)
async def app_root(request: Request):
    return _moved(request, "/today")


@router.get("/app/{path:path}", include_in_schema=False)
async def app_path(path: str, request: Request):
    # Leading slashes stripped: "/app//host" must not become the protocol-relative "//host".
    return _moved(request, "/" + quote(path.lstrip("/"), safe="/"))


@router.get("/garmin", include_in_schema=False)
async def garmin_root(request: Request):
    return _moved(request, "/recovery")


@router.get("/garmin/{path:path}", include_in_schema=False)
async def garmin_path(path: str, request: Request):
    return _moved(request, "/recovery/" + quote(path.lstrip("/"), safe="/"))


@router.get("/hevy", include_in_schema=False)
async def hevy_root(request: Request):
    return _moved(request, "/workouts")
