"""FastAPI dependencies: DB session, Redis, and the single-user auth guard.

The session factory and Redis client reuse the core's tuned setup and are built
lazily so tests can override them via ``app.dependency_overrides`` without a real
DB/Redis.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import AsyncIterator, Callable, Optional

from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from web.config import API_PATH_PREFIX, SESSION_COOKIE

from vitals.i18n import current_lang

logger = logging.getLogger(__name__)

# ── DB ───────────────────────────────────────────────────────────────────────
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None
_db_lock = threading.Lock()


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        with _db_lock:
            if _session_factory is None:
                from vitals.config import load_config
                from vitals.database import create_session_factory

                _session_factory = create_session_factory(load_config())
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── Redis ────────────────────────────────────────────────────────────────────
_redis: Optional[Redis] = None
_redis_lock = threading.Lock()


def get_redis_client() -> Redis:
    global _redis
    if _redis is None:
        with _redis_lock:
            if _redis is None:
                url = os.getenv("VITALS_REDIS_URL", "redis://vitals_redis:6379/0")
                _redis = Redis.from_url(url, decode_responses=True)
    return _redis


async def get_redis() -> Redis:
    return get_redis_client()


# ── Auth guard ───────────────────────────────────────────────────────────────
class NotAuthenticated(HTTPException):
    """401 that the app's exception handler turns into a /login redirect for
    HTML GETs (and leaves as JSON 401 for API calls)."""

    def __init__(self) -> None:
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


async def require_auth(request: Request) -> str:
    """Guard every protected route. Returns the authenticated username or raises."""
    # Lazy import breaks the web.auth ↔ web.deps cycle: auth.py imports the login
    # rate-limiter (web.ratelimit → web.deps), so deps must not import auth at
    # module-load time.
    from web.auth import read_session

    token = request.cookies.get(SESSION_COOKIE)
    username = read_session(token)
    if username is None:
        raise NotAuthenticated()
    return username


# ── Dashboard modules ──────────────────────────────────────────────────────────
class ModuleDisabled(HTTPException):
    """Raised when an Optional module's route is hit while the module is off.

    The app's exception handler turns this into a redirect to the dashboard for
    HTML GETs (and a JSON 404 for API calls) — a disabled module behaves as if it
    isn't there."""

    def __init__(self, key: str) -> None:
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=f"Module '{key}' is disabled")
        self.key = key


async def load_enabled_modules(
    request: Request,
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> None:
    """Global dependency: resolve the enabled-module map once per request and stash
    it on ``request.state`` so every template (notably base.html nav) can read it
    without each router passing it through context.

    Fail-safe: any error yields the safe defaults — the chrome must always render.
    """
    from vitals.services import modules_service

    try:
        request.state.enabled_modules = await modules_service.get_enabled_modules(db, redis)
    except Exception:
        logger.exception("module-state load failed; using safe defaults")
        request.state.enabled_modules = dict(modules_service.DEFAULT_STATE)


async def load_nav_status(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> None:
    """Global dependency: today's readout for the nav rail's status card (and the
    phone's "More" screen), stashed on ``request.state``.

    Only for document requests: the rail is chrome, so an MCP call or a JSON API
    read would pay four pointless queries for markup it never renders.

    "Is this a document request" is decided by ruling API clients OUT, not by
    requiring ``text/html`` in. **A boosted navigation sends no Accept header at
    all** — htmx leaves XHR's default alone — so requiring ``text/html`` skipped
    the reads on exactly the requests that re-render the whole rail, and the card
    blinked out of existence on every click and back on every reload. A missing
    or wildcard Accept now counts as a document; only a client that explicitly
    asks for something else (``application/json``, ``text/event-stream``) is
    skipped.

    Fail-safe: any error yields an empty list — the card just doesn't draw.
    """
    request.state.nav_status = []
    accept = request.headers.get("accept", "")
    if request.method != "GET":
        return
    if accept and "text/html" not in accept and "*/*" not in accept:
        return
    # A fetch sends ``Accept: */*``, which counts as a document above — but the
    # API serves the card's numbers itself (``/api/v1/session``), so paying for
    # them on every call would run the four reads twice. The React app's shell
    # (``/app/...``, web/spa.py) is a document that draws no rail either: the app
    # reads the same numbers from ``/api/v1/session`` as soon as it boots.
    path = request.url.path
    if path == "/app" or path.startswith((API_PATH_PREFIX, "/app/")):
        return
    from vitals.services import nav_status_service

    try:
        request.state.nav_status = await nav_status_service.rail_stats(
            db, getattr(request.state, "enabled_modules", None)
        )
    except Exception:
        logger.exception("nav status load failed; hiding the status card")


async def load_language(
    request: Request,
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> None:
    """Global dependency: resolve the UI language once per request and stash
    it on ``request.state`` + the ``ContextVar`` so both templates and deep
    service code (like ``raise_alert``) can read it without extra arguments.

    Fail-safe: any error yields ``"en"`` — the UI must always render.
    """
    from vitals.services import language_service

    try:
        lang = await language_service.get_language(db, redis)
    except Exception:
        logger.exception("language load failed; defaulting to 'en'")
        lang = "en"
    current_lang.set(lang)
    request.state.lang = lang




def require_module(key: str) -> Callable:
    """Build a dependency that 404s (→ redirect) when module ``key`` is disabled.

    Relies on ``load_enabled_modules`` having populated ``request.state`` first
    (it runs as a global dependency, before route-level ones)."""

    async def _dep(request: Request) -> None:
        enabled = getattr(request.state, "enabled_modules", None) or {}
        if not enabled.get(key, False):
            raise ModuleDisabled(key)

    return _dep
