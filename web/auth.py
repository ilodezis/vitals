"""Single-user authentication logic, session cookie management, and auth router.

Uses itsdangerous timed serialization for signed session cookies, matching
the single-user configuration loaded from web/config.py.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from web.config import SESSION_COOKIE, get_web_config
from web.security import verify_password, verify_password_dummy
from web.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_serializer() -> URLSafeTimedSerializer:
    cfg = get_web_config()
    return URLSafeTimedSerializer(cfg.session_secret, salt="vitals-session")


def _get_mcp_serializer() -> URLSafeTimedSerializer:
    """Separate salt from the session serializer so a session cookie and an MCP
    access token can never be mistaken for one another (signature verification
    fails across salts even though both derive from the same session secret).
    """
    cfg = get_web_config()
    return URLSafeTimedSerializer(cfg.session_secret, salt="vitals-mcp")


def safe_next(next: str | None) -> str:
    """Confine the post-login redirect to a local path (open-redirect guard).

    Accept only a value beginning with a single ``/``; reject absolute URLs and
    protocol-relative ``//host`` targets (which browsers resolve off-site).
    Anything else falls back to ``/``.
    """
    if next and next.startswith("/") and not next.startswith("//"):
        return next
    return "/"


def read_session(token: str | None) -> Optional[str]:
    """Verify and load the username from a signed session token.

    Returns the username if valid, or None if expired, tampered, or — since MCP
    access tokens are dict payloads, not bare usernames — actually an MCP token
    presented as a session cookie.
    """
    if not token:
        return None
    cfg = get_web_config()
    serializer = _get_serializer()
    try:
        payload = serializer.loads(token, max_age=cfg.session_ttl)
    except (SignatureExpired, BadSignature):
        return None
    if not isinstance(payload, str):
        return None
    return payload


def create_session(username: str) -> str:
    """Generate a signed session token for a username."""
    serializer = _get_serializer()
    return serializer.dumps(username)


def set_session_cookie(response: Response, token: str) -> None:
    """Set the session cookie on an HTTP response."""
    cfg = get_web_config()
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=cfg.session_ttl,
        expires=cfg.session_ttl,
        path="/",
        secure=cfg.cookie_secure,
        httponly=True,
        samesite=cfg.cookie_samesite,
    )


def clear_session_cookie(response: Response) -> None:
    """Clear the session cookie from an HTTP response."""
    response.delete_cookie(
        key=SESSION_COOKIE,
        path="/",
    )


def authenticate(username: str, password: str) -> bool:
    """Verify single-user credentials with constant-time check fallback."""
    cfg = get_web_config()
    if username != cfg.auth_username:
        verify_password_dummy(password)
        return False
    return verify_password(password, cfg.auth_password_hash)


# ── Auth Endpoints ────────────────────────────────────────────────────────────


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: Optional[str] = None):
    # If already logged in, redirect to dashboard
    token = request.cookies.get(SESSION_COOKIE)
    if read_session(token) is not None:
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(request, "login.html", {"next": safe_next(next)})


@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: Optional[str] = Form(None),
):
    next_url = safe_next(next)
    if authenticate(username, password):
        token = create_session(username)
        response = RedirectResponse(url=next_url, status_code=status.HTTP_303_SEE_OTHER)
        set_session_cookie(response, token)
        return response

    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": "Неверное имя пользователя или пароль", "next": next_url},
    )


@router.get("/logout")
@router.post("/logout")
async def logout(request: Request):
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    clear_session_cookie(response)
    return response
