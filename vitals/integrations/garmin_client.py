"""Garmin Connect client (web session via ``garminconnect`` / ``garth``).

Garmin has no official API, so this wraps the community ``garminconnect`` library,
which logs in with the user's credentials and reuses an OAuth token session. To
avoid repeated logins (each one risks a captcha/MFA challenge and a temporary
block), the garth token session is cached in **Redis** (fast, shared) **and on
disk** (survives a Redis flush) — the plan's "session/token cache in Redis +
disk".

The library is synchronous (``requests`` under the hood), so every blocking call
runs in a thread via ``asyncio.to_thread``. ``garminconnect`` is **lazy-imported**
so neither importing this module nor the test suite needs the dependency
installed; only an actual fetch does.

The client returns **raw** upstream payloads — one dict of sub-responses per day,
and the raw activity list — and the service normalises + stores them. That keeps
all Garmin-specific shapes in one place and lets the service be unit-tested with a
fake client (no network, no credentials).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date as date_type
from typing import Any, Optional

from vitals.config import Config, load_config

logger = logging.getLogger(__name__)

REDIS_SESSION_KEY = "garmin:session"
# Re-use a cached session for a day before forcing a token refresh.
SESSION_TTL_SECONDS = 24 * 3600

# Sub-metrics fetched for a day. Each maps to a garminconnect method; a failure on
# one metric never aborts the day (maximal capture, best-effort).
_DAILY_METHODS = (
    ("summary", "get_user_summary"),
    ("sleep", "get_sleep_data"),
    ("rhr", "get_rhr_day"),
    ("hrv", "get_hrv_data"),
    ("stress", "get_stress_data"),
    ("training_readiness", "get_training_readiness"),
    ("max_metrics", "get_max_metrics"),
    ("training_status", "get_training_status"),
)


class GarminNotConfigured(RuntimeError):
    """Raised when a fetch is attempted without Garmin credentials."""


class GarminAuthError(RuntimeError):
    """Login failed (bad credentials, expired token, captcha)."""


class GarminMFARequired(GarminAuthError):
    """Garmin demanded an MFA code we can't satisfy headlessly. The service turns
    this into a critical ``warn`` alert; the user pre-seeds the token store
    out-of-band to recover."""


class GarminClient:
    def __init__(self, config: Optional[Config] = None, redis: Any = None):
        self._config = config or load_config()
        self._redis = redis
        self._garmin: Any = None  # cached logged-in garminconnect.Garmin

    @classmethod
    def from_config(cls, config: Optional[Config] = None, redis: Any = None) -> "GarminClient":
        return cls(config, redis)

    @property
    def is_configured(self) -> bool:
        return bool(self._config.garmin_email and self._config.garmin_password)

    # ── Session / login ─────────────────────────────────────────────────────────
    async def _load_cached_tokens(self) -> Optional[str]:
        if self._redis is None:
            return None
        try:
            return await self._redis.get(REDIS_SESSION_KEY)
        except Exception:
            return None

    async def _store_tokens(self, garmin: Any) -> None:
        try:
            token_str = await asyncio.to_thread(garmin.garth.dumps)
        except Exception:
            return
        if self._redis is not None and token_str:
            try:
                await self._redis.set(REDIS_SESSION_KEY, token_str, ex=SESSION_TTL_SECONDS)
            except Exception:
                logger.warning("Could not cache Garmin session in Redis")

    def _login_blocking(self, cached_token: Optional[str]) -> Any:
        """Resume from a cached token if possible, else the disk token store, else
        a full credential login. Runs in a worker thread."""
        from garminconnect import Garmin  # lazy

        garmin = Garmin(self._config.garmin_email, self._config.garmin_password)

        # 1) Redis-cached garth token session.
        if cached_token:
            try:
                garmin.garth.loads(cached_token)
                return garmin
            except Exception:
                logger.info("Cached Garmin token unusable — falling back to disk/login")

        # 2) On-disk token store (survives a Redis flush / restart).
        try:
            garmin.login(self._config.garmin_token_dir)
            return garmin
        except Exception:
            logger.info("No usable Garmin disk session — performing a fresh login")

        # 3) Fresh credential login.
        try:
            result = garmin.login()
        except Exception as e:  # noqa: BLE001
            raise GarminAuthError(str(e)) from e

        # Newer garminconnect returns ("needs_mfa", state) when MFA is required.
        if isinstance(result, tuple) and result and result[0] == "needs_mfa":
            raise GarminMFARequired("Garmin requires an MFA code")

        try:
            garmin.garth.dump(self._config.garmin_token_dir)
        except Exception:
            logger.warning("Could not persist Garmin session to disk")
        return garmin

    async def _ensure_login(self) -> Any:
        if self._garmin is not None:
            return self._garmin
        if not self.is_configured:
            raise GarminNotConfigured("VITALS_GARMIN_EMAIL / VITALS_GARMIN_PASSWORD not set")
        cached = await self._load_cached_tokens()
        garmin = await asyncio.to_thread(self._login_blocking, cached)
        await self._store_tokens(garmin)
        self._garmin = garmin
        return garmin

    # ── Fetches ─────────────────────────────────────────────────────────────────
    async def fetch_daily(self, on_date: date_type) -> dict:
        """All daily sub-metrics for ``on_date`` as a dict of raw payloads. Each
        missing/failed sub-metric is ``None`` rather than aborting the day."""
        garmin = await self._ensure_login()
        ds = on_date.isoformat()

        def _blocking() -> dict:
            out: dict = {}
            for key, method_name in _DAILY_METHODS:
                try:
                    method = getattr(garmin, method_name)
                    out[key] = method(ds)
                except Exception as e:  # noqa: BLE001
                    logger.warning("Garmin %s(%s) failed: %s", method_name, ds, e)
                    out[key] = None
            # body battery + body composition use a (start, end) range signature.
            for key, method_name in (
                ("body_battery", "get_body_battery"),
                ("body_composition", "get_body_composition"),
            ):
                try:
                    out[key] = getattr(garmin, method_name)(ds, ds)
                except Exception as e:  # noqa: BLE001
                    logger.warning("Garmin %s(%s) failed: %s", method_name, ds, e)
                    out[key] = None
            return out

        return await asyncio.to_thread(_blocking)

    async def fetch_activities(self, start: date_type, end: date_type) -> list[dict]:
        """Recorded activities between ``start`` and ``end`` (inclusive)."""
        garmin = await self._ensure_login()

        def _blocking() -> list[dict]:
            try:
                return garmin.get_activities_by_date(start.isoformat(), end.isoformat()) or []
            except Exception as e:  # noqa: BLE001
                logger.warning("Garmin get_activities_by_date failed: %s", e)
                return []

        return await asyncio.to_thread(_blocking)
