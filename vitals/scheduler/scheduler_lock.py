"""Redis-based distributed lock + liveness heartbeat for scheduler jobs.

Ported near-verbatim from Boxly's ``bot/services/scheduler_lock.py``. Vitals runs
one ``vitals_app`` container today, but the lock keeps every scheduled job
single-runner if that's ever scaled to >1 worker (defence in depth), and the
heartbeat lets ``/health`` flag a stalled scheduler.

    SET scheduler:lock:<job_id> NX EX <ttl>  → first worker wins; others skip.
    Release is compare-and-delete by token so we never drop a lock we no longer
    own (TTL expired + another worker took over). TTL is the crash safety net.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Awaitable, Callable, Optional

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


# ── Heartbeat ────────────────────────────────────────────────────────────────
# Each tick stamps a Redis key with the current epoch; /health compares its age
# and reports the scheduler as stale once a tick is overdue. Epoch seconds keep
# the age maths trivial and timezone-free.
def _heartbeat_key(job_id: str) -> str:
    return f"scheduler:last_run:{job_id}"


async def record_scheduler_heartbeat(redis: Redis, job_id: str) -> None:
    """Stamp ``scheduler:last_run:{job_id}`` with now. Best-effort: a Redis hiccup
    must never break the job whose liveness we're recording."""
    try:
        await redis.set(_heartbeat_key(job_id), str(int(time.time())))
    except Exception:
        logger.warning("Could not record scheduler heartbeat for %s", job_id)


async def scheduler_heartbeat_age(redis: Redis, job_id: str) -> Optional[float]:
    """Seconds since ``job_id`` last recorded a heartbeat, or None if it never has
    (key missing / unreadable) — which /health treats as 'stale' too."""
    try:
        raw = await redis.get(_heartbeat_key(job_id))
    except Exception:
        return None
    if raw is None:
        return None
    try:
        return max(0.0, time.time() - float(raw))
    except (ValueError, TypeError):
        return None


# Release only if we still own the lock. A blind DEL would delete a *different*
# worker's lock if ours had already expired (TTL) and been re-acquired. Compare-
# and-delete by token closes that.
_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


async def with_scheduler_lock(
    redis: Redis,
    job_id: str,
    ttl_seconds: int,
    fn: Callable[..., Awaitable[Any]],
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Acquire ``scheduler:lock:{job_id}``, run ``fn``, release.

    Returns the function result, or None if the lock could not be acquired
    (another worker is running the same job). The lock value is a per-acquire
    random token; release is compare-and-delete.
    """
    lock_key = f"scheduler:lock:{job_id}"
    token = uuid.uuid4().hex
    acquired = await redis.set(lock_key, token, nx=True, ex=ttl_seconds)
    if not acquired:
        logger.info("Scheduler lock busy: %s — another worker holds it", job_id)
        return None

    logger.info("Acquired scheduler lock: %s (ttl=%ds)", job_id, ttl_seconds)
    try:
        return await fn(*args, **kwargs)
    finally:
        try:
            await redis.eval(_RELEASE_SCRIPT, 1, lock_key, token)
        except Exception:
            logger.warning("Could not release scheduler lock %s — relying on TTL", job_id)
