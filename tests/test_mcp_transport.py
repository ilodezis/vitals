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
        tools = await session.list_tools()

    by_name = {tool.name: tool for tool in tools}
    assert "get_weight_logs" in by_name  # a core tool, never module-gated
    assert by_name["get_weight_logs"].annotations.read_only_hint is True
    assert by_name["delete_record"].annotations.destructive_hint is True


async def test_mcp_calls_a_tool_over_http(client):
    async with _connect() as session:
        result = await session.call_tool("get_settings", {"section": "modules"})

    assert result.data["enabled"]["nutrition"] is True


# ── Static agent token (VITALS_MCP_AGENT_TOKEN) ───────────────────────────────

AGENT_TOKEN = "agent-token-" + "x" * 32  # comfortably over the 32-char minimum
_INIT_BODY = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "agent-test", "version": "0"},
    },
}
_MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


@asynccontextmanager
async def _connect_lifespan():
    from web.main import app

    async with app.state.mcp_lifespan(app):
        yield


async def _initialize(client, bearer: str | None):
    headers = dict(_MCP_HEADERS)
    if bearer is not None:
        headers["Authorization"] = f"Bearer {bearer}"
    return await client.post("/mcp/", json=_INIT_BODY, headers=headers)


async def test_agent_token_authorizes_mcp_initialize(client, monkeypatch):
    monkeypatch.setenv("VITALS_MCP_AGENT_TOKEN", AGENT_TOKEN)
    async with _connect_lifespan():
        response = await _initialize(client, AGENT_TOKEN)

    assert response.status_code == 200
    assert "serverInfo" in response.text


async def test_wrong_agent_token_is_rejected(client, monkeypatch):
    monkeypatch.setenv("VITALS_MCP_AGENT_TOKEN", AGENT_TOKEN)

    response = await _initialize(client, AGENT_TOKEN[:-1] + "y")

    assert response.status_code == 401
    assert "resource_metadata" in response.headers["www-authenticate"]


@pytest.mark.parametrize("bearer", ["", "anything", AGENT_TOKEN])
async def test_agent_path_is_closed_when_token_unset(client, monkeypatch, bearer):
    monkeypatch.delenv("VITALS_MCP_AGENT_TOKEN", raising=False)

    response = await _initialize(client, bearer)

    assert response.status_code == 401
    assert "resource_metadata" in response.headers["www-authenticate"]


async def test_empty_agent_token_setting_is_off(client, monkeypatch):
    monkeypatch.setenv("VITALS_MCP_AGENT_TOKEN", "")

    assert (await _initialize(client, "")).status_code == 401


async def test_agent_token_does_not_open_non_mcp_routes(client, monkeypatch):
    monkeypatch.setenv("VITALS_MCP_AGENT_TOKEN", AGENT_TOKEN)
    headers = {"Authorization": f"Bearer {AGENT_TOKEN}"}

    rest = await client.get("/api/v1/settings", headers=headers)
    page = await client.get("/today", headers=headers)
    oauth = await client.post("/oauth/token", headers=headers, data={})

    assert rest.status_code == 401
    assert page.status_code in (302, 303, 307, 401)  # login redirect or refusal, never the page
    assert oauth.status_code in (400, 401, 403, 422)  # never an issued token
    assert "access_token" not in oauth.text


def test_short_agent_token_fails_startup(monkeypatch):
    from web.config import get_web_config

    monkeypatch.setenv("VITALS_MCP_AGENT_TOKEN", "x" * 31)
    with pytest.raises(RuntimeError, match="VITALS_MCP_AGENT_TOKEN"):
        get_web_config()

    monkeypatch.setenv("VITALS_MCP_AGENT_TOKEN", "x" * 32)
    assert get_web_config().mcp_agent_token == "x" * 32
