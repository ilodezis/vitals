"""Skincare service (Phase 3).

The evening checklist upsert is the conflict-engine hot path: its boolean flags
*are* the proposed state, so "retinoid + peel same evening" (a same-domain rule)
and "active isotretinoin → no peel" (supplements ↔ skincare) both evaluate off
the checklist being saved. :func:`resolve_today` exposes today's checklist to
rules triggered from *other* domains (e.g. activating isotretinoin today).
"""
from __future__ import annotations

from datetime import date as date_type
from typing import Any, Optional, Sequence

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import Domain, Source
from vitals.models.skincare import DOMAIN, SkincareLog, SkincareObservation, SkincareProduct
from vitals.services import conflict_engine
from vitals.utils.timeutils import today_local

_FLAGS = (
    "retinoid", "azelaic", "peel", "niacinamide_spf", "moisturizer",
    "vitamin_c", "benzoyl_peroxide",
)


# ── Checklist log ─────────────────────────────────────────────────────────────
async def get_log(session: AsyncSession, on_date: date_type) -> Optional[SkincareLog]:
    result = await session.execute(
        select(SkincareLog).where(SkincareLog.date == on_date)
    )
    return result.scalar_one_or_none()


async def upsert_log(
    session: AsyncSession,
    *,
    on_date: date_type,
    retinoid: bool = False,
    azelaic: bool = False,
    peel: bool = False,
    niacinamide_spf: bool = False,
    moisturizer: bool = False,
    vitamin_c: bool = False,
    benzoyl_peroxide: bool = False,
    note: Optional[str] = None,
    override: bool = False,
) -> SkincareLog:
    proposed = {
        "retinoid": retinoid,
        "azelaic": azelaic,
        "peel": peel,
        "niacinamide_spf": niacinamide_spf,
        "moisturizer": moisturizer,
        "vitamin_c": vitamin_c,
        "benzoyl_peroxide": benzoyl_peroxide,
    }
    await conflict_engine.enforce(
        session,
        Domain.SKINCARE.value,
        proposed,
        override=override,
        entity_ref=f"skincare:{on_date.isoformat()}",
    )

    row = await get_log(session, on_date)
    if row is None:
        row = SkincareLog(date=on_date, domain=DOMAIN, source=Source.MANUAL.value)
        session.add(row)
    row.retinoid = retinoid
    row.azelaic = azelaic
    row.peel = peel
    row.niacinamide_spf = niacinamide_spf
    row.moisturizer = moisturizer
    row.vitamin_c = vitamin_c
    row.benzoyl_peroxide = benzoyl_peroxide
    if note is not None:
        row.note = note
    await session.flush()
    return row


async def list_logs(session: AsyncSession) -> Sequence[SkincareLog]:
    result = await session.execute(
        select(SkincareLog).order_by(SkincareLog.date.desc())
    )
    return result.scalars().all()


async def delete_log(session: AsyncSession, log_id: int) -> bool:
    row = await session.get(SkincareLog, log_id)
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


# ── Observations ──────────────────────────────────────────────────────────────
async def add_observation(
    session: AsyncSession,
    *,
    on_date: date_type,
    inflammation: Optional[int] = None,
    pih: Optional[int] = None,
    zone: Optional[str] = None,
    note: Optional[str] = None,
) -> SkincareObservation:
    row = SkincareObservation(
        date=on_date,
        domain=DOMAIN,
        source=Source.MANUAL.value,
        inflammation=inflammation,
        pih=pih,
        zone=zone,
        note=note,
    )
    session.add(row)
    await session.flush()
    return row


async def list_observations(session: AsyncSession) -> Sequence[SkincareObservation]:
    result = await session.execute(
        select(SkincareObservation).order_by(
            SkincareObservation.date.desc(), SkincareObservation.id.desc()
        )
    )
    return result.scalars().all()


async def delete_observation(session: AsyncSession, observation_id: int) -> bool:
    row = await session.get(SkincareObservation, observation_id)
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


# ── Conflict-engine resolver ──────────────────────────────────────────────────
async def resolve_today(session: AsyncSession) -> list[dict]:
    """Today's checklist flags as a single match item (empty list if no log yet)."""
    row = await get_log(session, today_local())
    if row is None:
        return []
    return [{flag: getattr(row, flag) for flag in _FLAGS}]


# ── Skincare Products CRUD ───────────────────────────────────────────────────
async def list_products(
    session: AsyncSession, *, active_only: bool = False
) -> Sequence[SkincareProduct]:
    stmt = select(SkincareProduct)
    if active_only:
        stmt = stmt.where(SkincareProduct.active.is_(True))
    stmt = stmt.order_by(SkincareProduct.active.desc(), SkincareProduct.name)
    result = await session.execute(stmt)
    return result.scalars().all()


async def add_product(
    session: AsyncSession,
    *,
    name: str,
    type: str,
    active_ingredient: Optional[str] = None,
    description: Optional[str] = None,
    usage_instructions: Optional[str] = None,
    default_time: str = "evening",
    schedule_days: list[int] = [],
    active: bool = True,
) -> SkincareProduct:
    row = SkincareProduct(
        name=name,
        type=type,
        active_ingredient=active_ingredient,
        description=description,
        usage_instructions=usage_instructions,
        default_time=default_time,
        schedule_days=schedule_days,
        active=active,
    )
    session.add(row)
    await session.flush()
    return row


async def update_product(
    session: AsyncSession,
    product_id: int,
    *,
    name: str,
    type: str,
    active_ingredient: Optional[str] = None,
    description: Optional[str] = None,
    usage_instructions: Optional[str] = None,
    default_time: str = "evening",
    schedule_days: list[int] = [],
    active: bool = True,
) -> Optional[SkincareProduct]:
    row = await session.get(SkincareProduct, product_id)
    if row is None:
        return None
    row.name = name
    row.type = type
    row.active_ingredient = active_ingredient
    row.description = description
    row.usage_instructions = usage_instructions
    row.default_time = default_time
    row.schedule_days = schedule_days
    row.active = active
    await session.flush()
    return row


async def delete_product(session: AsyncSession, product_id: int) -> bool:
    row = await session.get(SkincareProduct, product_id)
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


# ── Full view collection for API / UI ─────────────────────────────────────────
async def collect(session: AsyncSession) -> dict[str, Any]:
    """Collect everything needed by the Skincare dashboard in one round-trip."""
    from vitals.models.conflict_rule import ConflictRule
    from vitals.services import alerts_service

    products = await list_products(session)
    logs = await list_logs(session)
    observations = await list_observations(session)
    today_l = await get_log(session, today_local())
    active_alerts = await alerts_service.list_active(session, domain=Domain.SKINCARE.value)

    # Active conflict rules concerning skincare
    rules_stmt = select(ConflictRule).where(
        ConflictRule.active.is_(True),
        or_(ConflictRule.domain_a == "skincare", ConflictRule.domain_b == "skincare"),
    )
    rules_result = await session.execute(rules_stmt)
    conflict_rules = rules_result.scalars().all()

    prods_data = [
        {
            "id": p.id,
            "name": p.name,
            "type": p.type,
            "active_ingredient": p.active_ingredient,
            "ing": p.active_ingredient,
            "description": p.description,
            "desc": p.description,
            "usage_instructions": p.usage_instructions,
            "use": p.usage_instructions,
            "default_time": p.default_time,
            "time": p.default_time,
            "schedule_days": p.schedule_days or [],
            "days": p.schedule_days or [],
            "active": p.active,
            "on": p.active,
        }
        for p in products
    ]

    logs_data = [
        {
            "id": l.id,
            "date": l.date.isoformat(),
            "retinoid": l.retinoid,
            "azelaic": l.azelaic,
            "peel": l.peel,
            "niacinamide_spf": l.niacinamide_spf,
            "moisturizer": l.moisturizer,
            "vitamin_c": l.vitamin_c,
            "benzoyl_peroxide": l.benzoyl_peroxide,
            "note": l.note,
        }
        for l in logs
    ]

    obs_data = [
        {
            "id": o.id,
            "date": o.date.isoformat(),
            "inflammation": o.inflammation,
            "inf": o.inflammation,
            "pih": o.pih,
            "zone": o.zone,
            "note": o.note,
        }
        for o in observations
    ]

    rules_data = [
        {
            "id": r.id,
            "code": r.code,
            "severity": r.severity,
            "sev": r.severity,
            "kind": r.category or "other",
            "msg": r.message,
            "hard": r.severity == "block",
        }
        for r in conflict_rules
    ]

    today_log_data = (
        {
            "id": today_l.id,
            "date": today_l.date.isoformat(),
            "retinoid": today_l.retinoid,
            "azelaic": today_l.azelaic,
            "peel": today_l.peel,
            "niacinamide_spf": today_l.niacinamide_spf,
            "moisturizer": today_l.moisturizer,
            "vitamin_c": today_l.vitamin_c,
            "benzoyl_peroxide": today_l.benzoyl_peroxide,
            "note": today_l.note,
        }
        if today_l
        else None
    )

    active_prods = [p for p in prods_data if p["active"]]

    return {
        "products": prods_data,
        "active_count": len(active_prods),
        "total_count": len(prods_data),
        "today_log": today_log_data,
        "logs": logs_data,
        "observations": obs_data,
        "rules": rules_data,
        "alerts": [
            {
                "id": a.id,
                "domain": a.domain,
                "severity": a.severity,
                "alert_key": a.alert_key,
                "message": a.message,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in active_alerts
        ],
        "today": today_local().isoformat(),
    }

