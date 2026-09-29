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
    if clean_site == "shoulder_left":
        clean_site = "arm_left"
    elif clean_site == "shoulder_right":
        clean_site = "arm_right"
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


def site_frequency(injections: Sequence[Injection]) -> dict[str, int]:
    """How many times each body-map site has been used — feeds the rotation
    mini-map (I1) so the owner can see at a glance which sites are overdue for
    reuse. Pure function over already-fetched rows, no extra query."""
    counts: dict[str, int] = {}
    for inj in injections:
        if inj.site:
            counts[inj.site] = counts.get(inj.site, 0) + 1
    return counts


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
    """Raise a ``note`` alert while the current dose is plateaued; resolve it once
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
            # A plateau is a reading of the trend, not something that went
            # wrong — the quiet ``note`` tone, not amber.
            severity=Severity.NOTE.value,
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


# ── Full view collection for API / UI ─────────────────────────────────────────
SITE_TO_FRONTEND: dict[str, str] = {
    "arm_left": "shoulder_left",
    "arm_right": "shoulder_right",
    "shoulder_left": "shoulder_left",
    "shoulder_right": "shoulder_right",
    "abdomen_left": "abdomen_left",
    "abdomen_right": "abdomen_right",
    "thigh_left": "thigh_left",
    "thigh_right": "thigh_right",
}


async def collect(
    session: AsyncSession, *, on_date: Optional[date_type] = None
) -> dict[str, Any]:
    """Collect everything needed by the GLP-1 screen in one round-trip."""
    today = on_date or today_local()
    active_phase = await active_dose_phase(session, on_date=today)
    injections = await list_injections(session)
    last_inj = injections[0] if injections else None
    phases = await list_dose_phases(session)
    side_effects = await list_side_effects(session)

    drug = active_phase.drug if active_phase else (last_inj.drug if last_inj else "Семаглутид")
    dose_mg = active_phase.dose_mg if active_phase else (last_inj.dose_mg if last_inj else 0.0)
    since_date = active_phase.start_date if active_phase else (last_inj.date if last_inj else today)
    since_iso = since_date.isoformat()
    day_on_dose = max(1, (today - since_date).days + 1) if active_phase else 0

    if last_inj:
        last_iso = last_inj.date.isoformat()
        next_date = last_inj.date + timedelta(days=7)
        next_iso = next_date.isoformat()
        days_to_next = max(0, (next_date - today).days)
        unscheduled = False
    else:
        last_iso = None
        next_iso = today.isoformat()
        days_to_next = 0
        unscheduled = True

    cycle = {
        "lastIso": last_iso,
        "nextIso": next_iso,
        "daysToNext": days_to_next,
        "unscheduled": unscheduled,
    }

    dose_phases_list = []
    for p in sorted(phases, key=lambda x: x.start_date):
        dose_phases_list.append({
            "id": p.id,
            "fromIso": p.start_date.isoformat(),
            "toIso": (p.end_date or today).isoformat(),
            "doseMg": p.dose_mg,
            "drug": p.drug,
            "note": p.note,
        })

    start_trend = phases[0].start_date if phases else (today - timedelta(days=90))
    weights = await weight_service.list_active_weights(session, start=start_trend, end=today)
    trend = [{"date": w.date.isoformat(), "kg": w.weight_kg} for w in weights]

    plateau_info = await evaluate_plateau(session, on_date=today)
    if plateau_info:
        summary = t(
            "alert.glp1_plateau",
            drug=plateau_info["drug"],
            dose=plateau_info["dose_mg"],
            days=plateau_info["days_on_dose"],
            slope=plateau_info["slope_per_week"],
        )
    elif active_phase and len(trend) >= 2:
        diff_kg = trend[-1]["kg"] - trend[0]["kg"]
        sign = "−" if diff_kg < 0 else "+"
        summary = f"На {dose_mg:g} мг: {sign}{abs(diff_kg):.1f} кг с {since_iso}."
    else:
        summary = ""

    site_labels = {
        "shoulder_left": "Плечо Л",
        "shoulder_right": "Плечо П",
        "abdomen_left": "Живот Л",
        "abdomen_right": "Живот П",
        "thigh_left": "Бедро Л",
        "thigh_right": "Бедро П",
    }

    inj_list = []
    for inj in injections:
        site_key = SITE_TO_FRONTEND.get(inj.site, inj.site or "abdomen_left")
        inj_list.append({
            "id": inj.id,
            "dateIso": inj.date.isoformat(),
            "site": site_key,
            "doseMg": inj.dose_mg,
            "drug": inj.drug,
            "note": inj.note,
        })

    se_list = []
    for se in side_effects:
        se_list.append({
            "id": se.id,
            "dateIso": se.date.isoformat(),
            "name": se.effect_type,
            "severity": se.severity,
            "note": se.note,
        })

    return {
        "drug": drug,
        "doseMg": dose_mg,
        "sinceIso": since_iso,
        "dayOnDose": day_on_dose,
        "cycle": cycle,
        "dosePhases": dose_phases_list,
        "trend": trend,
        "summary": summary,
        "siteLabels": site_labels,
        "injections": inj_list,
        "sideEffects": se_list,
    }

