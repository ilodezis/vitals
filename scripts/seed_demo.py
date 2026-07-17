#!/usr/bin/env python3
"""Current, deterministic local dataset used for browser and UI work.

It fills every UI surface, including detail views added after v1, and is
idempotent. The caller owns the transaction.
"""
from __future__ import annotations

import asyncio
import math
import os
import random
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

from sqlalchemy import delete

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("VITALS_DATABASE_URL", "sqlite+aiosqlite:///local_vitals.db")
os.environ.setdefault("VITALS_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("VITALS_TIMEZONE", "Europe/Chisinau")

from vitals.config import load_config
from vitals.database import create_session_factory
from vitals.enums import (
    AnnotationKind,
    Domain,
    Drug,
    Evidence,
    InjectionSite,
    LabFlag,
    MilestoneStatus,
    NoiseDirection,
    Severity,
    Source,
)
from vitals.models.app_settings import AppSetting
from vitals.models.body_scan import BodyScan, BodyScanMetric
from vitals.models.conflict_rule import ConflictRule
from vitals.models.garmin import (
    SERIES_BODY_BATTERY,
    SERIES_SLEEP_BB,
    SERIES_SLEEP_HR,
    SERIES_SLEEP_HRV,
    SERIES_SLEEP_MOVEMENT,
    SERIES_SLEEP_RESPIRATION,
    SERIES_SLEEP_SPO2,
    SERIES_SLEEP_STRESS,
    SERIES_STRESS,
    GarminActivity,
    GarminDaily,
    GarminIntraday,
)
from vitals.models.genetics import GeneticVariant
from vitals.models.glp1 import DosePhase, Injection, SideEffect
from vitals.models.hevy import HevyExercise, HevySet, HevyWorkout
from vitals.models.labs import LabMarker, LabResult
from vitals.models.milestones import Milestone, WeeklyDigest
from vitals.models.nutrition import MealLog
from vitals.models.skincare import SkincareLog, SkincareObservation, SkincareProduct
from vitals.models.supplements import Supplement
from vitals.models.system_alert import SystemAlert
from vitals.models.timeline import Annotation
from vitals.models.weight import BodyMeasurement, NoiseMarker, WeightLog
from vitals.services import conflict_catalog
from vitals.services.modules_service import MODULE_REGISTRY
from vitals.utils.timeutils import today_local

TODAY = today_local()


def _d(days_ago: int) -> date:
    return TODAY - timedelta(days=days_ago)


def _weight(days_ago: int) -> float:
    trend = 94.0 - (90 - days_ago) * (8.0 / 90)
    noise = 0.24 * math.sin(days_ago * 1.71) + 0.11 * math.cos(days_ago * 0.47)
    return round(trend + noise, 1)


async def _seed_supplements(session) -> int:
    await session.execute(delete(Supplement))
    rows = [
        Supplement(name=name, key=key, dose=dose, timing=timing,
                   evidence=evidence, active=active, note=note,
                   domain=Domain.SUPPLEMENTS, source=Source.MANUAL)
        for name, key, dose, timing, evidence, active, note in (
            ("Креатин моногидрат", "creatine", "5 г", "утром", Evidence.A, True, "Без загрузочной фазы"),
            ("Витамин D3", "vitamin_d", "4000 МЕ", "днём, во время обеда", Evidence.A, True, "До следующего анализа 25-OH D"),
            ("Омега-3", "omega3", "2 г EPA+DHA", "днём, во время обеда", Evidence.A, True, None),
            ("Магний глицинат", "magnesium", "400 мг", "вечером", Evidence.B, True, None),
            ("Цинк пиколинат", "zinc", "15 мг", "вечером", Evidence.B, True, None),
            ("Псиллиум", "psyllium", "8 г", "вечером, перед ужином", Evidence.A, True, None),
            ("Электролиты", "electrolytes", "1 порция", "днём, во время тренировки", Evidence.B, True, None),
            ("Мелатонин", "melatonin", "1 мг", "ночью, перед сном", Evidence.B, True, "Только при сбитом режиме"),
            ("Железо бисглицинат", "iron", "36 мг", "утром", Evidence.B, False, "Приостановлено: ферритин нормализовался"),
        )
    ]
    session.add_all(rows)
    return len(rows)


async def _seed_genetics(session) -> int:
    await session.execute(delete(GeneticVariant))
    rows = [
        ("MTHFR", "rs1801133", "CT", "mthfr_heterozygous", Domain.SUPPLEMENTS,
         "Умеренно сниженный метаболизм фолатов", "Предпочитать пищевые фолаты; избегать мегадоз без врача"),
        ("CYP1A2", "rs762551", "AC", "cyp1a2_slow_metabolizer", Domain.GARMIN,
         "Промежуточная скорость метаболизма кофеина", "Не употреблять кофеин после 14:00"),
        ("APOE", "rs429358", "CT", "apoe_e3e4", Domain.LABS,
         "Один аллель ε4", "Контролировать LDL и ApoB"),
        ("FTO", "rs9939609", "AT", "fto_risk_heterozygous", Domain.WEIGHT,
         "Один аллель риска", "Белок и силовые тренировки снижают влияние"),
        ("HFE", "rs1800562", "GG", "hfe_c282y_normal", Domain.LABS,
         "Распространённый вариант", "Ориентироваться на ферритин как практический маркер"),
        ("ACTN3", "rs1815739", "CT", "actn3_mixed", Domain.WORKOUTS,
         "Смешанный силовой и выносливый профиль", "Подходит смешанная программа"),
    ]
    session.add_all([
        GeneticVariant(gene=gene, rsid=rsid, genotype=genotype, marker=marker,
                       impact=interpretation, impact_domain=impact_domain,
                       interpretation=interpretation, action_notes=action,
                       domain=Domain.GENETICS, source=Source.VCF_IMPORT)
        for gene, rsid, genotype, marker, impact_domain, interpretation, action in rows
    ])
    return len(rows)


async def _seed_digests(session) -> int:
    await session.execute(delete(WeeklyDigest))
    rows = [
        WeeklyDigest(
            date=_d(7),
            content="""## Неделя в фокусе

Вес продолжает плавно снижаться, а силовые показатели стабильны. Недавний
перелёт добавил временный шум на весах, поэтому скользящая средняя сейчас
важнее одного утреннего измерения.

## Восстановление

Сон стабильный; HRV немного ниже личной базы. Сегодня можно тренироваться
по плану, но без проверки максимума.""",
            context_json={"weight_trend_kg_week": -0.58, "sleep_avg_hours": 7.6,
                          "hrv_avg": 49.8, "protein_avg_g": 145,
                          "attention": ["vitamin_d"]},
            model="anthropic/claude-sonnet-4.6",
            domain=Domain.MILESTONES, source=Source.SCHEDULER,
        ),
        WeeklyDigest(
            date=_d(14),
            content="""## Хорошая динамика

Талия уменьшается быстрее веса, а InBody показывает сохранение мышечной
массы. Тренировочная нагрузка остаётся продуктивной и привычной.

## Обратить внимание

Лёгкая изжога была единичной и появилась после позднего ужина.""",
            context_json={"waist_change_cm": -1.4, "muscle_mass_kg": 38.3,
                          "training_status": "PRODUCTIVE"},
            model="anthropic/claude-sonnet-4.6",
            domain=Domain.MILESTONES, source=Source.SCHEDULER,
        ),
    ]
    session.add_all(rows)
    return len(rows)


async def _seed_weight(session) -> int:
    await session.execute(delete(NoiseMarker))
    await session.execute(delete(BodyMeasurement))
    await session.execute(delete(WeightLog))
    weights = [
        WeightLog(date=_d(day), weight_kg=_weight(day), superseded=False,
                  domain=Domain.WEIGHT, source=Source.MANUAL)
        for day in range(90, -1, -2)
    ]
    # Keep a losing Garmin row so provenance/priority states are represented.
    weights.append(WeightLog(
        date=_d(2), weight_kg=_weight(2) + 0.4, superseded=True,
        note="Весы Garmin; запись заменена ручной проверкой",
        domain=Domain.WEIGHT, source=Source.GARMIN_API,
    ))
    measurements = []
    for day, neck, waist, fat in (
        (90, 40.5, 95.0, 22.1), (75, 40.2, 93.8, 21.2),
        (60, 39.9, 92.1, 20.4), (45, 39.6, 90.7, 19.6),
        (30, 39.3, 89.2, 18.7), (15, 39.0, 87.8, 17.9),
        (3, 38.8, 86.9, 17.2),
    ):
        measurements.append(BodyMeasurement(
            date=_d(day), neck_cm=neck, waist_cm=waist, body_fat_pct=fat,
            lbm_kg=round(_weight(day) * (1 - fat / 100), 1),
            domain=Domain.WEIGHT, source=Source.MANUAL,
        ))
    noise = [
        NoiseMarker(start_date=_d(74), end_date=_d(69),
                    reason="Простуда и обезвоживание", direction=NoiseDirection.DOWN,
                    domain=Domain.WEIGHT, source=Source.MANUAL),
        NoiseMarker(start_date=_d(43), end_date=_d(34),
                    reason="Старт креатина: задержка воды", direction=NoiseDirection.UP,
                    domain=Domain.WEIGHT, source=Source.MANUAL),
        NoiseMarker(start_date=_d(4), end_date=None,
                    reason="Перелёт и солёная еда", direction=NoiseDirection.UP,
                    domain=Domain.WEIGHT, source=Source.MANUAL),
    ]
    session.add_all([*weights, *measurements, *noise])
    return len(weights) + len(measurements) + len(noise)


def _metric(key, label, value, unit, category, low=None, high=None, segment=None):
    return BodyScanMetric(
        metric_key=key, label=label, value=value, unit=unit, category=category,
        ref_low=low, ref_high=high, segment=segment,
    )


async def _seed_body_scans(session) -> int:
    await session.execute(delete(BodyScanMetric))
    await session.execute(delete(BodyScan))
    scans = []
    for day, weight, muscle, fat, lean, visceral, phase, ratio, score in (
        (75, 92.5, 37.6, 21.4, 72.7, 93, 6.1, .383, 75),
        (38, 89.4, 38.0, 19.2, 72.2, 82, 6.4, .380, 79),
        (7, 86.7, 38.3, 17.3, 71.7, 72, 6.7, .377, 83),
    ):
        metrics = [
            _metric("weight", "Масса тела", weight, "kg", "composition"),
            _metric("skeletal_muscle_mass", "Скелетная мышечная масса", muscle, "kg", "composition", 33, 40),
            _metric("body_fat_pct", "Процент жира", fat, "%", "composition", 10, 20),
            _metric("lean_body_mass", "Безжировая масса", lean, "kg", "composition"),
            _metric("body_fat_mass", "Жировая масса", round(weight * fat / 100, 1), "kg", "composition"),
            _metric("visceral_fat_area", "Площадь висцерального жира", visceral, "cm²", "composition", 0, 100),
            _metric("total_body_water", "Общая вода организма", round(lean * .72, 1), "L", "water"),
            _metric("ecw_tbw_ratio", "Соотношение ECW/TBW", ratio, None, "water", .36, .39),
            _metric("phase_angle", "Фазовый угол", phase, "°", "score", 5.5, 8),
            _metric("inbody_score", "Оценка InBody", score, None, "score", 70, 100),
            _metric("bmr", "Базовый обмен", 1690 + score, "kcal", "derived"),
        ]
        for segment, value in {
            "right_arm": 3.75, "left_arm": 3.70, "trunk": 29.4,
            "right_leg": 10.65, "left_leg": 10.58,
        }.items():
            metrics.append(_metric("segmental_lean", "Сегментарная безжировая масса", value, "kg", "segmental", segment=segment))
        scans.append(BodyScan(
            date=_d(day), device="InBody 770", note="Утром натощак, до тренировки",
            domain=Domain.BODY_COMPOSITION, source=Source.BODY_SCAN, metrics=metrics,
        ))
    session.add_all(scans)
    return len(scans)


_STAGES = (
    ("awake", 12), ("light", 48), ("deep", 76), ("light", 92),
    ("rem", 34), ("light", 76), ("deep", 42), ("light", 54),
    ("rem", 34), ("awake", 12),
)


def _sleep(start: datetime):
    cursor, sleeping, awake, result = start, 0, 0, []
    for stage, minutes in _STAGES:
        end = cursor + timedelta(minutes=minutes)
        result.append({"start": cursor.isoformat(timespec="seconds"),
                       "end": end.isoformat(timespec="seconds"), "stage": stage})
        if stage == "awake":
            awake += minutes
        else:
            sleeping += minutes
        cursor = end
    return result, cursor, sleeping, awake


def _whole_day_series(session, on_date: date) -> int:
    battery = 26.0
    for minute in range(0, 1440, 5):
        ts = datetime.combine(on_date, time()) + timedelta(minutes=minute)
        asleep = minute < 420 or minute >= 1380
        stress = (13 if asleep else 31) + 12 * abs(math.sin(minute / 83))
        if 1020 < minute < 1080:
            stress += 18
        battery = max(8, min(95, battery + (.72 if asleep else -(.1 + stress / 220))))
        session.add_all([
            GarminIntraday(date=on_date, series_type=SERIES_STRESS, ts=ts, value=round(stress, 1),
                           domain=Domain.GARMIN, source=Source.GARMIN_API),
            GarminIntraday(date=on_date, series_type=SERIES_BODY_BATTERY, ts=ts, value=round(battery, 1),
                           domain=Domain.GARMIN, source=Source.GARMIN_API),
        ])
    return 576


def _night_series(session, on_date: date, start: datetime, end: datetime) -> int:
    kinds = (SERIES_SLEEP_HR, SERIES_SLEEP_SPO2, SERIES_SLEEP_RESPIRATION,
             SERIES_SLEEP_STRESS, SERIES_SLEEP_BB, SERIES_SLEEP_HRV,
             SERIES_SLEEP_MOVEMENT)
    total = int((end - start).total_seconds() / 60)
    count = 0
    for minute in range(0, total + 1, 10):
        phase = minute / 47
        values = (
            52 + 4 * math.sin(phase), 96.2 - .8 * abs(math.sin(phase * .7)),
            14.1 + 1.1 * math.sin(phase * .9), 13 + 7 * abs(math.sin(phase * 1.3)),
            28 + 56 * minute / total, 49 + 11 * math.sin(phase * 1.15),
            max(0, 1.8 * math.sin(phase * 2.7)),
        )
        session.add_all([
            GarminIntraday(date=on_date, series_type=kind,
                           ts=start + timedelta(minutes=minute), value=round(value, 1),
                           domain=Domain.GARMIN, source=Source.GARMIN_API)
            for kind, value in zip(kinds, values)
        ])
        count += 7
    return count


async def _seed_garmin(session) -> int:
    await session.execute(delete(GarminIntraday))
    await session.execute(delete(GarminActivity))
    await session.execute(delete(GarminDaily))
    daily, bounds = [], {}
    for day in range(29, -1, -1):
        on_date = _d(day)
        bedtime = datetime.combine(on_date - timedelta(days=1), time(23, 2))
        bedtime += timedelta(minutes=round(12 * math.sin(day / 3)))
        stages, wake, sleep_minutes, awake_minutes = _sleep(bedtime)
        bounds[day] = bedtime, wake
        score = max(62, min(93, round(81 + 7 * math.sin(day / 4.2))))
        hrv = round(51 + 7 * math.sin(day / 5) - (3 if day < 3 else 0), 1)
        daily.append(GarminDaily(
            date=on_date, sleep_seconds=sleep_minutes * 60, sleep_score=score,
            deep_sleep_seconds=118 * 60, light_sleep_seconds=270 * 60,
            rem_sleep_seconds=68 * 60, awake_seconds=awake_minutes * 60,
            sleep_start=bedtime, sleep_end=wake, awake_count=4,
            restless_moments=round(9 + 3 * abs(math.sin(day))),
            avg_sleep_stress=16, avg_sleep_hr=53, spo2_lowest=91 if day == 9 else 94,
            respiration_lowest=12.3, respiration_highest=16.8,
            body_battery_change=58, breathing_disruption="NONE", sleep_need_actual=480,
            sleep_stages=stages,
            breathing_events=[{"start": (bedtime + timedelta(hours=2)).isoformat(timespec="seconds"),
                               "end": (bedtime + timedelta(hours=2, minutes=20)).isoformat(timespec="seconds"),
                               "value": 0}],
            resting_hr=round(56 - 2 * math.sin(day / 6)), avg_hr=74, max_hr=171, min_hr=47,
            hrv_avg=hrv, hrv_status="BALANCED" if hrv >= 48 else "LOW",
            avg_respiration=14.5, spo2_avg=96.4, avg_stress=round(31 + 5 * math.sin(day / 3)),
            max_stress=78, body_battery_high=round(84 + 5 * math.sin(day / 4)),
            body_battery_low=21, steps=round(8200 + 2600 * math.sin(day / 2.7)),
            floors_climbed=8, active_calories=round(520 + 140 * math.sin(day / 2.2)),
            bmr_calories=1840, total_calories=round(2360 + 140 * math.sin(day / 2.2)),
            intensity_minutes_moderate=34, intensity_minutes_vigorous=18 if day % 3 == 1 else 6,
            training_readiness=round(72 + 10 * math.sin(day / 4.5)), vo2max=47.2,
            training_status="PRODUCTIVE" if day < 18 else "MAINTAINING",
            acute_load=round(438 + 35 * math.sin(day / 5), 1),
            load_ratio=round(102 + 8 * math.sin(day / 5), 1),
            domain=Domain.GARMIN, source=Source.GARMIN_API,
        ))
    session.add_all(daily)
    intraday = sum(_whole_day_series(session, _d(day)) for day in (1, 0))
    intraday += sum(_night_series(session, _d(day), *bounds[day]) for day in (2, 1, 0))

    templates = (
        ("running", "Утренняя пробежка", 5200, 1760, 382, 148, 172, 38, 238, 3.4, 1.2),
        ("strength_training", "Силовая тренировка", 0, 4380, 410, 126, 166, None, None, 2.5, 2.1),
        ("cycling", "Велопрогулка", 18200, 3220, 536, 139, 169, 126, 204, 3.1, .8),
    )
    activities = []
    for index, day in enumerate((27, 23, 19, 15, 11, 7, 4, 1)):
        kind, name, distance, duration, calories, avg_hr, max_hr, elevation, power, aerobic, anaerobic = templates[index % 3]
        split_count = 5 if kind == "running" else (4 if kind == "cycling" else 0)
        splits = ([{"index": split + 1, "distance_m": distance / split_count,
                    "duration_s": duration / split_count, "avg_hr": avg_hr + split,
                    "max_hr": max_hr - 4 + split, "avg_speed_mps": distance / duration}
                   for split in range(split_count)] or None)
        activities.append(GarminActivity(
            date=_d(day), external_id=f"demo-activity-{index + 1:03d}",
            activity_type=kind, name=name, start_time=datetime.combine(_d(day), time(18, 15)),
            duration_seconds=duration, distance_m=distance or None, calories=calories,
            avg_hr=avg_hr, max_hr=max_hr, elevation_gain_m=elevation, avg_power=power,
            training_effect_aerobic=aerobic, training_effect_anaerobic=anaerobic,
            hr_zone_seconds=[{"zone": zone, "secs": round(duration * share), "low_hr": low}
                             for zone, share, low in ((1, .08, 95), (2, .22, 115),
                                                      (3, .38, 135), (4, .25, 153), (5, .07, 170))],
            splits=splits, domain=Domain.GARMIN, source=Source.GARMIN_API,
        ))
    session.add_all(activities)
    return len(daily) + intraday + len(activities)


_LABS = {
    "Glucose (fasting)": ("metabolic", "mmol/L", 3.9, 5.6, [5.5, 5.2, 4.9]),
    "Insulin (fasting)": ("metabolic", "μIU/mL", 2.6, 24.9, [12.4, 9.7, 7.8]),
    "HbA1c": ("metabolic", "%", 4, 5.7, [5.6, 5.4, 5.2]),
    "Vitamin D (25-OH)": ("vitamins", "ng/mL", 30, 100, [21, 24, 28]),
    "Ferritin": ("iron", "ng/mL", 30, 400, [58, 71, 84]),
    "TSH": ("thyroid", "mIU/L", .4, 4, [2.6, 2.2, 1.9]),
    "ALT": ("liver", "U/L", 0, 41, [38, 31, 26]),
    "AST": ("liver", "U/L", 0, 40, [31, 27, 24]),
    "Creatinine": ("kidney", "μmol/L", 62, 106, [96, 93, 89]),
    "LDL cholesterol": ("lipids", "mmol/L", 0, 3, [3.5, 3.2, 2.8]),
    "HDL cholesterol": ("lipids", "mmol/L", 1, 2.5, [1.15, 1.22, 1.31]),
    "Triglycerides": ("lipids", "mmol/L", 0, 1.7, [1.62, 1.42, 1.18]),
}


async def _seed_labs(session) -> int:
    await session.execute(delete(LabResult))
    await session.execute(delete(LabMarker))
    markers = [LabMarker(name=name, category=category, unit=unit, ref_low=low,
                         ref_high=high, tier=1 if category in {"metabolic", "liver", "kidney", "thyroid"} else 2,
                         retest_interval_days=90 if category in {"metabolic", "vitamins"} else 180,
                         domain=Domain.LABS)
               for name, (category, unit, low, high, _) in _LABS.items()]
    results = []
    for panel_index, day in enumerate((120, 60, 14)):
        for name, (_, unit, low, high, values) in _LABS.items():
            value = values[panel_index]
            flag = LabFlag.LOW if value < low else (LabFlag.HIGH if value > high else LabFlag.NORMAL)
            results.append(LabResult(date=_d(day), marker=name, value=value, unit=unit,
                                     ref_low=low, ref_high=high, flag=flag,
                                     lab_name="Invitro", domain=Domain.LABS,
                                     source=Source.LAB_PARSER))
    session.add_all([*markers, *results])
    return len(markers) + len(results)


async def _seed_glp1(session) -> int:
    await session.execute(delete(SideEffect))
    await session.execute(delete(Injection))
    await session.execute(delete(DosePhase))
    phases = [
        DosePhase(start_date=_d(84), end_date=_d(57), drug=Drug.SEMAGLUTIDE, dose_mg=.25,
                  note="Стартовая титрация", domain=Domain.GLP1, source=Source.MANUAL),
        DosePhase(start_date=_d(56), end_date=_d(22), drug=Drug.SEMAGLUTIDE, dose_mg=.5,
                  note="Хорошая переносимость", domain=Domain.GLP1, source=Source.MANUAL),
        DosePhase(start_date=_d(21), end_date=None, drug=Drug.SEMAGLUTIDE, dose_mg=1,
                  note="Текущая доза", domain=Domain.GLP1, source=Source.MANUAL),
    ]
    sites = list(InjectionSite)
    injections = []
    for index, day in enumerate(range(77, -1, -7)):
        dose = .25 if day >= 57 else (.5 if day >= 22 else 1)
        injections.append(Injection(date=_d(day), drug=Drug.SEMAGLUTIDE, dose_mg=dose,
                                    site=sites[index % len(sites)],
                                    domain=Domain.GLP1, source=Source.MANUAL))
    effects = [
        SideEffect(date=_d(76), effect_type="Тошнота", severity=2,
                   note="Только утром после первой инъекции", domain=Domain.GLP1, source=Source.MANUAL),
        SideEffect(date=_d(52), effect_type="Запор", severity=3,
                   note="Прошёл после коррекции воды и клетчатки", domain=Domain.GLP1, source=Source.MANUAL),
        SideEffect(date=_d(14), effect_type="Изжога", severity=1,
                   note="Однократно после позднего ужина", domain=Domain.GLP1, source=Source.MANUAL),
    ]
    session.add_all([*phases, *injections, *effects])
    return len(phases) + len(injections) + len(effects)


async def _seed_nutrition(session) -> int:
    await session.execute(delete(MealLog))
    meals = (
        ("Овсянка, банан и протеин", time(8, 20), 430, 34, 9, 58),
        ("Греческий йогурт с ягодами", time(11, 10), 210, 21, 6, 20),
        ("Курица, рис и овощи", time(14), 560, 49, 13, 61),
        ("Лосось, батат и салат", time(19, 15), 520, 41, 20, 43),
    )
    rows = []
    for day in range(13, -1, -1):
        for index, (name, eaten_at, calories, protein, fat, carbs) in enumerate(meals):
            scale = 1.08 if _d(day).weekday() >= 5 and index == 3 else 1 + .025 * math.sin(day + index)
            rows.append(MealLog(date=_d(day), name=name, eaten_at=eaten_at,
                                calories=round(calories * scale), protein_g=round(protein * scale, 1),
                                fat_g=round(fat * scale, 1), carbs_g=round(carbs * scale, 1),
                                domain=Domain.NUTRITION, source=Source.MANUAL))
    session.add_all(rows)
    return len(rows)


async def _seed_skincare(session) -> int:
    await session.execute(delete(SkincareObservation))
    await session.execute(delete(SkincareLog))
    await session.execute(delete(SkincareProduct))
    logs = []
    for day in range(13, -1, -1):
        on_date = _d(day)
        peel = on_date.weekday() == 5
        retinoid = on_date.weekday() in (0, 2, 4) and not peel
        logs.append(SkincareLog(date=on_date, retinoid=retinoid,
                                azelaic=not peel and not retinoid, peel=peel,
                                niacinamide_spf=True, moisturizer=True,
                                vitamin_c=not retinoid and not peel,
                                benzoyl_peroxide=day == 9,
                                note="Кожа спокойная" if day < 3 else None,
                                domain=Domain.SKINCARE, source=Source.MANUAL))
    observations = [
        SkincareObservation(date=_d(day), inflammation=infl, pih=pih, zone=zone, note=note,
                            domain=Domain.SKINCARE, source=Source.MANUAL)
        for day, infl, pih, zone, note in (
            (13, 3, 4, "подбородок", "Два воспаления после поездки"),
            (10, 3, 4, "щёки", "Без новых элементов"),
            (7, 2, 3, "подбородок", "Краснота уменьшается"),
            (4, 2, 3, "T-зона", "Барьер без сухости"),
            (1, 1, 2, "щёки", "Активных воспалений нет"),
        )
    ]
    all_days = list(range(7))
    products = [
        SkincareProduct(name="Differin 0.1%", type="Ретиноид", active_ingredient="Адапален 0.1%",
                        description="Текстура и профилактика акне", default_time="evening",
                        schedule_days=[0, 2, 4], active=True),
        SkincareProduct(name="Azelik 20%", type="Азелаиновая кислота", active_ingredient="Azelaic acid 20%",
                        description="Воспаления и постакне", default_time="evening",
                        schedule_days=[1, 3, 6], active=True),
        SkincareProduct(name="BHA 2%", type="Пилинг", active_ingredient="Salicylic acid 2%",
                        description="Эксфолиация раз в неделю", default_time="evening",
                        schedule_days=[5], active=True),
        SkincareProduct(name="Vitamin C 15%", type="Антиоксидант", active_ingredient="L-ascorbic acid 15%",
                        description="Тон и антиоксидантная защита", default_time="morning",
                        schedule_days=all_days, active=True),
        SkincareProduct(name="Niacinamide 5%", type="Сыворотка", active_ingredient="Niacinamide 5%",
                        description="Поддержка барьера", default_time="morning",
                        schedule_days=all_days, active=True),
        SkincareProduct(name="CeraVe Lotion", type="Увлажнение", active_ingredient="Ceramides",
                        description="Восстановление барьера", default_time="both",
                        schedule_days=all_days, active=True),
        SkincareProduct(name="Anthelios SPF 50+", type="SPF", active_ingredient="UV filters",
                        description="Ежедневная UVA/UVB защита", default_time="morning",
                        schedule_days=all_days, active=True),
    ]
    session.add_all([*logs, *observations, *products])
    return len(logs) + len(observations) + len(products)


async def _seed_workouts(session) -> int:
    await session.execute(delete(HevySet))
    await session.execute(delete(HevyExercise))
    await session.execute(delete(HevyWorkout))
    programs = (
        ("Жим", (("Bench Press", "bench", 82.5), ("Incline DB Press", "incline", 26),
                  ("Lateral Raise", "lateral", 10))),
        ("Тяга", (("Lat Pulldown", "pulldown", 57.5), ("Barbell Row", "row", 65),
                  ("Dumbbell Curl", "curl", 14))),
        ("Ноги", (("Back Squat", "squat", 90), ("Romanian Deadlift", "rdl", 72.5),
                  ("Leg Press", "leg_press", 145))),
    )
    workouts = []
    for index, day in enumerate((24, 21, 18, 14, 11, 8, 5, 2), start=1):
        title, exercises = programs[(index - 1) % len(programs)]
        workout = HevyWorkout(date=_d(day), external_id=f"demo-workout-{index:03d}",
                              title=f"{title} · {chr(65 + ((index - 1) // 3) % 2)}",
                              start_time=datetime.combine(_d(day), time(18, 30)),
                              duration_seconds=3900 + index * 45, program="Рекомпозиция 3×",
                              domain=Domain.WORKOUTS, source=Source.HEVY_API, exercises=[])
        for exercise_index, (exercise_name, template, base_weight) in enumerate(exercises):
            exercise = HevyExercise(exercise_index=exercise_index, title=exercise_name,
                                    exercise_template_id=template)
            exercise.sets = [
                HevySet(set_index=set_index, set_type="normal",
                        weight_kg=round(base_weight + index * .35 + set_index * .5, 1),
                        reps=10 - set_index)
                for set_index in range(3)
            ]
            workout.exercises.append(exercise)
        workouts.append(workout)
    session.add_all(workouts)
    return len(workouts)


async def _seed_timeline(session) -> int:
    await session.execute(delete(Annotation))
    rows = [
        Annotation(date=_d(72), end_date=_d(67), kind=AnnotationKind.TRAVEL,
                   title="Поездка в Стамбул", note="Другой режим сна и питания",
                   domain=Domain.TIMELINE, source=Source.MANUAL),
        Annotation(date=_d(56), kind=AnnotationKind.PROTOCOL_CHANGE,
                   title="Переход на 0.5 мг", note="Аппетит стабилизировался",
                   domain=Domain.GLP1, source=Source.MANUAL),
        Annotation(date=_d(24), end_date=_d(20), kind=AnnotationKind.ILLNESS,
                   title="ОРВИ", note="Четыре дня без тренировок",
                   domain=Domain.TIMELINE, source=Source.MANUAL),
        Annotation(date=_d(12), kind=AnnotationKind.LIFE_EVENT,
                   title="Новый тренировочный блок", note="Фокус на сохранении силы",
                   domain=Domain.WORKOUTS, source=Source.MANUAL),
        Annotation(date=_d(4), kind=AnnotationKind.TRAVEL,
                   title="Короткий перелёт", note="Временная задержка воды",
                   domain=Domain.WEIGHT, source=Source.MANUAL),
    ]
    session.add_all(rows)
    return len(rows)


async def _seed_milestones(session) -> int:
    await session.execute(delete(Milestone))
    rows = [
        Milestone(domain=Domain.WEIGHT, name="Достичь веса 85 кг", target_value=85,
                  target_unit="кг", deadline=_d(-28), status=MilestoneStatus.ACTIVE),
        Milestone(domain=Domain.WEIGHT, name="Жир ниже 15%", target_value=15,
                  target_unit="%", deadline=_d(-60), status=MilestoneStatus.ACTIVE),
        Milestone(domain=Domain.WORKOUTS, name="Жим лёжа 100 кг", target_value=100,
                  target_unit="кг", deadline=_d(-75), status=MilestoneStatus.ACTIVE),
        Milestone(domain=Domain.LABS, name="Витамин D выше 40", target_value=40,
                  target_unit="нг/мл", deadline=_d(-55), status=MilestoneStatus.ACTIVE,
                  note="Пересдать анализ через восемь недель"),
        Milestone(domain=Domain.WEIGHT, name="Первые 5 кг сброшены", target_value=89,
                  target_unit="кг", status=MilestoneStatus.ACHIEVED,
                  note="Достигнуто без потери силовых показателей"),
        Milestone(domain=Domain.GARMIN, name="Повысить VO₂max до 50", target_value=50,
                  status=MilestoneStatus.PAUSED, note="Вернуться к цели после фазы дефицита"),
    ]
    session.add_all(rows)
    return len(rows)


async def _seed_alerts(session) -> int:
    await session.execute(delete(SystemAlert))
    rows = [
        SystemAlert(domain=Domain.LABS, severity=Severity.WARN,
                    message="Vitamin D ниже целевого диапазона — ретест через 8 недель",
                    alert_key="labs.demo.vitamin_d_low", entity_ref="marker:vitamin_d"),
        SystemAlert(domain=Domain.GARMIN, severity=Severity.INFO,
                    message="HRV немного ниже личной базы последние 3 дня",
                    alert_key="garmin.demo.hrv_watch", entity_ref=""),
    ]
    session.add_all(rows)
    return len(rows)


async def _seed_settings(session) -> int:
    await session.execute(delete(AppSetting))
    charts = [
        {"id": "demo-recovery", "name": "Вес и восстановление", "normalize": True,
         "series": [
             {"domain": "weight", "metric_key": "weight.weight_kg", "param": None, "label": None, "color_slot": 0},
             {"domain": "garmin", "metric_key": "garmin.hrv_avg", "param": None, "label": None, "color_slot": 1},
             {"domain": "garmin", "metric_key": "garmin.sleep_score", "param": None, "label": None, "color_slot": 2},
         ]},
        {"id": "demo-composition", "name": "Рекомпозиция тела", "normalize": False,
         "series": [
             {"domain": "weight", "metric_key": "weight.body_fat_pct", "param": None, "label": "Navy", "color_slot": 0},
             {"domain": "body_comp", "metric_key": "body_comp.metric", "param": "body_fat_pct", "label": "InBody", "color_slot": 1},
             {"domain": "body_comp", "metric_key": "body_comp.metric", "param": "skeletal_muscle_mass", "label": "Мышцы", "color_slot": 2},
         ]},
    ]
    session.add_all([
        AppSetting(key="enabled_modules", value={key: True for key in MODULE_REGISTRY}),
        AppSetting(key="ui_language", value="ru"),
        AppSetting(key="custom_charts", value=charts),
    ])
    return 3


async def seed_all(session) -> dict[str, int]:
    """Replace all demo-owned data and flush; safe to call on every local start."""
    random.seed(42)
    counts = {
        "supplements": await _seed_supplements(session),
        "genetics": await _seed_genetics(session),
        "weight": await _seed_weight(session),
        "body_scans": await _seed_body_scans(session),
        "garmin": await _seed_garmin(session),
        "labs": await _seed_labs(session),
        "glp1": await _seed_glp1(session),
        "nutrition": await _seed_nutrition(session),
        "skincare": await _seed_skincare(session),
        "workouts": await _seed_workouts(session),
        "timeline": await _seed_timeline(session),
        "milestones": await _seed_milestones(session),
    }
    counts["digests"] = await _seed_digests(session)
    await session.execute(delete(ConflictRule))
    await session.flush()
    counts["conflict_rules"] = (await conflict_catalog.sync_catalog(session))["total"]
    counts["alerts"] = await _seed_alerts(session)
    counts["settings"] = await _seed_settings(session)
    await session.flush()
    return counts


async def main() -> None:
    config = load_config()
    factory = create_session_factory(config)
    async with factory() as session:
        print("Refreshing the current Vitals UI demo dataset...")
        counts = await seed_all(session)
        await session.commit()
        for name, count in counts.items():
            print(f"  + {name}: {count}")
        print("Done! Start the server: python run_local.py")


if __name__ == "__main__":
    asyncio.run(main())
