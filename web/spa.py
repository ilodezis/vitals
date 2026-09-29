"""The React app's HTML shell, served at ``/app`` behind the login.

Vite builds into ``web/static/app``. The hashed JS/CSS/fonts it emits ride the
existing public ``/static`` mount (their year-long cache is set in
``web/csrf.py``), so the app adds no anonymous surface of its own. Only the shell
is served here, for every ``/app`` path, so a deep link or a reload lands on the
client router instead of a 404. Like every page it depends on ``require_auth``: a
stranger's browser is sent to ``/login?next=...`` by the ``NotAuthenticated``
handler in ``web/main.py``.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, PlainTextResponse

from web.deps import require_auth
from web.templating import STATIC_DIR

# Read on every request, not at import: a rebuild is picked up without a restart.
SPA_INDEX = os.path.join(STATIC_DIR, "app", "index.html")

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/app", include_in_schema=False)
@router.get("/app/{path:path}", include_in_schema=False)
async def app_shell(path: str = ""):
    if not os.path.isfile(SPA_INDEX):
        return PlainTextResponse("frontend not built", status_code=503)
    # The shell names the current asset hashes; a cached copy would boot a build
    # whose files are already gone.
    return FileResponse(SPA_INDEX, media_type="text/html", headers={"Cache-Control": "no-store"})
