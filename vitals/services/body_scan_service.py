"""Body-composition scan service — InBody / МедАсс (BIA) (optional module).

Owns the ``body_comp`` domain. A scan is an upload (or agent/manual entry) of a
bicompedance analyzer sheet; we capture **every** printed metric generically.

Pipeline (two-step because of the edit-before-save preview):

  1. :func:`extract_from_file` — a photo/PDF → a structured dict via the same
     OpenRouter vision model the labs parser uses (the document is also kept raw).
  2. :func:`normalize_extracted` — pure mapping of printed labels onto canonical
     metric keys (the editable preview rows).
  3. :func:`save_scan` — persist the owner-edited rows as a ``BodyScan`` + child
     ``BodyScanMetric`` rows, stamp the raw payload processed, and **bridge** the
     scan's weight / body-fat% / LBM into the weight domain (a second source that
     coexists with Navy — see ``weight_service``).

Like labs, nothing here blocks and the LLM is optional — every value can be
entered by hand, so the module works with no key configured.
"""
from __future__ import annotations

import logging
from datetime import date as date_type
from typing import Any, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from vitals.enums import Domain, Severity, Source
from vitals.i18n import t
from vitals.models.body_scan import DOMAIN, BodyScan, BodyScanMetric
from vitals.models.raw_payload import RawPayload
from vitals.services import alerts_service, conflict_engine, raw_payload_service, weight_service
from vitals.services.analytics.body_metrics import (
    CAT_OTHER,
    METRIC_REGISTRY,
    body_fat_pct_from_scan,
    canonical_segment,
    display_name,
    lbm_from_scan,
    normalize_metric,
    weight_from_scan,
)
from vitals.integrations.vision import file_to_image_urls
from vitals.utils.timeutils import now_local, today_local

logger = logging.getLogger(__name__)

VISCERAL_ALERT_KEY = "body_comp.visceral_high"
PHASE_ALERT_KEY = "body_comp.phase_low"


# ── LLM extraction (optional auto-fill) ───────────────────────────────────────
_EXTRACT_SYSTEM = (
    "You are a body-composition analyzer parser (InBody / МедАсс / bioimpedance). "
    "Extract EVERY printed metric from the device sheet image(s). Respond ONLY with "
    'JSON of the form: {"date": "YYYY-MM-DD"|null, "device": string|null, "metrics": '
    '[{"label": string, "value": number, "unit": string|null, "ref_low": number|null, '
    '"ref_high": number|null, "segment": string|null}]}. '
    "label = the metric name exactly as printed (keep its original language). "
    "value = a plain number only (no ranges or units inside it). "
    "unit = the printed unit or null. ref_low/ref_high = the normal/target range "
    "bounds when shown, else null. segment = one of right_arm,left_arm,trunk,"
    "right_leg,left_leg for per-limb segmental rows, otherwise null. Use the "
    "measurement date. If a field is unknown use null. Never invent metrics."
)


async def extract_from_file(
    file_bytes: bytes,
    *,
    llm: Any,
    content_type: str = "image/jpeg",
    filename: Optional[str] = None,
) -> dict:
    """Send the sheet to the vision model and return the parsed structured dict.
    PDFs are rendered to images first. Raises whatever the LLM client raises
    (e.g. ``LLMNotConfigured``) so the router can surface a clear message."""
    image_urls = file_to_image_urls(
        file_bytes, content_type=content_type, filename=filename
    )
    return await llm.extract_json(
        "Extract every metric from this body-composition analyzer report.",
        system=_EXTRACT_SYSTEM,
        image_urls=image_urls,
    )


def normalize_extracted(extracted: dict) -> list[dict]:
    """Pure: turn a raw vision dict into normalized, editable metric rows.

    Each row is ``{metric_key, label, value, unit, ref_low, ref_high, segment,
    category}``. Unparseable rows (no label / non-numeric value) are dropped."""
    rows: list[dict] = []
    for item in extracted.get("metrics") or []:
        row = _normalize_item(item)
        if row is not None:
            rows.append(row)
    return rows


def _normalize_item(item: dict) -> Optional[dict]:
    """Normalize one metric dict (from vision, the preview, or an agent call).

    Driven by the printed ``label`` when present (so editing/auditing is stable);
    falls back to an explicit ``metric_key`` for agent calls with no label."""
    label = (item.get("label") or "").strip()
    value = _num(item.get("value"))
    if value is None:
        return None
    seg_in = item.get("segment")
    if label:
        key, category, segment = normalize_metric(label, seg_in)
    else:
        key = item.get("metric_key")
        if not key:
            return None
        spec = METRIC_REGISTRY.get(key)
        category = item.get("category") or (spec.category if spec else CAT_OTHER)
        segment = canonical_segment(seg_in)
    return {
        "metric_key": key,
        "label": label or (display_name(key) or key),
        "value": value,
        "unit": (item.get("unit") or None),
        "ref_low": _num(item.get("ref_low")),
        "ref_high": _num(item.get("ref_high")),
        "segment": segment,
        "category": category,
    }


async def save_scan(
    session: AsyncSession,
    *,
    on_date: date_type,
    device: Optional[str] = None,
    file_key: Optional[str] = None,
    raw_payload_id: Optional[int] = None,
    metrics: Sequence[dict],
    note: Optional[str] = None,
    source: str = Source.BODY_SCAN.value,
    override: bool = False,
) -> BodyScan:
    """Persist a scan and its metrics (owner-edited rows), stamp the raw payload
    processed, and bridge weight into the weight domain. Does not commit.

    May raise ``ConflictBlocked`` if a cross-domain block rule fires without
    ``override`` (override plumbing kept consistent with the weight domain)."""
    await conflict_engine.enforce(
        session,
        Domain.BODY_COMPOSITION.value,
        {"scan": True},
        override=override,
        entity_ref=f"body_scan:{on_date.isoformat()}",
    )

    scan = BodyScan(
        date=on_date,
        domain=DOMAIN,
        source=source,
        device=(device or None),
        file_key=file_key,
        raw_payload_id=raw_payload_id,
        note=note,
    )
    session.add(scan)
    await session.flush()

    normalized = [n for n in (_normalize_item(m) for m in metrics) if n is not None]
    for n in normalized:
        session.add(BodyScanMetric(scan_id=scan.id, **n))
    await session.flush()

    # Mark the verbatim vision payload processed (it stays unchanged — the owner's
    # edits live only in the normalized rows, so the original extraction is an
    # audit trail we can always re-parse).
    if raw_payload_id is not None:
        raw = await session.get(RawPayload, raw_payload_id)
        if raw is not None:
            raw.processed_at = now_local()

    # Bridge the scan's weight into the weight domain as the BODY_SCAN source so it
    # appears on the weight trend. Priority: manual ≈ scan > Garmin (Garmin never
    # supersedes a scan). Enforced in weight_service.
    w = weight_from_scan(normalized)
    if w is not None and w > 0:
        await weight_service.log_weight(
            session,
            on_date=on_date,
            weight_kg=w,
            source=Source.BODY_SCAN.value,
            override=override,
        )
    await session.flush()
    return scan


async def ingest_extracted(
    session: AsyncSession,
    extracted: dict,
    *,
    file_key: Optional[str] = None,
    device: Optional[str] = None,
) -> BodyScan:
    """Convenience: store the raw payload + save a scan straight from a vision
    dict (no preview). Used by tests and any auto-ingest path; the web flow uses
    the two-step upload→confirm instead so the owner can edit first."""
    on_date = _parse_date(extracted.get("date")) or today_local()
    dev = device or extracted.get("device")
    raw_row = await raw_payload_service.upsert_raw_payload(
        session,
        domain=DOMAIN,
        source=Source.BODY_SCAN.value,
        external_id=file_key or f"body_scan:{on_date.isoformat()}",
        payload=extracted,
    )
    rows = normalize_extracted(extracted)
    return await save_scan(
        session,
        on_date=on_date,
        device=dev,
        file_key=file_key,
        raw_payload_id=raw_row.id,
        metrics=rows,
    )


# ── Reads ─────────────────────────────────────────────────────────────────────
async def list_scans(
    session: AsyncSession,
    *,
    start: Optional[date_type] = None,
    end: Optional[date_type] = None,
) -> Sequence[BodyScan]:
    stmt = select(BodyScan).options(selectinload(BodyScan.metrics))
    if start is not None:
        stmt = stmt.where(BodyScan.date >= start)
    if end is not None:
        stmt = stmt.where(BodyScan.date <= end)
    stmt = stmt.order_by(BodyScan.date.desc(), BodyScan.id.desc())
    return (await session.execute(stmt)).scalars().all()


async def get_scan(session: AsyncSession, scan_id: int) -> Optional[BodyScan]:
    stmt = (
        select(BodyScan)
        .where(BodyScan.id == scan_id)
        .options(selectinload(BodyScan.metrics))
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def latest_scan(session: AsyncSession) -> Optional[BodyScan]:
    stmt = (
        select(BodyScan)
        .options(selectinload(BodyScan.metrics))
        .order_by(BodyScan.date.desc(), BodyScan.id.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


async def metric_history(
    session: AsyncSession,
    metric_key: str,
    *,
    segment: Optional[str] = None,
    start: Optional[date_type] = None,
    end: Optional[date_type] = None,
) -> list[dict]:
    """Chronological series for one metric (optionally a single segment)."""
    stmt = (
        select(BodyScanMetric, BodyScan.date)
        .join(BodyScan, BodyScanMetric.scan_id == BodyScan.id)
        .where(BodyScanMetric.metric_key == metric_key)
    )
    seg = canonical_segment(segment)
    if seg is not None:
        stmt = stmt.where(BodyScanMetric.segment == seg)
    if start is not None:
        stmt = stmt.where(BodyScan.date >= start)
    if end is not None:
        stmt = stmt.where(BodyScan.date <= end)
    stmt = stmt.order_by(BodyScan.date, BodyScanMetric.id)
    rows = (await session.execute(stmt)).all()
    return [
        {
            "date": d.isoformat(),
            "value": m.value,
            "unit": m.unit,
            "segment": m.segment,
            "ref_low": m.ref_low,
            "ref_high": m.ref_high,
        }
        for (m, d) in rows
    ]


# Display labels for the canonical segments (chart-builder picklist only — the
# label->segment direction already lives in body_metrics.SEGMENT_ALIASES).
# Public (not underscore-prefixed): reused by chart_data_service for auto-labeling
# saved chart series.
SEGMENT_LABELS_RU = {
    "right_arm": "правая рука",
    "left_arm": "левая рука",
    "trunk": "туловище",
    "right_leg": "правая нога",
    "left_leg": "левая нога",
}


async def available_metrics(session: AsyncSession) -> list[dict]:
    """Distinct (metric_key, segment) pairs actually present across all scans,
    each with a display label and a stable ``value`` (``metric_key`` for
    whole-body rows, ``"metric_key:segment"`` for segmental rows) — the
    parameter picklist for the chart-builder catalog (analogous to
    ``hevy_service.exercise_catalog``)."""
    result = await session.execute(
        select(BodyScanMetric.metric_key, BodyScanMetric.segment)
        .distinct()
        .order_by(BodyScanMetric.metric_key, BodyScanMetric.segment)
    )
    out: list[dict] = []
    for metric_key, segment in result.all():
        label = display_name(metric_key) or metric_key
        if segment:
            out.append({
                "value": f"{metric_key}:{segment}",
                "label": f"{label} — {SEGMENT_LABELS_RU.get(segment, segment)}",
            })
        else:
            out.append({"value": metric_key, "label": label})
    return out


async def bia_chart_points(session: AsyncSession) -> dict:
    """BIA body-fat % and LBM series (latest scan per date) for the weight chart.
    Coexists with the Navy series — both are drawn."""
    scans = (
        await session.execute(
            select(BodyScan)
            .options(selectinload(BodyScan.metrics))
            .order_by(BodyScan.date, BodyScan.id)
        )
    ).scalars().all()

    by_date: dict[date_type, BodyScan] = {}
    for s in scans:
        by_date[s.date] = s  # ascending order → latest id per date wins

    bf: list[dict] = []
    lbm: list[dict] = []
    for d in sorted(by_date):
        ms = by_date[d].metrics
        b = body_fat_pct_from_scan(ms)
        if b is not None:
            bf.append({"date": d.isoformat(), "value": b})
        lbm_val = lbm_from_scan(ms)
        if lbm_val is not None:
            lbm.append({"date": d.isoformat(), "value": lbm_val})
    return {"bf": bf, "lbm": lbm}


async def delete_scan(session: AsyncSession, scan_id: int) -> bool:
    """Delete a scan (cascades to its metrics). Returns False if not found.

    The bridged weight row is left as-is (it's an independent weight log); the
    owner can remove it from the weight tab if desired."""
    scan = await session.get(BodyScan, scan_id)
    if scan is None:
        return False
    await session.delete(scan)
    await session.flush()
    return True


# ── Alerts (light) ────────────────────────────────────────────────────────────
async def refresh_alerts(session: AsyncSession) -> None:
    """Raise/clear passive ``info`` alerts from the latest scan: visceral fat above
    its printed range, or phase angle below its printed range. Idempotent. Each
    alert is bound to the triggering scan's id, so a dismissal sticks forever
    for that scan — only a newer scan can raise it again."""
    scan = await latest_scan(session)
    if scan is None:
        await alerts_service.resolve_superseded(session, alert_key=VISCERAL_ALERT_KEY, keep_entity=None)
        await alerts_service.resolve_superseded(session, alert_key=PHASE_ALERT_KEY, keep_entity=None)
        return

    entity = str(scan.id)
    await alerts_service.resolve_superseded(session, alert_key=VISCERAL_ALERT_KEY, keep_entity=entity)
    await alerts_service.resolve_superseded(session, alert_key=PHASE_ALERT_KEY, keep_entity=entity)

    by_key = {m.metric_key: m for m in scan.metrics}

    vfa = by_key.get("visceral_fat_area") or by_key.get("visceral_fat_level")
    if vfa is not None and vfa.ref_high is not None and vfa.value > vfa.ref_high:
        if not await alerts_service._was_ever_dismissed(session, VISCERAL_ALERT_KEY, entity):
            await alerts_service.raise_alert(
                session,
                domain=Domain.BODY_COMPOSITION.value,
                severity=Severity.INFO.value,
                message=t("alert.body_visceral_high", value=vfa.value, unit=((" " + vfa.unit) if vfa.unit else "")),
                alert_key=VISCERAL_ALERT_KEY,
                entity_ref=entity,
            )
    else:
        await alerts_service.resolve_by_key(session, alert_key=VISCERAL_ALERT_KEY, entity_ref=entity)

    phase = by_key.get("phase_angle")
    if phase is not None and phase.ref_low is not None and phase.value < phase.ref_low:
        if not await alerts_service._was_ever_dismissed(session, PHASE_ALERT_KEY, entity):
            await alerts_service.raise_alert(
                session,
                domain=Domain.BODY_COMPOSITION.value,
                severity=Severity.INFO.value,
                message=t("alert.body_phase_low", value=phase.value),
                alert_key=PHASE_ALERT_KEY,
                entity_ref=entity,
            )
    else:
        await alerts_service.resolve_by_key(session, alert_key=PHASE_ALERT_KEY, entity_ref=entity)


# ── Helpers ───────────────────────────────────────────────────────────────────
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
