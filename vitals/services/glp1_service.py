"""GLP-1 Protocol service (Phase 2).

Owns the GLP-1 domain:

  * **Injections** — CRUD over the shot log (date, drug, dose, body-map site).
  * **Dose phases** — date ranges of "on dose X" that paint the weight chart
    overlay and bound the plateau check. Adding a new open-ended phase closes the
    previous open one the day before (the timeline has no gaps/overlaps).
  * **Side effects** — symptom log graded 1-5.
  * **Plateau detection** — once the current dose has run ``PLATEAU_MIN_DAYS``,
    if the noise-excluded weight trend over the phase is flatter than
    ``PLATEAU_SLOPE_THRESHOLD`` we raise a passive ``warn`` alert (no
    auto-escalation — the product is a navigator, the dose decision is the user's).

Mutating fns run the conflict-engine override plumbing so the override UX stays
wired end-to-end, consistent with the weight service.
"""
from __future__ import annotations

from datetime import date as date_type, timedelta
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import Domain, InjectionSite, Severity, Source
from vitals.i18n import t
from vitals.models.glp1 import DOMAIN, DosePhase, Injection, SideEffect
from vitals.services import alerts_service, conflict_engine, weight_service
from vitals.services.analytics.regression import fit_trend
from vitals.utils.timeutils import today_local

PLATEAU_ALERT_KEY = "glp1.plateau"

# A dose must have run at least this long before a plateau call is meaningful
# (early water-weight swings on a new dose aren't a plateau).
PLATEAU_MIN_DAYS = 14
# Weekly slope (kg/week) at or above which the trend counts as stalled. The
# trend is computed over the current phase with noise ranges excluded; a value
# of -0.1 means "losing less than 100 g/week" is treated as a plateau.
PLATEAU_SLOPE_THRESHOLD = -0.1

_INJECTION_SITES = frozenset(s.value for s in InjectionSite)


def _validate_injection(
    *, drug: str, dose_mg: float, site: Optional[str]
) -> tuple[str, Optional[str]]:
    """Sanitise write-path inputs before they touch the DB. The GLP-1 write tools
    are reachable from MCP (an LLM), which bypasses the HTML form entirely — so a
    hallucinated ``dose_mg=-5`` or a garbage ``site`` must be rejected here, not
    left to surface as a raw DB IntegrityError or, worse, to land in the data lake.

    ``drug`` stays free-text (real GLP-1 agonists are broader than the two-value
    enum) but must be non-empty; ``site`` must be a known ``InjectionSite`` or null.
    Returns the cleaned ``(drug, site)``.
    """
    clean_drug = (drug or "").strip()
    if not clean_drug:
        raise ValueError("drug is required")
    if dose_mg is None or dose_mg <= 0:
        raise ValueError("dose_mg must be a positive number")
    clean_site = (site or "").strip() or None
    if clean_site is not None and clean_site not in _INJECTION_SITES:
        raise ValueError(f"unknown injection site: {site!r}")
    return clean_drug, clean_site


# ── Injections ────────────────────────────────────────────────────────────────
async def log_injection(
    session: AsyncSession,
    *,
    on_date: date_type,
    drug: str,
    dose_mg: float,
    site: Optional[str] = None,
    note: Optional[str] = None,
    override: bool = False,
) -> Injection:
    drug, site = _validate_injection(drug=drug, dose_mg=dose_mg, site=site)
    await conflict_engine.enforce(
        session,
        Domain.GLP1.value,
        {"drug": drug, "dose_mg": dose_mg},
        override=override,
        entity_ref=f"injection:{on_date.isoformat()}",
    )
    row = Injection(
        date=on_date,
        domain=DOMAIN,
        source=Source.MANUAL.value,
        drug=drug,
        dose_mg=dose_mg,
        site=site,
        note=note,
    )
    session.add(row)
    await session.flush()
    return row


async def list_injections(session: AsyncSession) -> Sequence[Injection]:
    result = await session.execute(
        select(Injection).order_by(Injection.date.desc(), Injection.id.desc())
    )
    return result.scalars().all()


async def last_injection(session: AsyncSession) -> Optional[Injection]:
    result = await session.execute(
        select(Injection).order_by(Injection.date.desc(), Injection.id.desc()).limit(1)
    )
    return result.scalars().first()


async def update_injection(
    session: AsyncSession,
    injection_id: int,
    *,
    on_date: date_type,
    drug: str,
    dose_mg: float,
    site: Optional[str] = None,
    note: Optional[str] = None,
    override: bool = False,
) -> Optional[Injection]:
    row = await session.get(Injection, injection_id)
    if row is None:
        return None
    drug, site = _validate_injection(drug=drug, dose_mg=dose_mg, site=site)
    # Run the same conflict-engine gate as log_injection so editing a shot can't
    # slip past a cross-domain block that a fresh log would have caught.
    await conflict_engine.enforce(
        session,
        Domain.GLP1.value,
        {"drug": drug, "dose_mg": dose_mg},
        override=override,
        entity_ref=f"injection:{on_date.isoformat()}",
    )
    row.date = on_date
    row.drug = drug
    row.dose_mg = dose_mg
    row.site = site
    row.note = note
    await session.flush()
    return row


async def delete_injection(session: AsyncSession, injection_id: int) -> bool:
    row = await session.get(Injection, injection_id)
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


# ── Dose phases ───────────────────────────────────────────────────────────────
async def list_dose_phases(session: AsyncSession) -> Sequence[DosePhase]:
    result = await session.execute(
        select(DosePhase)
        .where(DosePhase.domain == DOMAIN)
        .order_by(DosePhase.start_date)
    )
    return result.scalars().all()


async def active_dose_phase(
    session: AsyncSession, *, on_date: Optional[date_type] = None
) -> Optional[DosePhase]:
    """The phase covering ``on_date`` (today by default): start <= date and
    (end is null or date <= end). The newest matching phase wins."""
    day = on_date or today_local()
    phases = await list_dose_phases(session)
    match: Optional[DosePhase] = None
    for p in phases:
        if p.start_date <= day and (p.end_date is None or day <= p.end_date):
            if match is None or p.start_date >= match.start_date:
                match = p
    return match


async def resolve_active(session: AsyncSession) -> list[dict]:
    """Conflict-engine resolver: the current dose phase (if any) as a match item
    — lets a rule reference "on drug X at dose >= Y" against the ongoing phase,
    not just a one-off injection being logged right now."""
    phase = await active_dose_phase(session)
    if phase is None:
        return []
    return [{"drug": phase.drug, "dose_mg": phase.dose_mg, "active": True}]


async def add_dose_phase(
    session: AsyncSession,
    *,
    start_date: date_type,
    drug: str,
    dose_mg: float,
    end_date: Optional[date_type] = None,
    note: Optional[str] = None,
) -> DosePhase:
    """Add a dose phase. If it's open-ended (no ``end_date``), close any other
    still-open phase the day before this one starts so the timeline doesn't
    overlap (a single current dose at a time)."""
    if end_date is None:
        result = await session.execute(
            select(DosePhase).where(
                DosePhase.domain == DOMAIN, DosePhase.end_date.is_(None)
            )
        )
        for open_phase in result.scalars().all():
            if open_phase.start_date < start_date:
                open_phase.end_date = start_date - timedelta(days=1)

    phase = DosePhase(
        domain=DOMAIN,
        source=Source.MANUAL.value,
        start_date=start_date,
        end_date=end_date,
        drug=drug,
        dose_mg=dose_mg,
        note=note,
    )
    session.add(phase)
    await session.flush()
    return phase


async def delete_dose_phase(session: AsyncSession, phase_id: int) -> bool:
    row = await session.get(DosePhase, phase_id)
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


async def dose_phase_overlays(session: AsyncSession) -> list[dict]:
    """Phases shaped for the weight chart's GLP-1 colour overlay."""
    phases = await list_dose_phases(session)
    return [
        {
            "start": p.start_date.isoformat(),
            "end": p.end_date.isoformat() if p.end_date else None,
            "drug": p.drug,
            "dose_mg": p.dose_mg,
            "label": f"{p.drug} {p.dose_mg:g} {t('common.mg')}",
        }
        for p in phases
    ]


# ── Side effects ──────────────────────────────────────────────────────────────
async def log_side_effect(
    session: AsyncSession,
    *,
    on_date: date_type,
    effect_type: str,
    severity: int,
    note: Optional[str] = None,
) -> SideEffect:
    row = SideEffect(
        date=on_date,
        domain=DOMAIN,
        source=Source.MANUAL.value,
        effect_type=effect_type,
        severity=severity,
        note=note,
    )
    session.add(row)
    await session.flush()
    return row


async def list_side_effects(session: AsyncSession) -> Sequence[SideEffect]:
    result = await session.execute(
        select(SideEffect).order_by(SideEffect.date.desc(), SideEffect.id.desc())
    )
    return result.scalars().all()


async def delete_side_effect(session: AsyncSession, effect_id: int) -> bool:
    row = await session.get(SideEffect, effect_id)
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


# ── Plateau detection ─────────────────────────────────────────────────────────
async def evaluate_plateau(
    session: AsyncSession, *, on_date: Optional[date_type] = None
) -> Optional[dict]:
    """Pure read: is the current dose plateaued? Returns a context dict
    (drug, dose, days_on_dose, slope_per_week) when a plateau is detected on the
    current phase, else ``None``. Writes nothing."""
    today = on_date or today_local()
    phase = await active_dose_phase(session, on_date=today)
    if phase is None:
        return None

    days_on_dose = (today - phase.start_date).days
    if days_on_dose < PLATEAU_MIN_DAYS:
        return None

    weights = await weight_service.list_active_weights(
        session, start=phase.start_date, end=today
    )
    points = [(w.date, w.weight_kg) for w in weights]
    ranges = await weight_service._noise_ranges(session)
    trend = fit_trend(points, exclude=ranges)
    if trend is None:
        return None

    if trend.slope_per_week >= PLATEAU_SLOPE_THRESHOLD:
        return {
            "drug": phase.drug,
            "dose_mg": phase.dose_mg,
            "days_on_dose": days_on_dose,
            "slope_per_week": round(trend.slope_per_week, 3),
        }
    return None


async def refresh_plateau_alert(
    session: AsyncSession, *, on_date: Optional[date_type] = None
) -> Optional[object]:
    """Raise a ``warn`` alert while the current dose is plateaued; resolve it once
    progress resumes (or the dose changes). Idempotent — safe on every dashboard
    load / scheduler tick. Respects same-day dismissal like the noise alert."""
    context = await evaluate_plateau(session, on_date=on_date)
    if context is not None:
        if await alerts_service._was_dismissed_today(session, PLATEAU_ALERT_KEY, ""):
            return None
        message = t(
            "alert.glp1_plateau",
            drug=context["drug"],
            dose=context["dose_mg"],
            days=context["days_on_dose"],
            slope=context["slope_per_week"],
        )
        return await alerts_service.raise_alert(
            session,
            domain=Domain.GLP1.value,
            severity=Severity.WARN.value,
            message=message,
            alert_key=PLATEAU_ALERT_KEY,
        )
    return await alerts_service.resolve_by_key(session, alert_key=PLATEAU_ALERT_KEY)


# ── Scheduler job ─────────────────────────────────────────────────────────────
async def plateau_job(session_factory, redis=None) -> None:
    """Daily plateau check (registered in vitals/scheduler/jobs.py). Runs the same
    refresh the dashboard does, so the alert is fresh even without a page load."""
    async with session_factory() as session:
        from vitals.services.language_service import get_language
        from vitals.i18n import current_lang
        lang = await get_language(session, redis)
        current_lang.set(lang)

        await refresh_plateau_alert(session)
        await session.commit()
