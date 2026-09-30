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

import base64
import logging
import math
from datetime import date as date_type, timedelta
from typing import Any, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import Domain, LabFlag, Severity, Source
from vitals.i18n import decimal, t
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

    If the result carries no range, fall back to the catalog's default range so a
    flag can still be computed. Raises ``ValueError`` on a nameless marker or an
    implausible value, and :class:`ConflictBlocked` when a hard cross-domain rule
    fires without ``override``."""
    marker = normalize_marker(marker)
    if not marker:
        raise ValueError("marker is required")
    if value is None or not math.isfinite(value) or abs(value) > _VALUE_ABS_MAX:
        raise ValueError(f"implausible lab value for {marker}: {value!r}")
    catalog = await _ensure_marker(
        session, marker, unit=unit, ref_low=ref_low, ref_high=ref_high
    )
    eff_low = ref_low if ref_low is not None else catalog.ref_low
    eff_high = ref_high if ref_high is not None else catalog.ref_high
    flag = compute_flag(value, eff_low, eff_high)

    # The same gate every other write path runs, before the row exists: a hard
    # rule (an active potassium supplement meeting a hyperkalemic potassium
    # result) stops the save unless the caller overrides, and soft rules keep
    # doing what they did — an alert, never a block.
    await conflict_engine.enforce(
        session,
        Domain.LABS.value,
        {"marker": marker, "value": value, "flag": flag},
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
    row.flag = compute_flag(row.value, row.ref_low, row.ref_high)

    await session.flush()
    await refresh_alerts(session)
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
    """Chronological series for one marker (the per-marker chart)."""
    marker = normalize_marker(marker)
    result = await session.execute(
        select(LabResult).where(LabResult.marker == marker).order_by(LabResult.date)
    )
    return [
        {
            "date": r.date.isoformat(),
            "value": r.value,
            "flag": r.flag,
            "ref_low": r.ref_low,
            "ref_high": r.ref_high,
        }
        for r in result.scalars().all()
    ]


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
    5.0}} against the current panel, not just a freshly logged result."""
    latest = await latest_per_marker(session)
    return [{"marker": r.marker, "value": r.value, "flag": r.flag} for r in latest]


async def delete_result(session: AsyncSession, result_id: int) -> bool:
    row = await session.get(LabResult, result_id)
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
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
        await book.resolve_superseded(alert_key=key, marker=r.marker, keep_entity=entity)
        if is_out_of_range(r.flag):
            if book.was_ever_dismissed(key, entity):
                continue
            tier = markers.get(r.marker).tier if markers.get(r.marker) else 2
            critical = _is_critical(r.flag) or tier == 1
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
                    flag=t(f"enum.flag.{r.flag}"),
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


# Shared PDF→PNG rasteriser (kept under this name for the call below).
from vitals.integrations.vision import pdf_pages_png as _pdf_pages_png


async def extract_from_file(
    file_bytes: bytes,
    *,
    llm: Any,
    content_type: str = "image/jpeg",
    filename: Optional[str] = None,
) -> dict:
    """Send the document to a vision model and return the parsed structured dict.
    PDFs are rendered to images first (all pages up to a limit). Raises whatever
    the LLM client raises (e.g. ``LLMNotConfigured``) so the router can surface
    a clear message."""
    is_pdf = (content_type or "").lower() == "application/pdf" or (
        filename or ""
    ).lower().endswith(".pdf")

    if is_pdf:
        pages_png = _pdf_pages_png(file_bytes)
        image_urls = []
        for png_bytes in pages_png:
            b64 = base64.b64encode(png_bytes).decode("ascii")
            image_urls.append(f"data:image/png;base64,{b64}")

        return await llm.extract_json(
            "Extract all lab markers from this report.",
            system=_EXTRACT_SYSTEM,
            image_urls=image_urls,
        )
    else:
        if not (content_type or "").startswith("image/"):
            content_type = "image/jpeg"
        b64 = base64.b64encode(file_bytes).decode("ascii")
        image_url = f"data:{content_type};base64,{b64}"
        return await llm.extract_json(
            "Extract all lab markers from this report image.",
            system=_EXTRACT_SYSTEM,
            image_url=image_url,
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


async def reparse_from_raw(session: AsyncSession, raw_row: RawPayload) -> None:
    """Re-run extraction ingest against a lab payload already on disk — no new
    upload. Covers uploads the owner never confirmed (extracted but abandoned
    at the preview step), so those markers aren't lost. Reuses
    :func:`ingest_extracted` (dedupes by date+marker+value, so this is safe even
    if some rows were confirmed by hand before the sweep got to it). Preserves
    ``fetched_at``: this is a reparse, not a new upload. Used by
    :func:`reparse_pending` (the nightly sweep — raw_payload_service.
    sweep_pending_job)."""
    extracted = raw_row.payload if isinstance(raw_row.payload, dict) else {}
    original_fetched_at = raw_row.fetched_at
    await ingest_extracted(session, extracted, file_key=raw_row.external_id)
    raw_row.fetched_at = original_fetched_at


async def reparse_pending(
    session: AsyncSession,
    *,
    limit: int = raw_payload_service.REPARSE_BATCH,
    since_days: int = raw_payload_service.REPARSE_WINDOW_DAYS,
) -> int:
    """Sweep lab raw payloads (extractions never confirmed by the owner) still
    pending a normalized row. Does not commit."""
    has_normalized = (
        select(LabResult.id).where(LabResult.raw_payload_id == RawPayload.id).exists()
    )
    return await raw_payload_service.sweep_domain(
        session,
        domain=DOMAIN,
        reparse=reparse_from_raw,
        has_normalized=has_normalized,
        limit=limit,
        since_days=since_days,
    )


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

