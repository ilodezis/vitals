"""OAuth 2.0 Auth Server router for Vitals.

Implements metadata discovery, authorization page, and token exchange for Claude.ai.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
from typing import Optional
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from web.auth import read_session, _get_mcp_serializer
from web.config import SESSION_COOKIE, get_web_config
from web.deps import get_redis, SESSION_COOKIE

logger = logging.getLogger(__name__)

router = APIRouter(tags=["oauth"])


def verify_pkce(code_verifier: str, code_challenge: str, method: Optional[str]) -> bool:
    """Verifies the Proof Key for Code Exchange (PKCE) challenge."""
    if not method or method == "plain":
        return secrets.compare_digest(code_verifier, code_challenge)
    elif method == "S256":
        sha256_hash = hashlib.sha256(code_verifier.encode("utf-8")).digest()
        calculated_challenge = base64.urlsafe_b64encode(sha256_hash).decode("utf-8").rstrip("=")
        stripped_challenge = code_challenge.rstrip("=")
        return secrets.compare_digest(calculated_challenge, stripped_challenge)
    return False


# ── Metadata Discovery (RFC 8414) ────────────────────────────────────────────

@router.get("/.well-known/oauth-authorization-server")
async def oauth_metadata(request: Request):
    """Exposes the authorization server discovery document."""
    base_url = str(request.base_url).rstrip("/")
    return {
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/oauth/authorize",
        "token_endpoint": f"{base_url}/oauth/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
        "code_challenge_methods_supported": ["S256", "plain"]
    }


# ── Authorization Consent View ────────────────────────────────────────────────

@router.get("/oauth/authorize", response_class=HTMLResponse)
async def oauth_authorize(
    request: Request,
    response_type: str,
    client_id: str,
    redirect_uri: str,
    state: Optional[str] = None,
    code_challenge: Optional[str] = None,
    code_challenge_method: Optional[str] = None,
):
    """Renders the OAuth authorization consent page, prompting login if needed."""
    from web.templating import templates
    cfg = get_web_config()

    from vitals.i18n import t
    if client_id != cfg.mcp_client_id:
        return templates.TemplateResponse(
            request,
            "oauth_authorize.html",
            {"error": t("oauth.error.invalid_client"), "client_id": client_id, "redirect_uri": redirect_uri},
        )

    if response_type != "code":
        return templates.TemplateResponse(
            request,
            "oauth_authorize.html",
            {"error": t("oauth.error.unsupported_response"), "client_id": client_id, "redirect_uri": redirect_uri},
        )

    if redirect_uri not in cfg.mcp_redirect_uris:
        return templates.TemplateResponse(
            request,
            "oauth_authorize.html",
            {"error": t("oauth.error.invalid_redirect"), "client_id": client_id, "redirect_uri": redirect_uri},
        )

    # Check if the user is already authenticated in Vitals
    token = request.cookies.get(SESSION_COOKIE)
    username = read_session(token)
    if username is None:
        # Redirect to login page and preserve this consent flow as target
        next_path = str(request.url.path)
        if request.url.query:
            next_path += f"?{request.url.query}"
        # next_path itself contains '&'/'?' (redirect_uri, code_challenge, state…);
        # it must be percent-encoded as a single query value or those characters
        # get parsed as separate top-level params on /login, truncating `next`
        # down to just "/oauth/authorize?response_type=code" and losing
        # client_id/redirect_uri — which then 422s after a successful login.
        login_url = f"/login?{urlencode({'next': next_path})}"
        return RedirectResponse(url=login_url, status_code=status.HTTP_302_FOUND)

    # Render consent form
    return templates.TemplateResponse(
        request,
        "oauth_authorize.html",
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "redirect_domain": urlsplit(redirect_uri).netloc,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
        },
    )


@router.post("/oauth/authorize/approve")
async def oauth_approve(
    request: Request,
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    state: Optional[str] = Form(None),
    code_challenge: Optional[str] = Form(None),
    code_challenge_method: Optional[str] = Form(None),
    redis = Depends(get_redis),
):
    """Processes user approval, stores code details in Redis, and redirects."""
    token = request.cookies.get(SESSION_COOKIE)
    username = read_session(token)
    if username is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    cfg = get_web_config()
    if client_id != cfg.mcp_client_id:
        raise HTTPException(status_code=400, detail="Invalid client_id")

    if redirect_uri not in cfg.mcp_redirect_uris:
        raise HTTPException(status_code=400, detail="redirect_uri not allowed")

    # Issue a secure authorization code
    code = f"code_{secrets.token_urlsafe(32)}"

    # Store code payload in Redis (5 minutes TTL)
    code_payload = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "username": username,
    }
    await redis.setex(f"oauth_code:{code}", 300, json.dumps(code_payload))

    # Redirect back to Claude's callback URL. Params are urlencoded so a state
    # value carrying '&'/'=' can't break out and inject extra query parameters.
    params = {"code": code}
    if state:
        params["state"] = state
    separator = "&" if "?" in redirect_uri else "?"
    target_url = f"{redirect_uri}{separator}{urlencode(params)}"

    return RedirectResponse(url=target_url, status_code=status.HTTP_302_FOUND)


# ── Token Exchange ────────────────────────────────────────────────────────────

@router.post("/oauth/token")
async def oauth_token(
    request: Request,
    redis = Depends(get_redis),
):
    """Exchanges an authorization code for a signed JWT access token."""
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
    else:
        form_data = await request.form()
        body = dict(form_data)

    grant_type = body.get("grant_type")
    code = body.get("code")
    redirect_uri = body.get("redirect_uri")
    client_id = body.get("client_id")
    client_secret = body.get("client_secret")
    code_verifier = body.get("code_verifier")

    cfg = get_web_config()

    # Read credentials from Basic Auth header if missing in body
    if not client_secret:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("basic "):
            try:
                decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
                cid, csec = decoded.split(":", 1)
                if not client_id:
                    client_id = cid
                client_secret = csec
            except Exception:
                pass

    if client_id != cfg.mcp_client_id:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_client", "error_description": "Client ID mismatch"},
        )

    # Fail-closed: an unconfigured secret must never act as a wildcard credential.
    if not cfg.mcp_client_secret:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_client", "error_description": "Client secret not configured"},
        )

    if not secrets.compare_digest(client_secret or "", cfg.mcp_client_secret):
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_client", "error_description": "Client secret mismatch"},
        )

    if grant_type != "authorization_code":
        return JSONResponse(
            status_code=400,
            content={"error": "unsupported_grant_type", "error_description": "Only authorization_code is supported"},
        )

    if not code:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_request", "error_description": "Missing code"},
        )

    # Fetch + delete the code atomically (GETDEL, Redis 6.2+; prod runs redis:7) so
    # two concurrent token requests can't both read it before it's removed — true
    # single-use even under a race, not just sequentially.
    code_key = f"oauth_code:{code}"
    code_raw = await redis.getdel(code_key)
    if not code_raw:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_grant", "error_description": "Code expired or invalid"},
        )

    code_data = json.loads(code_raw)

    if redirect_uri not in cfg.mcp_redirect_uris or redirect_uri != code_data["redirect_uri"]:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_grant", "error_description": "Redirect URI mismatch"},
        )

    # Verify PKCE challenge if requested during authorize step
    stored_challenge = code_data.get("code_challenge")
    stored_method = code_data.get("code_challenge_method")
    if stored_challenge:
        if not code_verifier:
            return JSONResponse(
                status_code=400,
                content={"error": "invalid_grant", "error_description": "Missing code_verifier"},
            )
        if not verify_pkce(code_verifier, stored_challenge, stored_method):
            return JSONResponse(
                status_code=400,
                content={"error": "invalid_grant", "error_description": "PKCE verification failed"},
            )

    # Sign the access token. Lifetime is 1 year (see expires_in below), enforced
    # on every request via max_age in the MCP auth middleware. Uses a dedicated
    # salt — see web.auth._get_mcp_serializer — so this token can never be replayed
    # as a session cookie or vice versa.
    #
    # Revocation: tokens are stateless (no server-side store), so to revoke an
    # issued token before it expires, rotate VITALS_SESSION_SECRET — that
    # invalidates every signature at once (all MCP tokens AND session cookies →
    # re-login + re-connect the Claude.ai connector). There is no per-token revoke.
    serializer = _get_mcp_serializer()
    token_payload = {
        "username": code_data["username"],
        "client_id": client_id,
        "type": "mcp_access_token",
    }
    access_token = serializer.dumps(token_payload)

    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": 31536000,  # 1 year
    }
