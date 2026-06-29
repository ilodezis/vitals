"""FastAPI application entrypoint for the Vitals panel.

Integrates the single-user auth exception handler, database session pooling,
Redis cache connection, and background APScheduler thread.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from web.auth import router as auth_router
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
    require_module,
)
from web.templating import STATIC_DIR

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
    from vitals.services.conflict_registrations import register_all_resolvers

    config = load_config()

    # Attach per-module jobs before the scheduler reads the registry.
    register_all_jobs()
    # Register cross-domain conflict resolvers (supplements/genetics/skincare).
    register_all_resolvers()

    if redis is not None:
        await seed_heartbeats(redis)

    scheduler = setup_scheduler(session_factory, redis, timezone=config.timezone)
    scheduler.start()
    app.state.scheduler = scheduler

    yield

    # ── Shutdown ─────────────────────────────────────────────────────────────
    scheduler.shutdown()


app = FastAPI(
    title="Vitals Health OS",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    # Resolve the enabled-module map once per request → request.state (read by
    # base.html nav and the require_module guards below).
    dependencies=[Depends(load_language), Depends(load_enabled_modules)],
)

# Install security barriers
add_csrf_origin_check(app)
add_security_headers(app)

# Mount static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ── Exception Handlers ────────────────────────────────────────────────────────


@app.exception_handler(NotAuthenticated)
async def auth_exception_handler(request: Request, exc: NotAuthenticated):
    """Redirect unauthorized browser navigation to the login form,

    but return JSON 401 responses for background API/HTMX calls.
    """
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
            login_url += f"?next={next_param}"
        return RedirectResponse(url=login_url, status_code=status.HTTP_302_FOUND)

    return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "Not authenticated"})


@app.exception_handler(ModuleDisabled)
async def module_disabled_handler(request: Request, exc: ModuleDisabled):
    """A disabled Optional module behaves as if absent: redirect browser GETs to
    the dashboard, return JSON 404 for API/HTMX calls."""
    accept = request.headers.get("accept", "")
    if request.method == "GET" and "text/html" in accept:
        return RedirectResponse(url="/weight", status_code=status.HTTP_303_SEE_OTHER)
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": exc.detail})


# ── Health check ─────────────────────────────────────────────────────────────


@app.get("/health")
async def health(
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
    try:
        await redis_client.ping()
        redis_ok = True

        from vitals.scheduler.scheduler import KEEPALIVE_JOB_ID
        from vitals.scheduler.scheduler_lock import scheduler_heartbeat_age

        heartbeat_age = await scheduler_heartbeat_age(redis_client, KEEPALIVE_JOB_ID)
    except Exception as e:
        logger.error("Healthcheck Redis check failed: %s", e)

    # We allow the heartbeat age to be up to 120s (since it runs every 60s)
    scheduler_ok = heartbeat_age is not None and heartbeat_age < 120.0
    status_str = "ok" if (db_ok and redis_ok and scheduler_ok) else "error"

    return {
        "status": status_str,
        "database": "ok" if db_ok else "down",
        "redis": "ok" if redis_ok else "down",
        "scheduler_heartbeat_age_seconds": heartbeat_age,
    }


# ── Base redirection ──────────────────────────────────────────────────────────


@app.get("/")
async def root():
    return RedirectResponse(url="/weight", status_code=status.HTTP_303_SEE_OTHER)


# ── Include Routers ───────────────────────────────────────────────────────────

app.include_router(auth_router)

# Routers under web/routers/ will be included dynamically to avoid import cycles.
# These routers will be imported and registered below.
from web.routers.alerts import router as alerts_router  # noqa: E402
from web.routers.weight import router as weight_router  # noqa: E402
from web.routers.glp1 import router as glp1_router  # noqa: E402
from web.routers.supplements import router as supplements_router  # noqa: E402
from web.routers.genetics import router as genetics_router  # noqa: E402
from web.routers.skincare import router as skincare_router  # noqa: E402
from web.routers.hevy import router as hevy_router  # noqa: E402
from web.routers.garmin import router as garmin_router  # noqa: E402
from web.routers.labs import router as labs_router  # noqa: E402
from web.routers.reports import router as reports_router  # noqa: E402
from web.routers.nutrition import router as nutrition_router  # noqa: E402
from web.routers.settings import router as settings_router  # noqa: E402

# Core modules — always reachable.
app.include_router(alerts_router)
app.include_router(weight_router)
app.include_router(garmin_router)
app.include_router(labs_router)
app.include_router(reports_router)
app.include_router(settings_router)

# Optional modules — guarded: a disabled module's routes 404 → redirect to /weight.
app.include_router(glp1_router, dependencies=[Depends(require_module("glp1"))])
app.include_router(hevy_router, dependencies=[Depends(require_module("hevy"))])
app.include_router(supplements_router, dependencies=[Depends(require_module("supplements"))])
app.include_router(genetics_router, dependencies=[Depends(require_module("genetics"))])
app.include_router(skincare_router, dependencies=[Depends(require_module("skincare"))])
app.include_router(nutrition_router, dependencies=[Depends(require_module("nutrition"))])

# ── OAuth & MCP Integration ──────────────────────────────────────────────────
try:
    from web.routers.oauth import router as oauth_router  # noqa: E402
    from web.routers.mcp import get_mcp_app  # noqa: E402

    app.include_router(oauth_router)
    app.mount("/mcp", get_mcp_app())
except ImportError:
    import logging
    logging.getLogger(__name__).warning("MCP/OAuth disabled (fastmcp not available)")

