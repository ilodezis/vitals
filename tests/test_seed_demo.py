"""Contract tests for the local UI demo dataset.

The local runner is the designer's fixture: each visible module should open
with enough current, varied data to exercise its real states instead of an
empty screen or an obsolete schema snapshot.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from scripts import seed_demo
from vitals.models.app_settings import AppSetting
from vitals.models.body_scan import BodyScan, BodyScanMetric
from vitals.models.conflict_rule import ConflictRule
from vitals.models.garmin import (
    SLEEP_SERIES_TYPES,
    GarminActivity,
    GarminDaily,
    GarminIntraday,
)
from vitals.models.genetics import GeneticVariant
from vitals.models.glp1 import DosePhase, Injection, SideEffect
from vitals.models.hevy import HevyWorkout
from vitals.models.labs import LabResult
from vitals.models.milestones import Milestone, WeeklyDigest
from vitals.models.nutrition import MealLog
from vitals.models.skincare import SkincareLog, SkincareObservation, SkincareProduct
from vitals.models.supplements import Supplement
from vitals.models.system_alert import SystemAlert
from vitals.models.timeline import Annotation
from vitals.models.weight import BodyMeasurement, NoiseMarker, WeightLog
from vitals.services.modules_service import MODULE_REGISTRY
from vitals.services.supplements_service import timing_bucket

pytestmark = pytest.mark.asyncio


async def _count(session, model) -> int:
    return int(
        (await session.execute(select(func.count()).select_from(model))).scalar_one()
    )


async def test_seed_all_populates_every_current_ui_surface(db_session):
    await seed_demo.seed_all(db_session)
    await db_session.flush()

    # Core history-rich surfaces.
    assert await _count(db_session, WeightLog) >= 45
    assert await _count(db_session, BodyMeasurement) >= 6
    assert await _count(db_session, NoiseMarker) >= 3
    assert await _count(db_session, GarminDaily) >= 30
    assert await _count(db_session, GarminActivity) >= 6
    assert await _count(db_session, LabResult) >= 24
    assert await _count(db_session, HevyWorkout) >= 8

    # Optional modules and their newer sub-features.
    assert await _count(db_session, BodyScan) >= 3
    assert await _count(db_session, BodyScanMetric) >= 30
    assert await _count(db_session, Injection) >= 10
    assert await _count(db_session, DosePhase) >= 3
    assert await _count(db_session, SideEffect) >= 3
    assert await _count(db_session, MealLog) >= 40
    assert await _count(db_session, SkincareLog) >= 14
    assert await _count(db_session, SkincareObservation) >= 5
    assert await _count(db_session, SkincareProduct) >= 6
    assert await _count(db_session, Supplement) >= 7
    assert await _count(db_session, GeneticVariant) >= 4
    assert await _count(db_session, Annotation) >= 4
    assert await _count(db_session, Milestone) >= 5
    assert await _count(db_session, WeeklyDigest) >= 2
    assert await _count(db_session, SystemAlert) >= 2

    active_timings = (
        await db_session.execute(
            select(Supplement.timing).where(Supplement.active.is_(True))
        )
    ).scalars().all()
    assert {"утро", "день", "вечер", "ночь"}.issubset(
        {timing_bucket(value) for value in active_timings}
    )

    # Latest cards must be current, not a day behind like the old seed.
    latest_weight = (
        await db_session.execute(select(WeightLog).order_by(WeightLog.date.desc()))
    ).scalars().first()
    latest_garmin = (
        await db_session.execute(select(GarminDaily).order_by(GarminDaily.date.desc()))
    ).scalars().first()
    latest_skin = (
        await db_session.execute(select(SkincareLog).order_by(SkincareLog.date.desc()))
    ).scalars().first()
    assert latest_weight.date == seed_demo.TODAY
    assert latest_garmin.date == seed_demo.TODAY
    assert latest_skin.date == seed_demo.TODAY

    # The redesigned Garmin tabs need the post-v1 fields and all sleep charts.
    assert latest_garmin.sleep_start is not None
    assert latest_garmin.sleep_end is not None
    assert latest_garmin.sleep_stages
    assert latest_garmin.training_status
    assert latest_garmin.acute_load is not None
    assert latest_garmin.load_ratio is not None
    series_types = set(
        (await db_session.execute(select(GarminIntraday.series_type))).scalars().all()
    )
    assert set(SLEEP_SERIES_TYPES).issubset(series_types)

    detailed_activity = (
        await db_session.execute(
            select(GarminActivity).where(GarminActivity.hr_zone_seconds.is_not(None))
        )
    ).scalars().first()
    assert detailed_activity is not None
    assert detailed_activity.splits
    assert detailed_activity.training_effect_aerobic is not None

    # Body-composition headline/history keys used by the Weight tab.
    metric_keys = set(
        (await db_session.execute(select(BodyScanMetric.metric_key))).scalars().all()
    )
    assert {
        "body_fat_pct",
        "lean_body_mass",
        "skeletal_muscle_mass",
        "visceral_fat_area",
        "phase_angle",
        "ecw_tbw_ratio",
        "segmental_lean",
    }.issubset(metric_keys)

    # Interactions must show the current curated catalog, not three legacy rows.
    assert await _count(db_session, ConflictRule) >= 100

    enabled = await db_session.get(AppSetting, "enabled_modules")
    assert enabled is not None
    assert enabled.value == {key: True for key in MODULE_REGISTRY}
    saved_charts = await db_session.get(AppSetting, "custom_charts")
    assert saved_charts is not None and len(saved_charts.value) >= 2
    language = await db_session.get(AppSetting, "ui_language")
    assert language is not None and language.value == "ru"


async def test_seed_all_is_repeatable_without_duplicates(db_session):
    tracked = (
        WeightLog,
        BodyScan,
        BodyScanMetric,
        GarminDaily,
        GarminActivity,
        GarminIntraday,
        HevyWorkout,
        LabResult,
        Annotation,
        ConflictRule,
    )

    await seed_demo.seed_all(db_session)
    await db_session.commit()
    first = {model: await _count(db_session, model) for model in tracked}

    await seed_demo.seed_all(db_session)
    await db_session.commit()
    second = {model: await _count(db_session, model) for model in tracked}

    assert second == first


async def test_seeded_ui_copy_matches_russian_language_setting(db_session):
    await seed_demo.seed_all(db_session)
    await db_session.flush()

    digests = (
        await db_session.execute(select(WeeklyDigest).order_by(WeeklyDigest.date.desc()))
    ).scalars().all()
    milestones = (await db_session.execute(select(Milestone))).scalars().all()
    supplements = (await db_session.execute(select(Supplement))).scalars().all()

    assert all("## " in digest.content for digest in digests)
    assert "Неделя в фокусе" in digests[0].content
    assert {milestone.name for milestone in milestones} >= {
        "Достичь веса 85 кг",
        "Жим лёжа 100 кг",
    }
    timings = {supplement.timing for supplement in supplements}
    assert "утром" in timings
    # The workout electrolyte deliberately carries a "днём, …" prefix so it
    # lands in the protocol's daytime bucket while keeping the RU copy.
    assert any("во время тренировки" in timing for timing in timings)
    assert all(
        not note or "Paused" not in note
        for note in (supplement.note for supplement in supplements)
    )


async def test_run_local_initializes_a_seeded_current_database(tmp_path: Path):
    # run_local intentionally overwrites VITALS_* env vars and web.deps._redis
    # as part of its executable setup (so the script can never touch a real
    # database). Those side effects fire on import and would leak into every
    # test that runs after this one in the same process — most visibly by
    # replacing the auth credentials the shared login fixture uses. Snapshot
    # both and restore them so this test stays hermetic.
    import os

    import web.deps

    env_before = dict(os.environ)
    redis_before = web.deps._redis
    try:
        import run_local

        db_path = (tmp_path / "local-vitals.db").as_posix()
        database_url = f"sqlite+aiosqlite:///{db_path}"
        await run_local.init_db(database_url=database_url)
    finally:
        os.environ.clear()
        os.environ.update(env_before)
        web.deps._redis = redis_before

    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            weight_count = (
                await connection.execute(select(func.count()).select_from(WeightLog))
            ).scalar_one()
            body_scan_count = (
                await connection.execute(select(func.count()).select_from(BodyScan))
            ).scalar_one()
            garmin_activity_count = (
                await connection.execute(select(func.count()).select_from(GarminActivity))
            ).scalar_one()
        assert weight_count >= 45
        assert body_scan_count >= 3
        assert garmin_activity_count >= 6
    finally:
        await engine.dispose()
