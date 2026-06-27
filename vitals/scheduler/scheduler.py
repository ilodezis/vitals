"""APScheduler framework for Vitals.

The foundation ships the *framework* + a 1-minute ``keepalive`` heartbeat so
``/health`` can detect a stalled scheduler from day one. Per-module jobs (Hevy
every 6h, Garmin poll, weekly digest, plateau/lab checks) attach by calling
:func:`register_job` at import/startup — no edits here.

Every job runs under the Redis lock (single-runner across workers) and stamps a
heartbeat each tick. Job functions have the signature
``async def job(session_factory, redis) -> None``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from vitals.scheduler.scheduler_lock import (
    record_scheduler_heartbeat,
    with_scheduler_lock,
)

logger = logging.getLogger(__name__)

JobFunc = Callable[[async_sessionmaker[AsyncSession], Optional[Redis]], Awaitable[None]]

KEEPALIVE_JOB_ID = "keepalive"


@dataclass
class JobSpec:
    id: str
    func: JobFunc
    trigger: str  # "interval" | "cron"
    trigger_kwargs: dict = field(default_factory=dict)
    lock_ttl: int = 300
    heartbeat: bool = True


_registry: dict[str, JobSpec] = {}


def register_job(
    job_id: str,
    func: JobFunc,
    *,
    trigger: str,
    lock_ttl: int = 300,
    heartbeat: bool = True,
    **trigger_kwargs: Any,
) -> None:
    """Register a scheduled job. Modules call this at import/startup. Re-registering
    the same id replaces the previous spec."""
    _registry[job_id] = JobSpec(
        id=job_id,
        func=func,
        trigger=trigger,
        trigger_kwargs=trigger_kwargs,
        lock_ttl=lock_ttl,
        heartbeat=heartbeat,
    )


def clear_jobs() -> None:
    """Drop all registered jobs (test isolation)."""
    _registry.clear()


def heartbeat_job_ids() -> list[str]:
    """Job ids ``/health`` should watch — the keepalive plus every registered job
    that records a heartbeat."""
    ids = [KEEPALIVE_JOB_ID]
    ids.extend(spec.id for spec in _registry.values() if spec.heartbeat)
    return ids


def _make_runner(
    spec: JobSpec,
    session_factory: async_sessionmaker[AsyncSession],
    redis: Optional[Redis],
) -> Callable[[], Awaitable[None]]:
    async def _run() -> None:
        # Liveness stamp first — recorded every tick even when the lock is busy.
        if redis is not None and spec.heartbeat:
            await record_scheduler_heartbeat(redis, spec.id)
        try:
            if redis is None:
                await spec.func(session_factory, redis)
            else:
                await with_scheduler_lock(
                    redis, spec.id, spec.lock_ttl, spec.func, session_factory, redis
                )
        except Exception:
            logger.exception("Scheduled job %s failed", spec.id)

    return _run


async def _keepalive(redis: Optional[Redis]) -> None:
    if redis is not None:
        await record_scheduler_heartbeat(redis, KEEPALIVE_JOB_ID)


def setup_scheduler(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Optional[Redis] = None,
    *,
    timezone: str = "Europe/Chisinau",
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=timezone)

    for spec in _registry.values():
        scheduler.add_job(
            _make_runner(spec, session_factory, redis),
            trigger=spec.trigger,
            id=spec.id,
            replace_existing=True,
            **spec.trigger_kwargs,
        )

    # Always-on heartbeat so a dead scheduler is detectable even before any module
    # job is registered.
    scheduler.add_job(
        lambda: _keepalive(redis),
        trigger="interval",
        minutes=1,
        id=KEEPALIVE_JOB_ID,
        replace_existing=True,
    )
    return scheduler


async def seed_heartbeats(redis: Optional[Redis]) -> None:
    """Seed every monitored heartbeat at startup so ``/health`` is green
    immediately (APScheduler's first interval tick is one minute out)."""
    if redis is None:
        return
    for job_id in heartbeat_job_ids():
        await record_scheduler_heartbeat(redis, job_id)
