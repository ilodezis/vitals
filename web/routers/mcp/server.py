"""Tool visibility, bearer auth and the ASGI app factory."""
from __future__ import annotations

import hmac

from fastmcp.server.middleware import Middleware

from vitals.services import modules_service
from web.routers.mcp import _core
from web.routers.mcp._core import TOOL_MODULES, get_session_factory, logger, mcp


class ModuleVisibilityMiddleware(Middleware):
    """Hide a switched-off module's tools from ``tools/list``.

    They already refuse the call ("module '<key>' is disabled") — listing them only
    spends the conversation's budget on schemas for domains the owner does not
    track, and invites the model to try them. Resolved per request rather than
    latched at import, so flipping a toggle in Settings takes effect on the next
    reconnect without a restart. Fails open: if the module state can't be read, the
    full surface is listed rather than an empty one.
    """

    async def on_list_tools(self, context, call_next):
        tools = await call_next(context)
        try:
            session_factory = get_session_factory()
            async with session_factory() as session:
                enabled = await modules_service.get_enabled_modules(session)
        except Exception:
            logger.warning("mcp: module state unavailable; listing every tool", exc_info=True)
            return tools
        return [t for t in tools if enabled.get(TOOL_MODULES.get(t.name, ""), True)]


mcp.add_middleware(ModuleVisibilityMiddleware())


def _www_authenticate(scope) -> bytes:
    """The 401 challenge, pointing at this resource's metadata (RFC 9728 §5.1).

    A bare ``Bearer`` leaves a fresh client guessing where tokens come from; the
    ``resource_metadata`` link is how it finds the authorization server. Built from
    the request's own host so it stays right behind the reverse proxy (uvicorn runs
    with --forwarded-allow-ips, so the scheme is the external one)."""
    from web.routers.oauth import PROTECTED_RESOURCE_PATH

    host = dict(scope.get("headers", [])).get(b"host", b"").decode("utf-8", "ignore")
    if not host:
        return b"Bearer"
    url = f"{scope.get('scheme', 'https')}://{host}{PROTECTED_RESOURCE_PATH}"
    return f'Bearer resource_metadata="{url}"'.encode("utf-8")


class MCPAuthMiddleware:
    """ASGI middleware that intercepts all requests to the MCP application

    and validates the signed Bearer access token in the Authorization header.
    """
    def __init__(self, app, client_id: str):
        self.app = app
        self.client_id = client_id

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if scope.get("method") == "OPTIONS":
            # No access-control-allow-origin: the actual MCP responses carry no CORS
            # headers, so a wildcard here grants nothing. Claude.ai's connector is
            # server-side (not a browser), so it never sends a preflight anyway.
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"access-control-allow-methods", b"GET, POST, DELETE, OPTIONS"),
                    (b"access-control-allow-headers", b"Authorization, Content-Type"),
                    (b"content-length", b"0"),
                ]
            })
            await send({
                "type": "http.response.body",
                "body": b"",
                "more_body": False
            })
            return

        # Check Authorization header
        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode("utf-8")

        # Bearer header ONLY. We deliberately do not accept the token via a query
        # param (?token=/?access_token=): query strings leak into reverse-proxy
        # access logs, browser history and Referer headers, and this token is
        # long-lived. Claude.ai's connector sends the Authorization header.
        token = None
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:]

        authenticated = False
        if token:
            from web.auth import _get_mcp_serializer
            from itsdangerous import SignatureExpired, BadSignature
            serializer = _get_mcp_serializer()
            try:
                # Validate access token with 1 year TTL limit
                payload = serializer.loads(token, max_age=31536000)
                if (
                    isinstance(payload, dict)
                    and payload.get("type") == "mcp_access_token"
                    and payload.get("client_id") == self.client_id
                ):
                    authenticated = True
            except (SignatureExpired, BadSignature):
                pass

            # Optional static agent token (VITALS_MCP_AGENT_TOKEN) for clients that
            # cannot run the OAuth flow. Off when unset; this middleware only guards
            # /mcp, so the token opens nothing else. Constant-time comparison.
            if not authenticated:
                from web.config import get_web_config

                agent_token = get_web_config().mcp_agent_token
                if agent_token and hmac.compare_digest(
                    token.encode("utf-8"), agent_token.encode("utf-8")
                ):
                    authenticated = True

        if not authenticated:
            response_body = b'{"detail":"Unauthorized. Invalid or missing MCP access token."}'
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(response_body)).encode("utf-8")),
                    (b"www-authenticate", _www_authenticate(scope)),
                ]
            })
            await send({
                "type": "http.response.body",
                "body": response_body,
                "more_body": False
            })
            return

        # Track whether the downstream app already began the response, so on a
        # mid-stream failure we don't try to start a second one (that would raise).
        response_started = False
        response_done = False

        async def _send(message):
            nonlocal response_started, response_done
            if response_done:
                return
            if message["type"] == "http.response.start":
                if response_started:
                    # A streaming endpoint can emit a second response start after
                    # the stream is over (e.g. an empty Response() once the client
                    # hangs up). Forwarding it trips an assertion inside the
                    # BaseHTTPMiddleware wrappers from web/csrf.py and logs a
                    # traceback on every connector reconnect. Drop it and anything
                    # after it — the response is finished either way.
                    response_done = True
                    return
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, _send)
        except TypeError:
            logger.exception("MCP app raised TypeError handling %s", scope.get("path"))
            if not response_started:
                body = b'{"detail":"Internal server error in MCP handler."}'
                await send({
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("utf-8")),
                    ],
                })
                await send({
                    "type": "http.response.body",
                    "body": body,
                    "more_body": False,
                })


def get_mcp_app(host_app=None) -> tuple[object, object]:
    """Wraps the FastMCP Starlette app with Bearer authorization middleware.

    Returns ``(app, lifespan)``. Streamable HTTP builds its session manager inside
    the lifespan, and ``app.mount()`` does not run a sub-app's lifespan — so the
    caller must enter it explicitly or every request fails with "manager not
    initialized". See web/main.py. ``host_app`` is the app it is mounted on, for
    the tools that act on it (re-timing the scheduler).
    """
    from web.config import get_web_config

    _core._HOST_APP = host_app
    cfg = get_web_config()
    # Streamable HTTP (the SSE transport is deprecated in the MCP spec since
    # 2025-03). path="/" so that mounting on /mcp lands the endpoint on /mcp/
    # rather than /mcp/mcp — the library's own default path would be appended.
    raw_app = mcp.http_app(transport="http", path="/")
    return MCPAuthMiddleware(raw_app, client_id=cfg.mcp_client_id), raw_app.router.lifespan_context
