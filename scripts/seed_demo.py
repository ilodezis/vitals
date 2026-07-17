#!/usr/bin/env python3
"""Seed a local dev instance with realistic demo data.

Persona: Alex, 27, 185 cm, fat-loss journey over 3 months (94 → 86 kg).
Run AFTER `python run_local.py` has been started at least once (creates the DB).

Usage:
    python scripts/seed_demo.py
"""
import asyncio
import os
import sys
import random
from datetime import date, datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("VITALS_DATABASE_URL", "sqlite+aiosqlite:///local_vitals.db")
os.environ.setdefault("VITALS_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("VITALS_TIMEZONE", "Europe/Chisinau")

from sqlalchemy import delete

from vitals.config import load_config
from vitals.database import create_session_factory
from vitals.enums import (
    Domain,
    Drug,
    Evidence,
    InjectionSite,
    LabFlag,
    MilestoneStatus,
    RuleType,
    Severity,
    Source,
)
from vitals.models.app_settings import AppSetting
from vitals.models.conflict_rule import ConflictRule
from vitals.models.garmin import (
    SERIES_BODY_BATTERY,
    SERIES_STRESS,
    GarminDaily,
    GarminIntraday,
)
from vitals.models.genetics import GeneticVariant
from vitals.models.glp1 import DosePhase, Injection
from vitals.models.hevy import HevyExercise, HevySet, HevyWorkout
from vitals.models.labs import LabMarker, LabResult
from vitals.models.milestones import Milestone, WeeklyDigest
from vitals.models.nutrition import MealLog
from vitals.models.skincare import SkincareLog, SkincareProduct
from vitals.models.supplements import Supplement
from vitals.models.weight import BodyMeasurement, WeightLog
from vitals.utils.timeutils import today_local

random.seed(42)

TODAY = today_local()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _d(days_ago: int) -> date:
    return TODAY - timedelta(days=days_ago)


def _weight_curve(days_ago: int) -> float:
    """94 kg at day -90, dropping to ~86 kg at day 0 with realistic noise."""
    base = 94.0 - (90 - days_ago) * (8.0 / 90)
    noise = random.uniform(-0.4, 0.4)
    return round(base + noise, 1)


# ---------------------------------------------------------------------------
# Seed functions
# ---------------------------------------------------------------------------

async def seed_supplements(session):
    await session.execute(delete(Supplement))
    items = [
        Supplement(name="Creatine Monohydrate", key="creatine", dose="5 g",
                   timing="утро", evidence=Evidence.A, active=True,
                   domain=Domain.SUPPLEMENTS, source=Source.MANUAL),
        Supplement(name="Vitamin D3", key="vitamin_d", dose="4000 IU",
                   timing="день", evidence=Evidence.A, active=True,
                   domain=Domain.SUPPLEMENTS, source=Source.MANUAL),
        Supplement(name="Omega-3 Fish Oil", key="omega3", dose="2 g EPA+DHA",
                   timing="день", evidence=Evidence.A, active=True,
                   domain=Domain.SUPPLEMENTS, source=Source.MANUAL),
        Supplement(name="Magnesium Glycinate", key="magnesium", dose="400 mg",
                   timing="вечер", evidence=Evidence.B, active=True,
                   domain=Domain.SUPPLEMENTS, source=Source.MANUAL),
        Supplement(name="Zinc Picolinate", key="zinc", dose="25 mg",
                   timing="вечер", evidence=Evidence.B, active=True,
                   domain=Domain.SUPPLEMENTS, source=Source.MANUAL),
        Supplement(name="Melatonin", key="melatonin", dose="3 mg",
                   timing="ночь", evidence=Evidence.B, active=True,
                   domain=Domain.SUPPLEMENTS, source=Source.MANUAL),
        Supplement(name="Iron Bisglycinate", key="iron", dose="36 mg",
                   timing="утро", evidence=Evidence.B, active=False,
                   note="Paused — ferritin normalized",
                   domain=Domain.SUPPLEMENTS, source=Source.MANUAL),
    ]
    session.add_all(items)


async def seed_genetics(session):
    await session.execute(delete(GeneticVariant))
    items = [
        GeneticVariant(gene="MTHFR", rsid="rs1801133", genotype="CT",
                       marker="mthfr_heterozygous",
                       impact="Reduced folate metabolism (~65% activity)",
                       impact_domain=Domain.SUPPLEMENTS,
                       interpretation="Heterozygous C677T — moderate effect",
                       action_notes="Consider methylfolate over folic acid",
                       domain=Domain.GENETICS, source=Source.VCF_IMPORT),
        GeneticVariant(gene="CYP1A2", rsid="rs762551", genotype="AC",
                       marker="cyp1a2_slow_metabolizer",
                       impact="Slow caffeine metabolism",
                       impact_domain=Domain.SUPPLEMENTS,
                       interpretation="One slow allele — intermediate metabolizer",
                       action_notes="Limit caffeine after 2 PM",
                       domain=Domain.GENETICS, source=Source.VCF_IMPORT),
        GeneticVariant(gene="APOE", rsid="rs429358", genotype="CT",
                       marker="apoe_e3e4",
                       impact="APOE ε3/ε4 — elevated cardiovascular risk",
                       impact_domain=Domain.LABS,
                       interpretation="One ε4 allele; monitor lipids closely",
                       action_notes="Prioritize omega-3, minimize saturated fat",
                       domain=Domain.GENETICS, source=Source.VCF_IMPORT),
        GeneticVariant(gene="FTO", rsid="rs9939609", genotype="AT",
                       marker="fto_risk_heterozygous",
                       impact="Moderately increased obesity risk",
                       impact_domain=Domain.WEIGHT,
                       interpretation="One risk allele — ~1.3× risk vs TT",
                       action_notes="Higher protein intake may counteract the effect",
                       domain=Domain.GENETICS, source=Source.VCF_IMPORT),
    ]
    session.add_all(items)


async def seed_lab_markers(session):
    await session.execute(delete(LabMarker))
    markers = [
        LabMarker(name="Glucose (fasting)", category="metabolic",
                  unit="mmol/L", ref_low=3.9, ref_high=5.6, tier=1,
                  domain=Domain.LABS),
        LabMarker(name="Insulin (fasting)", category="metabolic",
                  unit="μIU/mL", ref_low=2.6, ref_high=24.9, tier=1,
                  domain=Domain.LABS),
        LabMarker(name="TSH", category="thyroid",
                  unit="mIU/L", ref_low=0.4, ref_high=4.0, tier=1,
                  retest_interval_days=180, domain=Domain.LABS),
        LabMarker(name="Vitamin D (25-OH)", category="vitamins",
                  unit="ng/mL", ref_low=30.0, ref_high=100.0, tier=2,
                  retest_interval_days=90, domain=Domain.LABS),
        LabMarker(name="HbA1c", category="metabolic",
                  unit="%", ref_low=4.0, ref_high=5.7, tier=1,
                  retest_interval_days=90, domain=Domain.LABS),
        LabMarker(name="Triglycerides", category="lipids",
                  unit="mg/dL", ref_low=0.0, ref_high=150.0, tier=2,
                  domain=Domain.LABS),
    ]
    session.add_all(markers)


async def seed_conflict_rules(session):
    await session.execute(delete(ConflictRule))
    rules = [
        ConflictRule(
            rule_type=RuleType.SOFT_WARN,
            domain_a=Domain.SUPPLEMENTS, condition_a={"key": "iron", "active": True},
            domain_b=Domain.GENETICS, condition_b={"marker": "hemochromatosis_carrier"},
            severity=Severity.WARN,
            message="Iron supplementation with hemochromatosis carrier status — monitor ferritin",
            active=True,
        ),
        ConflictRule(
            rule_type=RuleType.HARD_BLOCK,
            domain_a=Domain.SKINCARE, condition_a={"retinoid": True},
            domain_b=Domain.SKINCARE, condition_b={"peel": True},
            severity=Severity.BLOCK,
            message="Retinoid and chemical peel on the same day — high irritation risk",
            active=True,
        ),
        ConflictRule(
            rule_type=RuleType.TIMING_SEPARATION,
            domain_a=Domain.SUPPLEMENTS, condition_a={"key": "iron", "active": True},
            domain_b=Domain.SUPPLEMENTS, condition_b={"key": "zinc", "active": True},
            severity=Severity.WARN,
            message="Iron and zinc compete for absorption — take 2+ hours apart",
            params={"hours": 2},
            active=True,
        ),
    ]
    session.add_all(rules)


async def seed_dose_phases(session):
    await session.execute(delete(DosePhase))
    phases = [
        DosePhase(
            start_date=_d(84), end_date=_d(57),
            drug=Drug.SEMAGLUTIDE, dose_mg=0.25,
            note="Titration — starting dose",
            domain=Domain.GLP1, source=Source.MANUAL,
        ),
        DosePhase(
            start_date=_d(56), end_date=None,
            drug=Drug.SEMAGLUTIDE, dose_mg=0.5,
            note="Maintenance dose",
            domain=Domain.GLP1, source=Source.MANUAL,
        ),
    ]
    session.add_all(phases)


async def seed_weight(session):
    await session.execute(delete(WeightLog))
    days = sorted(random.sample(range(1, 91), 20), reverse=True)
    for d in days:
        session.add(WeightLog(
            date=_d(d), weight_kg=_weight_curve(d), superseded=False,
            domain=Domain.WEIGHT, source=Source.MANUAL,
        ))


async def seed_measurements(session):
    await session.execute(delete(BodyMeasurement))
    data = [
        (90, 40.5, 95.0, 22.1, None),
        (60, 39.8, 92.0, 20.5, None),
        (30, 39.2, 89.5, 19.0, None),
        (7,  38.8, 87.0, 17.8, None),
    ]
    for days_ago, neck, waist, bf, lbm in data:
        w = _weight_curve(days_ago)
        computed_lbm = round(w * (1 - bf / 100), 1)
        session.add(BodyMeasurement(
            date=_d(days_ago), neck_cm=neck, waist_cm=waist,
            body_fat_pct=bf, lbm_kg=computed_lbm,
            domain=Domain.WEIGHT, source=Source.MANUAL,
        ))


def _seed_intraday_day(session, d):
    """One day's stress / Body Battery curves at a 5-minute cadence (the real
    device samples every ~3 min; coarser here just to keep the demo DB small).
    Shaped like a real day — battery charges through the night and drains once
    stress picks up — so the dashboard chart shows the relationship it exists for."""
    battery = random.randint(20, 35)
    for slot in range(0, 24 * 60, 5):
        ts = datetime.combine(d, time(0, 0)) + timedelta(minutes=slot)
        asleep = slot < 7 * 60 or slot > 23 * 60
        stress = random.randint(8, 22) if asleep else random.randint(20, 75)
        # Sleep recharges, waking hours drain roughly in step with stress.
        battery += random.uniform(0.8, 1.6) if asleep else -stress / 60.0
        battery = max(5.0, min(100.0, battery))
        session.add(GarminIntraday(
            date=d, series_type=SERIES_STRESS, ts=ts, value=float(stress),
            domain=Domain.GARMIN, source=Source.GARMIN_API,
        ))
        session.add(GarminIntraday(
            date=d, series_type=SERIES_BODY_BATTERY, ts=ts, value=round(battery, 1),
            domain=Domain.GARMIN, source=Source.GARMIN_API,
        ))


async def seed_garmin(session):
    await session.execute(delete(GarminIntraday))
    await session.execute(delete(GarminDaily))
    # Intraday curves only for the two most recent days: at ~576 rows a day they
    # are the densest thing in the lake, and the dashboard only charts the latest.
    for i in (2, 1):
        _seed_intraday_day(session, _d(i))
    for i in range(14, 0, -1):
        d = _d(i)
        sleep_h = random.uniform(6.5, 8.5)
        session.add(GarminDaily(
            date=d,
            sleep_seconds=int(sleep_h * 3600),
            sleep_score=random.randint(65, 92),
            deep_sleep_seconds=int(random.uniform(0.8, 1.8) * 3600),
            light_sleep_seconds=int(random.uniform(2.5, 4.0) * 3600),
            rem_sleep_seconds=int(random.uniform(1.0, 2.0) * 3600),
            awake_seconds=int(random.uniform(0.1, 0.5) * 3600),
            resting_hr=random.randint(52, 62),
            hrv_avg=round(random.uniform(35, 65), 1),
            hrv_status=random.choice(["balanced", "balanced", "low", "optimal"]),
            avg_stress=random.randint(25, 45),
            body_battery_high=random.randint(75, 100),
            body_battery_low=random.randint(10, 35),
            steps=random.randint(5000, 13000),
            active_calories=random.randint(300, 700),
            training_readiness=random.randint(45, 85),
            vo2max=round(random.uniform(42, 48), 1),
            domain=Domain.GARMIN, source=Source.GARMIN_API,
        ))


async def seed_meals(session):
    await session.execute(delete(MealLog))
    meal_templates = [
        ("Oatmeal with banana and whey", time(8, 30), 420, 32, 8, 62),
        ("Greek yogurt with berries", time(11, 0), 180, 18, 5, 16),
        ("Chicken breast with rice and veggies", time(13, 30), 550, 48, 12, 58),
        ("Protein shake (whey + milk)", time(16, 0), 220, 35, 4, 12),
        ("Salmon with sweet potato", time(19, 0), 480, 38, 18, 42),
        ("Cottage cheese with almonds", time(21, 0), 200, 24, 8, 6),
        ("Eggs (3) with toast and avocado", time(8, 0), 450, 28, 24, 32),
        ("Turkey wrap with hummus", time(13, 0), 380, 32, 12, 38),
        ("Steak with broccoli", time(19, 30), 520, 45, 28, 8),
        ("Casein shake before bed", time(22, 0), 130, 25, 1, 4),
    ]
    for i in range(8):  # 0 = today, 1..7 = past week
        d = _d(i)
        day_meals = random.sample(meal_templates, random.randint(3, 4))
        for name, eaten_at, cal, prot, fat, carbs in day_meals:
            noise = random.uniform(0.9, 1.1)
            session.add(MealLog(
                date=d, name=name, eaten_at=eaten_at,
                calories=round(cal * noise),
                protein_g=round(prot * noise, 1),
                fat_g=round(fat * noise, 1),
                carbs_g=round(carbs * noise, 1),
                domain=Domain.NUTRITION, source=Source.MANUAL,
            ))


async def seed_skincare(session):
    await session.execute(delete(SkincareLog))
    await session.execute(delete(SkincareProduct))
    for i in range(7, 0, -1):
        d = _d(i)
        dow = d.weekday()
        is_peel_day = dow in (1, 5)  # Tue, Sat
        session.add(SkincareLog(
            date=d,
            retinoid=not is_peel_day,
            azelaic=not is_peel_day,
            peel=is_peel_day,
            niacinamide_spf=True,
            moisturizer=True,
            domain=Domain.SKINCARE, source=Source.MANUAL,
        ))
    all_days = [0, 1, 2, 3, 4, 5, 6]
    peel_days = [2, 6]  # Tue, Sat
    non_peel = [0, 1, 3, 4, 5]  # Sun, Mon, Wed, Thu, Fri
    products = [
        SkincareProduct(
            name="Differin 0.1%", type="Retinoid",
            active_ingredient="Adapalene 0.1%",
            description="Topical retinoid for acne and texture",
            default_time="evening", schedule_days=non_peel, active=True,
        ),
        SkincareProduct(
            name="Azelik 20%", type="Azelaic acid",
            active_ingredient="Azelaic acid 20%",
            description="Anti-inflammatory, PIH treatment",
            default_time="evening", schedule_days=non_peel, active=True,
        ),
        SkincareProduct(
            name="BHA Peel 2%", type="Chemical peel",
            active_ingredient="Salicylic acid 2%",
            description="Exfoliation, pore clearing",
            default_time="evening", schedule_days=peel_days, active=True,
        ),
        SkincareProduct(
            name="Niacinamide + Zinc Serum", type="Serum",
            active_ingredient="Niacinamide 10%, Zinc PCA 1%",
            description="Sebum control, barrier repair",
            default_time="morning", schedule_days=all_days, active=True,
        ),
        SkincareProduct(
            name="SPF 50 Sunscreen", type="Sunscreen",
            active_ingredient="UV filters",
            description="Daily UV protection",
            default_time="morning", schedule_days=all_days, active=True,
        ),
        SkincareProduct(
            name="CeraVe Moisturizer", type="Moisturizer",
            active_ingredient="Ceramides, Hyaluronic acid",
            description="Barrier repair, hydration",
            default_time="both", schedule_days=all_days, active=True,
        ),
    ]
    session.add_all(products)


async def seed_injections(session):
    await session.execute(delete(Injection))
    sites = list(InjectionSite)
    for i in range(4):
        days_ago = 7 * (4 - i)
        dose = 0.25 if days_ago > 56 else 0.5
        session.add(Injection(
            date=_d(days_ago),
            drug=Drug.SEMAGLUTIDE,
            dose_mg=dose,
            site=sites[i % len(sites)],
            domain=Domain.GLP1, source=Source.MANUAL,
        ))


async def seed_labs(session):
    await session.execute(delete(LabResult))
    panel_date = _d(21)
    results = [
        ("Glucose (fasting)", 5.1, "mmol/L", 3.9, 5.6, LabFlag.NORMAL),
        ("Insulin (fasting)", 8.3, "μIU/mL", 2.6, 24.9, LabFlag.NORMAL),
        ("TSH", 2.1, "mIU/L", 0.4, 4.0, LabFlag.NORMAL),
        ("Vitamin D (25-OH)", 28.0, "ng/mL", 30.0, 100.0, LabFlag.LOW),
        ("HbA1c", 5.3, "%", 4.0, 5.7, LabFlag.NORMAL),
        ("Triglycerides", 128.0, "mg/dL", 0.0, 150.0, LabFlag.NORMAL),
    ]
    for marker, val, unit, lo, hi, flag in results:
        session.add(LabResult(
            date=panel_date, marker=marker, value=val, unit=unit,
            ref_low=lo, ref_high=hi, flag=flag,
            lab_name="Invitro",
            domain=Domain.LABS, source=Source.LAB_PARSER,
        ))


async def seed_workouts(session):
    await session.execute(delete(HevyWorkout))

    programs = [
        ("Push A", "A", [
            ("Bench Press (Barbell)", "tmpl_bench", [
                (60, 8, "warmup"), (80, 8, "normal"), (85, 6, "normal"), (85, 5, "normal"),
            ]),
            ("Overhead Press (Dumbbell)", "tmpl_ohp", [
                (16, 10, "normal"), (18, 8, "normal"), (18, 7, "normal"),
            ]),
            ("Incline Dumbbell Press", "tmpl_incline_db", [
                (24, 10, "normal"), (26, 8, "normal"), (26, 7, "normal"),
            ]),
            ("Lateral Raise", "tmpl_lateral", [
                (8, 15, "normal"), (10, 12, "normal"), (10, 10, "normal"),
            ]),
            ("Tricep Pushdown", "tmpl_tri_push", [
                (25, 12, "normal"), (30, 10, "normal"), (30, 8, "normal"),
            ]),
        ]),
        ("Pull A", "A", [
            ("Lat Pulldown", "tmpl_lat_pull", [
                (50, 10, "normal"), (55, 8, "normal"), (57.5, 7, "normal"),
            ]),
            ("Barbell Row", "tmpl_bb_row", [
                (50, 8, "warmup"), (60, 8, "normal"), (65, 6, "normal"), (65, 6, "normal"),
            ]),
            ("Face Pull", "tmpl_face_pull", [
                (15, 15, "normal"), (17.5, 12, "normal"), (17.5, 12, "normal"),
            ]),
            ("Dumbbell Curl", "tmpl_db_curl", [
                (12, 10, "normal"), (14, 8, "normal"), (14, 7, "normal"),
            ]),
        ]),
        ("Legs", "B", [
            ("Squat (Barbell)", "tmpl_squat", [
                (60, 8, "warmup"), (80, 6, "normal"), (90, 5, "normal"), (90, 4, "normal"),
            ]),
            ("Romanian Deadlift", "tmpl_rdl", [
                (60, 8, "normal"), (70, 8, "normal"), (70, 7, "normal"),
            ]),
            ("Leg Press", "tmpl_leg_press", [
                (120, 10, "normal"), (140, 8, "normal"), (140, 8, "normal"),
            ]),
            ("Leg Curl (Machine)", "tmpl_leg_curl", [
                (35, 12, "normal"), (40, 10, "normal"), (40, 9, "normal"),
            ]),
            ("Calf Raise", "tmpl_calf", [
                (60, 15, "normal"), (70, 12, "normal"), (70, 12, "normal"),
            ]),
        ]),
        ("Push B", "B", [
            ("Bench Press (Barbell)", "tmpl_bench", [
                (60, 8, "warmup"), (82.5, 7, "normal"), (87.5, 5, "normal"), (87.5, 5, "normal"),
            ]),
            ("Dumbbell Shoulder Press", "tmpl_db_shoulder", [
                (18, 10, "normal"), (20, 8, "normal"), (20, 7, "normal"),
            ]),
            ("Cable Fly", "tmpl_cable_fly", [
                (10, 12, "normal"), (12.5, 10, "normal"), (12.5, 10, "normal"),
            ]),
            ("Overhead Tricep Extension", "tmpl_tri_ext", [
                (15, 12, "normal"), (17.5, 10, "normal"), (17.5, 9, "normal"),
            ]),
        ]),
        ("Pull B", "A", [
            ("Deadlift (Barbell)", "tmpl_deadlift", [
                (80, 5, "warmup"), (100, 5, "normal"), (110, 3, "normal"), (110, 3, "normal"),
            ]),
            ("Seated Cable Row", "tmpl_cable_row", [
                (50, 10, "normal"), (55, 8, "normal"), (55, 8, "normal"),
            ]),
            ("Lat Pulldown (Close Grip)", "tmpl_lat_close", [
                (45, 10, "normal"), (50, 8, "normal"), (50, 8, "normal"),
            ]),
            ("Hammer Curl", "tmpl_hammer", [
                (14, 10, "normal"), (16, 8, "normal"), (16, 7, "normal"),
            ]),
        ]),
        ("Legs + Core", "B", [
            ("Front Squat", "tmpl_front_squat", [
                (40, 8, "warmup"), (60, 6, "normal"), (65, 5, "normal"), (65, 5, "normal"),
            ]),
            ("Bulgarian Split Squat", "tmpl_bss", [
                (12, 10, "normal"), (14, 8, "normal"), (14, 8, "normal"),
            ]),
            ("Leg Extension", "tmpl_leg_ext", [
                (40, 12, "normal"), (45, 10, "normal"), (45, 10, "normal"),
            ]),
            ("Cable Crunch", "tmpl_cable_crunch", [
                (30, 15, "normal"), (35, 12, "normal"), (35, 12, "normal"),
            ]),
        ]),
    ]

    workout_days = [3, 5, 8, 10, 13, 15]
    for idx, days_ago in enumerate(workout_days):
        title, program, exercises = programs[idx % len(programs)]
        d = _d(days_ago)
        start_hour = random.choice([9, 10, 17, 18])

        workout = HevyWorkout(
            date=d,
            external_id=f"demo-workout-{idx + 1:03d}",
            title=title,
            start_time=d.timetuple()[:3] and None,  # keep it simple — no datetime for SQLite
            duration_seconds=random.randint(3600, 5400),
            program=program,
            domain=Domain.WORKOUTS, source=Source.HEVY_API,
            exercises=[],
        )

        for ex_idx, (ex_title, tmpl_id, sets_data) in enumerate(exercises):
            exercise = HevyExercise(
                exercise_index=ex_idx,
                title=ex_title,
                exercise_template_id=tmpl_id,
            )
            for set_idx, (weight, reps, set_type) in enumerate(sets_data):
                exercise.sets.append(HevySet(
                    set_index=set_idx,
                    set_type=set_type,
                    weight_kg=weight,
                    reps=reps,
                ))
            workout.exercises.append(exercise)

        session.add(workout)


async def seed_milestones(session):
    await session.execute(delete(Milestone))
    items = [
        Milestone(domain=Domain.WEIGHT, name="Reach 85 kg",
                  target_value=85.0, target_unit="kg",
                  deadline=_d(-30),
                  status=MilestoneStatus.ACTIVE),
        Milestone(domain=Domain.WEIGHT, name="Body fat under 15%",
                  target_value=15.0, target_unit="%",
                  status=MilestoneStatus.ACTIVE),
        Milestone(domain=Domain.WORKOUTS, name="Bench press 100 kg",
                  target_value=100.0, target_unit="kg",
                  status=MilestoneStatus.ACTIVE),
        Milestone(domain=Domain.LABS, name="Vitamin D above 40 ng/mL",
                  target_value=40.0, target_unit="ng/mL",
                  status=MilestoneStatus.ACTIVE,
                  note="Supplementing 4000 IU daily, retest in 3 months"),
    ]
    session.add_all(items)


async def seed_digests(session):
    await session.execute(delete(WeeklyDigest))

    digest_ru = (
        "## \U0001f4c9 Вес: тренд есть, но смотреть надо на MA\n\n"
        "Главное, что нужно понять про текущую картину с весом — она зашумлена. "
        "Активен маркер **«Загрузка креатином»** (стартовал 2 недели назад), direction: up. "
        "Это значит: часть снижения, которую ты видишь в цифрах, — артефакт. "
        "Тело набирало воду от креатина, и на этом фоне реальная потеря жира выглядит "
        "*лучше*, чем показывает тренд. Но как только маркер закроется, скользящее среднее "
        "начнёт подтягиваться вверх — это не откат, это просто уход шума.\n\n"
        "Теперь по цифрам. **MA7 = 88.2 кг** (7 дней назад). Latest = **87.1 кг** (сегодня). "
        "Разрыв в 1.1 кг между ними — это не «я похудел на 1.1 за неделю», это просто то, что "
        "MA считалась в другой момент. Реальный тренд по модели — **~0.7 кг/нед**, и это хорошая "
        "цифра, особенно с учётом того, что шум направлен вверх.\n\n"
        "## \U0001f3af Цель 85 кг: математика норм, но есть нюанс\n\n"
        "**30 дней до дедлайна, нужно скинуть ещё ~2 кг.** При темпе ~0.7 кг/нед это ~2.8 кг "
        "за 4 недели — запас есть. Но после завершения креатиновой загрузки видимый темп "
        "снижения, скорее всего, замедлится — тело «вернёт» часть водного веса в MA. "
        "Это создаст психологическое ощущение стагнации, хотя жир продолжит уходить. "
        "Важно не паниковать в этот момент и не начинать резать калории ещё сильнее.\n\n"
        "## \U0001f4aa Тренировки: прогрессия идёт\n\n"
        "3 сессии за неделю (Push A, Pull A, Legs). Жим лёжа: 82.5 → 85 кг на 6 повторов — "
        "солидно. Тяга верхнего блока +2.5 кг. Приседания стабильно на 90 кг. "
        "Объём адекватный, RPE в пределах 7–8 — прогрессивная перегрузка работает.\n\n"
        "## \U0001f6cc Восстановление: среднее, но объяснимо\n\n"
        "Сон в среднем 7ч 12мин (score 78). HRV тренд слегка вниз последние 3 дня "
        "(52 → 41 мс) — скорее всего, накопленная усталость после тренировок. "
        "Body Battery восстанавливается нормально (low 20s → high 80s дневной цикл). "
        "Training Readiness колеблется 55–70 — в зелёной зоне.\n\n"
        "**Рекомендация:** восстановление достаточное, несмотря на снижение HRV. "
        "Если HRV не восстановится за 2–3 дня — имеет смысл сделать deload-неделю. "
        "Следующая тренировка: Pull B — можно проводить.\n\n"
        "## \U0001f489 GLP-1: стабильно\n\n"
        "5-я неделя на 0.5 мг семаглутида. Побочных эффектов нет. "
        "Аппетит подавлен стабильно, без резких провалов энергии. "
        "Плато не зафиксировано (`plateau: null`), всё ок.\n\n"
        "## \U0001f372 Питание: в рамках\n\n"
        "Среднее за неделю: 1,780 ккал/день, 158г белка — попадание в цели. "
        "Небольшой профицит в субботу (cheat meal), но в рамках недельного дефицита "
        "это не критично. Белок стабильно выше 150г — хорошо для сохранения LBM.\n\n"
        "## \U0001f9ea Анализы: обратить внимание\n\n"
        "Витамин D — 28 ng/mL (ниже референса 30–100). Сейчас на 4000 IU ежедневно. "
        "Ретест через 2 месяца. Остальные маркеры (глюкоза, инсулин, ТТГ, HbA1c, "
        "триглицериды) — в норме."
    )

    digest_en = (
        "## \U0001f4c9 Weight: trend is there, but look at the MA\n\n"
        "The key thing about the current weight picture — it's noisy. "
        "**Creatine loading** noise marker is active (started 2 weeks ago), direction: up. "
        "This means the scale is artificially inflated by water retention, so the real "
        "fat loss is actually *better* than the raw numbers show. Once the marker closes, "
        "the moving average will tick up briefly — that's not a reversal, just noise clearing.\n\n"
        "Numbers: **MA7 = 88.2 kg** (7 days ago). Latest = **87.1 kg** (today). "
        "The 1.1 kg gap is a timing artifact, not a weekly loss rate. "
        "Model-estimated trend: **~0.7 kg/week** — solid, especially considering the "
        "upward noise bias.\n\n"
        "## \U0001f3af Goal 85 kg: math works, with a caveat\n\n"
        "**30 days to deadline, ~2 kg left to lose.** At ~0.7 kg/week that's ~2.8 kg "
        "over 4 weeks — buffer exists. But post-creatine loading, the visible rate will "
        "likely slow as the body \"returns\" water weight into the MA. This will *feel* "
        "like a plateau even though fat loss continues. Don't panic-cut calories.\n\n"
        "## \U0001f4aa Training: progressing\n\n"
        "3 sessions this week (Push A, Pull A, Legs). Bench press: 82.5 → 85 kg for "
        "6 reps — solid progression. Lat pulldown +2.5 kg. Squat holding steady at 90 kg. "
        "Volume appropriate, RPE 7–8 range — progressive overload is working.\n\n"
        "## \U0001f6cc Recovery: moderate but explainable\n\n"
        "Average sleep 7h 12min (score 78). HRV trending down over the last 3 days "
        "(52 → 41 ms) — likely accumulated training fatigue. Body Battery recovering "
        "normally (low 20s → high 80s daily cycle). Training Readiness 55–70 — green zone.\n\n"
        "**Recommendation:** recovery is sufficient despite the HRV dip. If HRV doesn't "
        "rebound within 2–3 days, consider a deload week. Next session: Pull B is fine "
        "to proceed.\n\n"
        "## \U0001f489 GLP-1: stable\n\n"
        "Week 5 on 0.5 mg semaglutide. No side effects. Appetite suppression stable, "
        "no energy crashes. Plateau not detected (`plateau: null`), all good.\n\n"
        "## \U0001f372 Nutrition: on target\n\n"
        "Weekly average: 1,780 kcal/day, 158g protein — hitting targets. "
        "Slight surplus Saturday (cheat meal) but within the weekly deficit — not critical. "
        "Protein consistently above 150g — good for LBM preservation.\n\n"
        "## \U0001f9ea Labs: flag\n\n"
        "Vitamin D at 28 ng/mL (below reference 30–100). Currently supplementing "
        "4000 IU daily. Retest in 2 months. All other markers (glucose, insulin, TSH, "
        "HbA1c, triglycerides) — normal."
    )

    session.add(WeeklyDigest(
        date=_d(7),
        content=digest_en,
        model="anthropic/claude-sonnet-4.6",
        domain=Domain.MILESTONES, source=Source.SCHEDULER,
    ))
    session.add(WeeklyDigest(
        date=_d(14),
        content=digest_ru,
        model="anthropic/claude-sonnet-4.6",
        domain=Domain.MILESTONES, source=Source.SCHEDULER,
    ))


async def seed_app_settings(session):
    await session.execute(delete(AppSetting))
    session.add_all([
        AppSetting(
            key="enabled_modules",
            value={
                "glp1": True,
                "hevy": True,
                "supplements": True,
                "genetics": True,
                "skincare": True,
                "nutrition": True,
            },
        ),
        AppSetting(key="language", value="ru"),
    ])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    config = load_config()
    factory = create_session_factory(config)

    async with factory() as session:
        print("Seeding demo data (persona: Alex, 27, 185 cm, fat loss)...")

        await seed_supplements(session)
        print("  + Supplements (7)")

        await seed_genetics(session)
        print("  + Genetic variants (4)")

        await seed_lab_markers(session)
        print("  + Lab markers (6)")

        await seed_conflict_rules(session)
        print("  + Conflict rules (3)")

        await seed_dose_phases(session)
        print("  + GLP-1 dose phases (2)")

        await seed_weight(session)
        print("  + Weight logs (~20)")

        await seed_measurements(session)
        print("  + Body measurements (4)")

        await seed_garmin(session)
        print("  + Garmin daily (14 days)")

        await seed_meals(session)
        print("  + Meal logs (8 days incl. today)")

        await seed_skincare(session)
        print("  + Skincare logs (7 days) + products (6)")

        await seed_injections(session)
        print("  + GLP-1 injections (4)")

        await seed_labs(session)
        print("  + Lab results (1 panel, 6 markers)")

        await seed_workouts(session)
        print("  + Hevy workouts (6 sessions)")

        await seed_milestones(session)
        print("  + Milestones (4)")

        await seed_digests(session)
        print("  + Weekly digests (2: ru + en)")

        await seed_app_settings(session)
        print("  + App settings (all modules enabled)")

        await session.commit()
        print("\nDone! Start the server: python run_local.py")


if __name__ == "__main__":
    asyncio.run(main())
