"""Model registry — import every model here so a single
``import vitals.models`` registers them all on ``Base.metadata`` (used by Alembic
autogenerate and by the tests' ``create_all``).
"""
from vitals.models.base import Base, TimestampMixin
from vitals.models.mixins import InsightsMixin, insights_index
from vitals.models.raw_payload import RawPayload
from vitals.models.system_alert import SystemAlert
from vitals.models.conflict_rule import ConflictRule
from vitals.models.app_settings import AppSetting

# Phase 1 — Weight & Body Composition.
from vitals.models.weight import (
    WeightLog,
    BodyMeasurement,
    ProgressPhoto,
    NoiseMarker,
)

# Body composition — InBody / МедАсс (BIA) scans.
from vitals.models.body_scan import BodyScan, BodyScanMetric

# Phase 2 — GLP-1 Protocol.
from vitals.models.glp1 import (
    Injection,
    DosePhase,
    SideEffect,
)

# Phase 3 — Supplements / Genetics / Skincare.
from vitals.models.supplements import Supplement
from vitals.models.genetics import GeneticVariant
from vitals.models.skincare import SkincareLog, SkincareObservation, SkincareProduct

# Module 5 — Hevy workouts.
from vitals.models.hevy import HevyWorkout, HevyExercise, HevySet

# Module 6 — Garmin activity & recovery.
from vitals.models.garmin import GarminDaily, GarminActivity, GarminIntraday

# Module 7 — Lab results & parser.
from vitals.models.labs import LabResult, LabMarker

# Nutrition — meal logging with macros.
from vitals.models.nutrition import MealLog

# Module 10 — Milestones & weekly reporting.
from vitals.models.milestones import Milestone, WeeklyDigest

# Timeline — cross-domain event feed + chart annotations.
from vitals.models.timeline import Annotation

__all__ = [
    "Base",
    "TimestampMixin",
    "InsightsMixin",
    "insights_index",
    "RawPayload",
    "SystemAlert",
    "ConflictRule",
    "AppSetting",
    "WeightLog",
    "BodyMeasurement",
    "ProgressPhoto",
    "NoiseMarker",
    "BodyScan",
    "BodyScanMetric",
    "Injection",
    "DosePhase",
    "SideEffect",
    "Supplement",
    "GeneticVariant",
    "SkincareLog",
    "SkincareObservation",
    "SkincareProduct",
    "HevyWorkout",
    "HevyExercise",
    "HevySet",
    "GarminDaily",
    "GarminActivity",
    "GarminIntraday",
    "LabResult",
    "LabMarker",
    "MealLog",
    "Milestone",
    "WeeklyDigest",
    "Annotation",
]
