"""Cross-domain metric registry for the custom chart builder (pure logic, no I/O).

Declares every time-series metric a user can plot, across every domain, as a
flat ``REGISTRY`` keyed by a globally unique ``key``. Two shapes of entry:

  * **Simple** (``param_kind="none"``) — one column on one model, resolved
    generically by ``chart_data_service._simple_series`` via a plain
    ``GROUP BY date`` + aggregate query. Covers weight, garmin, glp1,
    nutrition, skincare.
  * **Parametrized** (``param_kind != "none"``) — the metric needs a
    sub-parameter chosen at chart-build time (a lab marker, a Hevy exercise, a
    BIA metric+segment). These carry no ``model``/``column`` — they're
    resolved through the existing domain services (``labs_service``,
    ``hevy_service``, ``body_scan_service``) so their own business rules
    (marker aliasing, segment canonicalization, working-set filtering) aren't
    duplicated here.

``domain`` values double as ``vitals.services.modules_service.MODULE_REGISTRY``
keys (for gating) and as the catalog's grouping key in the builder UI — they
are NOT always the same string as ``vitals.enums.Domain`` (e.g. Hevy's module
key is ``"hevy"``, while ``Domain.WORKOUTS == "workouts"``).

genetics and supplements are excluded — both are static reference catalogs,
not time series.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal, Optional

from vitals.models.garmin import GarminActivity, GarminDaily
from vitals.models.glp1 import Injection, SideEffect
from vitals.models.nutrition import MealLog
from vitals.models.skincare import SkincareObservation
from vitals.models.weight import BodyMeasurement, WeightLog

ParamKind = Literal["none", "labs_marker", "hevy_exercise", "body_scan_metric"]
Aggregate = Literal["avg", "sum", "max", "min"]


@dataclass(frozen=True)
class MetricField:
    key: str
    domain: str
    label_ru: str
    label_en: str
    unit: Optional[str]
    param_kind: ParamKind = "none"
    module_key: Optional[str] = None
    model: Optional[type] = None
    column: Optional[str] = None
    aggregate: Aggregate = "avg"
    extra_filter: Optional[Callable] = None
    transform: Optional[Callable[[float], float]] = None


def _d(key: str, domain: str, label_ru: str, label_en: str, unit: Optional[str], **kw) -> MetricField:
    return MetricField(key, domain, label_ru, label_en, unit, **kw)


REGISTRY: dict[str, MetricField] = {
    m.key: m
    for m in (
        # ── weight (core) ────────────────────────────────────────────────────
        _d(
            "weight.weight_kg", "weight", "Вес", "Weight", "кг",
            model=WeightLog, column="weight_kg",
            extra_filter=lambda s: s.where(WeightLog.superseded.is_(False)),
        ),
        _d("weight.neck_cm", "weight", "Окружность шеи", "Neck", "см", model=BodyMeasurement, column="neck_cm"),
        _d("weight.waist_cm", "weight", "Окружность талии", "Waist", "см", model=BodyMeasurement, column="waist_cm"),
        _d("weight.hips_cm", "weight", "Окружность бёдер", "Hips", "см", model=BodyMeasurement, column="hips_cm"),
        _d("weight.body_fat_pct", "weight", "Процент жира (Navy)", "Body fat % (Navy)", "%", model=BodyMeasurement, column="body_fat_pct"),
        _d("weight.lbm_kg", "weight", "Безжировая масса (Navy)", "LBM (Navy)", "кг", model=BodyMeasurement, column="lbm_kg"),

        # ── garmin (core) ────────────────────────────────────────────────────
        _d("garmin.sleep_hours", "garmin", "Сон", "Sleep", "ч", model=GarminDaily, column="sleep_seconds", transform=lambda v: v / 3600),
        _d("garmin.sleep_score", "garmin", "Оценка сна", "Sleep score", None, model=GarminDaily, column="sleep_score"),
        _d("garmin.resting_hr", "garmin", "Пульс покоя", "Resting HR", "уд/мин", model=GarminDaily, column="resting_hr"),
        _d("garmin.avg_hr", "garmin", "Средний пульс за день", "Avg HR", "уд/мин", model=GarminDaily, column="avg_hr"),
        _d("garmin.hrv_avg", "garmin", "HRV", "HRV", "мс", model=GarminDaily, column="hrv_avg"),
        _d("garmin.avg_respiration", "garmin", "Частота дыхания", "Respiration", "вд/мин", model=GarminDaily, column="avg_respiration"),
        _d("garmin.spo2_avg", "garmin", "SpO2", "SpO2", "%", model=GarminDaily, column="spo2_avg"),
        _d("garmin.avg_stress", "garmin", "Уровень стресса", "Stress level", None, model=GarminDaily, column="avg_stress"),
        _d("garmin.max_stress", "garmin", "Макс. стресс", "Max stress", None, model=GarminDaily, column="max_stress"),
        _d("garmin.body_battery_high", "garmin", "Body Battery (макс)", "Body Battery high", None, model=GarminDaily, column="body_battery_high"),
        _d("garmin.body_battery_low", "garmin", "Body Battery (мин)", "Body Battery low", None, model=GarminDaily, column="body_battery_low"),
        _d("garmin.steps", "garmin", "Шаги", "Steps", None, model=GarminDaily, column="steps"),
        _d("garmin.floors_climbed", "garmin", "Этажи", "Floors climbed", None, model=GarminDaily, column="floors_climbed"),
        _d("garmin.active_calories", "garmin", "Активные калории", "Active calories", "ккал", model=GarminDaily, column="active_calories"),
        _d("garmin.total_calories", "garmin", "Калории (всего)", "Total calories", "ккал", model=GarminDaily, column="total_calories"),
        _d("garmin.intensity_minutes_moderate", "garmin", "Умеренная активность", "Moderate intensity", "мин", model=GarminDaily, column="intensity_minutes_moderate"),
        _d("garmin.intensity_minutes_vigorous", "garmin", "Интенсивная активность", "Vigorous intensity", "мин", model=GarminDaily, column="intensity_minutes_vigorous"),
        _d("garmin.training_readiness", "garmin", "Готовность к тренировке", "Training readiness", None, model=GarminDaily, column="training_readiness"),
        _d("garmin.vo2max", "garmin", "VO2max", "VO2max", None, model=GarminDaily, column="vo2max"),
        _d("garmin.activity_distance_m", "garmin", "Дистанция (тренировки)", "Activity distance", "м", model=GarminActivity, column="distance_m", aggregate="sum"),
        _d("garmin.activity_calories", "garmin", "Калории (тренировки)", "Activity calories", "ккал", model=GarminActivity, column="calories", aggregate="sum"),
        _d("garmin.activity_avg_hr", "garmin", "Средний пульс (тренировки)", "Activity avg HR", "уд/мин", model=GarminActivity, column="avg_hr", aggregate="avg"),
        _d("garmin.activity_duration", "garmin", "Длительность тренировок", "Activity duration", "мин", model=GarminActivity, column="duration_seconds", aggregate="sum", transform=lambda v: v / 60),

        # ── glp1 (optional) ──────────────────────────────────────────────────
        _d("glp1.dose_mg", "glp1", "Доза GLP-1", "GLP-1 dose", "мг", model=Injection, column="dose_mg", aggregate="sum", module_key="glp1"),
        _d("glp1.side_effect_severity", "glp1", "Тяжесть побочных эффектов", "Side-effect severity", None, model=SideEffect, column="severity", aggregate="max", module_key="glp1"),

        # ── nutrition (optional) ─────────────────────────────────────────────
        _d("nutrition.calories", "nutrition", "Калории", "Calories", "ккал", model=MealLog, column="calories", aggregate="sum", module_key="nutrition"),
        _d("nutrition.protein_g", "nutrition", "Белок", "Protein", "г", model=MealLog, column="protein_g", aggregate="sum", module_key="nutrition"),
        _d("nutrition.fat_g", "nutrition", "Жиры", "Fat", "г", model=MealLog, column="fat_g", aggregate="sum", module_key="nutrition"),
        _d("nutrition.carbs_g", "nutrition", "Углеводы", "Carbs", "г", model=MealLog, column="carbs_g", aggregate="sum", module_key="nutrition"),

        # ── skincare (optional) ──────────────────────────────────────────────
        _d("skincare.inflammation", "skincare", "Воспаление", "Inflammation", None, model=SkincareObservation, column="inflammation", aggregate="max", module_key="skincare"),
        _d("skincare.pih", "skincare", "Поствоспалительная гиперпигментация", "PIH", None, model=SkincareObservation, column="pih", aggregate="max", module_key="skincare"),

        # ── parametrized groups (resolved through their own domain service) ──
        _d("labs.marker", "labs", "Лабораторный маркер", "Lab marker", None, param_kind="labs_marker"),
        _d("hevy.working_weight", "hevy", "Рабочий вес (упражнение)", "Working weight (exercise)", "кг", param_kind="hevy_exercise", module_key="hevy"),
        _d("body_comp.metric", "body_comp", "Метрика BIA", "BIA metric", None, param_kind="body_scan_metric", module_key="body_comp"),
    )
}


# Domain group labels for the builder UI (ru, en). Keys match ``MetricField.domain``
# / ``modules_service.MODULE_REGISTRY`` — not always the same string as
# ``vitals.enums.Domain`` (e.g. Hevy's module key is "hevy", not "workouts").
DOMAIN_LABELS: dict[str, tuple[str, str]] = {
    "weight": ("Вес", "Weight"),
    "garmin": ("Организм", "Garmin"),
    "glp1": ("GLP-1", "GLP-1"),
    "nutrition": ("Питание", "Nutrition"),
    "skincare": ("Кожа", "Skincare"),
    "labs": ("Анализы", "Labs"),
    "hevy": ("Тренировки", "Workouts"),
    "body_comp": ("Состав тела", "Body composition"),
}


def get(key: str) -> MetricField:
    """Look up a metric by key. Raises ``KeyError`` for an unknown key — callers
    (the router / config service) turn that into a user-facing validation error."""
    return REGISTRY[key]


def metrics_for_domain(domain: str) -> list[MetricField]:
    return [m for m in REGISTRY.values() if m.domain == domain]


def all_domains() -> list[str]:
    """Distinct domains in registry order (first-seen)."""
    seen: set[str] = set()
    out: list[str] = []
    for m in REGISTRY.values():
        if m.domain not in seen:
            seen.add(m.domain)
            out.append(m.domain)
    return out
