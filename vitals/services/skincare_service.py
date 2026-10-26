"""Skincare service (Phase 3).

The evening checklist upsert is the conflict-engine hot path: its boolean flags
*are* the proposed state, so "retinoid + peel same evening" (a same-domain rule)
and "active isotretinoin → no peel" (supplements ↔ skincare) both evaluate off
the checklist being saved. :func:`resolve_today` exposes today's checklist to
rules triggered from *other* domains (e.g. activating isotretinoin today).

**Done-tracking.** The day's plan is the catalog read for a date: every active
product whose ``schedule_days`` include that weekday, in the slot(s) its
``default_time`` names. Ticking one writes a ``SkincareCheck`` and sets the
product's ``active_flag`` on that day's ``SkincareLog`` — so the checklist the
engine evaluates is now *what was ticked*, and the old hand-filled form is no
longer needed to feed it. Unticking clears the flag only when no other tick of
the day still carries it.

**The routine day.** "Today" here is :func:`prefs.routine_today`, not the
calendar: until the owner's day ends (05:00 by default) an evening round still
belongs to the evening before, so the plan, the ticks and the conflict check all
land on the night they were done.

**How and when.** Products come in their order of application (``step``), and
each plan item carries ``how`` — the product's instructions for that slot. A
slot of a day can also carry a note (``SkincareNote``): «ретиноид сегодня
пропусти», shown above the checklist.
"""
from __future__ import annotations

from datetime import date as date_type, timedelta
from typing import Any, Optional, Sequence

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import Domain, Source
from vitals.models.skincare import (
    DOMAIN,
    SkincareCheck,
    SkincareLog,
    SkincareNote,
    SkincareObservation,
    SkincarePhoto,
    SkincareProduct,
)
from vitals.services import conflict_engine, photo_derivatives
from vitals.services.proactive import prefs
from vitals.utils.timeutils import now_local

_FLAGS = (
    "retinoid", "azelaic", "peel", "niacinamide_spf", "moisturizer",
    "vitamin_c", "benzoyl_peroxide",
)
# The flags a product can be mapped to — the same set, public for the API.
ACTIVE_FLAGS = _FLAGS

SLOT_MORNING = "morning"
SLOT_EVENING = "evening"
SLOTS = (SLOT_MORNING, SLOT_EVENING)

# How far back the diary shows planned-vs-done. Two weeks reads as a pattern;
# further back the schedule it is measured against may well have changed.
HISTORY_DAYS = 14

# A note is a line or two above a checklist, not a diary entry.
NOTE_MAX_CHARS = 500


async def today(session: AsyncSession) -> date_type:
    """The routine day the skincare checklist is on right now."""
    return await prefs.routine_today(session)


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
    row = await get_log(session, await today(session))
    if row is None:
        return []
    return [{flag: getattr(row, flag) for flag in _FLAGS}]


# ── The day's plan and what was done ─────────────────────────────────────────
def schedule_weekday(on_date: date_type) -> int:
    """The catalog's weekday numbering: Monday=1 … Saturday=6, Sunday=0 (JS ``getDay``)."""
    return (on_date.weekday() + 1) % 7


def scheduled_in(product: SkincareProduct, on_date: date_type, slot: str) -> bool:
    """Is ``product`` planned for ``slot`` on ``on_date``?"""
    if not product.active:
        return False
    if schedule_weekday(on_date) not in (product.schedule_days or []):
        return False
    time = product.default_time or SLOT_EVENING
    return time == "both" or time == slot


def _clean_flag(flag: Optional[str]) -> Optional[str]:
    return flag if flag in _FLAGS else None


def how_to(product: SkincareProduct, slot: str) -> Optional[str]:
    """How to apply ``product`` in ``slot``: that slot's own instructions, else
    the general ones."""
    own = product.usage_morning if slot == SLOT_MORNING else product.usage_evening
    return (own or product.usage_instructions or "").strip() or None


async def checks_between(
    session: AsyncSession, start: date_type, end: date_type
) -> Sequence[SkincareCheck]:
    result = await session.execute(
        select(SkincareCheck)
        .where(SkincareCheck.date >= start, SkincareCheck.date <= end)
        .order_by(SkincareCheck.date, SkincareCheck.done_at)
    )
    return result.scalars().all()


async def notes_between(
    session: AsyncSession, start: date_type, end: date_type
) -> Sequence[SkincareNote]:
    result = await session.execute(
        select(SkincareNote).where(SkincareNote.date >= start, SkincareNote.date <= end)
    )
    return result.scalars().all()


def _plan_from(
    products: Sequence[SkincareProduct],
    checks: Sequence[SkincareCheck],
    on_date: date_type,
    notes: Sequence[SkincareNote] = (),
) -> dict[str, Any]:
    """``{slot: [item, …], "notes": {slot: text}}`` for one day. An item is a
    planned product with its tick, or a tick on a product that was *not* planned
    that day (applied off schedule) — the plan alone would lose those. ``notes``
    holds only the slots that have one."""
    day_checks = [c for c in checks if c.date == on_date]
    by_id = {p.id: p for p in products}
    plan: dict[str, Any] = {}
    for slot in SLOTS:
        done = {c.product_id: c for c in day_checks if c.slot == slot}
        items = []
        for p in products:
            if not scheduled_in(p, on_date, slot):
                continue
            check = done.pop(p.id, None)
            items.append(
                {
                    "product_id": p.id,
                    "name": p.name,
                    "flag": _clean_flag(p.active_flag),
                    "how": how_to(p, slot),
                    "planned": True,
                    "done": check is not None,
                    "done_at": check.done_at.isoformat() if check is not None else None,
                }
            )
        for check in done.values():
            product = by_id.get(check.product_id)
            items.append(
                {
                    "product_id": check.product_id,
                    "name": check.product_name,
                    "flag": _clean_flag(check.active_flag),
                    "how": how_to(product, slot) if product is not None else None,
                    "planned": False,
                    "done": True,
                    "done_at": check.done_at.isoformat(),
                }
            )
        plan[slot] = items
    plan["notes"] = {n.slot: n.text for n in notes if n.date == on_date and n.slot in SLOTS}
    return plan


async def plan_for(session: AsyncSession, on_date: date_type) -> dict[str, Any]:
    """The day's routine, slot by slot, each item with whether it was done, plus
    the day's notes."""
    products = await list_products(session, active_only=True)
    checks = await checks_between(session, on_date, on_date)
    notes = await notes_between(session, on_date, on_date)
    return _plan_from(products, checks, on_date, notes)


async def plans_between(
    session: AsyncSession, start: date_type, end: date_type
) -> list[dict]:
    """``[{"date", "morning", "evening"}, …]`` for every day from ``end`` back to
    ``start`` (both inclusive), newest first — :func:`plan_for` over a range, with
    one read of the catalog and the ticks."""
    products = await list_products(session, active_only=True)
    checks = await checks_between(session, start, end)
    notes = await notes_between(session, start, end)
    out = []
    day = end
    while day >= start:
        out.append({"date": day.isoformat(), **_plan_from(products, checks, day, notes)})
        day -= timedelta(days=1)
    return out


async def history(
    session: AsyncSession, *, end: Optional[date_type] = None, days: int = HISTORY_DAYS
) -> list[dict]:
    """Planned vs done for the last ``days`` days before ``end`` (exclusive),
    newest first.

    Starts no earlier than the first tick ever recorded: before tracking existed
    every planned product would read as missed, which is a fact about the app,
    not about the skin.
    """
    end = end or await today(session)
    first = (
        await session.execute(select(SkincareCheck.date).order_by(SkincareCheck.date).limit(1))
    ).scalars().first()
    if first is None:
        return []
    start = max(first, end - timedelta(days=days))
    if start >= end:
        return []
    products = await list_products(session, active_only=True)
    checks = await checks_between(session, start, end - timedelta(days=1))
    notes = await notes_between(session, start, end - timedelta(days=1))
    out = []
    day = end - timedelta(days=1)
    while day >= start:
        plan = _plan_from(products, checks, day, notes)
        if any(plan[slot] for slot in SLOTS):
            out.append({"date": day.isoformat(), **plan})
        day -= timedelta(days=1)
    return out


async def _get_check(
    session: AsyncSession, on_date: date_type, product_id: int, slot: str
) -> Optional[SkincareCheck]:
    result = await session.execute(
        select(SkincareCheck).where(
            SkincareCheck.date == on_date,
            SkincareCheck.product_id == product_id,
            SkincareCheck.slot == slot,
        )
    )
    return result.scalars().first()


async def set_check(
    session: AsyncSession,
    *,
    on_date: date_type,
    product_id: int,
    slot: str,
    done: bool,
    override: bool = False,
    source: str = Source.MANUAL.value,
) -> list:
    """Tick or untick one product in one slot. Idempotent either way.

    Ticking a product with a flag runs the conflict engine on the day's checklist
    *with that flag set* — the same evaluation the hand-filled form used to run —
    and raises :class:`ConflictBlocked` on a blocking rule unless ``override``.
    Returns the violations that fired (non-blocking, or overridden).

    Raises ``LookupError`` for an unknown product and ``ValueError`` for an
    unknown slot.
    """
    if slot not in SLOTS:
        raise ValueError(f"unknown slot: {slot}")
    existing = await _get_check(session, on_date, product_id, slot)

    if not done:
        if existing is None:
            return []
        flag = _clean_flag(existing.active_flag)
        await session.delete(existing)
        await session.flush()
        if flag is not None:
            await _clear_flag_if_unused(session, on_date, flag)
        return []

    if existing is not None:
        return []
    product = await session.get(SkincareProduct, product_id)
    if product is None:
        raise LookupError(f"no skincare product {product_id}")

    flag = _clean_flag(product.active_flag)
    violations: list = []
    log = await get_log(session, on_date)
    if flag is not None and not (log is not None and getattr(log, flag)):
        proposed = {f: bool(log is not None and getattr(log, f)) for f in _FLAGS}
        proposed[flag] = True
        violations = await conflict_engine.enforce(
            session,
            Domain.SKINCARE.value,
            proposed,
            override=override,
            entity_ref=f"skincare:{on_date.isoformat()}",
        )
        if log is None:
            log = SkincareLog(date=on_date, domain=DOMAIN, source=source)
            session.add(log)
        setattr(log, flag, True)

    session.add(
        SkincareCheck(
            date=on_date,
            domain=DOMAIN,
            source=source,
            product_id=product.id,
            product_name=product.name,
            slot=slot,
            active_flag=flag,
            done_at=now_local(),
        )
    )
    await session.flush()
    return violations


async def _clear_flag_if_unused(session: AsyncSession, on_date: date_type, flag: str) -> None:
    """Drop ``flag`` from the day's log unless another tick still sets it. A log
    left with nothing on it and no note is removed: it would only show up in the
    diary as an empty day."""
    still = (
        await session.execute(
            select(SkincareCheck.id).where(
                SkincareCheck.date == on_date, SkincareCheck.active_flag == flag
            )
        )
    ).scalars().first()
    if still is not None:
        return
    log = await get_log(session, on_date)
    if log is None:
        return
    setattr(log, flag, False)
    if not any(getattr(log, f) for f in _FLAGS) and not log.note:
        await session.delete(log)
    await session.flush()


async def complete_slot(
    session: AsyncSession,
    *,
    on_date: date_type,
    slot: str,
    override: bool = False,
    source: str = Source.MANUAL.value,
) -> list:
    """Tick everything planned for ``slot`` that is still open. Returns the
    violations that fired along the way."""
    violations: list = []
    for item in (await plan_for(session, on_date))[slot]:
        if item["done"] or item["product_id"] is None:
            continue
        violations += await set_check(
            session,
            on_date=on_date,
            product_id=item["product_id"],
            slot=slot,
            done=True,
            override=override,
            source=source,
        )
    return violations


# ── Notes on a slot of a day ─────────────────────────────────────────────────
async def set_note(
    session: AsyncSession,
    *,
    on_date: date_type,
    slot: str,
    text: Optional[str],
    source: str = Source.MANUAL.value,
) -> Optional[SkincareNote]:
    """Write the note on ``slot`` of ``on_date``, replacing any there. Empty text
    removes it (returns ``None``). Raises ``ValueError`` for an unknown slot or a
    note past :data:`NOTE_MAX_CHARS`."""
    if slot not in SLOTS:
        raise ValueError(f"unknown slot: {slot}")
    text = (text or "").strip()
    if len(text) > NOTE_MAX_CHARS:
        raise ValueError(f"a note is at most {NOTE_MAX_CHARS} characters")
    result = await session.execute(
        select(SkincareNote).where(SkincareNote.date == on_date, SkincareNote.slot == slot)
    )
    row = result.scalar_one_or_none()
    if not text:
        if row is not None:
            await session.delete(row)
            await session.flush()
        return None
    if row is None:
        row = SkincareNote(date=on_date, domain=DOMAIN, source=source, slot=slot, text=text)
        session.add(row)
    else:
        row.text = text
        row.source = source
    await session.flush()
    return row


# ── Face photo diary ──────────────────────────────────────────────────────────
async def add_photo(
    session: AsyncSession, *, on_date: date_type, file_key: str, note: Optional[str] = None
) -> SkincarePhoto:
    photo = SkincarePhoto(
        date=on_date, domain=DOMAIN, source=Source.MANUAL.value, file_key=file_key, note=note
    )
    session.add(photo)
    await session.flush()
    return photo


async def list_photos(session: AsyncSession) -> Sequence[SkincarePhoto]:
    result = await session.execute(
        select(SkincarePhoto).order_by(SkincarePhoto.date.desc(), SkincarePhoto.id.desc())
    )
    return result.scalars().all()


async def delete_photo(session: AsyncSession, photo_id: int) -> Optional[str]:
    """Delete a photo row. Returns its ``file_key`` so the caller can remove the
    file once the delete is committed, or ``None`` when there was no such row."""
    row = await session.get(SkincarePhoto, photo_id)
    if row is None:
        return None
    file_key = row.file_key
    await session.delete(row)
    await session.flush()
    return file_key


# ── Skincare Products CRUD ───────────────────────────────────────────────────
async def list_products(
    session: AsyncSession, *, active_only: bool = False
) -> Sequence[SkincareProduct]:
    stmt = select(SkincareProduct)
    if active_only:
        stmt = stmt.where(SkincareProduct.active.is_(True))
    stmt = stmt.order_by(
        SkincareProduct.active.desc(),
        SkincareProduct.step.asc().nulls_last(),
        SkincareProduct.name,
    )
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
    active_flag: Optional[str] = None,
    usage_morning: Optional[str] = None,
    usage_evening: Optional[str] = None,
    step: Optional[int] = None,
) -> SkincareProduct:
    row = SkincareProduct(
        name=name,
        type=type,
        active_ingredient=active_ingredient,
        description=description,
        usage_instructions=usage_instructions,
        usage_morning=usage_morning,
        usage_evening=usage_evening,
        step=step,
        default_time=default_time,
        schedule_days=schedule_days,
        active=active,
        active_flag=_clean_flag(active_flag),
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
    active_flag: Optional[str] = None,
    usage_morning: Optional[str] = None,
    usage_evening: Optional[str] = None,
    step: Optional[int] = None,
) -> Optional[SkincareProduct]:
    row = await session.get(SkincareProduct, product_id)
    if row is None:
        return None
    row.name = name
    row.type = type
    row.active_ingredient = active_ingredient
    row.description = description
    row.usage_instructions = usage_instructions
    row.usage_morning = usage_morning
    row.usage_evening = usage_evening
    row.step = step
    row.default_time = default_time
    row.schedule_days = schedule_days
    row.active = active
    row.active_flag = _clean_flag(active_flag)
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
    today_d = await today(session)
    today_l = await get_log(session, today_d)
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
            "usage_morning": p.usage_morning,
            "usage_evening": p.usage_evening,
            "step": p.step,
            "default_time": p.default_time,
            "time": p.default_time,
            "schedule_days": p.schedule_days or [],
            "days": p.schedule_days or [],
            "active": p.active,
            "on": p.active,
            "active_flag": _clean_flag(p.active_flag),
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
    photos = await list_photos(session)

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
        "today": today_d.isoformat(),
        "plan": await plan_for(session, today_d),
        "history": await history(session, end=today_d),
        "photos": [
            {
                "id": ph.id,
                "date": ph.date.isoformat(),
                **photo_derivatives.photo_urls(ph.file_key),
                "note": ph.note,
            }
            for ph in photos
        ],
        "flags": list(ACTIVE_FLAGS),
    }

