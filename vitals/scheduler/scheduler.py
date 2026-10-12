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
from datetime import datetime
from functools import partial
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

# APScheduler's own default grace is one second: an event loop busy for a second
# at the fire time (a PDF being rasterised, a slow query) silently dropped the
# run — the Monday digest, the nightly sweep — with nothing but a log line. An
# hour of grace still runs a late tick; ``coalesce`` folds a backlog of missed
# ticks (an interval job after a long stall) into one run instead of a burst.
JOB_DEFAULTS = {"misfire_grace_time": 3600, "coalesce": True}

# One active alert per failing job — the id is part of the key (never a timestamp,
# which would defeat the dedupe index and pile up a row per failed tick).
JOB_FAILED_KEY_PREFIX = "scheduler.job_failed"


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


# How many upcoming fires to sample when sizing a job's staleness budget. Eight
# covers a full cycle of every schedule in use (a 4-times-a-day cron, a weekly
# digest), so the widest real gap is always among the samples.
_FIRE_SAMPLES = 8
# Slack on top of that gap: a tick may start late or run long, and a false
# "scheduler is dead" is worse than noticing a genuinely dead job minutes later.
_BUDGET_SLACK_SECONDS = 300.0


def _max_gap_seconds(spec: JobSpec, timezone: str) -> float:
    """Longest wait between two consecutive fires of ``spec``'s schedule.

    Measured with the job's own APScheduler trigger rather than parsed by hand —
    a cron at 03:00/11:00/16:00/22:00 has an 8-hour worst gap that no arithmetic
    over the kwargs would give us.
    """
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    factory = CronTrigger if spec.trigger == "cron" else IntervalTrigger
    trigger = factory(timezone=timezone, **spec.trigger_kwargs)
    now = datetime.now(trigger.timezone)

    fires: list[datetime] = []
    previous: Optional[datetime] = None
    for _ in range(_FIRE_SAMPLES):
        nxt = trigger.get_next_fire_time(previous, previous or now)
        if nxt is None:  # a finite schedule that has run out
            break
        fires.append(nxt)
        previous = nxt

    gaps = [(b - a).total_seconds() for a, b in zip(fires, fires[1:])]
    return max(gaps) if gaps else 86400.0


def heartbeat_budgets(timezone: str) -> dict[str, float]:
    """How stale each watched job's heartbeat may get before ``/health`` calls the
    scheduler unhealthy, in seconds.

    A one-minute keepalive and an eight-hour Garmin poll cannot share a single
    threshold: the old fixed 120s only ever fitted the keepalive, so every module
    job could stop firing without turning ``/health`` red. Each job now gets a
    budget derived from its own schedule.
    """
    budgets = {KEEPALIVE_JOB_ID: 120.0}
    for spec in _registry.values():
        if spec.heartbeat:
            budgets[spec.id] = _max_gap_seconds(spec, timezone) + _BUDGET_SLACK_SECONDS
    return budgets


async def _record_job_outcome(
    session_factory: async_sessionmaker[AsyncSession], job_id: str, error: Optional[str]
) -> None:
    """Raise a ``warn`` alert when a job run failed; clear it when one succeeds.

    Without this a broken sync is invisible: the heartbeat is stamped before the
    run, so ``/health`` stays green while the data lake quietly stops filling.
    One guard on the shared runner covers every registered job — ``hevy_service``
    handles no errors at all today and ``garmin_service`` only auth/MFA ones.
    """
    from vitals.enums import Domain, Severity
    from vitals.i18n import t
    from vitals.services import alerts_service

    alert_key = f"{JOB_FAILED_KEY_PREFIX}:{job_id}"
    try:
        async with session_factory() as session:
            if error is None:
                await alerts_service.resolve_by_key(session, alert_key=alert_key)
            else:
                await alerts_service.raise_alert(
                    session,
                    domain=Domain.SYSTEM.value,
                    severity=Severity.WARN.value,
                    message=t("alert.job_failed", job=job_id, error=error),
                    alert_key=alert_key,
                )
            await session.commit()
    except Exception:
        # Alert bookkeeping must never break the tick that reported the failure.
        logger.exception("Could not record outcome of scheduled job %s", job_id)


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
        except Exception as exc:
            logger.exception("Scheduled job %s failed", spec.id)
            detail = str(exc)[:200] or exc.__class__.__name__
            await _record_job_outcome(session_factory, spec.id, detail)
        else:
            await _record_job_outcome(session_factory, spec.id, None)

    return _run


async def _keepalive(redis: Optional[Redis]) -> None:
    if redis is not None:
        await record_scheduler_heartbeat(redis, KEEPALIVE_JOB_ID)


def apply_registry(
    scheduler: AsyncIOScheduler,
    session_factory: async_sessionmaker[AsyncSession],
    redis: Optional[Redis] = None,
) -> None:
    """(Re)attach the registry to a scheduler — including a *running* one.

    This is what makes a settings save take effect without a restart:
    ``register_all_jobs`` rebuilds the registry from the new settings and this
    replaces the live jobs with it. Removing what is no longer registered matters
    just as much as adding — switch the Garmin pulse off and the old interval job
    would otherwise keep firing until the next deploy.
    """
    for spec in _registry.values():
        scheduler.add_job(
            _make_runner(spec, session_factory, redis),
            trigger=spec.trigger,
            id=spec.id,
            replace_existing=True,
            **spec.trigger_kwargs,
        )

    keep = set(_registry) | {KEEPALIVE_JOB_ID}
    for job in scheduler.get_jobs():
        if job.id not in keep:
            scheduler.remove_job(job.id)


def setup_scheduler(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Optional[Redis] = None,
    *,
    timezone: str = "Europe/Chisinau",
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=timezone, job_defaults=JOB_DEFAULTS)

    apply_registry(scheduler, session_factory, redis)

    # Always-on heartbeat so a dead scheduler is detectable even before any module
    # job is registered.
    #
    # ``partial``, not ``lambda: _keepalive(redis)``: a lambda that *returns* a
    # coroutine is not a coroutine function, so APScheduler's executor called it
    # synchronously and threw the coroutine away — the heartbeat was never
    # recorded, and /health reported the scheduler dead from two minutes after
    # boot forever. ``partial`` keeps ``iscoroutinefunction`` true.
    scheduler.add_job(
        partial(_keepalive, redis),
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
