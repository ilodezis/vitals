"""Integration tests for Vitals OAuth 2.0 authorization server and MCP tools."""
from __future__ import annotations

import html
import json
from datetime import date
from urllib.parse import parse_qs, urlsplit
import pytest
from sqlalchemy import select

from vitals.enums import Source
from vitals.models import WeightLog, GarminDaily, GarminActivity, HevyWorkout, LabResult
from web.auth import create_session, read_session, _get_mcp_serializer, _get_serializer
from web.config import SESSION_COOKIE

# PKCE pair used across the flow tests: CODE_CHALLENGE is the S256 of CODE_VERIFIER.
CODE_VERIFIER = "some_challenge"
CODE_CHALLENGE = "bhmDDzo_BXLob8jrOdLgvkzIe7gymOatjCthDDsvQIE"



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
        "/oauth/authorize?response_type=code&client_id=vitals-claude-connector"
        "&redirect_uri=https://claude.ai/callback"
        f"&code_challenge={CODE_CHALLENGE}&code_challenge_method=S256"
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
        f"&code_challenge={CODE_CHALLENGE}&code_challenge_method=S256"
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


async def test_oauth_error_page_has_no_approve_form(auth_client):
    """A refused request shows only "Close": pressing Allow on an error screen
    used to post the same bad request again and answer with raw JSON."""
    response = await auth_client.get(
        "/oauth/authorize?response_type=code&client_id=vitals-claude-connector&redirect_uri=https://evil.com/callback"
    )
    assert response.status_code == 200
    assert "/oauth/authorize/approve" not in response.text
    assert "Закрыть" in response.text


async def test_oauth_authorize_shows_redirect_target(auth_client):
    """The consent screen displays the real destination domain."""
    response = await auth_client.get(
        "/oauth/authorize?response_type=code&client_id=vitals-claude-connector&redirect_uri=https://claude.ai/callback"
        f"&code_challenge={CODE_CHALLENGE}&code_challenge_method=S256"
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
            "code_challenge": CODE_CHALLENGE,
            "code_challenge_method": "S256",
        },
    )
    assert response.status_code == 400


# ── Callback allowlist is per-host, not per-URL ───────────────────────────────
# Gemini Spark's callback carries the owner's Google account id and the MCP host
# in its path, so it differs on every installation — the allowlist matches the
# host and leaves the path alone.
GEMINI_REDIRECT = (
    "https://oauth-redirect.googleusercontent.com/r/"
    "user_bound_custom-mcp-110072519687538803290-vitals_example_com"
)


async def test_oauth_approve_accepts_per_user_google_callback(auth_client):
    """The path is not pinned: an unseen per-user Google callback still mints a code."""
    response = await auth_client.post(
        "/oauth/authorize/approve",
        data={
            "client_id": "vitals-claude-connector",
            "redirect_uri": GEMINI_REDIRECT,
            "code_challenge": CODE_CHALLENGE,
            "code_challenge_method": "S256",
        },
    )
    assert response.status_code == 302
    assert response.headers["location"].startswith(f"{GEMINI_REDIRECT}?code=")


@pytest.mark.parametrize("redirect_uri", [
    "http://claude.ai/callback",              # plaintext — a code would ride the wire
    "https://claude.ai@evil.com/callback",    # userinfo dressed up as the allowed host
    "https://evil.claude.ai/callback",        # subdomain is a different host, not a suffix match
    "https://claude.ai.evil.com/callback",    # allowed host as a prefix of an attacker's
])
async def test_oauth_approve_rejects_lookalike_callbacks(auth_client, redirect_uri):
    """Host matching must be exact — no scheme downgrade, no userinfo/suffix tricks."""
    response = await auth_client.post(
        "/oauth/authorize/approve",
        data={
            "client_id": "vitals-claude-connector",
            "redirect_uri": redirect_uri,
            "code_challenge": CODE_CHALLENGE,
            "code_challenge_method": "S256",
        },
    )
    assert response.status_code == 400


async def test_csp_form_action_allows_any_https_callback(client):
    """Chrome enforces form-action across the whole approval redirect chain,
    including hops inside the connector's own product that no allowlist here can
    predict. A host-pinned form-action swallows the "Approve" click silently, so
    the header must not pin one — redirect_allowed() is what gates the target."""
    response = await client.get("/login", headers={"Accept": "text/html"})
    csp = response.headers["Content-Security-Policy"]
    form_action = csp.split("form-action ", 1)[1].split(";", 1)[0]

    assert "https:" in form_action.split()


async def test_oauth_full_flow_and_token_exchange(auth_client, redis):
    """Test full OAuth 2.0 flow: authorize approve -> code generation -> token exchange."""
    # 1. Approve authorization
    response = await auth_client.post(
        "/oauth/authorize/approve",
        data={
            "client_id": "vitals-claude-connector",
            "redirect_uri": "https://claude.ai/callback",
            "state": "oauth-state-123",
            "code_challenge": "bhmDDzo_BXLob8jrOdLgvkzIe7gymOatjCthDDsvQIE",
            "code_challenge_method": "S256",
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
            "code_verifier": "some_challenge",  # S256 hashes to code_challenge above
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
        data={"client_id": "vitals-claude-connector", "redirect_uri": "https://claude.ai/callback",
              "code_challenge": CODE_CHALLENGE, "code_challenge_method": "S256"},
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
        data={"client_id": "vitals-claude-connector", "redirect_uri": "https://claude.ai/callback",
              "code_challenge": CODE_CHALLENGE, "code_challenge_method": "S256"},
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
    response = await client.get("/mcp/", headers={"Authorization": f"Bearer {session_token}"})
    assert response.status_code == 401


async def test_mcp_middleware_typeerror_returns_500_not_hang():
    """A TypeError from the wrapped MCP app must produce a 500 JSON response, not a
    silent no-response that leaves the client hanging."""
    from web.routers.mcp import MCPAuthMiddleware

    async def _raising_app(scope, receive, send):
        raise TypeError("boom")

    middleware = MCPAuthMiddleware(_raising_app, client_id="vitals-claude-connector")
    token = _get_mcp_serializer().dumps({
        "username": "tester",
        "client_id": "vitals-claude-connector",
        "type": "mcp_access_token",
    })
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp/",
        "headers": [(b"authorization", f"Bearer {token}".encode("utf-8"))],
    }
    sent: list[dict] = []

    async def _receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def _send(message):
        sent.append(message)

    await middleware(scope, _receive, _send)

    start = next(m for m in sent if m["type"] == "http.response.start")
    assert start["status"] == 500
    body = next(m for m in sent if m["type"] == "http.response.body")
    assert b"Internal server error" in body["body"]


async def test_mcp_middleware_drops_second_response_start():
    """A streaming endpoint can emit a second ``http.response.start`` after the client
    hangs up. Passing it through trips an assertion in the BaseHTTPMiddleware stack
    from web/csrf.py and logs a traceback on every reconnect — swallow it."""
    from web.routers.mcp import MCPAuthMiddleware

    async def _streaming_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"data: hi\n\n", "more_body": True})
        # Client disconnected; the endpoint returns an empty Response().
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    middleware = MCPAuthMiddleware(_streaming_app, client_id="vitals-claude-connector")
    token = _get_mcp_serializer().dumps({
        "username": "tester",
        "client_id": "vitals-claude-connector",
        "type": "mcp_access_token",
    })
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/mcp/",
        "headers": [(b"authorization", f"Bearer {token}".encode("utf-8"))],
    }
    sent: list[dict] = []

    async def _receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def _send(message):
        sent.append(message)

    await middleware(scope, _receive, _send)

    assert [m["type"] for m in sent] == ["http.response.start", "http.response.body"]


async def test_mcp_auth_middleware(client, redis):
    """Test that MCP endpoints require a valid Bearer token and reject invalid/missing tokens."""
    # GET /mcp/ without auth should return 401
    r_unauth = await client.get("/mcp/")
    assert r_unauth.status_code == 401

    # POST /mcp/ without auth should return 401
    r_unauth_post = await client.post("/mcp/", json={})
    assert r_unauth_post.status_code == 401

    # Test OPTIONS request passes without auth (CORS/Preflight support)
    r_options = await client.options("/mcp/")
    assert r_options.status_code == 200
    # The happy path (valid token reaching the MCP app) needs a live session manager
    # → test_mcp_initialize_over_streamable_http.


async def test_mcp_initialize_over_streamable_http(client):
    """The streamable-HTTP session manager only exists while the mounted app's own
    lifespan is running, and app.mount() never runs it — web/main.py has to forward it
    via app.state.mcp_lifespan. Drop that forwarding and the server still boots, so
    this is the only test that catches it: a real ``initialize`` over /mcp/."""
    from web.main import app

    mcp_lifespan = app.state.mcp_lifespan  # set by main.py at mount time

    token = _get_mcp_serializer().dumps({
        "username": "tester",
        "client_id": "vitals-claude-connector",
        "type": "mcp_access_token",
    })

    # The `client` fixture uses ASGITransport, which does not run lifespans — enter
    # the MCP one by hand.
    async with mcp_lifespan(app):
        r = await client.post(
            "/mcp/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "0"},
                },
            },
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, text/event-stream",
            },
        )

    assert r.status_code == 200
    assert "protocolVersion" in r.text


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
        spo2_lowest=91,
        training_status="PRODUCTIVE",
        domain="garmin",
        source=Source.GARMIN_API.value,
    )
    garmin_activity = GarminActivity(
        date=date(2026, 6, 15),
        external_id="garmin-act-1",
        activity_type="running",
        name="Morning run",
        avg_hr=140,
        training_effect_aerobic=3.4,
        hr_zone_seconds=[{"zone": 1, "secs": 120.0, "low_hr": 101}],
        splits=[{"index": 1, "distance_m": 1000.0, "avg_hr": 150}],
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
    db_session.add_all([w_log, garmin_log, garmin_activity, workout_log, lab_log])
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
        # New sleep-detail column reflected automatically via serialize_row.
        assert garmin_data["daily_recovery"][0]["spo2_lowest"] == 91
        # New training-status column reflected automatically via serialize_row.
        assert garmin_data["daily_recovery"][0]["training_status"] == "PRODUCTIVE"
        # Per-activity detail: scalar + JSONB columns serialize through.
        assert len(garmin_data["activities"]) == 1
        act = garmin_data["activities"][0]
        assert act["training_effect_aerobic"] == 3.4
        assert act["hr_zone_seconds"][0]["low_hr"] == 101
        assert act["splits"][0]["distance_m"] == 1000.0

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


# ── Security hardening ────────────────────────────────────────────────────────
async def test_oauth_code_single_use_rejects_reuse(auth_client, redis):
    """An authorization code is consumed atomically on first exchange; a second
    exchange with the same code is rejected (invalid_grant)."""
    approve = await auth_client.post(
        "/oauth/authorize/approve",
        data={"client_id": "vitals-claude-connector",
              "redirect_uri": "https://claude.ai/callback",
              "code_challenge": CODE_CHALLENGE, "code_challenge_method": "S256"},
    )
    code = approve.headers["location"].split("code=")[1].split("&")[0]

    body = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": "https://claude.ai/callback",
        "client_id": "vitals-claude-connector",
        "client_secret": "test-mcp-secret",
        "code_verifier": CODE_VERIFIER,
    }
    first = await auth_client.post("/oauth/token", data=body)
    assert first.status_code == 200
    second = await auth_client.post("/oauth/token", data=body)
    assert second.status_code == 400
    assert second.json()["error"] == "invalid_grant"


async def test_mcp_query_string_token_rejected(client):
    """A valid MCP token presented via ?token=/?access_token= (not the Authorization
    header) is rejected — query-string tokens leak into proxy logs, so only the
    Bearer header is accepted."""
    token = _get_mcp_serializer().dumps({
        "username": "tester",
        "client_id": "vitals-claude-connector",
        "type": "mcp_access_token",
    })
    assert (await client.get(f"/mcp/?token={token}")).status_code == 401
    assert (await client.get(f"/mcp/?access_token={token}")).status_code == 401


# ── PKCE is mandatory, not opportunistic ──────────────────────────────────────
async def test_authorize_without_pkce_is_refused(auth_client):
    """No challenge on the consent page means the token exchange would have nothing
    to verify — refuse before a code is ever minted."""
    response = await auth_client.get(
        "/oauth/authorize?response_type=code&client_id=vitals-claude-connector"
        "&redirect_uri=https://claude.ai/callback"
    )
    assert response.status_code == 200
    assert "PKCE" in response.text


async def test_authorize_with_plain_challenge_is_refused(auth_client):
    """The metadata advertises S256 only; ``plain`` protects nothing."""
    response = await auth_client.get(
        "/oauth/authorize?response_type=code&client_id=vitals-claude-connector"
        "&redirect_uri=https://claude.ai/callback"
        f"&code_challenge={CODE_CHALLENGE}&code_challenge_method=plain"
    )
    assert response.status_code == 200
    assert "PKCE" in response.text


async def test_approve_without_pkce_is_refused(auth_client):
    """The approve endpoint is reachable on its own — a code minted there without a
    challenge would be exchangeable without a verifier."""
    response = await auth_client.post(
        "/oauth/authorize/approve",
        data={"client_id": "vitals-claude-connector",
              "redirect_uri": "https://claude.ai/callback"},
    )
    assert response.status_code == 400


async def test_token_exchange_rejects_wrong_code_verifier(auth_client):
    """The whole point of PKCE: holding the code is not enough."""
    approve = await auth_client.post(
        "/oauth/authorize/approve",
        data={"client_id": "vitals-claude-connector",
              "redirect_uri": "https://claude.ai/callback",
              "code_challenge": CODE_CHALLENGE, "code_challenge_method": "S256"},
    )
    code = approve.headers["location"].split("code=")[1].split("&")[0]

    token_response = await auth_client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://claude.ai/callback",
            "client_id": "vitals-claude-connector",
            "client_secret": "test-mcp-secret",
            "code_verifier": "not-the-verifier",
        },
    )
    assert token_response.status_code == 400
    assert token_response.json()["error"] == "invalid_grant"


async def test_token_exchange_rejects_missing_code_verifier(auth_client):
    approve = await auth_client.post(
        "/oauth/authorize/approve",
        data={"client_id": "vitals-claude-connector",
              "redirect_uri": "https://claude.ai/callback",
              "code_challenge": CODE_CHALLENGE, "code_challenge_method": "S256"},
    )
    code = approve.headers["location"].split("code=")[1].split("&")[0]

    token_response = await auth_client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://claude.ai/callback",
            "client_id": "vitals-claude-connector",
            "client_secret": "test-mcp-secret",
        },
    )
    assert token_response.status_code == 400
    assert token_response.json()["error"] == "invalid_grant"


async def test_token_exchange_rejects_code_stored_without_challenge(auth_client, redis):
    """A code that somehow reached Redis without a challenge must not fall through
    to "PKCE wasn't requested, issue the token anyway"."""
    import json as _json

    code = "code_legacy_no_pkce"
    await redis.set(f"oauth_code:{code}", _json.dumps({
        "client_id": "vitals-claude-connector",
        "redirect_uri": "https://claude.ai/callback",
        "code_challenge": None,
        "code_challenge_method": None,
        "username": "tester",
    }), ex=300)

    token_response = await auth_client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://claude.ai/callback",
            "client_id": "vitals-claude-connector",
            "client_secret": "test-mcp-secret",
        },
    )
    assert token_response.status_code == 400
    assert token_response.json()["error"] == "invalid_grant"


# ── Protected-resource discovery (RFC 9728) ───────────────────────────────────
async def test_protected_resource_metadata(client):
    response = await client.get("/.well-known/oauth-protected-resource")
    assert response.status_code == 200
    data = response.json()
    assert data["resource"] == "http://test/mcp"
    assert data["authorization_servers"] == ["http://test"]
    assert data["bearer_methods_supported"] == ["header"]


async def test_401_points_at_the_resource_metadata(client):
    """A bare ``Bearer`` leaves a fresh client guessing where tokens come from."""
    response = await client.get("/mcp/")
    assert response.status_code == 401
    challenge = response.headers["www-authenticate"]
    assert challenge.startswith("Bearer ")
    assert 'resource_metadata="http://test/.well-known/oauth-protected-resource"' in challenge


async def test_oauth_state_is_url_encoded(auth_client):
    """A state value carrying reserved characters is percent-encoded in the redirect
    so it can't break out and inject extra query parameters."""
    r = await auth_client.post(
        "/oauth/authorize/approve",
        data={"client_id": "vitals-claude-connector",
              "redirect_uri": "https://claude.ai/callback",
              "state": "a b&evil=1",
              "code_challenge": CODE_CHALLENGE, "code_challenge_method": "S256"},
    )
    loc = r.headers["location"]
    assert "state=a b&evil=1" not in loc          # raw reserved chars must not leak
    assert "a+b%26evil%3D1" in loc                 # '&' and '=' are encoded
