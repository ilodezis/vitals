"""Timeline service — the cross-domain event feed + per-domain chart overlays.

Two kinds of events feed the ``/timeline`` page:
  * **manual** ``Annotation`` rows the owner drops (trip, illness, protocol
    change, a free-form note) — the only thing genuinely missing from every
    other domain table;
  * **derived** events read live from other domains' own rows (GLP-1 dose
    changes, lab draws, BIA scans, achieved milestones, noise periods) — never
    duplicated into ``annotations``; the domain's own row stays the source of
    truth, this just re-shapes it into a ``TimelineEvent`` for the feed.

``overlays_for`` only surfaces **manual** flags on a domain's chart. Derived
markers (noise ranges, GLP-1 dose phases) are already drawn by their own domain
service as first-class chart series (``weight_service.chart_series``'s ``noise``/
``phases`` keys) — re-emitting them here would double-draw the same box.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type
from typing import Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import AnnotationKind, Domain, MilestoneStatus, Source
from vitals.i18n import t
from vitals.models.timeline import Annotation

DOMAIN = Domain.TIMELINE.value

# Tone for a manual annotation, by kind — an illness/travel flag reads as a
# mild warning (context for a wobble in the trend), a protocol change is
# neutral information, life events/notes carry no tone at all.
_TONE_BY_KIND: dict[str, str] = {
    AnnotationKind.ILLNESS.value: "warn",
    AnnotationKind.TRAVEL.value: "warn",
    AnnotationKind.PROTOCOL_CHANGE.value: "",
    AnnotationKind.LIFE_EVENT.value: "",
    AnnotationKind.NOTE.value: "",
}


@dataclass(frozen=True)
class TimelineEvent:
    date: date_type
    end_date: Optional[date_type]
    domain: str
    kind: str
    title: str
    detail: Optional[str]
    tone: str  # 'good' | 'bad' | 'warn' | ''
    source: str  # 'manual' | 'derived'
    ref: str

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "domain": self.domain,
            "kind": self.kind,
            "title": self.title,
            "detail": self.detail,
            "tone": self.tone,
            "source": self.source,
            "ref": self.ref,
        }


# ── Manual annotations (CRUD) ─────────────────────────────────────────────────
async def create_annotation(
    session: AsyncSession,
    *,
    title: str,
    on_date: date_type,
    end_date: Optional[date_type] = None,
    kind: str = AnnotationKind.NOTE.value,
    domain: str = DOMAIN,
    note: Optional[str] = None,
) -> Annotation:
    row = Annotation(
        date=on_date,
        end_date=end_date,
        domain=domain,
        source=Source.MANUAL.value,
        kind=kind,
        title=title,
        note=note,
    )
    session.add(row)
    await session.flush()
    return row


async def update_annotation(
    session: AsyncSession,
    annotation_id: int,
    *,
    title: str,
    on_date: date_type,
    end_date: Optional[date_type] = None,
    kind: str,
    domain: str,
    note: Optional[str] = None,
) -> Optional[Annotation]:
    row = await session.get(Annotation, annotation_id)
    if row is None:
        return None
    row.title = title
    row.date = on_date
    row.end_date = end_date
    row.kind = kind
    row.domain = domain
    row.note = note
    await session.flush()
    return row


async def get_annotation(session: AsyncSession, annotation_id: int) -> Optional[Annotation]:
    return await session.get(Annotation, annotation_id)


async def delete_annotation(session: AsyncSession, annotation_id: int) -> bool:
    row = await session.get(Annotation, annotation_id)
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


async def list_annotations(
    session: AsyncSession,
    *,
    domain: Optional[str] = None,
    start: Optional[date_type] = None,
    end: Optional[date_type] = None,
) -> Sequence[Annotation]:
    """Annotations overlapping ``[start, end]`` (either bound optional). A point
    annotation (``end_date is None``) overlaps a range iff its ``date`` falls
    inside it; a ranged one overlaps iff the two ranges intersect."""
    stmt = select(Annotation)
    if domain is not None:
        stmt = stmt.where(Annotation.domain == domain)
    effective_end = func.coalesce(Annotation.end_date, Annotation.date)
    if start is not None:
        stmt = stmt.where(effective_end >= start)
    if end is not None:
        stmt = stmt.where(Annotation.date <= end)
    stmt = stmt.order_by(Annotation.date.desc(), Annotation.id.desc())
    result = await session.execute(stmt)
    return result.scalars().all()


# ── Derived events (read-only re-shape of other domains' own rows) ───────────
async def _derived_events(
    session: AsyncSession, *, start: Optional[date_type], end: Optional[date_type]
) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []

    # GLP-1 dose phase starts — the injection log itself is too frequent to
    # surface individually here (it would flood the feed); a phase *change* is
    # the meaningful protocol event, and it's the same transition already
    # painted as a band on the weight chart.
    from vitals.models.glp1 import DOMAIN as GLP1_DOMAIN, DosePhase

    p_stmt = select(DosePhase).where(DosePhase.domain == GLP1_DOMAIN)
    if start is not None:
        p_stmt = p_stmt.where(func.coalesce(DosePhase.end_date, DosePhase.start_date) >= start)
    if end is not None:
        p_stmt = p_stmt.where(DosePhase.start_date <= end)
    phases = (await session.execute(p_stmt)).scalars().all()
    for p in phases:
        events.append(TimelineEvent(
            date=p.start_date, end_date=None, domain=GLP1_DOMAIN,
            kind="protocol_change",
            title=t("timeline.derived.dose_phase_start", drug=t("enum.drug." + p.drug), dose=p.dose_mg),
            detail=None, tone="", source="derived", ref=f"dose_phase:{p.id}",
        ))

    # Lab draws — one event per collection date (however many markers it held).
    from vitals.models.labs import DOMAIN as LABS_DOMAIN, LabResult

    l_stmt = select(LabResult.date, func.count(LabResult.id)).where(LabResult.domain == LABS_DOMAIN)
    if start is not None:
        l_stmt = l_stmt.where(LabResult.date >= start)
    if end is not None:
        l_stmt = l_stmt.where(LabResult.date <= end)
    l_stmt = l_stmt.group_by(LabResult.date)
    for on_date, marker_count in (await session.execute(l_stmt)).all():
        events.append(TimelineEvent(
            date=on_date, end_date=None, domain=LABS_DOMAIN, kind="note",
            title=t("timeline.derived.labs_batch", n=marker_count),
            detail=None, tone="", source="derived", ref=f"labs:{on_date.isoformat()}",
        ))

    # BIA / InBody scans.
    from vitals.models.body_scan import BodyScan
    from vitals.models.body_scan import DOMAIN as BODY_DOMAIN

    b_stmt = select(BodyScan).where(BodyScan.domain == BODY_DOMAIN)
    if start is not None:
        b_stmt = b_stmt.where(BodyScan.date >= start)
    if end is not None:
        b_stmt = b_stmt.where(BodyScan.date <= end)
    for scan in (await session.execute(b_stmt)).scalars().all():
        device = scan.device or t("timeline.derived.device_unknown")
        events.append(TimelineEvent(
            date=scan.date, end_date=None, domain=BODY_DOMAIN, kind="note",
            title=t("timeline.derived.body_scan", device=device),
            detail=None, tone="", source="derived", ref=f"body_scan:{scan.id}",
        ))

    # Achieved milestones — no dated field on Milestone itself, so the moment
    # its status flipped to ACHIEVED (updated_at) stands in for "achieved on".
    from vitals.models.milestones import Milestone

    m_stmt = select(Milestone).where(Milestone.status == MilestoneStatus.ACHIEVED.value)
    for m in (await session.execute(m_stmt)).scalars().all():
        achieved_date = m.updated_at.date()
        if start is not None and achieved_date < start:
            continue
        if end is not None and achieved_date > end:
            continue
        events.append(TimelineEvent(
            date=achieved_date, end_date=None, domain=m.domain, kind="note",
            title=t("timeline.derived.milestone_achieved", name=m.name),
            detail=None, tone="good", source="derived", ref=f"milestone:{m.id}",
        ))

    # Noise markers (weight) — surfaced in the feed even though the chart
    # already shades them, so the timeline reads as a complete log of "why".
    from vitals.models.weight import DOMAIN as WEIGHT_DOMAIN, NoiseMarker

    n_stmt = select(NoiseMarker).where(NoiseMarker.domain == WEIGHT_DOMAIN)
    if start is not None:
        n_stmt = n_stmt.where(func.coalesce(NoiseMarker.end_date, NoiseMarker.start_date) >= start)
    if end is not None:
        n_stmt = n_stmt.where(NoiseMarker.start_date <= end)
    for n in (await session.execute(n_stmt)).scalars().all():
        events.append(TimelineEvent(
            date=n.start_date, end_date=n.end_date, domain=WEIGHT_DOMAIN, kind="note",
            title=t("timeline.derived.noise_period", reason=n.reason),
            detail=None, tone="warn", source="derived", ref=f"noise_marker:{n.id}",
        ))

    return events


async def list_events(
    session: AsyncSession,
    *,
    domains: Optional[Sequence[str]] = None,
    start: Optional[date_type] = None,
    end: Optional[date_type] = None,
    limit: int = 200,
) -> list[TimelineEvent]:
    """The unified feed: manual annotations + derived events, newest first."""
    events: list[TimelineEvent] = []

    for a in await list_annotations(session, start=start, end=end):
        events.append(TimelineEvent(
            date=a.date, end_date=a.end_date, domain=a.domain, kind=a.kind,
            title=a.title, detail=a.note, tone=_TONE_BY_KIND.get(a.kind, ""),
            source="manual", ref=f"annotation:{a.id}",
        ))

    events.extend(await _derived_events(session, start=start, end=end))

    if domains is not None:
        allowed = set(domains) | {DOMAIN}
        events = [e for e in events if e.domain in allowed]

    events.sort(key=lambda e: e.date, reverse=True)
    return events[:limit]


# ── Chart overlays ────────────────────────────────────────────────────────────
async def overlays_for(
    session: AsyncSession,
    *,
    domain: str,
    start: Optional[date_type] = None,
    end: Optional[date_type] = None,
) -> list[dict]:
    """Manual-annotation overlays for one domain's chart: the domain's own flags
    plus global ones (``Domain.TIMELINE``). Shape matches the existing noise/
    phase overlay dicts (``{start, end?, label, tone, kind}``) so the same
    Chart.js annotation plugin renders them."""
    own = await list_annotations(session, domain=domain, start=start, end=end)
    glob = (
        await list_annotations(session, domain=DOMAIN, start=start, end=end)
        if domain != DOMAIN
        else []
    )
    overlays = []
    for a in list(own) + list(glob):
        overlays.append({
            "start": a.date.isoformat(),
            "end": a.end_date.isoformat() if a.end_date else None,
            "label": a.title,
            "tone": _TONE_BY_KIND.get(a.kind, ""),
            "kind": a.kind,
        })
    return overlays
