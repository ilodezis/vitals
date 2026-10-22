"""Garmin Connect client (web session via ``garminconnect``).

Garmin has no official API, so this wraps the community ``garminconnect`` library,
which logs in with the user's credentials and reuses an OAuth token session. To
avoid repeated logins (each one risks a captcha/MFA challenge and a temporary
block), the token session is cached in **Redis** (fast, shared) **and on disk**
(survives a Redis flush) — the plan's "session/token cache in Redis + disk".

**Garmin rate-limits the login, not the reads.** A resumed token session costs
nothing, but a credential login runs five SSO strategies, and a burst of those
gets the *account* (not the IP) blocked for 48h+ — with every further attempt
extending the block. So this module keeps two guarantees:

  * a token session is never allowed to escalate into a credential login by
    accident (``_resume_blocking`` vs ``_fresh_login_blocking``), and
  * credential logins are rationed by a Redis breaker (``_reserve_login``).

Everything that keeps the token alive is therefore load-bearing, and a failure
to store it is reported (``token_warnings`` → a ``warn`` alert in the service)
rather than logged and forgotten: a session that silently fails to persist means
*every* poll logs in again, which is exactly how the account gets blocked.

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
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from vitals.config import Config, load_config

logger = logging.getLogger(__name__)

REDIS_SESSION_KEY = "garmin:session"
# Re-use a cached session for a day before forcing a token refresh.
SESSION_TTL_SECONDS = 24 * 3600

# ── Credential-login breaker ─────────────────────────────────────────────────
# A healthy token session never moves these counters: they only tick when a
# login actually happens. Three a day is generous for a working setup and far
# below the burst that triggers a block.
LOGIN_ATTEMPTS_KEY = "garmin:login_attempts"
LOGIN_PAUSE_KEY = "garmin:login_pause"
MAX_LOGINS_PER_DAY = 3
LOGIN_PAUSE_SECONDS = 6 * 3600

# A real session is ~2 KB of token JSON; anything shorter is a truncated or
# foreign value, not a token worth handing to the library.
_TOKEN_STRING_MIN_LEN = 512

# Sub-metrics fetched for a day. Each maps to a garminconnect method; a failure on
# one metric never aborts the day (maximal capture, best-effort).
_DAILY_METHODS = (
    ("summary", "get_user_summary"),
    ("sleep", "get_sleep_data"),
    ("rhr", "get_rhr_day"),
    ("hrv", "get_hrv_data"),
    ("stress", "get_stress_data"),
    ("heart_rate", "get_heart_rates"),
    ("training_readiness", "get_training_readiness"),
    ("max_metrics", "get_max_metrics"),
    ("training_status", "get_training_status"),
)

# Key under which :meth:`GarminClient.fetch_daily` lists the sub-metrics whose
# call raised. A ``None`` next to it means "Garmin did not answer", not "the day
# has no such data" — the service must not let it overwrite a stored value.
FAILED_KEY = "_failed"


class GarminNotConfigured(RuntimeError):
    """Raised when a fetch is attempted without Garmin credentials."""


class GarminAuthError(RuntimeError):
    """Login failed (bad credentials, expired token, captcha)."""


class GarminMFARequired(GarminAuthError):
    """Garmin demanded an MFA code we can't satisfy headlessly. The service turns
    this into a critical ``warn`` alert; the user pre-seeds the token store
    out-of-band to recover."""


class GarminLoginThrottled(GarminAuthError):
    """The breaker refused a credential login — the daily allowance is spent or a
    pause is in force. Never a reason to retry sooner: retries are what turn a
    Garmin rate-limit into a multi-day account block."""


async def login_breaker_state(redis: Any) -> dict:
    """What the credential-login breaker has spent — read-only, for the settings
    card. Without it the poll-frequency fields would be set blind: the whole
    reason a higher frequency is safe is that logins stay rationed.

    Unreadable state reports as ``paused=None`` rather than as "fine": a breaker
    nobody can see is exactly what the owner needs told.
    """
    if redis is None:
        return {"used": 0, "max": MAX_LOGINS_PER_DAY, "paused": None}
    try:
        used = int(await redis.get(LOGIN_ATTEMPTS_KEY) or 0)
        paused = bool(await redis.get(LOGIN_PAUSE_KEY))
    except Exception:  # noqa: BLE001
        logger.warning("Garmin breaker state unreadable", exc_info=True)
        return {"used": 0, "max": MAX_LOGINS_PER_DAY, "paused": None}
    return {"used": used, "max": MAX_LOGINS_PER_DAY, "paused": paused}


class GarminClient:
    def __init__(self, config: Optional[Config] = None, redis: Any = None):
        self._config = config or load_config()
        self._redis = redis
        self._garmin: Any = None  # cached logged-in garminconnect.Garmin
        # Token-store failures collected during this client's life; the service
        # turns them into a warn alert instead of letting them pass as log noise.
        self.token_warnings: list[str] = []

    @classmethod
    def from_config(cls, config: Optional[Config] = None, redis: Any = None) -> "GarminClient":
        return cls(config, redis)

    @property
    def is_configured(self) -> bool:
        return bool(self._config.garmin_email and self._config.garmin_password)

    # ── Session / login ─────────────────────────────────────────────────────────
    def _warn_token(self, message: str) -> None:
        """Record a token-store failure. These used to be swallowed, which is the
        worst possible outcome: the sync keeps working off the in-memory session
        while the stored one rots, and the day the process restarts every poll
        starts logging in again."""
        logger.warning("Garmin token store: %s", message)
        self.token_warnings.append(message)

    async def _load_cached_tokens(self) -> Optional[str]:
        if self._redis is None:
            return None
        try:
            return await self._redis.get(REDIS_SESSION_KEY)
        except Exception as e:  # noqa: BLE001
            self._warn_token(f"could not read the cached session from Redis: {e}")
            return None

    async def _store_tokens(self, garmin: Any) -> None:
        if self._redis is None:
            return
        try:
            token_str = await asyncio.to_thread(garmin.client.dumps)
        except Exception as e:  # noqa: BLE001
            self._warn_token(f"could not serialise the session: {e}")
            return
        if not token_str:
            self._warn_token("the library returned an empty session")
            return
        try:
            await self._redis.set(REDIS_SESSION_KEY, token_str, ex=SESSION_TTL_SECONDS)
        except Exception as e:  # noqa: BLE001
            self._warn_token(f"could not cache the session in Redis: {e}")

    def _resume_blocking(self, cached_token: Optional[str]) -> Any:
        """Log in from a stored token session — Redis first, then the disk store.
        Returns ``None`` when neither works, and **never** falls back to
        credentials. Runs in a worker thread.

        The split from ``_fresh_login_blocking`` is the whole point:
        ``Garmin.login(store)`` silently escalates to a full credential login when
        the store doesn't parse, so calling it blind would spend the expensive
        path without the breaker ever seeing it. Loading the tokens ourselves
        first is a local read with no network — and once they load, ``login()``
        stays on the token path: since 0.3.7 there is one more escalation (a
        cached token the API rejects triggers a fresh credential login), and it
        is skipped precisely because we pass ``return_on_mfa=True``."""
        from garminconnect import Garmin  # lazy

        sources = (("Redis", cached_token), ("disk", self._config.garmin_token_dir))
        for label, tokenstore in sources:
            if not tokenstore:
                continue
            if label == "Redis" and len(tokenstore) < _TOKEN_STRING_MIN_LEN:
                self._warn_token("the cached session is too short to be a token")
                continue
            # A fresh instance per attempt so a half-loaded store can't leak into
            # the next source.
            garmin = Garmin(
                self._config.garmin_email, self._config.garmin_password, return_on_mfa=True
            )
            try:
                if label == "Redis":
                    garmin.client.loads(tokenstore)
                else:
                    garmin.client.load(tokenstore)
                garmin.login(tokenstore)
                return garmin
            except Exception as e:  # noqa: BLE001
                logger.info("Garmin %s token session unusable: %s", label, e)
        return None

    def _fresh_login_blocking(self) -> Any:
        """A real credential login — the rationed path. Runs in a worker thread.

        Called with no token store on purpose: the stored session has already been
        tried and rejected by ``_resume_blocking``, and passing it again would just
        make the library retry the same dead token instead of the credentials."""
        from garminconnect import Garmin  # lazy

        garmin = Garmin(
            self._config.garmin_email, self._config.garmin_password, return_on_mfa=True
        )
        try:
            result = garmin.login()
        except Exception as e:  # noqa: BLE001
            raise GarminAuthError(str(e)) from e

        # With return_on_mfa the library hands back ("needs_mfa", state) instead of
        # prompting on a stdin nobody is attached to.
        if isinstance(result, tuple) and result and result[0] == "needs_mfa":
            raise GarminMFARequired("Garmin requires an MFA code")

        try:
            garmin.client.dump(self._config.garmin_token_dir)
        except Exception as e:  # noqa: BLE001
            self._warn_token(f"could not write the new session to the token store: {e}")
        return garmin

    async def _reserve_login(self) -> None:
        """Spend one credential login from the daily allowance, or refuse.

        Fails **closed**: if the counter can't be read or written we refuse rather
        than risk an uncounted login, because a missed sync costs a few hours and a
        blocked account costs days."""
        if self._redis is None:
            # Never the case in the app — the scheduler and the web both pass one.
            logger.warning("Garmin login breaker inactive: no Redis available")
            return
        try:
            if await self._redis.get(LOGIN_PAUSE_KEY):
                raise GarminLoginThrottled(
                    f"login paused for up to {LOGIN_PAUSE_SECONDS // 3600}h "
                    "after the daily limit was hit"
                )
            used = int(await self._redis.incr(LOGIN_ATTEMPTS_KEY))
            if used == 1:
                await self._redis.expire(LOGIN_ATTEMPTS_KEY, SESSION_TTL_SECONDS)
            if used > MAX_LOGINS_PER_DAY:
                await self._redis.set(LOGIN_PAUSE_KEY, "1", ex=LOGIN_PAUSE_SECONDS)
                raise GarminLoginThrottled(
                    f"{MAX_LOGINS_PER_DAY} logins already used in 24h — "
                    f"pausing for {LOGIN_PAUSE_SECONDS // 3600}h"
                )
        except GarminLoginThrottled:
            raise
        except Exception as e:  # noqa: BLE001
            raise GarminLoginThrottled(f"login breaker unavailable: {e}") from e

    async def _ensure_login(self) -> Any:
        if self._garmin is not None:
            return self._garmin
        if not self.is_configured:
            raise GarminNotConfigured("VITALS_GARMIN_EMAIL / VITALS_GARMIN_PASSWORD not set")
        cached = await self._load_cached_tokens()
        garmin = await asyncio.to_thread(self._resume_blocking, cached)
        if garmin is None:
            await self._reserve_login()
            garmin = await asyncio.to_thread(self._fresh_login_blocking)
        await self._store_tokens(garmin)
        self._garmin = garmin
        return garmin

    # ── Fetches ─────────────────────────────────────────────────────────────────
    async def fetch_daily(self, on_date: date_type) -> dict:
        """All daily sub-metrics for ``on_date`` as a dict of raw payloads. Each
        missing/failed sub-metric is ``None`` rather than aborting the day; the
        ones that failed are also listed under :data:`FAILED_KEY`."""
        garmin = await self._ensure_login()
        ds = on_date.isoformat()

        def _blocking() -> dict:
            out: dict = {}
            failed: list[str] = []
            for key, method_name in _DAILY_METHODS:
                try:
                    method = getattr(garmin, method_name)
                    out[key] = method(ds)
                except Exception as e:  # noqa: BLE001
                    logger.warning("Garmin %s(%s) failed: %s", method_name, ds, e)
                    out[key] = None
                    failed.append(key)
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
                    failed.append(key)
            if failed:
                out[FAILED_KEY] = failed
            return out

        return await asyncio.to_thread(_blocking)

    async def fetch_summary(self, on_date: date_type) -> dict:
        """The day summary alone — **one** upstream call (N3).

        The light pulse: steps, calories and intensity minutes move all day, the
        rest of the bundle (sleep, HRV, readiness) is settled by morning. Polling
        this every quarter hour costs one request and no login — the full
        :meth:`fetch_daily` would cost ten for numbers that haven't changed."""
        garmin = await self._ensure_login()
        ds = on_date.isoformat()

        def _blocking() -> dict:
            try:
                return garmin.get_user_summary(ds) or {}
            except Exception as e:  # noqa: BLE001
                logger.warning("Garmin get_user_summary(%s) failed: %s", ds, e)
                return {}

        return await asyncio.to_thread(_blocking)

    # ── Weight writes ──────────────────────────────────────────────────────────
    # Unlike the broad daily fetch above, these calls intentionally propagate
    # upstream failures.  The outbox service needs to distinguish a confirmed
    # write from one it must reconcile on the next attempt.
    async def fetch_daily_weigh_ins(self, on_date: date_type) -> Any:
        """Individual weigh-ins Garmin currently stores for ``on_date``."""
        garmin = await self._ensure_login()
        result = await asyncio.to_thread(garmin.get_daily_weigh_ins, on_date.isoformat())
        # Preserve ``None`` (missing/ambiguous response) versus an explicit empty
        # dict/list. The export safety layer treats only the latter as an empty day.
        return result

    async def add_weigh_in(self, weight_kg: float, measured_at: datetime) -> Any:
        """Create a manual Garmin weigh-in at a local wall-clock moment.

        ``garminconnect`` accepts an ISO timestamp and performs the web request;
        attaching the configured zone here prevents a UTC container from moving
        a late-evening measurement onto the wrong Garmin calendar day.
        """
        garmin = await self._ensure_login()
        zone = ZoneInfo(self._config.timezone)
        if measured_at.tzinfo is None:
            measured_at = measured_at.replace(tzinfo=zone)
        else:
            measured_at = measured_at.astimezone(zone)
        # Preserve the millisecond correlation marker used to recover the exact
        # ``samplePk`` after garminconnect's normal 204/None response.
        timestamp = measured_at.isoformat(timespec="milliseconds")
        return await asyncio.to_thread(
            garmin.add_weigh_in,
            float(weight_kg),
            unitKey="kg",
            timestamp=timestamp,
        )

    async def delete_weigh_in(self, sample_pk: str, on_date: date_type) -> Any:
        """Delete one known Garmin weigh-in by its opaque ``samplePk``."""
        garmin = await self._ensure_login()
        return await asyncio.to_thread(
            garmin.delete_weigh_in, sample_pk, on_date.isoformat()
        )

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

    async def fetch_activity_details(self, activity_id: Any) -> dict:
        """Per-activity detail: HR-zone boundaries + per-lap splits. Kept to two
        calls to bound the request fan-out (only run for the handful of
        activities inside a sync window). Best-effort — a failed sub-call yields
        ``None`` rather than aborting the activity. The activity summary already
        carries elevation/power/training-effect scalars, so those need no call."""
        garmin = await self._ensure_login()

        def _blocking() -> dict:
            out: dict = {}
            for key, method_name in (
                ("hr_zones", "get_activity_hr_zones"),
                ("splits", "get_activity_splits"),
            ):
                try:
                    out[key] = getattr(garmin, method_name)(activity_id)
                except Exception as e:  # noqa: BLE001
                    logger.warning("Garmin %s(%s) failed: %s", method_name, activity_id, e)
                    out[key] = None
            return out

        return await asyncio.to_thread(_blocking)
