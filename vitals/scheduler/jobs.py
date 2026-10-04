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

from typing import Any, Optional

from vitals.config import load_config
from vitals.scheduler.scheduler import clear_jobs, register_job
from vitals.services.proactive import prefs


def register_all_jobs(settings: Optional[dict[str, Any]] = None) -> None:
    """Register every module's scheduled jobs from ``settings``.

    ``None`` → the defaults, which is what the app used before the settings card
    existed. Called at startup *and* on every settings save, so it clears the
    registry first: re-registering has to be able to *remove* a job (the Garmin
    pulse switched off), not only replace one.
    """
    settings = prefs.sanitize(settings)
    clear_jobs()

    from vitals.services.glp1_service import plateau_job
    from vitals.services.hevy_service import sync_job as hevy_sync_job
    from vitals.services.garmin_service import sync_job as garmin_sync_job
    from vitals.services.garmin_weight_service import (
        OPERATION_LOCK_TTL_SECONDS,
        export_job as garmin_weight_export_job,
    )
    from vitals.services.digest_service import digest_job
    from vitals.services.environment.ingest import environment_poll_job
    from vitals.services.environment.rollup import environment_rollup_job
    from vitals.services.nutrition_service import day_end_job as nutrition_day_end_job
    from vitals.services.hrt_reminders import reminders_job as hrt_reminders_job
    from vitals.services.garmin_service import pulse_job as garmin_pulse_job
    from vitals.services.proactive.brief import brief_job, last_attempt_hour
    from vitals.services.proactive.day_plan import evening_job
    from vitals.services.proactive.nudges import nudges_job
    from vitals.services.raw_payload_service import sweep_pending_job as raw_payload_sweep_job
    from vitals.services.share_service import purge_job as share_purge_job

    # GLP-1 plateau check — once a day at 06:00 local. Cheap read; raises/clears a
    # passive warn alert so it's fresh even on days the dashboard isn't opened.
    register_job(
        "glp1_plateau",
        plateau_job,
        trigger="cron",
        hour=6,
        minute=0,
    )

    # HRT reminders — once a day at 07:00 local. Nags for overdue bloodwork
    # (while on cycle) and for missed scheduled injections; both idempotent.
    register_job(
        "hrt_reminders",
        hrt_reminders_job,
        trigger="cron",
        hour=7,
        minute=0,
    )

    # Nutrition day-end check — once a day at 23:00 local, once today's logged
    # totals are effectively final. Raises the very-low-calorie/protein GLP-1
    # warnings, which must never fire off a partial mid-day total.
    register_job(
        "nutrition_day_end",
        nutrition_day_end_job,
        trigger="cron",
        hour=23,
        minute=0,
    )

    # Raw-payload sweep (garmin/hevy/labs/body_comp) — nightly at 03:30 local, a
    # quiet hour clear of every other registered job. Re-derives normalized rows
    # for anything upsert_raw_payload left at processed_at IS NULL: a refreshed
    # Garmin/Hevy row, or a labs/body-comp upload the owner extracted but never
    # confirmed. See raw_payload_service.sweep_pending_job for why this is one
    # shared job rather than four.
    register_job(
        "raw_payload_sweep",
        raw_payload_sweep_job,
        trigger="cron",
        hour=3,
        minute=30,
    )

    # Doctor-report cleanup — nightly at 04:00 local, right after the raw-payload
    # sweep. Empties the frozen snapshot of every link whose lifetime has run out;
    # the row stays so /share can still show what was shared and when.
    register_job(
        "share_purge",
        share_purge_job,
        trigger="cron",
        hour=4,
        minute=0,
    )

    # Hevy sync — every 6h. No-ops when Hevy isn't configured.
    register_job(
        "hevy_sync",
        hevy_sync_job,
        trigger="interval",
        hours=6,
    )

    # Garmin poll — every N hours on the clock (default 6 → 00/06/12/18, the same
    # four polls a day the old fixed 3/11/16/22 cron did). A cron rather than an
    # interval so the times survive a deploy instead of re-phasing off boot.
    # No-ops when Garmin isn't configured.
    register_job(
        "garmin_sync",
        garmin_sync_job,
        trigger="cron",
        hour=f"*/{settings['garmin_sync_hours']}",
        minute=0,
    )

    # Outbound weight sync is a separate opt-in outbox. The job always exists so
    # the DB-backed switch applies without rebuilding the schedule; while off it
    # returns before constructing a Garmin client or touching the network.
    register_job(
        "garmin_weight_export",
        garmin_weight_export_job,
        trigger="interval",
        minutes=settings["garmin_weight_export_minutes"],
        lock_ttl=OPERATION_LOCK_TTL_SECONDS,
    )

    # Morning brief — 11:00 local by default. Syncs Garmin itself first (last
    # night's sleep is the point of the message), stays silent on an empty day, and
    # sends nothing at all until a Telegram channel is configured. Its own lock
    # TTL: the Garmin pull in front of it makes this the slowest job in the registry.
    #
    # An hourly *range*, not one fire: at the scheduled minute last night may not
    # be scored yet (he is still asleep, the watch has not closed the night), and
    # the brief refuses to read recovery off a running night. Each later hour
    # looks again; the delivery journal keeps it to one message a day, and the job
    # returns before the Garmin pull once that message has gone.
    brief_hour, brief_minute = prefs.hhmm(settings["brief_time"])
    register_job(
        "daily_brief",
        brief_job,
        trigger="cron",
        hour=f"{brief_hour}-{last_attempt_hour(brief_hour)}",
        minute=brief_minute,
        lock_ttl=900,
    )

    # Evening block — 23:45 local by default, deliberately not midnight: past 00:00
    # the message would ask about the wrong "tomorrow", which is why the settings
    # field is a time input (it cannot express anything past 23:59). Sums the day
    # up, invites a free-text answer, offers one-tap corrections for tomorrow.
    evening_hour, evening_minute = prefs.hhmm(settings["evening_time"])
    register_job(
        "evening_block",
        evening_job,
        trigger="cron",
        hour=evening_hour,
        minute=evening_minute,
    )

    # Garmin light pulse (N3) — today's step count between the full syncs, so an
    # evening nudge isn't reasoning off a number from hours ago. One request, no
    # login (the token session is resumed), and skipped outside the active hours
    # from the settings card. 0 seconds switches the job off entirely.
    if settings["pulse_seconds"]:
        register_job(
            "garmin_pulse",
            garmin_pulse_job,
            trigger="interval",
            seconds=settings["pulse_seconds"],
            lock_ttl=120,
            heartbeat=False,
        )

    # Nudges — hourly, at :05 so it never lands on top of the polls. Nothing is
    # sent unless a condition actually holds; quiet hours and the daily budget are
    # enforced downstream by delivery.send.
    register_job(
        "nudges",
        nudges_job,
        trigger="cron",
        minute=5,
    )

    # Environment station — polled by Vitals, never pushing. Registered only when
    # a station address is configured (it lives in the environment, so changing it
    # restarts the app anyway): an install without the hardware pays no tick every
    # ten seconds for nothing. The job itself also returns on its first line when
    # the module is off. The lock outlives one poll (3 s connect + 5 s read) with
    # room to spare; a poll that is still running makes the next tick skip rather
    # than pile up behind a stuck station.
    config = load_config()
    if config.env_station_url:
        register_job(
            "environment_poll",
            environment_poll_job,
            trigger="interval",
            seconds=config.env_poll_seconds,
            lock_ttl=30,
        )
        # Hourly rollup of the samples — cheap and idempotent, recomputes only the
        # hours touched since the last pass.
        register_job(
            "environment_rollup",
            environment_rollup_job,
            trigger="interval",
            minutes=5,
            lock_ttl=240,
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
