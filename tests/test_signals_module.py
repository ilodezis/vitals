"""The module switch and the settings that rebuild the schedule.

Two guarantees, both invisible when they break:

  * ``signals`` is the emergency switch. Off, the section must behave as if it
    isn't there **and the bot must go quiet** — a page that still renders, or a
    brief that still arrives, means there is no way to stop the feature short of
    a deploy.
  * A saved schedule has to reach the *running* scheduler. If it only lands in
    the DB, the settings page happily reports success while the jobs keep firing
    on yesterday's times until someone restarts the container.
"""
from __future__ import annotations

import pytest

from vitals.scheduler import scheduler as scheduler_mod
from vitals.scheduler.jobs import register_all_jobs
from vitals.services import modules_service, signals_service
from vitals.services.proactive import delivery, prefs


class FakeNotifier:
    channel = "telegram"

    def __init__(self):
        self.sent: list[str] = []

    async def send(self, text, *, buttons=None, reply_to=None) -> str:
        self.sent.append(text)
        return str(700 + len(self.sent))

    async def answer_callback(self, callback_id, text="") -> None:
        pass


# ── The module ────────────────────────────────────────────────────────────────
def test_signals_is_optional_and_off_by_default():
    spec = modules_service.MODULE_REGISTRY.get("signals")
    assert spec is not None
    assert spec.category == "optional"
    assert spec.route == "/signals"
    assert modules_service.DEFAULT_STATE["signals"] is False


async def test_disabled_module_makes_the_bot_silent(db_session):
    """The switch has to reach *sending*, not just the nav — otherwise turning the
    feature off still leaves the brief arriving every morning."""
    fake = FakeNotifier()

    assert await delivery.send(
        db_session, fake, text="бриф", category=delivery.CATEGORY_BRIEF
    ) is None
    assert fake.sent == []

    await modules_service.set_module_enabled(db_session, key="signals", enabled=True)
    await db_session.commit()

    assert await delivery.send(
        db_session, fake, text="бриф", category=delivery.CATEGORY_BRIEF
    ) is not None
    assert fake.sent == ["бриф"]


# ── The page ──────────────────────────────────────────────────────────────────
async def test_feed_shows_captured_rows_and_deletes_one(auth_client, db_session):
    rows = await signals_service.create_signals(
        db_session,
        items=[
            {"kind": "symptom", "key": "headache", "value_num": 4},
            {"kind": "exposure", "key": "coffee_late", "value_num": 200, "unit": "mg"},
        ],
    )
    await db_session.commit()

    feed = (await auth_client.get("/api/v1/signals")).json()["signals"]
    by_raw = {s["rawKey"]: s for s in feed}
    assert by_raw["headache"]["key"] == "headache"
    # Stored as an alias, shown folded.
    assert by_raw["coffee_late"]["key"] == "caffeine_late"

    r = await auth_client.delete(f"/api/v1/signals/{rows[0].id}")
    assert r.status_code == 204
    assert await signals_service.list_signals(db_session) != []
    assert all(s.id != rows[0].id for s in await signals_service.list_signals(db_session))


# ── The settings ──────────────────────────────────────────────────────────────
def test_sanitize_clamps_whatever_arrives():
    """The HTML min/max are a courtesy; this is the guard."""
    clean = prefs.sanitize(
        {
            "brief_time": "nonsense",
            "daily_budget": 9000,
            "garmin_sync_hours": 0,
            "garmin_weight_export_minutes": 1,
            "garmin_weight_max_age_days": 9000,
            "pulse_seconds": 5,          # below the floor, but not "off"
            "pulse_start_hour": 20,
            "pulse_end_hour": 20,        # a window nothing could ever run in
            "nudges": {"activity": False},
        }
    )
    assert clean["brief_time"] == prefs.DEFAULTS["brief_time"]
    assert clean["daily_budget"] == prefs.BUDGET_RANGE[1]
    assert clean["garmin_sync_hours"] == prefs.SYNC_HOURS_RANGE[0]
    assert clean["garmin_weight_export_minutes"] == prefs.WEIGHT_EXPORT_MINUTES_RANGE[0]
    assert clean["garmin_weight_max_age_days"] == prefs.WEIGHT_MAX_AGE_DAYS_RANGE[1]
    assert clean["pulse_seconds"] == prefs.PULSE_SECONDS_RANGE[0]
    assert clean["pulse_end_hour"] > clean["pulse_start_hour"]
    assert clean["nudges"] == {"activity": False, "nutrition": True, "data": True}
    # 0 means off and must survive the clamp that pulls 5 up to 60.
    assert prefs.sanitize({"pulse_seconds": 0})["pulse_seconds"] == 0


def test_settings_rebuild_the_job_triggers():
    register_all_jobs(
        {
            "brief_time": "07:30",
            "evening_time": "22:15",
            "garmin_sync_hours": 4,
            "garmin_weight_export_minutes": 45,
        }
    )
    registry = scheduler_mod._registry

    # A window, not one fire: the brief waits out a night that isn't scored yet.
    assert registry["daily_brief"].trigger_kwargs == {"hour": "7-12", "minute": 30}
    assert registry["evening_block"].trigger_kwargs == {"hour": 22, "minute": 15}
    assert registry["garmin_sync"].trigger_kwargs == {"hour": "*/4", "minute": 0}
    assert registry["garmin_weight_export"].trigger_kwargs == {"minutes": 45}


def test_switching_the_pulse_off_removes_the_job():
    """Re-registration must be able to *drop* a job, not only replace one."""
    register_all_jobs({"pulse_seconds": 300})
    assert scheduler_mod._registry["garmin_pulse"].trigger_kwargs == {"seconds": 300}

    register_all_jobs({"pulse_seconds": 0})
    assert "garmin_pulse" not in scheduler_mod._registry


async def test_saving_reschedules_without_a_restart(auth_client, db_session):
    """The whole point: the live scheduler is rebuilt in the same request."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from web.main import app

    register_all_jobs()
    scheduler = AsyncIOScheduler(timezone="Europe/Chisinau")
    scheduler_mod.apply_registry(scheduler, lambda: None, None)
    # Started, like the real one: a stopped scheduler keeps everything in a
    # pending list where replacing a job by id is deferred, so the test would
    # prove nothing about the case that matters.
    scheduler.start()
    app.state.scheduler = scheduler
    try:
        before = scheduler.get_job("daily_brief")
        assert "hour='11-16'" in str(before.trigger)

        r = await auth_client.post(
            "/api/v1/settings/proactive",
            json={
                "brief_time": "09:05",
                "evening_time": "23:00",
                "quiet_start": "01:00",
                "quiet_end": "08:00",
                "daily_budget": 6,
                "garmin_sync_hours": 3,
                "garmin_weight_export_minutes": 20,
                "garmin_weight_max_age_days": 14,
                "pulse_seconds": 0,
                "pulse_start_hour": 9,
                "pulse_end_hour": 22,
                "nudges": ["activity"],
                "week_template": {"mon": {"gym": True}},
            },
        )
        assert r.status_code == 200
        assert r.json()["saved"] is True

        after = scheduler.get_job("daily_brief")
        assert "hour='9-14'" in str(after.trigger)
        assert "minute='5'" in str(after.trigger)
        # Pulse switched off → gone from the running scheduler too.
        assert scheduler.get_job("garmin_pulse") is None
        assert scheduler.get_job("garmin_weight_export").trigger.interval.total_seconds() == 1200

        stored = await prefs.get_prefs(db_session)
        assert stored["daily_budget"] == 6
        assert stored["garmin_weight_export_minutes"] == 20
        assert stored["garmin_weight_max_age_days"] == 14
        assert stored["nudges"] == {"activity": True, "nutrition": False, "data": False}

        from vitals.services.proactive import day_plan

        template = await day_plan.get_week_template(db_session)
        assert template["mon"]["gym"] is True
        assert template["tue"]["gym"] is False
    finally:
        scheduler.shutdown(wait=False)
        app.state.scheduler = None


@pytest.mark.parametrize("value", ["1", "0"])
def test_week_template_booleans_survive_the_form_round_trip(value):
    """``bool("0")`` is ``True`` — the decoder is what stops a saved "без зала"
    silently becoming "зал"."""
    from vitals.services.proactive import day_plan

    assert day_plan.encode(day_plan.decode(value)) == value
