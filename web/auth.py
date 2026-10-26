"""Single-user authentication logic, session cookie management, and auth router.

Uses itsdangerous timed serialization for signed session cookies, matching
the single-user configuration loaded from web/config.py.
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.i18n import t
from vitals.services import passkey_service, twofa_service
from vitals.utils.passwords import verify_password, verify_password_dummy
from web.config import (
    PASSKEY_CEREMONY_COOKIE,
    PASSKEY_CEREMONY_TTL,
    PENDING_2FA_COOKIE,
    PENDING_2FA_TTL,
    SESSION_COOKIE,
    get_web_config,
)
from web.deps import get_redis, get_session
from web.ratelimit import login_rate_limit
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


def _get_pending_2fa_serializer() -> URLSafeTimedSerializer:
    """A third salt, for the handle issued between the password step and the code
    step. Same reasoning as the MCP salt above: this token must be worthless if
    presented anywhere a real session is expected, and signature verification
    across salts fails by construction.
    """
    cfg = get_web_config()
    return URLSafeTimedSerializer(cfg.session_secret, salt="vitals-2fa")


def create_pending_2fa(username: str) -> str:
    """Sign a handle saying "this username just passed the password check"."""
    return _get_pending_2fa_serializer().dumps(username)


def read_pending_2fa(token: str | None) -> Optional[str]:
    """The username behind a live pending handle, or None if absent/expired."""
    if not token:
        return None
    try:
        payload = _get_pending_2fa_serializer().loads(token, max_age=PENDING_2FA_TTL)
    except (SignatureExpired, BadSignature):
        return None
    return payload if isinstance(payload, str) else None


def set_pending_2fa_cookie(response: Response, token: str) -> None:
    cfg = get_web_config()
    response.set_cookie(
        key=PENDING_2FA_COOKIE,
        value=token,
        max_age=PENDING_2FA_TTL,
        path="/",
        secure=cfg.cookie_secure,
        httponly=True,
        samesite=cfg.cookie_samesite,
    )


def clear_pending_2fa_cookie(response: Response) -> None:
    response.delete_cookie(key=PENDING_2FA_COOKIE, path="/")


def passkey_rp() -> Optional[passkey_service.RelyingParty]:
    """Where passkeys are bound, or None while ``VITALS_PUBLIC_ORIGIN`` is unset."""
    return passkey_service.relying_party(get_web_config().public_origin)


def set_passkey_ceremony_cookie(response: Response, ceremony_id: str) -> None:
    cfg = get_web_config()
    response.set_cookie(
        key=PASSKEY_CEREMONY_COOKIE,
        value=ceremony_id,
        max_age=PASSKEY_CEREMONY_TTL,
        path="/",
        secure=cfg.cookie_secure,
        httponly=True,
        samesite=cfg.cookie_samesite,
    )


def clear_passkey_ceremony_cookie(response: Response) -> None:
    response.delete_cookie(key=PASSKEY_CEREMONY_COOKIE, path="/")


def safe_next(next: str | None) -> str:
    """Confine the post-login redirect to a local path (open-redirect guard).

    Accept only a value that resolves to a same-site path: it must begin with a
    single ``/`` and carry no scheme or host. Reject absolute URLs, protocol-
    relative ``//host``, and backslash tricks like ``/\\host`` (browsers normalise
    ``\\`` to ``/``, turning it into a protocol-relative off-site redirect).
    Anything else falls back to ``/``.
    """
    if not next or not next.startswith("/") or next.startswith("//") or "\\" in next:
        return "/"
    parsed = urlsplit(next)
    if parsed.scheme or parsed.netloc:
        return "/"
    return next


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
    return templates.TemplateResponse(
        request, "login.html", {"next": safe_next(next), "passkeys": passkey_rp() is not None}
    )


@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: Optional[str] = Form(None),
    # Bound password-guessing by IP. `rate_limit` can't guard this route (it needs
    # an authenticated username for its key), so `/login` gets a dedicated IP-based
    # limiter — this is the only pre-auth entry point and the one that needs it most.
    _rl: None = Depends(login_rate_limit(limit=10, window=300)),
    db: AsyncSession = Depends(get_session),
):
    next_url = safe_next(next)
    if authenticate(username, password):
        # 2FA on → the password alone completes nothing. Hand over only the
        # short-lived pending handle and send the browser to the code step; the
        # real session is minted there and nowhere else.
        if (await twofa_service.get_state(db)).enabled:
            response = RedirectResponse(
                url=f"/login/2fa?next={quote(next_url, safe='')}",
                status_code=status.HTTP_303_SEE_OTHER,
            )
            set_pending_2fa_cookie(response, create_pending_2fa(username))
            return response

        token = create_session(username)
        response = RedirectResponse(url=next_url, status_code=status.HTTP_303_SEE_OTHER)
        set_session_cookie(response, token)
        return response

    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "error": t("login.error.bad_credentials"),
            "next": next_url,
            "passkeys": passkey_rp() is not None,
        },
    )


# ── Second factor (step 2 of login, only when 2FA is switched on) ─────────────


@router.get("/login/2fa", response_class=HTMLResponse)
async def login_2fa_page(request: Request, next: Optional[str] = None):
    # Reachable only with a live pending handle, so the page can't be used to
    # probe whether 2FA is on for this install.
    if read_pending_2fa(request.cookies.get(PENDING_2FA_COOKIE)) is None:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(request, "login_2fa.html", {"next": safe_next(next)})


@router.post("/login/2fa")
async def login_2fa(
    request: Request,
    code: str = Form(...),
    next: Optional[str] = Form(None),
    # Global, not per-IP: six digits are guessable in bulk and rotating the
    # source address must not buy a fresh allowance. See ``login_rate_limit``.
    _rl: None = Depends(
        login_rate_limit(limit=10, window=300, bucket="login_2fa", per_ip=False)
    ),
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
):
    next_url = safe_next(next)
    token = request.cookies.get(PENDING_2FA_COOKIE)
    username = read_pending_2fa(token)
    if username is None:
        # Nothing to complete — five minutes ran out, or there was never a
        # password step. Start over rather than hint at which.
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    state = await twofa_service.get_state(db)
    step = twofa_service.verify_code(state.secret, code) if state.enabled else None
    if step is None or not await twofa_service.consume_step(redis, step):
        return templates.TemplateResponse(
            request,
            "login_2fa.html",
            {"error": t("login.error.bad_code"), "next": next_url},
        )

    response = RedirectResponse(url=next_url, status_code=status.HTTP_303_SEE_OTHER)
    set_session_cookie(response, create_session(username))
    clear_pending_2fa_cookie(response)
    return response


# ── Passkey sign-in (only when VITALS_PUBLIC_ORIGIN is set) ───────────────────
# A sign-in of its own, not a step after the password: the authenticator checks
# the owner's face/fingerprint/PIN before it signs, so the session is minted here
# without the TOTP step. See ``passkey_service`` for why that is two factors.


def _passkey_refused(code: str, status_code: int = status.HTTP_400_BAD_REQUEST) -> JSONResponse:
    response = JSONResponse({"error": code}, status_code=status_code)
    clear_passkey_ceremony_cookie(response)
    return response


@router.post("/login/passkey/options")
async def login_passkey_options(
    # Called on every visit to the login page (it arms the autofill), so the
    # budget is wider than the password form's. Still per-IP: it hands out
    # challenges, and a loop shouldn't be able to fill Redis with them.
    _rl: None = Depends(
        login_rate_limit(limit=30, window=300, bucket="login_passkey_options")
    ),
    redis: Redis = Depends(get_redis),
):
    rp = passkey_rp()
    if rp is None:
        return _passkey_refused("unavailable", status.HTTP_404_NOT_FOUND)
    options, challenge = passkey_service.authentication_options(rp)
    try:
        ceremony_id = await passkey_service.start_ceremony(
            redis, passkey_service.LOGIN, challenge
        )
    except Exception:
        logger.warning("passkey ceremony store unavailable", exc_info=True)
        return _passkey_refused("unavailable", status.HTTP_503_SERVICE_UNAVAILABLE)
    response = Response(content=options, media_type="application/json")
    set_passkey_ceremony_cookie(response, ceremony_id)
    return response


class PasskeyLoginBody(BaseModel):
    # What navigator.credentials.get() returned, in its JSON form.
    credential: dict[str, Any]
    next: Optional[str] = None


@router.post("/login/passkey/verify")
async def login_passkey_verify(
    request: Request,
    body: PasskeyLoginBody,
    _rl: None = Depends(login_rate_limit(limit=10, window=300, bucket="login_passkey")),
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
):
    rp = passkey_rp()
    if rp is None:
        return _passkey_refused("unavailable", status.HTTP_404_NOT_FOUND)
    challenge = await passkey_service.take_ceremony(
        redis, request.cookies.get(PASSKEY_CEREMONY_COOKIE), passkey_service.LOGIN
    )
    if challenge is None:
        return _passkey_refused("expired")
    try:
        await passkey_service.finish_authentication(
            db, rp, credential=body.credential, challenge=challenge
        )
    except passkey_service.PasskeyError as exc:
        return _passkey_refused(exc.code)
    await db.commit()

    response = JSONResponse({"redirect": safe_next(body.next)})
    set_session_cookie(response, create_session(get_web_config().auth_username))
    clear_pending_2fa_cookie(response)
    clear_passkey_ceremony_cookie(response)
    return response


# POST only: a GET logout is a link, and any page (or prefetcher) can point at it.
# Both templates already submit a form — masthead.html and more.html.
@router.post("/logout")
async def logout(request: Request):
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    clear_session_cookie(response)
    clear_pending_2fa_cookie(response)
    clear_passkey_ceremony_cookie(response)
    return response
