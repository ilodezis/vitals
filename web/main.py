"""FastAPI application entrypoint for the Vitals panel.

Integrates the single-user auth exception handler, database session pooling,
Redis cache connection, and background APScheduler thread.
"""
from __future__ import annotations

import logging
import os
from contextlib import AsyncExitStack, asynccontextmanager
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, HTTPException, Request, status
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from web.api import api_router, errors as api_errors
from web.auth import router as auth_router
from web.compression import AppGZipMiddleware
from web.csrf import add_csrf_origin_check, add_security_headers
from web.deps import (
    ModuleDisabled,
    NotAuthenticated,
    get_redis_client,
    get_session_factory,
    get_session,
    get_redis,
    load_enabled_modules,
    load_language,
    require_auth,
    require_module,
)
from web.templating import STATIC_DIR, templates

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    session_factory = get_session_factory()
    redis = None
    try:
        redis = get_redis_client()
    except Exception as e:
        logger.warning("Redis client could not be loaded at startup: %s", e)

    # Scheduler setup
    from vitals.config import load_config
    from vitals.scheduler.jobs import register_all_jobs
    from vitals.scheduler.scheduler import seed_heartbeats, setup_scheduler
    from vitals.services import conflict_catalog, hrt_catalog
    from vitals.services.conflict_registrations import register_all_resolvers
    from vitals.services.proactive import prefs

    config = load_config()

    # Register cross-domain conflict resolvers (supplements/genetics/skincare/...).
    register_all_resolvers()
    # Upsert the curated rule catalog (vitals/data/conflict_rules.yaml) — cheap,
    # idempotent, and keeps the DB in sync with the checked-in YAML on every
    # deploy without a data migration per rule change.
    async with session_factory() as session:
        # Job schedules come from the DB (Settings → proactive), so the registry is
        # attached here rather than before the session opens.
        register_all_jobs(await prefs.get_prefs(session))
        await conflict_catalog.sync_catalog(session)
        # Upsert the curated HRT compound catalog (vitals/data/hrt_compounds.yaml).
        await hrt_catalog.sync_catalog(session)
        # Register the hormone/safety bloodwork panel in the Labs catalog.
        from vitals.services import hrt_reminders
        await hrt_reminders.seed_hormone_panel(session)
        await session.commit()

    if redis is not None:
        await seed_heartbeats(redis)

    scheduler = setup_scheduler(session_factory, redis, timezone=config.timezone)
    scheduler.start()
    app.state.scheduler = scheduler

    async with AsyncExitStack() as stack:
        # The mounted MCP app builds its streamable-HTTP session manager in its own
        # lifespan, which app.mount() never runs — without this every /mcp/ request
        # fails with "manager not initialized".
        mcp_lifespan = getattr(app.state, "mcp_lifespan", None)
        if mcp_lifespan is not None:
            await stack.enter_async_context(mcp_lifespan(app))
        yield

    # ── Shutdown ─────────────────────────────────────────────────────────────
    scheduler.shutdown()


app = FastAPI(
    title="Vitals Health OS",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    # The third door, and the one that stayed open while the other two were shut:
    # an anonymous GET /openapi.json listed every path in the app, which tells a
    # stranger exactly which health modules this install runs. Nothing here is a
    # public API — the schema has no audience.
    openapi_url=None,
    # Resolve the language and the enabled-module map once per request → request.state
    # (read by the server-rendered pages and the require_module guards).
    dependencies=[
        Depends(load_language),
        Depends(load_enabled_modules),
    ],
)

# Install security barriers
add_csrf_origin_check(app)
add_security_headers(app)
# Outermost, so it compresses the response the headers middleware has finished.
app.add_middleware(AppGZipMiddleware)

# ── Uploaded files ───────────────────────────────────────────────────────────
# Lab sheets, InBody printouts and progress photos are written under
# ``static/uploads`` so they survive a rebuild on the same bind mount as the rest
# of the assets — but they are the owner's medical records, not site furniture,
# and the mount below hands anything in ``static`` to whoever asks. A random file
# name is not an access control: the URL never expires, logging out does not
# revoke it, and it outlives the session in history, caches and proxy logs.
#
# So this route claims the subtree ahead of the mount and puts the same session
# guard on it as every page. It MUST stay above ``app.mount`` — routes match in
# registration order, and the mount would swallow the prefix first.
UPLOADS_DIR = os.path.realpath(os.path.join(STATIC_DIR, "uploads"))


@app.get("/static/uploads/{key:path}", dependencies=[Depends(require_auth)])
async def serve_upload(key: str):
    path = os.path.realpath(os.path.join(UPLOADS_DIR, key))
    # ``..`` (and any symlink out) resolves to somewhere else: a miss, not a read.
    if not path.startswith(UPLOADS_DIR + os.sep) or not os.path.isfile(path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    # Never written to disk cache: the file is readable again on the next request,
    # and a logged-out browser should keep nothing. Matches the service worker,
    # which already refuses to cache this prefix.
    return FileResponse(path, headers={"Cache-Control": "private, no-store"})


# Mount static files — everything else under /static is public site furniture
# (CSS, JS, fonts, icons), reachable before login because the login page needs it.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ── Exception Handlers ────────────────────────────────────────────────────────


@app.exception_handler(NotAuthenticated)
async def auth_exception_handler(request: Request, exc: NotAuthenticated):
    """Redirect unauthorized browser navigation to the login form,

    but return JSON 401 responses for background API/HTMX calls.

    Under ``/api/`` it is always JSON, whatever the client accepts: a fetch that
    followed a redirect would get the login page's HTML where it expects data.
    """
    if api_errors.is_api_request(request):
        return api_errors.unauthenticated()

    # Check if this request accepts HTML (standard browser GET)
    accept = request.headers.get("accept", "")
    is_html = "text/html" in accept

    if request.method == "GET" and is_html:
        # Preserve next parameter if redirecting
        next_param = str(request.url.path)
        if request.url.query:
            next_param += f"?{request.url.query}"
        login_url = "/login"
        if next_param not in ("", "/"):
            # Percent-encode next_param as a single query value — it can itself
            # contain '&'/'?' (e.g. redirecting back into an OAuth authorize
            # URL), which would otherwise be parsed as separate top-level params
            # on /login and silently truncate `next`.
            login_url += f"?{urlencode({'next': next_param})}"
        return RedirectResponse(url=login_url, status_code=status.HTTP_302_FOUND)

    return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "Not authenticated"})



async def _populate_state_for_error_page(request: Request) -> None:
    """Fill ``request.state.lang`` for the 404 page.

    An unmatched route never runs the global ``load_language`` dependency, because it
    fires only once a route matches; the page reads the language off ``request.state``.
    Resolve it here with a fresh session/redis, falling back to English so the page
    renders no matter what.
    """
    from vitals.i18n import current_lang
    from vitals.services import language_service

    lang = "en"
    try:
        redis = get_redis_client()
        async with get_session_factory()() as db:
            try:
                lang = await language_service.get_language(db, redis)
            except Exception:
                logger.exception("404 page: language load failed; defaulting to 'en'")
    except Exception:
        logger.exception("404 page: could not open db/redis; defaulting to 'en'")

    current_lang.set(lang)
    request.state.lang = lang


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Render a branded 404 page for browser navigations and keep JSON 404s for API calls."""
    if exc.status_code != status.HTTP_404_NOT_FOUND:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    if api_errors.is_api_request(request):
        return api_errors.not_found()

    accept = request.headers.get("accept", "")
    if request.method == "GET" and "text/html" in accept:
        # Unmatched routes skip the global load_* dependencies, so the language is
        # unset — populate it or the page renders in the wrong language.
        await _populate_state_for_error_page(request)
        return templates.TemplateResponse(
            request,
            "404.html",
            {"requested_path": request.url.path},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": exc.detail})


@app.exception_handler(ModuleDisabled)
async def module_disabled_handler(request: Request, exc: ModuleDisabled):
    """A disabled Optional module behaves as if absent: redirect browser GETs to
    Today, return JSON 404 for API calls."""
    if api_errors.is_api_request(request):
        return api_errors.module_disabled()

    accept = request.headers.get("accept", "")
    if request.method == "GET" and "text/html" in accept:
        return RedirectResponse(url="/today", status_code=status.HTTP_303_SEE_OTHER)
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": exc.detail})


# ── Health check ─────────────────────────────────────────────────────────────


@app.get("/health")
async def health(
    request: Request,
    db_session: AsyncSession = Depends(get_session),
    redis_client = Depends(get_redis)
):
    db_ok = False
    try:
        await db_session.execute(text("SELECT 1"))
        db_ok = True
    except Exception as e:
        logger.error("Healthcheck DB check failed: %s", e)

    redis_ok = False
    heartbeat_age = None
    stale_jobs = None
    try:
        await redis_client.ping()
        redis_ok = True

        from vitals.config import load_config
        from vitals.scheduler.scheduler import KEEPALIVE_JOB_ID, heartbeat_budgets
        from vitals.scheduler.scheduler_lock import scheduler_heartbeat_age

        # Every heartbeating job is checked against a budget derived from its own
        # schedule — watching the keepalive alone left a module job free to stop
        # firing while /health stayed green.
        stale_jobs = []
        for job_id, budget in heartbeat_budgets(load_config().timezone).items():
            age = await scheduler_heartbeat_age(redis_client, job_id)
            if job_id == KEEPALIVE_JOB_ID:
                heartbeat_age = age
            if age is None or age > budget:
                stale_jobs.append(job_id)
    except Exception as e:
        logger.error("Healthcheck Redis check failed: %s", e)

    scheduler_ok = stale_jobs is not None and not stale_jobs
    status_str = "ok" if (db_ok and redis_ok and scheduler_ok) else "error"

    body = {
        "status": status_str,
        "database": "ok" if db_ok else "down",
        "redis": "ok" if redis_ok else "down",
        "scheduler": "ok" if scheduler_ok else "stale",
    }

    # Job ids name the modules this install runs (``hrt_reminders``,
    # ``glp1_plateau``, ...), so a stranger must not read them. The endpoint still
    # answers anonymously — hiding it behind require_auth would make external
    # monitoring go quietly red — but the diagnosis is for the owner only. Read the
    # cookie by hand rather than via Depends: absence must not raise.
    from web.auth import read_session
    from web.config import SESSION_COOKIE

    if read_session(request.cookies.get(SESSION_COOKIE)) is not None:
        body["scheduler_heartbeat_age_seconds"] = heartbeat_age
        body["stale_jobs"] = stale_jobs or []

    return body


# ── Base redirection ──────────────────────────────────────────────────────────


@app.get("/")
async def root():
    return RedirectResponse(url="/today", status_code=status.HTTP_303_SEE_OTHER)


# ── Include Routers ───────────────────────────────────────────────────────────

app.include_router(auth_router)

# The JSON API for the React app — session-guarded as a whole, one error contract.
app.include_router(api_router)

# The React app: its shell on every screen's address (its assets ride the /static mount), and
# the permanent redirects from the addresses it used to live at.
from web.spa import router as spa_router  # noqa: E402

app.include_router(spa_router)

from web.routers.external_api import router as external_api_router  # noqa: E402
from web.routers.telegram import router as telegram_router  # noqa: E402
from web.routers.public_report import router as public_report_router  # noqa: E402
from web.routers.share import router as share_router  # noqa: E402

# The owner's report download — the one file the Share screen links to outside the JSON API.
app.include_router(share_router)
# Read-only JSON API for an external personal dashboard (Bearer-token guarded, not session auth).
app.include_router(external_api_router)
# Telegram webhook — its own secret path + header, no session auth.
app.include_router(telegram_router)
# The published doctor document. The ONE anonymous route in the app: no
# require_auth (the visitor has no account) and no require_module gate (the
# module set is already baked into the frozen snapshot). Its own, stricter CSP
# is set per response — see web/routers/public_report.py.
app.include_router(public_report_router)

# ── OAuth & MCP Integration ──────────────────────────────────────────────────
try:
    from web.routers.oauth import router as oauth_router  # noqa: E402
    from web.routers.mcp import get_mcp_app  # noqa: E402

    app.include_router(oauth_router)
    mcp_app, mcp_lifespan = get_mcp_app()
    app.mount("/mcp", mcp_app)
    app.state.mcp_lifespan = mcp_lifespan
except ImportError:
    import logging
    logging.getLogger(__name__).warning("MCP/OAuth disabled (fastmcp not available)")

