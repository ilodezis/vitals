"""Body-composition metric registry & normalization (pure logic, no DB/I/O).

InBody and МедАсс analyzers print a known, finite vocabulary of metrics — unlike
the open-ended lab-marker space — so the registry lives in code (like
``labs_service.MARKER_ALIASES``), not a DB catalog. It maps every printed label
(Russian / English / common abbreviations) onto a canonical ``metric_key`` with a
display name (ru/en), a unit, a UI ``category``, and a ``headline`` flag.

Anything the registry doesn't recognise is still captured (``category='other'``)
via a slug of the printed label — the product never drops data.

Segmental rows (per-limb lean/fat) collapse to two keys —
``segmental_lean`` / ``segmental_fat`` — with the limb carried separately in the
``segment`` field, so history/grouping is ``(metric_key, segment)``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional

# ── UI categories ──────────────────────────────────────────────────────────────
CAT_COMPOSITION = "composition"
CAT_WATER = "water"
CAT_SEGMENTAL = "segmental"
CAT_SCORE = "score"
CAT_DERIVED = "derived"
CAT_OTHER = "other"

# Canonical limbs for segmental analysis.
SEGMENTS = ("right_arm", "left_arm", "trunk", "right_leg", "left_leg")


@dataclass(frozen=True)
class MetricDef:
    key: str
    ru: str
    en: str
    unit: Optional[str]
    category: str
    headline: bool = False


def _d(key, ru, en, unit, category, headline=False) -> MetricDef:
    return MetricDef(key, ru, en, unit, category, headline)


# Canonical registry. Order is render order within a category.
METRIC_REGISTRY: dict[str, MetricDef] = {
    m.key: m
    for m in (
        # ── Composition (mass breakdown) ─────────────────────────────────────
        _d("weight", "Вес", "Weight", "кг", CAT_COMPOSITION),
        _d("skeletal_muscle_mass", "Скелетно-мышечная масса", "Skeletal Muscle Mass", "кг", CAT_COMPOSITION, headline=True),
        _d("body_fat_mass", "Жировая масса", "Body Fat Mass", "кг", CAT_COMPOSITION),
        _d("body_fat_pct", "Процент жира", "Percent Body Fat", "%", CAT_COMPOSITION, headline=True),
        _d("lean_body_mass", "Безжировая масса", "Lean Body Mass", "кг", CAT_COMPOSITION),
        _d("fat_free_mass", "Тощая масса", "Fat Free Mass", "кг", CAT_COMPOSITION),
        _d("soft_lean_mass", "Сухая мышечная масса", "Soft Lean Mass", "кг", CAT_COMPOSITION),
        _d("protein", "Белок", "Protein", "кг", CAT_COMPOSITION),
        _d("minerals", "Минералы", "Minerals", "кг", CAT_COMPOSITION),
        _d("bone_mineral_content", "Костная масса", "Bone Mineral Content", "кг", CAT_COMPOSITION),
        _d("active_cell_mass", "Активная клеточная масса", "Active Cell Mass", "кг", CAT_COMPOSITION),
        _d("active_cell_mass_pct", "Доля активной клеточной массы", "Active Cell Mass %", "%", CAT_COMPOSITION),
        _d("visceral_fat_area", "Площадь висцерального жира", "Visceral Fat Area", "см²", CAT_COMPOSITION, headline=True),
        _d("visceral_fat_level", "Уровень висцерального жира", "Visceral Fat Level", None, CAT_COMPOSITION),
        _d("skeletal_muscle_mass_pct", "Доля скелетно-мышечной массы", "Skeletal Muscle Mass %", "%", CAT_COMPOSITION),
        _d("height", "Рост", "Height", "см", CAT_COMPOSITION),
        _d("waist_circumference", "Окружность талии", "Waist Circumference", "см", CAT_COMPOSITION),
        _d("hip_circumference", "Окружность бёдер", "Hip Circumference", "см", CAT_COMPOSITION),
        # ── Water / hydration ────────────────────────────────────────────────
        _d("total_body_water", "Общая жидкость организма", "Total Body Water", "л", CAT_WATER),
        _d("intracellular_water", "Внутриклеточная жидкость", "Intracellular Water", "л", CAT_WATER),
        _d("extracellular_water", "Внеклеточная жидкость", "Extracellular Water", "л", CAT_WATER),
        _d("ecw_tbw_ratio", "Отношение ВнеКЖ/ОВО", "ECW/TBW Ratio", None, CAT_WATER, headline=True),
        # ── Score / quality ──────────────────────────────────────────────────
        _d("phase_angle", "Фазовый угол", "Phase Angle", "", CAT_SCORE, headline=True),
        _d("inbody_score", "Балл InBody", "InBody Score", None, CAT_SCORE, headline=True),
        # ── Derived / targets ────────────────────────────────────────────────
        _d("bmi", "Индекс массы тела", "BMI", "кг/м²", CAT_DERIVED),
        _d("bmr", "Основной обмен", "Basal Metabolic Rate", "ккал", CAT_DERIVED),
        _d("bmr_per_m2", "Удельный основной обмен", "BMR per m²", "ккал/м²", CAT_DERIVED),
        _d("skeletal_muscle_index", "Индекс скелетной мускулатуры", "Skeletal Muscle Index", "кг/м²", CAT_DERIVED),
        _d("waist_hip_ratio", "Отношение талия/бёдра", "Waist-Hip Ratio", None, CAT_DERIVED),
        _d("obesity_degree", "Степень ожирения", "Obesity Degree", "%", CAT_DERIVED),
        _d("target_weight", "Целевой вес", "Target Weight", "кг", CAT_DERIVED),
        _d("weight_control", "Контроль веса", "Weight Control", "кг", CAT_DERIVED),
        _d("fat_control", "Контроль жира", "Fat Control", "кг", CAT_DERIVED),
        _d("muscle_control", "Контроль мышц", "Muscle Control", "кг", CAT_DERIVED),
        # ── Segmental (per-limb; limb in the ``segment`` field) ───────────────
        _d("segmental_lean", "Мышцы по сегментам", "Segmental Lean", "кг", CAT_SEGMENTAL),
        _d("segmental_fat", "Жир по сегментам", "Segmental Fat", "кг", CAT_SEGMENTAL),
    )
}

# Short list driving the compact summary chips (kept stable for the UI).
HEADLINE_KEYS: tuple[str, ...] = tuple(
    k for k, m in METRIC_REGISTRY.items() if m.headline
)


def _norm(text: str) -> str:
    """Lower-case, ё→е, collapse whitespace, strip trailing colon/units noise."""
    s = (text or "").strip().lower().replace("ё", "е")
    s = re.sub(r"\s+", " ", s)
    s = s.strip(" :*")
    return s


# Printed label → canonical key. Keys are ``_norm``-alised. Covers МедАсс (ru),
# InBody (en) and common abbreviations. Extend freely — unmatched labels still
# get captured as 'other'.
LABEL_ALIASES: dict[str, str] = {
    # weight
    "вес": "weight", "масса тела": "weight", "weight": "weight",
    # skeletal muscle
    "скелетно-мышечная масса": "skeletal_muscle_mass",
    "скелетная мышечная масса": "skeletal_muscle_mass",
    "смм": "skeletal_muscle_mass", "skeletal muscle mass": "skeletal_muscle_mass",
    "smm": "skeletal_muscle_mass",
    # fat
    "жировая масса": "body_fat_mass", "масса жира": "body_fat_mass",
    "body fat mass": "body_fat_mass", "bfm": "body_fat_mass",
    "процент жира": "body_fat_pct", "процент жировой массы": "body_fat_pct",
    "содержание жира": "body_fat_pct", "percent body fat": "body_fat_pct",
    "pbf": "body_fat_pct", "body fat percentage": "body_fat_pct", "% жира": "body_fat_pct",
    # МедАсс prints this as a combined "value + classification" row rather than a
    # bare "% жира" label — same metric, different phrasing on this device.
    "классификация по проценту жировой массы": "body_fat_pct",
    # МедАсс's height-normalized fat mass reading — closest canonical slot is
    # plain fat mass (kg); the normalization is a device-specific presentation,
    # not a distinct metric.
    "жировая масса (кг), нормированная по росту": "body_fat_mass",
    # lean / fat-free
    "безжировая масса": "lean_body_mass", "lean body mass": "lean_body_mass", "lbm": "lean_body_mass",
    "тощая масса": "fat_free_mass", "fat free mass": "fat_free_mass", "ffm": "fat_free_mass",
    "сухая мышечная масса": "soft_lean_mass", "soft lean mass": "soft_lean_mass", "slm": "soft_lean_mass",
    # protein / minerals / bone
    "белок": "protein", "protein": "protein",
    "минералы": "minerals", "минеральные вещества": "minerals", "minerals": "minerals", "mineral": "minerals",
    "костная масса": "bone_mineral_content", "минералы костей": "bone_mineral_content",
    "bone mineral content": "bone_mineral_content", "bmc": "bone_mineral_content",
    # cell mass
    "активная клеточная масса": "active_cell_mass", "active cell mass": "active_cell_mass", "акм": "active_cell_mass",
    "доля активной клеточной массы": "active_cell_mass_pct", "% акм": "active_cell_mass_pct",
    "доля скелетно-мышечной массы": "skeletal_muscle_mass_pct",
    # anthropometrics
    "рост": "height", "height": "height",
    "окр. талии": "waist_circumference", "окружность талии": "waist_circumference",
    "waist circumference": "waist_circumference",
    "окр. бедер": "hip_circumference", "окружность бедер": "hip_circumference",
    "hip circumference": "hip_circumference",
    "минеральная масса тела": "minerals",
    "соотношение талии/бедра": "waist_hip_ratio",
    # visceral
    "площадь висцерального жира": "visceral_fat_area", "висцеральный жир": "visceral_fat_area",
    "visceral fat area": "visceral_fat_area", "vfa": "visceral_fat_area",
    "уровень висцерального жира": "visceral_fat_level", "visceral fat level": "visceral_fat_level", "vfl": "visceral_fat_level",
    # water
    "общая жидкость организма": "total_body_water", "общая вода организма": "total_body_water",
    "общая жидкость": "total_body_water", "total body water": "total_body_water", "tbw": "total_body_water",
    "внутриклеточная жидкость": "intracellular_water", "клеточная жидкость": "intracellular_water",
    "intracellular water": "intracellular_water", "icw": "intracellular_water",
    "внеклеточная жидкость": "extracellular_water", "extracellular water": "extracellular_water", "ecw": "extracellular_water",
    "отношение внекж/ово": "ecw_tbw_ratio", "ecw/tbw": "ecw_tbw_ratio", "внекж/ово": "ecw_tbw_ratio",
    # score / quality
    "фазовый угол": "phase_angle", "phase angle": "phase_angle",
    "балл inbody": "inbody_score", "балл": "inbody_score", "inbody score": "inbody_score", "score": "inbody_score",
    # derived
    "индекс массы тела": "bmi", "имт": "bmi", "bmi": "bmi", "body mass index": "bmi",
    "основной обмен": "bmr", "базовый обмен": "bmr", "basal metabolic rate": "bmr", "bmr": "bmr",
    "удельный основной обмен": "bmr_per_m2",
    "индекс скелетной мускулатуры": "skeletal_muscle_index", "skeletal muscle index": "skeletal_muscle_index", "smi": "skeletal_muscle_index",
    "отношение талия/бедра": "waist_hip_ratio", "waist-hip ratio": "waist_hip_ratio", "whr": "waist_hip_ratio", "от/об": "waist_hip_ratio",
    "степень ожирения": "obesity_degree", "obesity degree": "obesity_degree",
    "целевой вес": "target_weight", "target weight": "target_weight",
    "контроль веса": "weight_control", "weight control": "weight_control",
    "контроль жира": "fat_control", "fat control": "fat_control",
    "контроль мышц": "muscle_control", "muscle control": "muscle_control",
}

# Printed limb label → canonical segment.
SEGMENT_ALIASES: dict[str, str] = {
    "right arm": "right_arm", "правая рука": "right_arm", "ra": "right_arm", "пр. рука": "right_arm",
    "left arm": "left_arm", "левая рука": "left_arm", "la": "left_arm", "лев. рука": "left_arm",
    "trunk": "trunk", "туловище": "trunk", "корпус": "trunk", "tr": "trunk",
    "right leg": "right_leg", "правая нога": "right_leg", "rl": "right_leg", "пр. нога": "right_leg",
    "left leg": "left_leg", "левая нога": "left_leg", "ll": "left_leg", "лев. нога": "left_leg",
}

_FAT_HINTS = ("жир", "fat")


def canonical_segment(value: Any) -> Optional[str]:
    """Map a printed/loose limb label onto one of ``SEGMENTS`` (or None)."""
    if not value:
        return None
    raw = str(value).strip().lower().replace("ё", "е")
    if raw in SEGMENTS:
        return raw
    return SEGMENT_ALIASES.get(_norm(raw))


def slugify(label: str) -> str:
    """Stable key for an unrecognised label (kept so 'other' metrics persist)."""
    s = _norm(label)
    s = re.sub(r"[^0-9a-zа-я]+", "_", s).strip("_")
    return (s or "metric")[:64]


def normalize_metric(label: str, segment: Any = None) -> tuple[str, str, Optional[str]]:
    """Resolve a printed label (+ optional segment) to ``(metric_key, category,
    segment)``.

    Segmental rows collapse to ``segmental_lean`` / ``segmental_fat`` with the
    limb returned separately. Unknown whole-body labels are slugged with
    ``category='other'`` so they're still captured."""
    seg = canonical_segment(segment)
    norm = _norm(label)
    if seg is not None:
        is_fat = any(h in norm for h in _FAT_HINTS)
        key = "segmental_fat" if is_fat else "segmental_lean"
        return key, CAT_SEGMENTAL, seg

    key = LABEL_ALIASES.get(norm)
    if key is None:
        # Some devices (e.g. МедАсс) print the unit inline as one or more
        # trailing "(кг)"/"(%)"/"(BMI)" annotations instead of a separate unit
        # field — strip trailing parenthetical groups one at a time and retry
        # before giving up.
        stripped = norm
        while key is None:
            next_stripped = re.sub(r"\s*\([^()]*\)\s*$", "", stripped).strip()
            if next_stripped == stripped:
                break
            stripped = next_stripped
            key = LABEL_ALIASES.get(stripped)
    if key is not None:
        return key, METRIC_REGISTRY[key].category, None
    return slugify(label), CAT_OTHER, None


def display_name(metric_key: str, lang: str = "ru") -> Optional[str]:
    """Localised display name for a canonical key, or None for 'other' keys."""
    spec = METRIC_REGISTRY.get(metric_key)
    if spec is None:
        return None
    return spec.ru if lang == "ru" else spec.en


# ── Headline extraction (for the weight-chart bridge & summary chips) ──────────
def _value_of(metrics: Iterable[Any], key: str, *, segment: Optional[str] = None) -> Optional[float]:
    """First numeric value for ``metric_key`` (optionally a specific segment).

    Accepts either dicts (``{"metric_key":..,"value":..,"segment":..}``) or ORM
    rows (``.metric_key`` / ``.value`` / ``.segment``)."""
    for m in metrics:
        mk = m.get("metric_key") if isinstance(m, dict) else getattr(m, "metric_key", None)
        if mk != key:
            continue
        if segment is not None:
            sg = m.get("segment") if isinstance(m, dict) else getattr(m, "segment", None)
            if sg != segment:
                continue
        val = m.get("value") if isinstance(m, dict) else getattr(m, "value", None)
        try:
            return float(val) if val is not None else None
        except (TypeError, ValueError):
            return None
    return None


def body_fat_pct_from_scan(metrics: Iterable[Any]) -> Optional[float]:
    """The scan's measured body-fat %, if present."""
    metrics = list(metrics)
    return _value_of(metrics, "body_fat_pct")


def lbm_from_scan(metrics: Iterable[Any], weight_kg: Optional[float] = None) -> Optional[float]:
    """Lean body mass from the scan: prefer an explicit lean/fat-free metric, else
    derive from weight and body-fat %. ``weight_kg`` falls back to the scan's own
    weight metric. Returns None when nothing is available."""
    metrics = list(metrics)
    explicit = _value_of(metrics, "lean_body_mass")
    if explicit is None:
        explicit = _value_of(metrics, "fat_free_mass")
    if explicit is not None:
        return round(explicit, 2)

    w = weight_kg if weight_kg is not None else _value_of(metrics, "weight")
    bf = _value_of(metrics, "body_fat_pct")
    if w is not None and bf is not None:
        return round(w * (1.0 - bf / 100.0), 2)
    return None


def weight_from_scan(metrics: Iterable[Any]) -> Optional[float]:
    """The scan's own weight reading (bridged into the weight domain)."""
    return _value_of(list(metrics), "weight")
