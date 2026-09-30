"""CSRF origin check + security headers (ported from Boxly's ``web/csrf.py``).

Session cookies are ``SameSite=lax`` (primary CSRF defence). This adds a second,
independent barrier: unsafe-method requests carrying a cross-origin ``Origin``
header are rejected. The CSP allows scripts only from our own origin: no inline
script and no ``eval`` (the React app compiles nothing at runtime).
"""
from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


async def _origin_check(request: Request, call_next):
    path = request.url.path
    # Server-to-server callers that authenticate with their own secret, not a
    # session cookie: MCP, the OAuth token exchange, and the Telegram webhook
    # (which a forged Origin header would otherwise 403 instead of ignore).
    if path.startswith("/mcp") or path.startswith("/tg/") or path == "/oauth/token":
        return await call_next(request)

    if request.method not in _SAFE_METHODS:
        origin = request.headers.get("origin")
        if origin:
            host = request.headers.get("host", "")
            if urlsplit(origin).netloc != host:
                return PlainTextResponse("Origin not allowed.", status_code=403)
    return await call_next(request)



def add_csrf_origin_check(app: FastAPI) -> None:
    app.middleware("http")(_origin_check)


# Scripts come only from our own origin — no 'unsafe-inline', no 'unsafe-eval'. The app is a
# React build (hashed files under /static/app) and the few server-rendered pages keep their
# behaviour in /static/server-pages.js, so nothing needs an inline script. The one outside
# host is Cloudflare's Web Analytics beacon, which Cloudflare injects at the edge (into the
# proxied HTML response) rather than anything we load, so it needs its own
# script-src/connect-src entries or the browser blocks it outright.
# style-src keeps 'unsafe-inline': the app's motion writes inline styles (Web Animations,
# transforms set from gestures) and the server pages carry their own <style>. img-src
# data:/blob: cover inline SVG and the photo previews. Fonts (Geologica / Golos Text) are
# self-hosted woff2, so font-src stays 'self'.
#
# form-action allows any https target, not just 'self': the consent form posts to
# /oauth/authorize/approve, that response 302s to the connector's callback, and the
# connector bounces on through hosts of its own — Chrome enforces form-action across
# the entire redirect chain, and a chain inside somebody else's product can't be
# enumerated here. Failure mode when it is too narrow: the "Approve" click does
# nothing, and the console names the *form action* instead of the blocked hop, which
# reads like a same-origin violation and sends you looking in the wrong place. The
# real gate on where an approval may land is redirect_allowed() in the OAuth router.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' https://static.cloudflareinsights.com; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob: https:; "
    "font-src 'self'; "
    "connect-src 'self' https://cloudflareinsights.com; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self' https:"
)
_SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": _CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


# The React app's build (Vite ``outDir``). Everything under ``assets/`` is named
# after its content hash, so a changed file is a new URL and the old one can be
# kept forever. Only answers that are the file itself: a miss mid-deploy must not
# stick in the browser as a year-long 404.
_APP_ASSETS_PREFIX = "/static/app/assets/"
_APP_SERVICE_WORKER = "/static/app/sw.js"
_CACHEABLE_STATUSES = frozenset({200, 304})


async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    for name, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)

    content_type = response.headers.get("content-type", "").lower()
    path = request.url.path
    is_file = response.status_code in _CACHEABLE_STATUSES

    if is_file and path.startswith(_APP_ASSETS_PREFIX):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"

    # Served from /static/app/ but controls the whole site, so it has to say so;
    # no-cache so a new worker is picked up on the next visit.
    elif is_file and path == _APP_SERVICE_WORKER:
        response.headers["Service-Worker-Allowed"] = "/"
        response.headers["Cache-Control"] = "no-cache"

    # Disable browser caching for HTML documents
    elif "text/html" in content_type:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"

    # For JS/CSS: no-cache forces the browser to revalidate via ETag/Last-Modified
    # on every load, so updated files are never served stale from browser cache.
    elif "javascript" in content_type or "text/css" in content_type:
        response.headers.setdefault("Cache-Control", "no-cache")

    return response


def add_security_headers(app: FastAPI) -> None:
    app.middleware("http")(_security_headers)
