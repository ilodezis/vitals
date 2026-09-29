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

# Everything under this prefix is the JSON API for the React app: it answers
# failures with ``{"error": ...}`` bodies and is never redirected to a login page.
API_PATH_PREFIX = "/api/"

# Short-lived handle tying the password step to the 2FA step. It carries no
# access on its own — it is signed with its own salt (see ``web/auth.py``), so it
# cannot be presented as a session cookie, and it only says "this username just
# passed the password check".
PENDING_2FA_COOKIE = "vitals_2fa"
PENDING_2FA_TTL = 300  # 5 minutes to reach for the phone and type the code

# Callback hosts of the AI clients allowed to connect to the MCP server. Matched
# by host rather than by full URL on purpose: Claude and ChatGPT each use one
# fixed callback path, but Google mints a per-user one
# (…/r/user_bound_custom-mcp-<google-account-id>-<mcp_host>), so a full-URL
# allowlist would need hand-editing on every install — and would put the owner's
# Google account id in a config file. Extend via VITALS_MCP_REDIRECT_HOSTS (csv).
DEFAULT_MCP_REDIRECT_HOSTS: tuple[str, ...] = (
    "claude.ai",                            # Claude.ai custom connector (web/desktop/mobile/Cowork)
    "chatgpt.com",                          # ChatGPT connector platform
    "oauth-redirect.googleusercontent.com", # Gemini Spark connected apps
)


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
    mcp_redirect_hosts: tuple[str, ...] = DEFAULT_MCP_REDIRECT_HOSTS
    # Shared secret for the read-only /external JSON API (a separate personal
    # dashboard app reads a few health glance cards from here server-to-server).
    # Empty = feature off: the endpoint fails closed with 503, never a
    # wildcard-open door.
    external_api_token: str = ""


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_pos_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else default


def _env_csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if not raw:
        return default
    values = tuple(v.strip() for v in raw.split(",") if v.strip())
    return values or default


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
        mcp_redirect_hosts=tuple(
            h.lower() for h in _env_csv("VITALS_MCP_REDIRECT_HOSTS", DEFAULT_MCP_REDIRECT_HOSTS)
        ),
        external_api_token=os.getenv("VITALS_EXTERNAL_API_TOKEN", ""),
    )

