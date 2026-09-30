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
HRT_SITE_MAP: dict[str, str] = {
    "delt_l": "delt_left",
    "delt_r": "delt_right",
    "vg_l": "ventroglute_left",
    "vg_r": "ventroglute_right",
    "glute_l": "glute_left",
    "glute_r": "glute_right",
    "quad_l": "quad_left",
    "quad_r": "quad_right",
}


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
    if site_v is not None and site_v in HRT_SITE_MAP:
        site_v = HRT_SITE_MAP[site_v]
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
    if site_v is not None and site_v in HRT_SITE_MAP:
        site_v = HRT_SITE_MAP[site_v]
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


# ── Full view collection for API / UI ─────────────────────────────────────────
SITE_LABELS_RU = {
    "delt_left": "Дельта Л",
    "delt_right": "Дельта П",
    "ventroglute_left": "Вентроягодица Л",
    "ventroglute_right": "Вентроягодица П",
    "glute_left": "Ягодица Л",
    "glute_right": "Ягодица П",
    "quad_left": "Квадрицепс Л",
    "quad_right": "Квадрицепс П",
    "vastus_lateralis_left": "ВЛБ Л",
    "vastus_lateralis_right": "ВЛБ П",
}


def _cycle_progress_data(cycle: Optional[HrtCycle], today: date_type) -> Optional[dict]:
    if cycle is None:
        return None
    if not cycle.end_date:
        elapsed = max((today - cycle.start_date).days, 0)
        return {
            "week": elapsed // 7 + 1,
            "weeks": None,
            "pct": None,
        }
    total = (cycle.end_date - cycle.start_date).days + 1
    if total <= 0:
        return None
    elapsed = min(max((today - cycle.start_date).days + 1, 0), total)
    return {
        "week": (elapsed - 1) // 7 + 1 if elapsed else 0,
        "weeks": (total - 1) // 7 + 1,
        "pct": round(elapsed * 100 / total),
    }


async def collect(
    session: AsyncSession, *, on_date: Optional[date_type] = None
) -> dict[str, Any]:
    """Collect everything needed by the HRT screen in one round-trip."""
    from vitals.services import (
        hrt_cycle_service,
        hrt_reminders,
        hrt_template_service,
    )

    today = on_date or today_local()
    await hrt_reminders.refresh_all(session)

    compounds = await list_compounds(session, active_only=True)
    all_compounds = await list_compounds(session, active_only=False)
    compound_names = {c.key: (c.name_ru or c.name) for c in all_compounds}

    doses = await list_doses(session, limit=100)
    last = await last_dose(session)
    side_effects = await list_side_effects(session)
    active_c = await hrt_cycle_service.active_cycle(session, on_date=today)
    all_cycles = await hrt_cycle_service.list_cycles(session)
    all_templates = await hrt_template_service.list_templates(session)

    planned_admins = await hrt_cycle_service.planned_administrations(
        session, start=today, end=today + timedelta(days=21), cycle=active_c
    )
    release_pts = await hrt_cycle_service.release_series(
        session, start=today - timedelta(days=30), end=today + timedelta(days=60), cycle=active_c
    )

    # Active cycle details
    active_cycle_dict = None
    if active_c is not None:
        prog = _cycle_progress_data(active_c, today)
        cadence = hrt_reminders.PANEL_WINDOW_BY_KIND.get(active_c.kind, 90)
        items_list = []
        for it in active_c.items:
            items_list.append({
                "id": it.id,
                "compoundKey": it.compound_key,
                "name": compound_names.get(it.compound_key, it.compound_key),
                "dose": it.schedule[0].get("dose", 0.0) if it.schedule else 0.0,
                "unit": it.unit or "mg",
                "every": it.schedule[0].get("interval_days") if it.schedule else None,
                "from": (it.start_offset_days // 7) + 1 if it.start_offset_days else 1,
                "durationDays": it.schedule[0].get("duration_days") if it.schedule else None,
                "note": it.note,
            })
        active_cycle_dict = {
            "id": active_c.id,
            "kind": active_c.kind,
            "name": active_c.name or "",
            "start": active_c.start_date.isoformat(),
            "end": active_c.end_date.isoformat() if active_c.end_date else None,
            "note": active_c.note,
            "cadence": cadence,
            "week": prog["week"] if prog else None,
            "weeks": prog["weeks"] if prog else None,
            "pct": prog["pct"] if prog else None,
            "items": items_list,
        }

    # Format doses
    doses_list = []
    for d in doses:
        doses_list.append({
            "id": d.id,
            "date": d.date.isoformat(),
            "name": compound_names.get(d.compound_key, d.compound_key),
            "compoundKey": d.compound_key,
            "dose": f"{d.dose:g} {d.unit}",
            "doseVal": d.dose,
            "unit": d.unit,
            "ml": d.volume_ml,
            "brand": d.brand,
            "lab": d.lab,
            "batch": d.batch,
            "site": d.site,
            "note": d.note,
        })

    # Format side effects
    side_list = []
    for se in side_effects:
        side_list.append({
            "id": se.id,
            "date": se.date.isoformat(),
            "name": se.effect_type,
            "sev": se.severity,
            "note": se.note,
        })

    # Format templates
    tpl_list = []
    for t in all_templates:
        tpl_items = []
        for it in (t.items or []):
            comp_key = it.get("compound_key", "")
            comp_name = compound_names.get(comp_key, comp_key)
            start_week = (it.get("start_offset_days", 0) // 7)
            tpl_items.append([comp_name, start_week])
        tpl_list.append({
            "id": t.id,
            "name": t.name,
            "kind": t.kind,
            "items": tpl_items,
            "exportJson": hrt_template_service.export_template_json(t),
        })

    # Format planned administrations
    planned_list = []
    for pa in planned_admins[:12]:
        dt_val = pa["date"]
        comp_k = pa["compound_key"]
        dose_val = pa["dose"]
        unit_val = pa.get("unit") or "mg"
        planned_list.append({
            "date": dt_val.isoformat() if hasattr(dt_val, "isoformat") else str(dt_val),
            "name": compound_names.get(comp_k, comp_k),
            "dose": f"{dose_val:g} {unit_val}",
        })

    # Site counts & labels
    site_counts = site_frequency(doses)

    # Last dose dict
    last_dict = None
    if last is not None:
        last_dict = {
            "date": last.date.isoformat(),
            "name": compound_names.get(last.compound_key, last.compound_key),
            "dose": f"{last.dose:g} {last.unit}",
        }

    return {
        "cycle": active_cycle_dict,
        "doses": doses_list,
        "sideEffects": side_list,
        "templates": tpl_list,
        "planned": planned_list,
        "release": release_pts,
        "catalog": len(compounds),
        "compounds": [
            {
                "id": c.id,
                "key": c.key,
                "name": c.name_ru or c.name,
                "compoundClass": c.compound_class,
                "route": c.route,
                "doseUnit": c.dose_unit,
                "concMgMl": c.conc_mg_ml,
            }
            for c in compounds
        ],
        "siteLabels": SITE_LABELS_RU,
        "siteCounts": site_counts,
        "last": last_dict,
    }

