"""Integration tests for Vitals OAuth 2.0 authorization server and MCP tools."""
from __future__ import annotations

import html
import json
from datetime import date
from urllib.parse import parse_qs, urlsplit
import pytest
from sqlalchemy import select

from vitals.enums import Source
from vitals.models import WeightLog, GarminDaily, HevyWorkout, LabResult
from web.auth import create_session, read_session, _get_mcp_serializer, _get_serializer
from web.config import SESSION_COOKIE, get_web_config

pytestmark = pytest.mark.asyncio


async def test_oauth_metadata_discovery(client):
    """Test standard RFC 8414 metadata discovery endpoint."""
    response = await client.get("/.well-known/oauth-authorization-server")
    assert response.status_code == 200
    data = response.json()
    assert data["issuer"] == "http://test"
    assert data["authorization_endpoint"] == "http://test/oauth/authorize"
    assert data["token_endpoint"] == "http://test/oauth/token"
    assert "code" in data["response_types_supported"]


async def test_oauth_authorize_unauthenticated_redirects(client):
    """GET /oauth/authorize redirects to /login if the browser session is unauthenticated."""
    response = await client.get(
        "/oauth/authorize?response_type=code&client_id=vitals-claude-connector&redirect_uri=https://claude.ai/callback"
    )
    assert response.status_code == 302
    parsed = urlsplit(response.headers["location"])
    assert parsed.path == "/login"
    assert parse_qs(parsed.query)["next"][0].startswith("/oauth/authorize")


async def test_oauth_authorize_unauthenticated_redirect_preserves_full_query(client):
    """The `next` param must be percent-encoded as a single value — the OAuth
    query string it carries (redirect_uri, code_challenge, state...) contains
    its own '&'/'?' characters that would otherwise be parsed as separate
    top-level params on /login, truncating `next` and 422ing after login."""
    original_query = (
        "response_type=code&client_id=vitals-claude-connector"
        "&redirect_uri=https://claude.ai/callback"
        "&code_challenge=abc123&code_challenge_method=S256&state=xyz789"
    )
    response = await client.get(f"/oauth/authorize?{original_query}")
    assert response.status_code == 302

    location = response.headers["location"]
    parsed = urlsplit(location)
    assert parsed.path == "/login"
    next_value = parse_qs(parsed.query)["next"][0]
    assert next_value == f"/oauth/authorize?{original_query}"


async def test_oauth_login_redirect_reaches_authorize_with_full_params(client):
    """End-to-end: an unauthenticated visit to /oauth/authorize with PKCE +
    state, followed by a successful login, must land back on the SAME
    /oauth/authorize URL with every original param intact (not a truncated
    /oauth/authorize?response_type=code that 422s)."""
    original_query = (
        "response_type=code&client_id=vitals-claude-connector"
        "&redirect_uri=https://claude.ai/callback"
        "&code_challenge=abc123&code_challenge_method=S256&state=xyz789"
    )
    r1 = await client.get(f"/oauth/authorize?{original_query}")
    login_url = r1.headers["location"]

    r2 = await client.get(login_url)
    assert r2.status_code == 200
    next_value = parse_qs(urlsplit(login_url).query)["next"][0]
    assert next_value == f"/oauth/authorize?{original_query}"
    # Jinja HTML-escapes the hidden field's value (e.g. & -> &amp;) — correct
    # and safe; escape before comparing to the raw query string.
    assert f'value="{html.escape(next_value)}"' in r2.text

    # Credentials match conftest's TEST_USERNAME/TEST_PASSWORD, referenced as
    # literals rather than re-imported (a site-packages `tests` package can
    # shadow `tests.conftest` and break the import — see auth_client fixture).
    r3 = await client.post("/login", data={"username": "tester", "password": "password", "next": next_value})
    assert r3.status_code == 303
    assert r3.headers["location"] == f"/oauth/authorize?{original_query}"


async def test_oauth_authorize_authenticated_renders(auth_client):
    """GET /oauth/authorize renders the consent template if authenticated."""
    response = await auth_client.get(
        "/oauth/authorize?response_type=code&client_id=vitals-claude-connector&redirect_uri=https://claude.ai/callback"
    )
    assert response.status_code == 200
    assert "Разрешение доступа" in response.text
    assert "Claude.ai" in response.text
    assert "Дневнику питания, калорийности и приемов пищи" in response.text
    assert "вносить записи в дневник питания" in response.text
    assert "read-only" not in response.text


async def test_oauth_authorize_invalid_client(auth_client):
    """GET /oauth/authorize with invalid client_id shows error message."""
    response = await auth_client.get(
        "/oauth/authorize?response_type=code&client_id=wrong-client&redirect_uri=https://claude.ai/callback"
    )
    assert response.status_code == 200
    assert "Неверный client_id" in response.text


async def test_oauth_authorize_invalid_redirect_uri(auth_client):
    """GET /oauth/authorize with a redirect_uri outside the allowlist is rejected,
    not silently carried through to the consent screen or a login redirect."""
    response = await auth_client.get(
        "/oauth/authorize?response_type=code&client_id=vitals-claude-connector&redirect_uri=https://evil.com/callback"
    )
    assert response.status_code == 200
    assert "Недопустимый redirect_uri" in response.text


async def test_oauth_authorize_invalid_redirect_uri_unauthenticated(client):
    """Same rejection happens before the unauthenticated login redirect, so an
    attacker can't ride the login flow into an approval with a bad redirect_uri."""
    response = await client.get(
        "/oauth/authorize?response_type=code&client_id=vitals-claude-connector&redirect_uri=https://evil.com/callback"
    )
    assert response.status_code == 200
    assert "Недопустимый redirect_uri" in response.text


async def test_oauth_authorize_shows_redirect_target(auth_client):
    """The consent screen displays the real destination domain."""
    response = await auth_client.get(
        "/oauth/authorize?response_type=code&client_id=vitals-claude-connector&redirect_uri=https://claude.ai/callback"
    )
    assert response.status_code == 200
    assert "Вы будете перенаправлены на" in response.text
    assert "claude.ai" in response.text


async def test_oauth_approve_invalid_redirect_uri(auth_client):
    """POST /oauth/authorize/approve rejects a redirect_uri outside the allowlist
    even if somehow reached (defense in depth behind the GET-time check)."""
    response = await auth_client.post(
        "/oauth/authorize/approve",
        data={
            "client_id": "vitals-claude-connector",
            "redirect_uri": "https://evil.com/callback",
            "state": "x",
        },
    )
    assert response.status_code == 400


async def test_oauth_full_flow_and_token_exchange(auth_client, redis):
    """Test full OAuth 2.0 flow: authorize approve -> code generation -> token exchange."""
    # 1. Approve authorization
    response = await auth_client.post(
        "/oauth/authorize/approve",
        data={
            "client_id": "vitals-claude-connector",
            "redirect_uri": "https://claude.ai/callback",
            "state": "oauth-state-123",
            "code_challenge": "some_challenge",
            "code_challenge_method": "plain",
        },
    )
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("https://claude.ai/callback?code=")
    assert "state=oauth-state-123" in location

    # Extract authorization code
    parts = location.split("code=")
    code = parts[1].split("&")[0]

    # Verify code details stored in Redis
    code_data_raw = await redis.get(f"oauth_code:{code}")
    assert code_data_raw is not None
    code_data = json.loads(code_data_raw)
    assert code_data["username"] == "tester"

    # 2. Exchange code for access token (POST /oauth/token)
    token_response = await auth_client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://claude.ai/callback",
            "client_id": "vitals-claude-connector",
            "client_secret": "test-mcp-secret",
            "code_verifier": "some_challenge",  # matches plain code_challenge
        },
    )
    assert token_response.status_code == 200
    token_data = token_response.json()
    assert token_data["token_type"] == "Bearer"
    assert "access_token" in token_data

    # Verify the code is deleted from Redis (single-use constraint)
    assert await redis.get(f"oauth_code:{code}") is None

    # Verify token signature and contents — signed with the dedicated MCP salt,
    # not the session salt (see web.auth._get_mcp_serializer).
    serializer = _get_mcp_serializer()
    payload = serializer.loads(token_data["access_token"], max_age=3600)
    assert payload["username"] == "tester"
    assert payload["client_id"] == "vitals-claude-connector"
    assert payload["type"] == "mcp_access_token"

    # The session serializer must NOT be able to verify an MCP token (different salt).
    with pytest.raises(Exception):
        _get_serializer().loads(token_data["access_token"], max_age=3600)


async def test_oauth_token_missing_client_secret_rejected(auth_client, redis, monkeypatch):
    """Fail-closed: an unconfigured VITALS_MCP_CLIENT_SECRET must refuse token
    issuance rather than skipping the secret check."""
    monkeypatch.setenv("VITALS_MCP_CLIENT_SECRET", "")

    response = await auth_client.post(
        "/oauth/authorize/approve",
        data={"client_id": "vitals-claude-connector", "redirect_uri": "https://claude.ai/callback"},
    )
    code = response.headers["location"].split("code=")[1].split("&")[0]

    token_response = await auth_client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://claude.ai/callback",
            "client_id": "vitals-claude-connector",
        },
    )
    assert token_response.status_code == 400
    assert token_response.json()["error"] == "invalid_client"


async def test_oauth_token_wrong_client_secret_rejected(auth_client, redis):
    """A client_secret that doesn't match the configured one is rejected."""
    response = await auth_client.post(
        "/oauth/authorize/approve",
        data={"client_id": "vitals-claude-connector", "redirect_uri": "https://claude.ai/callback"},
    )
    code = response.headers["location"].split("code=")[1].split("&")[0]

    token_response = await auth_client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://claude.ai/callback",
            "client_id": "vitals-claude-connector",
            "client_secret": "not-the-right-secret",
        },
    )
    assert token_response.status_code == 400
    assert token_response.json()["error"] == "invalid_client"


async def test_mcp_token_rejected_as_session_cookie(client):
    """An MCP access token (dict payload) must not authenticate a normal session
    even though it's signed with the same session_secret (different salt + type
    check in read_session)."""
    mcp_token = _get_mcp_serializer().dumps({
        "username": "tester",
        "client_id": "vitals-claude-connector",
        "type": "mcp_access_token",
    })
    client.cookies.set(SESSION_COOKIE, mcp_token)
    response = await client.get("/weight", headers={"Accept": "text/html"})
    assert response.status_code == 302
    assert "/login" in response.headers["location"]


async def test_session_token_rejected_as_mcp_bearer(client):
    """A session cookie token must not authenticate as an MCP Bearer token."""
    session_token = create_session("tester")
    response = await client.get("/mcp/sse", headers={"Authorization": f"Bearer {session_token}"})
    assert response.status_code == 401


async def test_mcp_auth_middleware(client, redis):
    """Test that MCP endpoints require a valid Bearer token and reject invalid/missing tokens."""
    # GET /mcp/sse without auth should return 401
    r_unauth = await client.get("/mcp/sse")
    assert r_unauth.status_code == 401

    # POST /mcp/messages without auth should return 401
    r_unauth_post = await client.post("/mcp/messages", json={})
    assert r_unauth_post.status_code == 401

    # Generate a valid token
    serializer = _get_mcp_serializer()
    valid_token = serializer.dumps({
        "username": "tester",
        "client_id": "vitals-claude-connector",
        "type": "mcp_access_token",
    })

    # Test OPTIONS request passes without auth (CORS/Preflight support)
    r_options = await client.options("/mcp/sse")
    assert r_options.status_code == 200

    # Test POST /mcp/messages with valid Bearer token (should bypass auth check and connect to starlette app)
    # Since we send empty body, FastMCP will parse it and return a JSON-RPC error response,
    # but the key is it must not return 401 Unauthorized.
    r_auth = await client.post("/mcp/messages", json={}, headers={"Authorization": f"Bearer {valid_token}"})
    assert r_auth.status_code != 401


async def test_mcp_read_only_tools_execution(db_session, session_factory):
    """Test that the read-only MCP tools execute and return valid serializable schemas."""
    # Pre-seed some test data
    w_log = WeightLog(
        date=date(2026, 6, 15),
        weight_kg=84.5,
        domain="weight",
        source=Source.MANUAL.value,
        superseded=False,
    )
    garmin_log = GarminDaily(
        date=date(2026, 6, 15),
        sleep_score=85,
        resting_hr=58,
        hrv_avg=65,
        domain="garmin",
        source=Source.GARMIN_API.value,
    )
    workout_log = HevyWorkout(
        date=date(2026, 6, 15),
        external_id="hevy-workout-1",
        title="Upper Body",
        domain="workouts",
        source=Source.HEVY_API.value,
    )
    lab_log = LabResult(
        date=date(2026, 6, 15),
        marker="Glucose",
        value=5.2,
        unit="mmol/L",
        domain="labs",
        source=Source.MANUAL.value,
    )
    db_session.add_all([w_log, garmin_log, workout_log, lab_log])
    await db_session.commit()

    # Import mcp app tools
    from web.routers.mcp import (
        get_user_profile,
        get_weight_logs,
        get_garmin_metrics,
        get_hevy_workouts,
        get_lab_results,
    )

    # Test get_user_profile
    profile = await get_user_profile()
    assert profile["height_cm"] == 190.0
    assert profile["sex"] == "male"

    # Override session dependencies so tools use the test database session
    # Note: get_session_factory in web.routers.mcp gets session_factory.
    # To mock it in tests, we patch get_session_factory to return our test session_factory fixture.
    import web.routers.mcp as mcp_router
    original_factory = mcp_router.get_session_factory
    mcp_router.get_session_factory = lambda: session_factory

    try:
        # Test get_weight_logs tool
        weights_data = await get_weight_logs(start_date="2026-06-10", end_date="2026-06-20")
        assert len(weights_data["weights"]) == 1
        assert weights_data["weights"][0]["weight_kg"] == 84.5

        # Test get_garmin_metrics tool
        garmin_data = await get_garmin_metrics(start_date="2026-06-10", end_date="2026-06-20")
        assert len(garmin_data["daily_recovery"]) == 1
        assert garmin_data["daily_recovery"][0]["sleep_score"] == 85
        assert garmin_data["daily_recovery"][0]["resting_hr"] == 58

        # Test get_hevy_workouts tool
        workouts_data = await get_hevy_workouts(start_date="2026-06-10", end_date="2026-06-20")
        assert len(workouts_data) == 1
        assert workouts_data[0]["title"] == "Upper Body"

        # Test get_lab_results tool
        labs_data = await get_lab_results()
        assert len(labs_data) == 1
        assert labs_data[0]["marker"] == "Glucose"
        assert labs_data[0]["value"] == 5.2
    finally:
        # Restore original session factory
        mcp_router.get_session_factory = original_factory
