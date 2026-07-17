"""HRT / TRT domain service (PR #1 — tracker core).

Owns the HRT domain:

  * **Compounds** — read/manage the molecule catalog (seeded by
    ``hrt_catalog.sync_catalog``; the user may add custom rows).
  * **Doses** — CRUD over the administration log. Injectables are entered as
    ``volume_ml`` × concentration and the mg is computed here; orals/IU/mcg are
    entered directly. The write path is sanitised because the same functions are
    reachable from MCP (an LLM), which bypasses the HTML form.
  * **Side effects** — symptom log graded 1-5.
  * **resolve_active** — the conflict-engine resolver: compounds dosed recently
    (a trailing window) exposed as match items, so cross-domain rules (PR #3 —
    e.g. "on an oral 17aa with high ALT/AST") can reference the current protocol.

Mutating fns run the conflict-engine override plumbing so the override UX is
wired end-to-end, consistent with the weight/GLP-1 services — even though the
HRT rule catalog itself lands in PR #3.
"""
from __future__ import annotations

from datetime import date as date_type, timedelta
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import Domain, DoseUnit, HrtInjectionSite, Source
from vitals.models.hrt import (
    DOMAIN,
    HrtCompound,
    HrtCycle,
    HrtDose,
    HrtSideEffect,
)
from vitals.services import conflict_engine
from vitals.utils.timeutils import today_local

# A compound counts as part of the "current protocol" for conflict matching if
# it was dosed within this trailing window. A coarse stand-in until cycles
# (PR #2) give an explicit active-protocol definition.
RECENT_WINDOW_DAYS = 21

_UNITS = frozenset(u.value for u in DoseUnit)
_SITES = frozenset(s.value for s in HrtInjectionSite)


# ── Compounds (catalog) ─────────────────────────────────────────────────────
async def get_compound(session: AsyncSession, key: str) -> Optional[HrtCompound]:
    result = await session.execute(
        select(HrtCompound).where(HrtCompound.key == key)
    )
    return result.scalars().first()


async def list_compounds(
    session: AsyncSession,
    *,
    active_only: bool = True,
    compound_class: Optional[str] = None,
) -> Sequence[HrtCompound]:
    stmt = select(HrtCompound)
    if active_only:
        stmt = stmt.where(HrtCompound.active.is_(True))
    if compound_class:
        stmt = stmt.where(HrtCompound.compound_class == compound_class)
    stmt = stmt.order_by(HrtCompound.compound_class, HrtCompound.name)
    return (await session.execute(stmt)).scalars().all()


async def set_compound_active(
    session: AsyncSession, compound_id: int, *, active: bool
) -> Optional[HrtCompound]:
    row = await session.get(HrtCompound, compound_id)
    if row is None:
        return None
    row.active = active
    await session.flush()
    return row


# ── Dose amount resolution ──────────────────────────────────────────────────
def _resolve_amount(
    *,
    dose: Optional[float],
    unit: Optional[str],
    volume_ml: Optional[float],
    concentration_mg_ml: Optional[float],
    compound: Optional[HrtCompound],
) -> tuple[float, str]:
    """Work out the numeric dose and its unit. If ``dose`` is omitted but a
    volume and a concentration are known (measured, else the catalog's typical
    value), compute mg = ml × mg/ml. Returns ``(dose, unit)``; raises on
    non-positive or unresolvable input."""
    default_unit = compound.dose_unit if compound is not None else DoseUnit.MG.value
    unit = (unit or default_unit or DoseUnit.MG.value).strip().lower()

    if dose is None:
        conc = concentration_mg_ml
        if conc is None and compound is not None:
            conc = compound.conc_mg_ml
        if volume_ml is not None and conc is not None:
            dose = float(volume_ml) * float(conc)
            unit = DoseUnit.MG.value
        else:
            raise ValueError(
                "provide dose, or volume_ml together with a known concentration"
            )

    if dose is None or dose <= 0:
        raise ValueError("dose must be a positive number")
    if unit not in _UNITS:
        raise ValueError(f"unknown dose unit: {unit!r}")
    return float(dose), unit


def _clean_str(value: Optional[str]) -> Optional[str]:
    cleaned = (value or "").strip()
    return cleaned or None


# ── Doses ───────────────────────────────────────────────────────────────────
async def log_dose(
    session: AsyncSession,
    *,
    compound_key: str,
    on_date: date_type,
    dose: Optional[float] = None,
    unit: Optional[str] = None,
    volume_ml: Optional[float] = None,
    concentration_mg_ml: Optional[float] = None,
    brand: Optional[str] = None,
    lab: Optional[str] = None,
    batch: Optional[str] = None,
    site: Optional[str] = None,
    note: Optional[str] = None,
    override: bool = False,
) -> HrtDose:
    key = (compound_key or "").strip()
    if not key:
        raise ValueError("compound_key is required")
    compound = await get_compound(session, key)

    dose_v, unit_v = _resolve_amount(
        dose=dose,
        unit=unit,
        volume_ml=volume_ml,
        concentration_mg_ml=concentration_mg_ml,
        compound=compound,
    )
    site_v = _clean_str(site)
    if site_v is not None and site_v not in _SITES:
        raise ValueError(f"unknown injection site: {site!r}")

    await conflict_engine.enforce(
        session,
        Domain.HRT.value,
        {
            "compound_key": key,
            "compound_class": compound.compound_class if compound else None,
        },
        override=override,
        entity_ref=f"dose:{on_date.isoformat()}:{key}",
    )

    row = HrtDose(
        date=on_date,
        domain=DOMAIN,
        source=Source.MANUAL.value,
        compound_id=compound.id if compound else None,
        compound_key=key,
        dose=dose_v,
        unit=unit_v,
        volume_ml=volume_ml,
        concentration_mg_ml=concentration_mg_ml,
        brand=_clean_str(brand),
        lab=_clean_str(lab),
        batch=_clean_str(batch),
        site=site_v,
        note=note,
    )
    session.add(row)
    await session.flush()
    return row


async def list_doses(
    session: AsyncSession,
    *,
    start: Optional[date_type] = None,
    end: Optional[date_type] = None,
    limit: Optional[int] = None,
) -> Sequence[HrtDose]:
    stmt = select(HrtDose)
    if start is not None:
        stmt = stmt.where(HrtDose.date >= start)
    if end is not None:
        stmt = stmt.where(HrtDose.date <= end)
    stmt = stmt.order_by(HrtDose.date.desc(), HrtDose.id.desc())
    if limit is not None:
        stmt = stmt.limit(limit)
    return (await session.execute(stmt)).scalars().all()


async def last_dose(session: AsyncSession) -> Optional[HrtDose]:
    result = await session.execute(
        select(HrtDose).order_by(HrtDose.date.desc(), HrtDose.id.desc()).limit(1)
    )
    return result.scalars().first()


def site_frequency(doses: Sequence[HrtDose]) -> dict[str, int]:
    """How many times each body-map site has been used — feeds the rotation
    mini-map. Pure function over already-fetched rows."""
    counts: dict[str, int] = {}
    for d in doses:
        if d.site:
            counts[d.site] = counts.get(d.site, 0) + 1
    return counts


async def update_dose(
    session: AsyncSession,
    dose_id: int,
    *,
    compound_key: str,
    on_date: date_type,
    dose: Optional[float] = None,
    unit: Optional[str] = None,
    volume_ml: Optional[float] = None,
    concentration_mg_ml: Optional[float] = None,
    brand: Optional[str] = None,
    lab: Optional[str] = None,
    batch: Optional[str] = None,
    site: Optional[str] = None,
    note: Optional[str] = None,
    override: bool = False,
) -> Optional[HrtDose]:
    row = await session.get(HrtDose, dose_id)
    if row is None:
        return None
    key = (compound_key or "").strip()
    if not key:
        raise ValueError("compound_key is required")
    compound = await get_compound(session, key)
    dose_v, unit_v = _resolve_amount(
        dose=dose,
        unit=unit,
        volume_ml=volume_ml,
        concentration_mg_ml=concentration_mg_ml,
        compound=compound,
    )
    site_v = _clean_str(site)
    if site_v is not None and site_v not in _SITES:
        raise ValueError(f"unknown injection site: {site!r}")

    await conflict_engine.enforce(
        session,
        Domain.HRT.value,
        {
            "compound_key": key,
            "compound_class": compound.compound_class if compound else None,
        },
        override=override,
        entity_ref=f"dose:{on_date.isoformat()}:{key}",
    )

    row.date = on_date
    row.compound_id = compound.id if compound else None
    row.compound_key = key
    row.dose = dose_v
    row.unit = unit_v
    row.volume_ml = volume_ml
    row.concentration_mg_ml = concentration_mg_ml
    row.brand = _clean_str(brand)
    row.lab = _clean_str(lab)
    row.batch = _clean_str(batch)
    row.site = site_v
    row.note = note
    await session.flush()
    return row


async def delete_dose(session: AsyncSession, dose_id: int) -> bool:
    row = await session.get(HrtDose, dose_id)
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


# ── Side effects ─────────────────────────────────────────────────────────────
async def log_side_effect(
    session: AsyncSession,
    *,
    on_date: date_type,
    effect_type: str,
    severity: int,
    note: Optional[str] = None,
) -> HrtSideEffect:
    clean_type = (effect_type or "").strip()
    if not clean_type:
        raise ValueError("effect_type is required")
    if severity is None or not (1 <= severity <= 5):
        raise ValueError("severity must be between 1 and 5")
    row = HrtSideEffect(
        date=on_date,
        domain=DOMAIN,
        source=Source.MANUAL.value,
        effect_type=clean_type,
        severity=severity,
        note=note,
    )
    session.add(row)
    await session.flush()
    return row


async def list_side_effects(session: AsyncSession) -> Sequence[HrtSideEffect]:
    result = await session.execute(
        select(HrtSideEffect).order_by(
            HrtSideEffect.date.desc(), HrtSideEffect.id.desc()
        )
    )
    return result.scalars().all()


async def delete_side_effect(session: AsyncSession, effect_id: int) -> bool:
    row = await session.get(HrtSideEffect, effect_id)
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


# ── Conflict-engine resolver ─────────────────────────────────────────────────
async def resolve_active(session: AsyncSession) -> list[dict]:
    """Current protocol as conflict-engine match items — lets a cross-domain rule
    reference "on an oral 17aa" or "on testosterone" (vs high liver enzymes /
    hematocrit from Labs) rather than only the single dose being logged. Combines
    compounds dosed within ``RECENT_WINDOW_DAYS`` with the active cycle's planned
    compounds. One item per distinct compound; catalog metadata joined in."""
    today = today_local()
    seen: dict[str, dict] = {}

    def _add(key, compound_class, route, aromatizes):
        if key and key not in seen:
            seen[key] = {
                "compound_key": key,
                "compound_class": compound_class,
                "route": route,
                "aromatizes": aromatizes,
                "active": True,
            }

    # Recently logged doses.
    cutoff = today - timedelta(days=RECENT_WINDOW_DAYS)
    result = await session.execute(
        select(
            HrtDose.compound_key,
            HrtCompound.compound_class,
            HrtCompound.route,
            HrtCompound.aromatizes,
        )
        .join(HrtCompound, HrtDose.compound_id == HrtCompound.id, isouter=True)
        .where(HrtDose.date >= cutoff)
    )
    for key, compound_class, route, aromatizes in result:
        _add(key, compound_class, route, aromatizes)

    # Compounds planned in the cycle covering today.
    cycles = (
        await session.execute(
            select(HrtCycle)
            .where(HrtCycle.domain == DOMAIN)
            .order_by(HrtCycle.start_date.desc())
        )
    ).scalars().all()
    active = next(
        (c for c in cycles
         if c.start_date <= today and (c.end_date is None or today <= c.end_date)),
        None,
    )
    if active is not None:
        for item in active.items:
            compound = (
                await session.execute(
                    select(
                        HrtCompound.compound_class,
                        HrtCompound.route,
                        HrtCompound.aromatizes,
                    ).where(HrtCompound.id == item.compound_id)
                )
            ).first() if item.compound_id else None
            if compound is not None:
                _add(item.compound_key, compound[0], compound[1], compound[2])
            else:
                _add(item.compound_key, None, None, None)

    return list(seen.values())
