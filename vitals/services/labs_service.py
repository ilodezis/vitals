"""Lab results & parser service (module 7).

Owns the labs domain:

  * **Manual entry & CRUD** — add a marker value with its reference range; the
    out-of-range ``flag`` is computed (pure :func:`compute_flag`).
  * **Marker catalog** — a row per marker is auto-created on first sight, holding
    the importance ``tier``, an optional retest interval, and the ``defer_until``
    used by "Defer Retest".
  * **History** — per-marker series for the charts.
  * **Alerts** — the latest value per marker drives an out-of-range alert
    (``info`` for a deferrable tier-2 low/high, ``warn`` for a tier-1 or critical
    value); overdue retests raise a passive ``info`` (suppressed while deferred).
  * **LLM extraction** — a PDF/image upload is turned into structured results by
    an OpenRouter vision model (the document is also kept raw). The LLM client is
    injected so the parser is unit-tested without network or a key.

Extraction is *optional* — every result can be entered manually, so the module
works with no LLM configured. :func:`add_result` runs the value through the
conflict engine's ``lab_safety`` rules, so logging a high potassium result while
a potassium supplement is active surfaces immediately. It uses the same
``enforce()``/override flow as every other write path rather than a quieter
read-only check: a hard rule stops the save and hands back the violation, and the
caller decides — the web form and the MCP tools both offer "save anyway".
"""
from __future__ import annotations

import logging
import math
from datetime import date as date_type, timedelta
from typing import Any, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import Domain, LabFlag, Severity, Source
from vitals.i18n import decimal, t
from vitals.integrations.vision import file_to_image_urls_async
from vitals.models.labs import DOMAIN, LabMarker, LabResult
from vitals.models.raw_payload import RawPayload
from vitals.services import alerts_service, conflict_engine, raw_payload_service
from vitals.utils.timeutils import now_local, today_local

logger = logging.getLogger(__name__)

OUT_OF_RANGE_KEY = "labs.out_of_range"
RETEST_DUE_KEY = "labs.retest_due"

# Sanity ceiling for a written value. The write path is reachable over MCP (an
# LLM) and from vision extraction, neither of which goes through the HTML form,
# so nonsense has to be stopped here. Real markers span many orders of magnitude
# (ng/ml up to cells per µl) and some are legitimately negative (blood-gas base
# excess), so this only catches the absurd — it is not a per-marker range.
_VALUE_ABS_MAX = 1_000_000.0

# "Critical" thresholds. For a two-sided range, a value more than this fraction of
# the range's *width* beyond a bound is critical (scales sensibly with the range).
# For a one-sided range (only one bound known) we fall back to a relative margin
# off that bound.
CRITICAL_WIDTH_FACTOR = 0.5
CRITICAL_MARGIN = 0.30


# ── Pure flag logic ───────────────────────────────────────────────────────────
def compute_flag(
    value: float,
    ref_low: Optional[float],
    ref_high: Optional[float],
    *,
    width_factor: float = CRITICAL_WIDTH_FACTOR,
    critical_margin: float = CRITICAL_MARGIN,
) -> Optional[str]:
    """Classify ``value`` against its reference range. Returns a ``LabFlag`` value,
    or ``None`` when no range is known. Either bound may be absent (one-sided
    ranges like "LDL < 3.0"). "Critical" scales with the range width for a
    two-sided range, else with a relative margin off the known bound."""
    if ref_low is None and ref_high is None:
        return None
    width = (ref_high - ref_low) if (ref_low is not None and ref_high is not None) else None

    if ref_low is not None and value < ref_low:
        critical = (
            value < ref_low - width_factor * width
            if width is not None
            else value <= ref_low * (1 - critical_margin)
        )
        return LabFlag.CRITICAL_LOW.value if critical else LabFlag.LOW.value

    if ref_high is not None and value > ref_high:
        critical = (
            value > ref_high + width_factor * width
            if width is not None
            else value >= ref_high * (1 + critical_margin)
        )
        return LabFlag.CRITICAL_HIGH.value if critical else LabFlag.HIGH.value

    return LabFlag.NORMAL.value


# ── Units ─────────────────────────────────────────────────────────────────────
# Spellings of one unit that labs print differently. Anything not listed is
# compared by its folded spelling (case, spaces, ё), so "мМоль/л" == "ммоль/л".
_UNIT_CLASSES = {
    "%": "%",
    "10^9/л": "10^9/l", "10^9/l": "10^9/l", "тыс/мкл": "10^9/l", "10^3/мкл": "10^9/l",
    "10^12/л": "10^12/l", "10^12/l": "10^12/l", "млн/мкл": "10^12/l", "10^6/мкл": "10^12/l",
    "кл/мкл": "/мкл", "клеток/мкл": "/мкл", "количество/мкл": "/мкл", "ед/мкл": "/мкл", "/мкл": "/мкл",
    "ммоль/л": "mmol/l", "mmol/l": "mmol/l", "мэкв/л": "mmol/l", "meq/l": "mmol/l",
    "нмоль/л": "nmol/l", "nmol/l": "nmol/l",
    "пмоль/л": "pmol/l", "pmol/l": "pmol/l",
    "мг/дл": "mg/dl", "mg/dl": "mg/dl",
    "мкг/дл": "ug/dl", "ug/dl": "ug/dl", "µg/dl": "ug/dl",
    "пг/мл": "pg/ml", "pg/ml": "pg/ml",
    "мкмоль/л": "umol/l", "umol/l": "umol/l",
    "г/л": "g/l", "g/l": "g/l",
    "г/дл": "g/dl", "g/dl": "g/dl",
    "мме/л": "miu/l", "мкме/мл": "miu/l", "мкед/мл": "miu/l", "мед/л": "miu/l",
    "miu/l": "miu/l", "uiu/ml": "miu/l",
    "ед/л": "u/l", "u/l": "u/l", "ме/л": "u/l",
    "нг/мл": "ng/ml", "ng/ml": "ng/ml", "мкг/л": "ng/ml",
    "фл": "fl", "fl": "fl",
    "пг": "pg", "pg": "pg",
}


def unit_class(unit: Optional[str]) -> Optional[str]:
    """A canonical key for comparing units: two results whose units share a
    class are on the same scale. ``None`` when no unit was given."""
    if unit is None:
        return None
    folded = unit.strip().lower().replace("ё", "е").replace(" ", "")
    if not folded:
        return None
    folded = folded.replace("*", "^").replace("×", "").replace("х10", "10").replace("x10", "10")
    return _UNIT_CLASSES.get(folded, folded)


def units_compatible(a: Optional[str], b: Optional[str]) -> bool:
    """True unless both units are known and on different scales."""
    ca, cb = unit_class(a), unit_class(b)
    return ca is None or cb is None or ca == cb


# Leukocyte differential counts. Labs print each both as a share of leukocytes
# (%) and as an absolute count; the two are different markers ("Лимфоциты %" and
# "Лимфоциты") and must never share a series or a reference range.
_DIFFERENTIAL = ("Нейтрофилы", "Лимфоциты", "Моноциты", "Эозинофилы", "Базофилы")


async def marker_for_unit(session: AsyncSession, marker: str, unit: Optional[str]) -> str:
    """The catalog marker a new result belongs to, given the unit it came in.

    A differential count goes to its ``%`` or absolute marker by unit. Any other
    marker whose catalog unit is on a different scale (urine sediment cells per
    µl under the blood "Эритроциты", g/dl next to g/l) gets a unit-qualified
    marker of its own, "Эритроциты (кл/мкл)", reused by every later result on
    that scale. Without a unit nothing can be told apart and the name stands."""
    name = normalize_marker(marker)
    if unit_class(unit) is None:
        return name
    base = name[:-2].rstrip() if name.endswith(" %") else name
    if base in _DIFFERENTIAL:
        return f"{base} %" if unit_class(unit) == "%" else base

    catalog = await get_marker(session, name)
    if catalog is None or units_compatible(catalog.unit, unit) or _convertible(name, catalog.unit, unit):
        return name
    result = await session.execute(
        select(LabMarker).where(LabMarker.name.startswith(f"{name} (")).order_by(LabMarker.id)
    )
    for variant in result.scalars().all():
        if units_compatible(variant.unit, unit):
            return variant.name
    return f"{name} ({unit.strip()})"


# ── Values as conflict rules read them ───────────────────────────────────────
# A rule's threshold is a bare number written in one unit ("Кортизол < 140" is
# nmol/l). A lab that prints µg/dl (10 µg/dl ≈ 276 nmol/l, a normal morning
# cortisol) must be converted before the comparison, or the rule fires on
# every normal result. Per marker: the unit the catalog's rules use and the
# factor from each other unit labs print.
_RULE_SCALE: dict[str, tuple[str, dict[str, float]]] = {
    "Кортизол": ("nmol/l", {"ug/dl": 27.59}),
    "Глюкоза": ("mmol/l", {"mg/dl": 0.0555}),
    "Креатинин": ("umol/l", {"mg/dl": 88.4}),
    "Гемоглобин": ("g/l", {"g/dl": 10.0}),
    "25-ОН витамин D": ("ng/ml", {"nmol/l": 0.4006}),
    "Витамин B12": ("pg/ml", {"pmol/l": 1.355}),
    "Холестерин-ЛПНП": ("mmol/l", {"mg/dl": 0.02586}),
    "Кальций общий": ("mmol/l", {"mg/dl": 0.2495}),
    "Магний": ("mmol/l", {"mg/dl": 0.4114}),
}


def _convertible(marker: str, a: Optional[str], b: Optional[str]) -> bool:
    """True when both units are scales :data:`_RULE_SCALE` converts between for
    ``marker`` — the same quantity in another unit (cortisol in µg/dl and nmol/l),
    which stays one marker."""
    scale = _RULE_SCALE.get(marker)
    if scale is None:
        return False
    known = {scale[0], *scale[1]}
    return unit_class(a) in known and unit_class(b) in known


def rule_value(marker: str, value: float, unit: Optional[str]) -> Optional[float]:
    """``value`` in the unit conflict rules for ``marker`` are written in, or
    ``None`` when its unit is known but cannot be converted — a threshold must
    never be compared across scales. Markers without a declared scale, and
    results without a unit, are passed through as they are."""
    scale = _RULE_SCALE.get(marker)
    cls = unit_class(unit)
    if scale is None or cls is None:
        return value
    canonical, factors = scale
    if cls == canonical:
        return value
    factor = factors.get(cls)
    return round(value * factor, 4) if factor is not None else None


# ── Plausibility ──────────────────────────────────────────────────────────────
# Bounds no living adult falls outside of, per marker and unit class — far wider
# than any reference range, so a real critical value is never caught here. A
# value beyond them is a misread document (a percentage read as a count, g/l
# read as g/dl), not a measurement.
_PLAUSIBLE: dict[tuple[str, str], tuple[float, float]] = {
    ("Эритроциты", "10^12/l"): (0.5, 10.0),
    ("Гемоглобин", "g/l"): (20.0, 260.0),
    ("Гемоглобин", "g/dl"): (2.0, 26.0),
    ("Гематокрит", "%"): (5.0, 80.0),
    ("Лейкоциты", "10^9/l"): (0.05, 1000.0),
    ("Тромбоциты", "10^9/l"): (1.0, 5000.0),
    ("Средний объем эритроцитов", "fl"): (40.0, 160.0),
    ("Среднее содержание гемоглобина в эритроците", "pg"): (10.0, 60.0),
    ("Средняя концентрация гемоглобина в эритроците", "g/l"): (150.0, 500.0),
    ("Средняя концентрация гемоглобина в эритроците", "g/dl"): (15.0, 50.0),
    ("Нейтрофилы", "10^9/l"): (0.0, 200.0),
    ("Лимфоциты", "10^9/l"): (0.0, 500.0),
    ("Моноциты", "10^9/l"): (0.0, 50.0),
    ("Эозинофилы", "10^9/l"): (0.0, 50.0),
    ("Базофилы", "10^9/l"): (0.0, 20.0),
    ("Калий", "mmol/l"): (1.0, 12.0),
    ("Натрий", "mmol/l"): (90.0, 200.0),
    ("Кальций общий", "mmol/l"): (0.8, 5.0),
    ("Гликированный гемоглобин (HbA1c)", "%"): (2.0, 25.0),
}


def is_implausible(marker: str, value: float, unit: Optional[str]) -> bool:
    """True when ``value`` cannot be a real measurement of ``marker`` in ``unit``:
    a percentage outside 0–100, or a value beyond the physiological bounds of
    :data:`_PLAUSIBLE`. Markers without bounds are never judged."""
    cls = unit_class(unit)
    if cls == "%" and not 0 <= value <= 100:
        return True
    bounds = _PLAUSIBLE.get((marker, cls)) if cls else None
    return bounds is not None and not bounds[0] <= value <= bounds[1]


def lab_flag(
    marker: str,
    value: float,
    unit: Optional[str],
    ref_low: Optional[float],
    ref_high: Optional[float],
) -> Optional[str]:
    """:func:`compute_flag`, except that an implausible value is ``suspect``
    whatever its range says."""
    if is_implausible(marker, value, unit):
        return LabFlag.SUSPECT.value
    return compute_flag(value, ref_low, ref_high)


def effective_range(
    row: LabResult, catalog: Optional[LabMarker]
) -> tuple[Optional[float], Optional[float]]:
    """The reference range a stored result is judged against: its own (the
    lab's, printed next to it), else the catalog's when the units agree."""
    if row.ref_low is not None or row.ref_high is not None:
        return row.ref_low, row.ref_high
    if catalog is not None and units_compatible(catalog.unit, row.unit):
        return catalog.ref_low, catalog.ref_high
    return None, None


def effective_flag(row: LabResult, catalog: Optional[LabMarker]) -> Optional[str]:
    """The flag of a stored result as it reads now. The stored ``flag`` was
    computed at write time and goes stale: a result saved before its marker had
    a range has none, and a misread value saved before the plausibility check
    reads as normal. Every read that hands flags out goes through this. With no
    range known at all the stored flag is kept — there is nothing to judge by."""
    low, high = effective_range(row, catalog)
    if low is None and high is None and not is_implausible(row.marker, row.value, row.unit):
        return row.flag
    return lab_flag(row.marker, row.value, row.unit, low, high)


def is_out_of_range(flag: Optional[str]) -> bool:
    return flag in (
        LabFlag.LOW.value,
        LabFlag.HIGH.value,
        LabFlag.CRITICAL_LOW.value,
        LabFlag.CRITICAL_HIGH.value,
    )


def _is_critical(flag: Optional[str]) -> bool:
    return flag in (LabFlag.CRITICAL_LOW.value, LabFlag.CRITICAL_HIGH.value)


# ── Marker name normalization ──────────────────────────────────────────────────
MARKER_ALIASES = {
    "определение иммунореактивного инсулина": "Инсулин",
    "определение тиреотропина, тиротропина, тиреоидного гормона (ттг)": "ТТГ",
    "тиреотропный гормон (ттг)": "ТТГ",
    "определение свободного тироксина (т4)": "Т4 свободный",
    "исследование антител к тиреоглобулину (ат-тг)": "АТ-ТГ",
    "исследование антител к тиреоидной пероксидазе (ат-тпо)": "АТ-ТПО",
    "определение холестерина общего": "Холестерин общий",
    "холестерин": "Холестерин общий",
    "определение триглицеридов общих": "Триглицериды",
    "определение липопротеинов высокой плотности (лпвп-альфа)": "Холестерин-ЛПВП",
    "холестерин липопротеидов низкой плотности (лпнп, ldl)": "Холестерин-ЛПНП",
    "холестерин-лпнп": "Холестерин-ЛПНП",
    "определение липопротеинов низкой плотности (лпнп-бета)": "Холестерин-ЛПНП",
    "холестерин-лпонп": "Холестерин-ЛПОНП",
    "определение липопротеинов очень низкой плотности (лпонп), пребета-лп": "Холестерин-ЛПОНП",
    "определение аланинаминотрансферазы (алт)": "АЛТ",
    "аланинаминотрансфераза (алт)": "АЛТ",
    "определение аспартатаминотрансферазы (аст)": "АСТ",
    "аспартатаминотрансфераза (аст)": "АСТ",
    "определение глюкозы": "Глюкоза",
    "глюкоза плазмы": "Глюкоза",
    "глюкоза полуколичественно": "Глюкоза",
    "определение гемоглобина a1c (гликированный гемоглобин)": "Гликированный гемоглобин (HbA1c)",
    "hba1c (гликированный гемоглобин)": "Гликированный гемоглобин (HbA1c)",
    "гемоглобин общий": "Гемоглобин",
    "количество эритроцитов": "Эритроциты",
    "средний объем эритроцита": "Средний объем эритроцитов",
    "средний объем эритроцитов (mcv)": "Средний объем эритроцитов",
    "среднее содержание hb в эритроците": "Среднее содержание гемоглобина в эритроците",
    "среднее содержание гемоглобина в эритроците": "Среднее содержание гемоглобина в эритроците",
    "среднее содержание гемоглобина в эритроците (mch)": "Среднее содержание гемоглобина в эритроците",
    "средняя концентрация гемоглобина в эритроците": "Средняя концентрация гемоглобина в эритроците",
    "средняя концентрация hb в эритроците (mchc)": "Средняя концентрация гемоглобина в эритроците",
    "ширина распределения эритроцитов по объему": "Гетерогенность эритроцитов по объему",
    "гетерогенность эритроцитов по объёму": "Гетерогенность эритроцитов по объему",
    "количество тромбоцитов": "Тромбоциты",
    "средний объем тромбоцитов в крови": "Средний объем тромбоцитов",
    "средний объем тромбоцитов (mpv)": "Средний объем тромбоцитов",
    "ширина распределения тромбоцитов по объему": "Гетерогенность тромбоцитов по объему",
    "гетерогенность тромбоцитов по объёму": "Гетерогенность тромбоцитов по объему",
    "отн.ширина распред.тромбоцитов по объему (pdw)": "Гетерогенность тромбоцитов по объему",
    "общий объем тромбоцитов в крови (тромбокрит, pct)": "Тромбокрит",
    "тромбокрит (pct)": "Тромбокрит",
    "количество лейкоцитов": "Лейкоциты",
    "абсолютное количество нейтрофилов": "Нейтрофилы",
    "нейтрофилы сегментоядерные": "Нейтрофилы",
    "нейтрофилы (общее число), %": "Нейтрофилы %",
    "абсолютное количество эозинофилов": "Эозинофилы",
    "эозинофилы %": "Эозинофилы %",
    "абсолютное количество базофилов": "Базофилы",
    "базофилы %": "Базофилы %",
    "абсолютное количество моноцитов": "Моноциты",
    "моноциты %": "Моноциты %",
    "абсолютное количество лимфоцитов": "Лимфоциты",
    "лимфоциты (общее число), %": "Лимфоциты %",
    "лимфоциты %": "Лимфоциты %",
    "скорость оседания эритроцитов (по вестергрену)": "СОЭ",
    "определение кальция общего": "Кальций общий",
    "определение альбумина": "Альбумин",
    "определение кортизола": "Кортизол",
    "исследование пролактина (прл)": "Пролактин",
    "25-он витамин d, ихла, суммарный (кальциферол)": "25-ОН витамин D",
}

def normalize_marker(name: str) -> str:
    """Standardize spelling, casing and known synonym names of a marker."""
    cleaned = name.strip()
    if not cleaned:
        return ""
    # Normalize ё -> е for spelling consistency
    lowered = cleaned.lower().replace("ё", "е")
    if lowered in MARKER_ALIASES:
        return MARKER_ALIASES[lowered]
    # Fallback: capitalize first character, keep the rest
    return cleaned[0].upper() + cleaned[1:]


# ── Marker catalog ────────────────────────────────────────────────────────────
async def get_marker(session: AsyncSession, name: str) -> Optional[LabMarker]:
    name = normalize_marker(name)
    result = await session.execute(select(LabMarker).where(LabMarker.name == name))
    return result.scalars().first()


async def _ensure_marker(
    session: AsyncSession,
    name: str,
    *,
    unit: Optional[str] = None,
    ref_low: Optional[float] = None,
    ref_high: Optional[float] = None,
) -> LabMarker:
    """Auto-create a catalog row on first sight; backfill null defaults but never
    clobber a tier/defer the user has set."""
    name = normalize_marker(name)
    marker = await get_marker(session, name)
    if marker is None:
        marker = LabMarker(
            domain=DOMAIN, name=name, unit=unit, ref_low=ref_low, ref_high=ref_high
        )
        session.add(marker)
        await session.flush()
        return marker
    if marker.unit is None and unit is not None:
        marker.unit = unit
    if marker.ref_low is None and ref_low is not None:
        marker.ref_low = ref_low
    if marker.ref_high is None and ref_high is not None:
        marker.ref_high = ref_high
    await session.flush()
    return marker


async def list_markers(session: AsyncSession) -> Sequence[LabMarker]:
    result = await session.execute(select(LabMarker).order_by(LabMarker.name))
    return result.scalars().all()


async def defer_retest(
    session: AsyncSession, marker: str, *, until: date_type, note: Optional[str] = None
) -> Optional[LabMarker]:
    """Pause the overdue-retest alert for a marker until ``until``."""
    marker = normalize_marker(marker)
    row = await get_marker(session, marker)
    if row is None:
        return None
    row.defer_until = until
    if note is not None:
        row.note = note
    await session.flush()
    await alerts_service.resolve_by_key(
        session, alert_key=RETEST_DUE_KEY, entity_ref=marker
    )
    return row


# ── Results ───────────────────────────────────────────────────────────────────
async def add_result(
    session: AsyncSession,
    *,
    on_date: date_type,
    marker: str,
    value: float,
    unit: Optional[str] = None,
    ref_low: Optional[float] = None,
    ref_high: Optional[float] = None,
    lab_name: Optional[str] = None,
    note: Optional[str] = None,
    source: str = Source.MANUAL.value,
    raw_payload_id: Optional[int] = None,
    override: bool = False,
) -> LabResult:
    """Record a marker value, computing its flag and ensuring its catalog row.

    The result is filed under the marker its unit belongs to (see
    :func:`marker_for_unit`), so a percentage and an absolute count, or a urine
    and a blood count, never share a series. If the result carries no range,
    fall back to the catalog's default range so a flag can still be computed; a
    value no person can have is flagged ``suspect`` (see :func:`lab_flag`).
    Raises ``ValueError`` on a nameless marker or an absurd value, and
    :class:`ConflictBlocked` when a hard cross-domain rule fires without
    ``override``."""
    marker = normalize_marker(marker)
    if not marker:
        raise ValueError("marker is required")
    if value is None or not math.isfinite(value) or abs(value) > _VALUE_ABS_MAX:
        raise ValueError(f"implausible lab value for {marker}: {value!r}")
    marker = await marker_for_unit(session, marker, unit)
    catalog = await _ensure_marker(
        session, marker, unit=unit, ref_low=ref_low, ref_high=ref_high
    )
    if ref_low is None and ref_high is None and units_compatible(catalog.unit, unit):
        eff_low, eff_high = catalog.ref_low, catalog.ref_high
    else:
        eff_low, eff_high = ref_low, ref_high
    flag = lab_flag(marker, value, unit or catalog.unit, eff_low, eff_high)

    # The same gate every other write path runs, before the row exists: a hard
    # rule (an active potassium supplement meeting a hyperkalemic potassium
    # result) stops the save unless the caller overrides, and soft rules keep
    # doing what they did — an alert, never a block. A suspect value is a misread
    # document, not a measurement, so it trips nothing.
    if flag != LabFlag.SUSPECT.value:
        await conflict_engine.enforce(
            session,
            Domain.LABS.value,
            {
                "marker": marker,
                "value": rule_value(marker, value, unit or catalog.unit),
                "flag": flag,
            },
            override=override,
            entity_ref=f"labs:{marker}",
        )

    row = LabResult(
        date=on_date,
        domain=DOMAIN,
        source=source,
        marker=marker,
        value=value,
        unit=unit or catalog.unit,
        ref_low=eff_low,
        ref_high=eff_high,
        flag=flag,
        lab_name=lab_name,
        note=note,
        raw_payload_id=raw_payload_id,
    )
    session.add(row)
    await session.flush()
    # A new latest value can also end a conflict (cortisol back in range).
    await conflict_engine.reconcile(session, Domain.LABS.value)
    return row


async def update_result(
    session: AsyncSession,
    result_id: int,
    *,
    on_date: Optional[date_type] = None,
    marker: Optional[str] = None,
    value: Optional[float] = None,
    unit: Optional[str] = None,
    ref_low: Optional[float] = None,
    ref_high: Optional[float] = None,
    lab_name: Optional[str] = None,
    note: Optional[str] = None,
) -> Optional[LabResult]:
    """Correct an existing result — a mistyped value or a range read off the wrong
    column. Only the fields passed are changed; ``flag`` is recomputed from the
    resulting value + range, and the alerts derived from it are refreshed.

    Without this, fixing a typo meant deleting the row and re-adding it, which is
    the one thing this project promises never to do to a measurement."""
    row = await session.get(LabResult, result_id)
    if row is None:
        return None

    if marker is not None:
        normalized = normalize_marker(marker)
        if not normalized:
            raise ValueError("marker is required")
        row.marker = normalized
    if value is not None:
        if not math.isfinite(value) or abs(value) > _VALUE_ABS_MAX:
            raise ValueError(f"implausible lab value for {row.marker}: {value!r}")
        row.value = value
    if on_date is not None:
        row.date = on_date
    if unit is not None:
        row.unit = unit
    if ref_low is not None:
        row.ref_low = ref_low
    if ref_high is not None:
        row.ref_high = ref_high
    if lab_name is not None:
        row.lab_name = lab_name
    if note is not None:
        row.note = note

    catalog = await _ensure_marker(
        session, row.marker, unit=row.unit, ref_low=row.ref_low, ref_high=row.ref_high
    )
    if row.ref_low is None:
        row.ref_low = catalog.ref_low
    if row.ref_high is None:
        row.ref_high = catalog.ref_high
    row.flag = lab_flag(row.marker, row.value, row.unit, row.ref_low, row.ref_high)

    await session.flush()
    await refresh_alerts(session)
    await conflict_engine.reconcile(session, Domain.LABS.value)
    return row


async def list_results(
    session: AsyncSession,
    *,
    marker: Optional[str] = None,
    end: Optional[date_type] = None,
    limit: int = 200,
) -> Sequence[LabResult]:
    """Newest first. ``end`` anchors the read at a date instead of at "now", so a
    report about a past window is not filled by results drawn after it."""
    stmt = select(LabResult)
    if marker is not None:
        marker = normalize_marker(marker)
        stmt = stmt.where(LabResult.marker == marker)
    if end is not None:
        stmt = stmt.where(LabResult.date <= end)
    stmt = stmt.order_by(LabResult.date.desc(), LabResult.id.desc()).limit(limit)
    result = await session.execute(stmt)
    return result.scalars().all()


async def marker_history(session: AsyncSession, marker: str) -> list[dict]:
    """Chronological series for one marker (the per-marker chart), with flags
    and ranges as they read now (see :func:`effective_flag`)."""
    marker = normalize_marker(marker)
    result = await session.execute(
        select(LabResult).where(LabResult.marker == marker).order_by(LabResult.date)
    )
    catalog = await get_marker(session, marker)
    out = []
    for r in result.scalars().all():
        ref_low, ref_high = effective_range(r, catalog)
        out.append({
            "date": r.date.isoformat(),
            "value": r.value,
            "flag": effective_flag(r, catalog),
            "ref_low": ref_low,
            "ref_high": ref_high,
        })
    return out


async def latest_per_marker(session: AsyncSession) -> list[LabResult]:
    """The most recent result for each marker (table + alert source)."""
    result = await session.execute(
        select(LabResult).order_by(LabResult.date.desc(), LabResult.id.desc())
    )
    seen: dict[str, LabResult] = {}
    for r in result.scalars().all():
        seen.setdefault(r.marker, r)
    return list(seen.values())


async def resolve_latest(session: AsyncSession) -> list[dict]:
    """Conflict-engine resolver: the latest value+flag per marker as match items
    — lets a lab_safety rule reference e.g. {"marker": "Калий", "value": {"$gt":
    5.0}} against the current panel, not just a freshly logged result. Values are
    in the unit the rules use (see :func:`rule_value`)."""
    latest = await latest_per_marker(session)
    catalog = {m.name: m for m in await list_markers(session)}
    items = []
    for r in latest:
        flag = effective_flag(r, catalog.get(r.marker))
        if flag == LabFlag.SUSPECT.value:
            continue  # a misread value must not trip a safety rule
        items.append({
            "marker": r.marker, "value": rule_value(r.marker, r.value, r.unit), "flag": flag,
        })
    return items


async def delete_result(session: AsyncSession, result_id: int) -> bool:
    row = await session.get(LabResult, result_id)
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    await conflict_engine.reconcile(session, Domain.LABS.value)
    return True


# ── Alerts ────────────────────────────────────────────────────────────────────
async def refresh_alerts(
    session: AsyncSession,
    *,
    on_date: Optional[date_type] = None,
    latest: Optional[list[LabResult]] = None,
    markers: Optional[dict[str, LabMarker]] = None,
) -> None:
    """Raise/clear out-of-range + overdue-retest alerts from the latest values.
    Idempotent — safe on every dashboard load / scheduler tick. Each alert is
    bound to the specific LabResult row that triggered it (``entity_ref =
    f"{marker}:{result_id}"``), so a dismissal sticks forever for that row —
    only a new result for the marker can raise it again. ``latest``/``markers``
    are what the caller already read (see :func:`collect`)."""
    today = on_date or today_local()
    if latest is None:
        latest = await latest_per_marker(session)
    if markers is None:
        markers = {m.name: m for m in await list_markers(session)}
    # Two reads for the whole pass instead of a handful per marker.
    book = await alerts_service.AlertBook.load(session, [OUT_OF_RANGE_KEY, RETEST_DUE_KEY])

    for r in latest:
        key = OUT_OF_RANGE_KEY
        entity = f"{r.marker}:{r.id}"
        flag = effective_flag(r, markers.get(r.marker))
        await book.resolve_superseded(alert_key=key, marker=r.marker, keep_entity=entity)
        if is_out_of_range(flag):
            if book.was_ever_dismissed(key, entity):
                continue
            tier = markers.get(r.marker).tier if markers.get(r.marker) else 2
            critical = _is_critical(flag) or tier == 1
            severity = Severity.WARN.value if critical else Severity.INFO.value
            await book.raise_alert(
                domain=Domain.LABS.value,
                severity=severity,
                message=t(
                    "alert.lab_out_of_range",
                    marker=r.marker,
                    value=decimal(f"{r.value:g}"),
                    unit=(' ' + r.unit) if r.unit else '',
                    # Localized flag label ("crit. high"), not the raw enum value.
                    flag=t(f"enum.flag.{flag}"),
                ),
                alert_key=key,
                entity_ref=entity,
            )
        else:
            await book.resolve_by_key(alert_key=key, entity_ref=entity)

        # Overdue retest (respecting a deferral) — bound to the same result row.
        marker_row = markers.get(r.marker)
        if marker_row and marker_row.retest_interval_days:
            due = r.date + timedelta(days=marker_row.retest_interval_days)
            deferred = marker_row.defer_until is not None and marker_row.defer_until >= today
            await book.resolve_superseded(
                alert_key=RETEST_DUE_KEY, marker=r.marker, keep_entity=entity
            )
            if today > due and not deferred:
                if book.was_ever_dismissed(RETEST_DUE_KEY, entity):
                    continue
                await book.raise_alert(
                    domain=Domain.LABS.value,
                    severity=Severity.INFO.value,
                    message=t("alert.lab_retest", marker=r.marker, date=r.date),
                    alert_key=RETEST_DUE_KEY,
                    entity_ref=entity,
                )
            else:
                await book.resolve_by_key(
                    alert_key=RETEST_DUE_KEY, entity_ref=entity
                )


# ── LLM extraction (optional auto-fill) ───────────────────────────────────────
_EXTRACT_SYSTEM = (
    "You are a medical lab-report parser. Extract every marker from the provided "
    "lab document image. Respond ONLY with JSON of the form: "
    '{"date": "YYYY-MM-DD", "lab_name": string|null, "results": '
    '[{"marker": string, "value": number, "unit": string|null, '
    '"ref_low": number|null, "ref_high": number|null}]}. '
    "Use the collection date. Numbers must be plain (no ranges in value). "
    "If a field is unknown use null."
)


async def extract_from_file(
    file_bytes: bytes,
    *,
    llm: Any,
    content_type: str = "image/jpeg",
    filename: Optional[str] = None,
) -> dict:
    """Send the document to a vision model and return the parsed structured dict.
    PDFs are rendered to images first (all pages up to a limit, off the event
    loop). Raises whatever the LLM client raises (e.g. ``LLMNotConfigured``) so
    the router can surface a clear message."""
    image_urls = await file_to_image_urls_async(
        file_bytes, content_type=content_type, filename=filename
    )
    return await llm.extract_json(
        "Extract all lab markers from this report.",
        system=_EXTRACT_SYSTEM,
        image_urls=image_urls,
    )


def normalize_extracted(extracted: dict) -> list[dict]:
    """Pure: turn a raw vision dict into normalized, editable marker rows for the
    upload preview. Each row is ``{marker, value, unit, ref_low, ref_high}``.
    Unparseable rows (no marker / non-numeric value) are dropped."""
    rows: list[dict] = []
    for item in extracted.get("results") or []:
        marker = (item.get("marker") or "").strip()
        value = _num(item.get("value"))
        if not marker or value is None:
            continue
        rows.append({
            "marker": normalize_marker(marker),
            "value": value,
            "unit": item.get("unit"),
            "ref_low": _num(item.get("ref_low")),
            "ref_high": _num(item.get("ref_high")),
        })
    return rows


async def confirm_extracted(
    session: AsyncSession,
    *,
    on_date: date_type,
    markers: Sequence[dict],
    lab_name: Optional[str] = None,
    raw_payload_id: Optional[int] = None,
    override: bool = False,
) -> list[LabResult]:
    """Persist the owner-edited marker rows from the upload preview (step 2 of
    upload -> preview -> confirm). Marks the raw payload processed. Does not
    commit — mirrors :func:`ingest_extracted` but trusts the caller's edits
    instead of re-deriving from the raw vision dict, and never drops a row as a
    'duplicate' (the owner already reviewed it)."""
    created: list[LabResult] = []
    for item in markers:
        marker = (item.get("marker") or "").strip()
        value = _num(item.get("value"))
        if not marker or value is None:
            continue
        row = await add_result(
            session,
            on_date=on_date,
            marker=marker,
            value=value,
            unit=item.get("unit"),
            ref_low=_num(item.get("ref_low")),
            ref_high=_num(item.get("ref_high")),
            lab_name=lab_name,
            source=Source.LAB_PARSER.value,
            raw_payload_id=raw_payload_id,
            override=override,
        )
        created.append(row)

    if raw_payload_id is not None:
        raw = await session.get(RawPayload, raw_payload_id)
        if raw is not None:
            raw.processed_at = now_local()

    return created


async def ingest_extracted(
    session: AsyncSession,
    extracted: dict,
    *,
    file_key: Optional[str] = None,
    override: bool = False,
) -> dict:
    """Persist an extracted document: keep it raw, then create a result row per
    marker (deduping identical (date, marker, value)). Does not commit.

    Returns ``{"created": int, "skipped": int, "results": list[LabResult]}`` — the
    freshly created rows (already flushed, so ``.flag``/``.id`` are populated),
    handy for a caller that wants to report back exactly what was saved (e.g. the
    MCP batch tool) without a follow-up query."""
    on_date = _parse_date(extracted.get("date")) or today_local()
    lab_name = extracted.get("lab_name")
    results = extracted.get("results") or []

    raw_row = await raw_payload_service.upsert_raw_payload(
        session,
        domain=DOMAIN,
        source=Source.LAB_PARSER.value,
        external_id=file_key or f"lab:{on_date.isoformat()}:{lab_name or '?'}",
        payload=extracted,
    )

    summary = {"created": 0, "skipped": 0, "results": []}
    for item in results:
        marker = (item.get("marker") or "").strip()
        value = _num(item.get("value"))
        if not marker or value is None:
            summary["skipped"] += 1
            continue
        if await _result_exists(session, on_date, marker, value):
            summary["skipped"] += 1
            continue
        try:
            row = await add_result(
                session,
                on_date=on_date,
                marker=marker,
                value=value,
                unit=item.get("unit"),
                ref_low=_num(item.get("ref_low")),
                ref_high=_num(item.get("ref_high")),
                lab_name=lab_name,
                source=Source.LAB_PARSER.value,
                raw_payload_id=raw_row.id,
                override=override,
            )
        except ValueError as e:
            # One garbled row must not cost the whole document — it stays in the
            # raw payload either way, so it can be re-parsed later.
            logger.warning("Skipping unusable extracted marker: %s", e)
            summary["skipped"] += 1
            continue
        summary["results"].append(row)
        summary["created"] += 1

    raw_row.processed_at = now_local()
    return summary


async def _result_exists(
    session: AsyncSession, on_date: date_type, marker: str, value: float
) -> bool:
    result = await session.execute(
        select(LabResult.id).where(
            LabResult.date == on_date,
            LabResult.marker == marker,
            LabResult.value == value,
        )
    )
    return result.first() is not None


def _num(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None and v != "" else None
    except (ValueError, TypeError):
        return None


def _parse_date(v: Any) -> Optional[date_type]:
    if not v:
        return None
    try:
        return date_type.fromisoformat(str(v)[:10])
    except ValueError:
        return None


# ── Full view collection for API / UI ─────────────────────────────────────────
async def collect(session: AsyncSession) -> dict[str, Any]:
    """Collect everything needed by the Labs dashboard in one round-trip."""
    today = today_local()
    # Every result once, oldest first: the latest per marker and every marker's history come
    # from the same read (the last row per marker is the one ``latest_per_marker`` picks).
    all_results = (
        await session.execute(select(LabResult).order_by(LabResult.date, LabResult.id))
    ).scalars().all()
    history_by_marker: dict[str, list[LabResult]] = {}
    for row in all_results:
        history_by_marker.setdefault(row.marker, []).append(row)
    latest_results = sorted(
        (rows[-1] for rows in history_by_marker.values()),
        key=lambda r: (r.date, r.id),
        reverse=True,
    )
    markers_catalog = {m.name: m for m in await list_markers(session)}
    await refresh_alerts(session, latest=latest_results, markers=markers_catalog)

    latest_sorted = sorted(
        latest_results,
        key=lambda r: (is_out_of_range(r.flag), r.date),
        reverse=True,
    )

    latest_date = latest_sorted[0].date.isoformat() if latest_sorted else today.isoformat()
    latest_lab = (latest_sorted[0].lab_name or "Инвитро") if latest_sorted else "—"
    latest_source = (latest_sorted[0].source or "PDF") if latest_sorted else "PDF"

    markers_out = []
    for r in latest_sorted:
        m_cat = markers_catalog.get(r.marker)
        history_rows = [{"date": h.date.isoformat(), "value": h.value} for h in history_by_marker.get(r.marker, [])]

        cat_key = (m_cat.category if m_cat and m_cat.category else "").lower()
        if not cat_key:
            name_lower = r.marker.lower()
            if any(k in name_lower for k in ("тестостерон", "ттг", "т4", "эстрадиол", "прогестерон", "пролактин", "фсг", "лг", "инсулин", "гспг")):
                cat_key = "hormones"
                cat_name = "Гормоны"
            elif any(k in name_lower for k in ("витамин", "ферритин", "b12", "железо", "цинк", "магний")):
                cat_key = "vitamins"
                cat_name = "Витамины"
            else:
                cat_key = "metabolism"
                cat_name = "Метаболизм"
        else:
            cat_name = m_cat.category

        lo = r.ref_low if r.ref_low is not None else (m_cat.ref_low if m_cat and m_cat.ref_low is not None else 0.0)
        hi = r.ref_high if r.ref_high is not None else (m_cat.ref_high if m_cat and m_cat.ref_high is not None else (lo * 2 or 100.0))
        span = hi - lo if hi > lo else max(hi, 1.0)
        min_val = max(0.0, lo - span * 0.3)
        max_val = hi + span * 0.3

        decimals = 2 if r.value < 1 else (1 if r.value < 100 else 0)

        hist_list = [{"dateIso": h["date"], "value": h["value"]} for h in history_rows]
        if not hist_list:
            hist_list = [{"dateIso": r.date.isoformat(), "value": r.value}]

        markers_out.append({
            "id": str(r.id),
            "name": r.marker,
            "groupKey": cat_key,
            "group": cat_name,
            "unit": r.unit or "",
            "value": r.value,
            "lo": lo,
            "hi": hi,
            "min": round(min_val, 2),
            "max": round(max_val, 2),
            "decimals": decimals,
            "history": hist_list,
        })

    return {
        "collectedIso": latest_date,
        "lab": latest_lab,
        "source": latest_source,
        "markers": markers_out,
    }

