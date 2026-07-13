"""CSRF origin check + security headers (ported from Boxly's ``web/csrf.py``).

Session cookies are ``SameSite=lax`` (primary CSRF defence). This adds a second,
independent barrier: unsafe-method requests carrying a cross-origin ``Origin``
header are rejected. The CSP keeps ``'unsafe-eval'`` because Alpine compiles every
``x-*`` expression with ``Function()`` — without it the UI silently breaks.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


async def _origin_check(request: Request, call_next):
    path = request.url.path
    if path.startswith("/mcp") or path == "/oauth/token":
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


# 'unsafe-eval' is REQUIRED by Alpine.js (Function() compilation of x-* directives).
# 'unsafe-inline' covers inline <script> + Alpine/HTMX inline attributes. img-src
# data:/blob: cover Chart.js canvases and inline SVG icons.
# Scripts and fonts are vendored under /static (no CDN) — the one exception is
# Cloudflare's Web Analytics beacon, which Cloudflare injects at the edge (into
# the proxied HTML response) rather than anything our own templates load, so
# there's no template reference to point at; it needs its own
# script-src/connect-src entries or the browser blocks it outright. Fonts
# (Inter / Outfit / Bricolage Grotesque — no monospace, per the design system)
# are self-hosted woff2 under web/static/fonts/, so font-src/style-src stay 'self'.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://static.cloudflareinsights.com; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob: https:; "
    "font-src 'self'; "
    "connect-src 'self' https://cloudflareinsights.com; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self' https://claude.ai"
)
_SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": _CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    for name, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)

    content_type = response.headers.get("content-type", "").lower()

    # Disable browser caching for HTML documents
    if "text/html" in content_type:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"

    # For JS/CSS: no-cache forces the browser to revalidate via ETag/Last-Modified
    # on every load, so updated files are never served stale from browser cache.
    elif "javascript" in content_type or "text/css" in content_type:
        response.headers.setdefault("Cache-Control", "no-cache")

    return response


def add_security_headers(app: FastAPI) -> None:
    app.middleware("http")(_security_headers)
