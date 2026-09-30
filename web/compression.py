"""Gzip for the React app's traffic, and for nothing else.

The API's JSON is highly repetitive (a year of daily rows is the same keys over
and over) and the screens read it on every visit: ``/api/v1/recovery`` is ~60 KB
as sent and a tenth of that compressed. A proxy in front may compress too
(Cloudflare does), but a plain nginx only compresses ``text/html`` unless told
otherwise, and a tunnel or a direct connection not at all.

Scoped by path rather than applied app-wide:

* ``/api/`` and ``/static/app/`` are what the app loads — JSON and hashed assets.
* The server-rendered pages carry the CSRF token next to text the visitor typed,
  the textbook setup for a compression side channel (BREACH), so HTML stays as is.
* ``/mcp`` and the webhooks stream or answer machines that gain nothing from it.
"""
from __future__ import annotations

from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

COMPRESSED_PREFIXES = ("/api/", "/static/app/")

# Below this a response fits in a packet or two anyway.
MINIMUM_SIZE = 1024
# Level 6 gets nearly all of 9's ratio on JSON at a fraction of the CPU.
COMPRESS_LEVEL = 6


class AppGZipMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=MINIMUM_SIZE, compresslevel=COMPRESS_LEVEL)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"].startswith(COMPRESSED_PREFIXES):
            await self.gzip(scope, receive, send)
        else:
            await self.app(scope, receive, send)
