"""Profile and nutrition goals saved in the database apply without a restart.

A save lands in ``app_settings`` and the runtime overlay, so every reader
(``load_config()``, the nutrition corridor, the Navy formula, the local clock)
sees it on the next call. ``.env`` stays the fallback for anything never saved.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from freezegun import freeze_time

from vitals import runtime_settings
from vitals.config import load_config
from vitals.models.app_settings import AppSetting
from vitals.services import nutrition_service, profile_store, weight_service
from vitals.services.analytics.navy import navy_body_fat_pct
from vitals.utils.timeutils import today_local
from web.services import profile_settings


async def test_saved_profile_reaches_load_config_at_once(db_session, monkeypatch):
    monkeypatch.setenv("VITALS_HEIGHT_CM", "190")
    monkeypatch.setenv("VITALS_USER_AGE", "18")
    assert load_config().height_cm == 190.0

    written = await profile_settings.apply_profile(
        db_session, height_cm="176", user_age="31", sex="female", user_goals="a, b"
    )
    await db_session.commit()

    assert written == {
        "VITALS_HEIGHT_CM": "176",
        "VITALS_SEX": "female",
        "VITALS_USER_AGE": "31",
        "VITALS_USER_GOALS": "a, b",
    }
    cfg = load_config()
    assert cfg.height_cm == 176.0
    assert cfg.sex == "female"
    assert cfg.user_age == 31
    assert cfg.user_goals == ["a", "b"]


async def test_saved_nutrition_goals_reach_the_corridor(db_session, monkeypatch):
    monkeypatch.setenv("VITALS_NUTRITION_PROTEIN_TARGET_G", "150")
    await profile_settings.apply_nutrition_goals(
        db_session, protein_target_g="170", calories_min="1600", calories_max="2000"
    )
    await db_session.commit()

    assert nutrition_service.get_goals(load_config()) == {
        "protein_target_g": 170.0,
        "calories_min": 1600,
        "calories_max": 2000,
    }


async def test_saved_height_feeds_the_navy_formula_without_restart(db_session, monkeypatch):
    monkeypatch.setenv("VITALS_HEIGHT_CM", "190")
    monkeypatch.setenv("VITALS_SEX", "male")
    before = await weight_service.upsert_body_measurement(
        db_session, on_date=date(2026, 1, 1), neck_cm=40.0, waist_cm=90.0
    )
    assert before.body_fat_pct == pytest.approx(
        navy_body_fat_pct(waist_cm=90.0, neck_cm=40.0, height_cm=190.0, sex="male")
    )

    await profile_settings.apply_profile(db_session, height_cm="170")
    after = await weight_service.upsert_body_measurement(
        db_session, on_date=date(2026, 1, 2), neck_cm=40.0, waist_cm=90.0
    )
    assert after.body_fat_pct == pytest.approx(
        navy_body_fat_pct(waist_cm=90.0, neck_cm=40.0, height_cm=170.0, sex="male")
    )
    assert after.body_fat_pct != before.body_fat_pct


async def test_saved_timezone_moves_today_local_at_once(db_session, monkeypatch):
    monkeypatch.setenv("VITALS_TIMEZONE", "Pacific/Pago_Pago")  # UTC-11
    with freeze_time("2026-03-10 12:00:00"):  # UTC
        assert today_local() == date(2026, 3, 10)
        await profile_settings.apply_profile(db_session, timezone="Pacific/Kiritimati")  # UTC+14
        assert today_local() == date(2026, 3, 11)
        assert load_config().timezone == "Pacific/Kiritimati"


async def test_env_file_is_the_fallback_when_nothing_was_saved(db_session, tmp_path, monkeypatch):
    env_file = tmp_path / "test.env"
    env_file.write_text("VITALS_HEIGHT_CM=181\nVITALS_NUTRITION_CALORIES_MIN=1400\n", encoding="utf-8")
    monkeypatch.setenv("VITALS_ENV_FILE", str(env_file))
    monkeypatch.setenv("VITALS_HEIGHT_CM", "181")

    profile = await profile_settings.read_profile(db_session)
    assert profile["height_cm"] == "181"
    assert profile["sex"] == "male"  # default
    goals = await profile_settings.read_nutrition_goals(db_session)
    assert goals["nutrition_calories_min"] == "1400"
    assert goals["nutrition_calories_max"] == "1700"  # default
    assert load_config().height_cm == 181.0

    # A save wins over .env, and .env itself is left alone.
    await profile_settings.apply_profile(db_session, height_cm="175")
    assert (await profile_settings.read_profile(db_session))["height_cm"] == "175"
    assert "VITALS_HEIGHT_CM=181" in env_file.read_text(encoding="utf-8")


async def test_startup_load_restores_the_overlay_from_the_db(db_session, monkeypatch):
    monkeypatch.setenv("VITALS_HEIGHT_CM", "190")
    await profile_store.save(db_session, {"VITALS_HEIGHT_CM": "168", "VITALS_TIMEZONE": "Asia/Tokyo"})
    await db_session.commit()

    runtime_settings.clear()  # a fresh process: overlay empty, row still there
    assert load_config().height_cm == 190.0

    restored = await profile_store.load(db_session)
    assert restored == {"VITALS_HEIGHT_CM": "168", "VITALS_TIMEZONE": "Asia/Tokyo"}
    assert load_config().height_cm == 168.0
    assert load_config().timezone == "Asia/Tokyo"


async def test_save_merges_into_one_row(db_session):
    await profile_store.save(db_session, {"VITALS_HEIGHT_CM": "180"})
    await profile_store.save(db_session, {"VITALS_SEX": "female"})
    await db_session.commit()

    row = await db_session.get(AppSetting, profile_store.SETTINGS_KEY)
    assert row.value == {"VITALS_HEIGHT_CM": "180", "VITALS_SEX": "female"}


async def test_save_refuses_keys_that_are_not_profile_settings(db_session):
    with pytest.raises(ValueError):
        await profile_store.save(db_session, {"VITALS_SESSION_SECRET": "x"})
    assert runtime_settings.get("VITALS_SESSION_SECRET") is None


async def test_malformed_row_reads_as_no_overrides(db_session):
    db_session.add(
        AppSetting(key=profile_store.SETTINGS_KEY, value={"VITALS_HEIGHT_CM": 5, "BOGUS": "1"})
    )
    await db_session.commit()
    assert await profile_store.load(db_session) == {}


async def test_unknown_timezone_is_not_saved(db_session):
    written = await profile_settings.apply_profile(db_session, timezone="Mars/Olympus")
    assert written == {}
    assert runtime_settings.get("VITALS_TIMEZONE") is None


async def test_timezone_change_retimes_the_running_scheduler(monkeypatch):
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from vitals.scheduler import scheduler as scheduler_mod
    from web import deps

    async def _job(session_factory, redis):  # pragma: no cover - never fired
        return None

    monkeypatch.setattr(deps, "get_session_factory", lambda: object())
    monkeypatch.setattr(deps, "get_redis_client", lambda: None)
    scheduler_mod.register_job("brief", _job, trigger="cron", hour=9, minute=0)

    # Started (paused, so nothing fires): a stopped scheduler only queues
    # replacements, which is not what production does.
    scheduler = AsyncIOScheduler(timezone="Europe/Chisinau")
    scheduler_mod.apply_registry(scheduler, object(), None)
    scheduler.start(paused=True)
    try:
        assert str(scheduler.get_job("brief").trigger.timezone) == "Europe/Chisinau"

        app = SimpleNamespace(state=SimpleNamespace(scheduler=scheduler))
        profile_settings.apply_timezone_to_scheduler(app, "Asia/Tokyo")

        assert str(scheduler.timezone) == "Asia/Tokyo"
        assert str(scheduler.get_job("brief").trigger.timezone) == "Asia/Tokyo"
    finally:
        scheduler.shutdown(wait=False)


def test_timezone_retime_is_a_noop_without_a_scheduler():
    profile_settings.apply_timezone_to_scheduler(None, "Asia/Tokyo")
    profile_settings.apply_timezone_to_scheduler(SimpleNamespace(state=SimpleNamespace()), "Asia/Tokyo")
