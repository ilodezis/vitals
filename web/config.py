"""Web-panel configuration (single-user).

Adds the few web-only knobs the core doesn't care about: the session signing
secret, cookie flags/lifetime, and the single account's credentials. Read lazily
(not at import) so the test suite can set env first and a missing secret only
blows up when the web app actually starts.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

SESSION_COOKIE = "vitals_session"
DEFAULT_SESSION_TTL = 30 * 24 * 3600  # 30 days


@dataclass(frozen=True)
class WebConfig:
    session_secret: str
    auth_username: str
    auth_password_hash: str
    session_ttl: int = DEFAULT_SESSION_TTL
    cookie_secure: bool = True
    cookie_samesite: str = "lax"
    mcp_client_id: str = "vitals-claude-connector"
    mcp_client_secret: str = ""


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_pos_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else default


def get_web_config() -> WebConfig:
    """Build the web config from the environment. Raises ``RuntimeError`` when a
    required secret is missing — there's no safe default for the session secret."""
    session_secret = os.getenv("VITALS_SESSION_SECRET")
    if not session_secret:
        raise RuntimeError("VITALS_SESSION_SECRET is not set")

    username = os.getenv("VITALS_AUTH_USERNAME")
    if not username:
        raise RuntimeError("VITALS_AUTH_USERNAME is not set")

    password_hash = os.getenv("VITALS_AUTH_PASSWORD_HASH", "")

    return WebConfig(
        session_secret=session_secret,
        auth_username=username,
        auth_password_hash=password_hash,
        session_ttl=_env_pos_int("VITALS_SESSION_TTL", DEFAULT_SESSION_TTL),
        cookie_secure=_env_bool("VITALS_COOKIE_SECURE", True),
        cookie_samesite=os.getenv("VITALS_COOKIE_SAMESITE", "lax"),
        mcp_client_id=os.getenv("VITALS_MCP_CLIENT_ID", "vitals-claude-connector"),
        mcp_client_secret=os.getenv("VITALS_MCP_CLIENT_SECRET", ""),
    )

