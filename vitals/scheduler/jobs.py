"""Per-module scheduled-job registrations.

The scheduler framework (``scheduler.py``) only ships the keepalive heartbeat;
each module attaches its jobs by calling :func:`register_job`. This module
gathers those calls behind :func:`register_all_jobs`, invoked once from the web
lifespan before :func:`setup_scheduler` reads the registry.

Keeping registration here (not at model/service import time) means importing a
service for a unit test never schedules anything — the test ``clear_jobs``
fixture stays effective and jobs only exist when the app actually boots.
"""
from __future__ import annotations

from vitals.scheduler.scheduler import register_job


def register_all_jobs() -> None:
    """Register every module's scheduled jobs. Idempotent (re-registering an id
    replaces it), so it's safe to call once per startup."""
    from vitals.services.glp1_service import plateau_job
    from vitals.services.hevy_service import sync_job as hevy_sync_job
    from vitals.services.garmin_service import sync_job as garmin_sync_job
    from vitals.services.digest_service import digest_job

    # GLP-1 plateau check — once a day at 06:00 local. Cheap read; raises/clears a
    # passive warn alert so it's fresh even on days the dashboard isn't opened.
    register_job(
        "glp1_plateau",
        plateau_job,
        trigger="cron",
        hour=6,
        minute=0,
    )

    # Hevy sync — every 6h. No-ops when Hevy isn't configured.
    register_job(
        "hevy_sync",
        hevy_sync_job,
        trigger="interval",
        hours=6,
    )

    # Garmin poll — scheduled at 03:00, 11:00, 16:00, and 22:00 local.
    # No-ops when Garmin isn't configured.
    register_job(
        "garmin_sync",
        garmin_sync_job,
        trigger="cron",
        hour="3,11,16,22",
        minute=0,
    )

    # Weekly AI digest — Mondays at 08:00 local. No-ops when no OpenRouter key.
    register_job(
        "weekly_digest",
        digest_job,
        trigger="cron",
        day_of_week="mon",
        hour=8,
        minute=0,
    )
