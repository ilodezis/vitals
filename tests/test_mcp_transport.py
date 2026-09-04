"""The MCP endpoint as a client actually reaches it: over HTTP, through the
mount and the Bearer guard.

Every other ``test_mcp_*`` module calls the tool functions directly, so the whole
transport half — the ``app.mount("/mcp", ...)`` in web/main.py, the lifespan the
mount does not run on its own, ``MCPAuthMiddleware``, and the protocol version the
library negotiates with a real client — has no coverage at all. A FastMCP upgrade
that changed any of them would leave the rest of the suite green and the connector
dead."""
from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

pytest.importorskip("web.routers.mcp")


@pytest.fixture(autouse=True)
def _use_test_factory(session_factory, monkeypatch):
    """Point the tools at the test database, as the other MCP tests do."""
    import web.routers.mcp as mcp_router

    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)


def _mint_token() -> str:
    """The same access token ``/oauth/token`` hands the connector."""
    from web.auth import _get_mcp_serializer
    from web.config import get_web_config

    return _get_mcp_serializer().dumps(
        {"type": "mcp_access_token", "client_id": get_web_config().mcp_client_id}
    )


@asynccontextmanager
async def _connect():
    """A real FastMCP client speaking to the mounted app in-process.

    The MCP sub-app's lifespan is entered here the way web/main.py enters it:
    ``app.mount()`` never runs a sub-app's lifespan, and the streamable-HTTP
    session manager is built inside it, so without this every request answers
    "task group was not initialized". It is a context manager rather than a
    fixture because the task group inside refuses to be exited from a different
    task than it was entered in, which is what a yielding fixture would do."""
    import httpx2
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport
    from web.main import app

    def factory(**kwargs) -> httpx2.AsyncClient:
        kwargs.pop("timeout", None)  # ASGITransport has no socket to time out on
        return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), **kwargs)

    transport = StreamableHttpTransport(
        "http://test/mcp/", auth=_mint_token(), httpx_client_factory=factory
    )
    async with app.state.mcp_lifespan(app):
        async with Client(transport) as session:
            yield session


async def test_mcp_rejects_a_request_without_a_token(client):
    response = await client.post(
        "/mcp/",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        headers={"Accept": "application/json, text/event-stream"},
    )

    assert response.status_code == 401
    # The challenge points at this resource's metadata document, or a fresh
    # client cannot find the authorization server (RFC 9728 §5.1).
    assert "resource_metadata" in response.headers["www-authenticate"]


async def test_mcp_lists_tools_over_http(client):
    async with _connect() as session:
        names = {tool.name for tool in await session.list_tools()}

    assert "get_weight_logs" in names  # a core tool, never module-gated


async def test_mcp_calls_a_tool_over_http(client):
    async with _connect() as session:
        result = await session.call_tool("get_modules", {})

    assert result.data["enabled"]["nutrition"] is True
