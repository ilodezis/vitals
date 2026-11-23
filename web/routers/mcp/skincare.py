"""Skincare catalog, checklist ticks, notes and observations."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from vitals.enums import Source
from vitals.models import (
    SkincareCheck,
    SkincareLog, SkincareObservation, SkincareProduct,
)
from vitals.services.conflict_engine import ConflictBlocked
from vitals.utils.timeutils import today_local
from web.routers.mcp._core import (
    READ, WRITE, _conflict_payload, _merged, _parse_date, gated, get_session_factory, logger,
    dispatch, serialize_row, serialize_written, tool,
)

async def get_skincare_logs(
    start_date: Optional[str] = None, end_date: Optional[str] = None, limit: int = 100
) -> dict:
    """The skincare *history* for a date range (YYYY-MM-DD), newest first, each
    series capped at ``limit`` rows (default 100):

      * ``checks`` — what was actually done: one row per product, slot (morning /
        evening) and day, the same ticks the app's checklist, the Telegram reminder
        and ``set_skincare_check`` write. ``product_id`` is null once the product
        was deleted from the catalog; ``product_name`` keeps the row readable.
      * ``observations`` — skin state: inflammation and PIH scores, zone, note.
      * ``day_flags`` — the day's actives as the conflict engine sees them
        (retinoid, azelaic, peel, …). Derived from the ticks; the rows from before
        the first tick are the old hand-filled checklist, and their ``note`` keeps
        what was written then.

    For the product catalog and what is planned today use
    ``get_skincare_routine``; to record a done product use ``set_skincare_check``.
    Face photos: ``list_photos(kind="face")``. READ tool."""

    session_factory = get_session_factory()
    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")

    def _ranged(stmt, model):
        if start:
            stmt = stmt.where(model.date >= start)
        if end:
            stmt = stmt.where(model.date <= end)
        return stmt

    async with session_factory() as session:
        checks = (await session.execute(
            _ranged(select(SkincareCheck), SkincareCheck)
            .order_by(SkincareCheck.date.desc(), SkincareCheck.slot, SkincareCheck.done_at)
            .limit(limit)
        )).scalars().all()
        observations = (await session.execute(
            _ranged(select(SkincareObservation), SkincareObservation)
            .order_by(SkincareObservation.date.desc()).limit(limit)
        )).scalars().all()
        logs = (await session.execute(
            _ranged(select(SkincareLog), SkincareLog)
            .order_by(SkincareLog.date.desc()).limit(limit)
        )).scalars().all()

        return {
            "checks": [serialize_row(c) for c in checks],
            "observations": [serialize_row(o) for o in observations],
            "day_flags": [serialize_row(l) for l in logs],
        }


# ── Skincare: the catalog, the day's plan and what was done ──────────────────
# The routine is the catalog read for a date: every product in use whose
# ``schedule_days`` include that weekday, in the slot(s) its ``default_time``
# names. A tick (``set_skincare_check``) is what records it as done — the same
# service call as a tap in the app or under the Telegram reminder, so it runs the
# same conflict check and sets the same day flags the engine reads.
SKINCARE_RANGE_MAX_DAYS = 31
_SKINCARE_TIMES = ("morning", "evening", "both")
_SKINCARE_CLEARABLE = (
    "active_ingredient", "description", "usage_instructions", "usage_morning",
    "usage_evening", "step", "active_flag",
)
_SKINCARE_STEP_RANGE = (1, 99)


def _skincare_schedule(
    default_time: Optional[str],
    schedule_days: Optional[list[int]],
    active_flag: Optional[str],
    step: Optional[int] = None,
) -> None:
    """Reject what the app's form can't produce: an unknown slot, a weekday
    outside 0..6, a conflict flag the engine has no rule key for, a step outside
    1..99."""
    from vitals.services import skincare_service

    low, high = _SKINCARE_STEP_RANGE
    if step is not None and not low <= step <= high:
        raise ValueError(f"step must be between {low} and {high}")

    if default_time is not None and default_time not in _SKINCARE_TIMES:
        raise ValueError(f"default_time must be one of {', '.join(_SKINCARE_TIMES)}")
    if schedule_days is not None and any(
        not isinstance(d, int) or isinstance(d, bool) or not 0 <= d <= 6 for d in schedule_days
    ):
        raise ValueError("schedule_days are weekday numbers 0..6 (Monday=1 … Saturday=6, Sunday=0)")
    if active_flag is not None and active_flag not in skincare_service.ACTIVE_FLAGS:
        raise ValueError(
            f"active_flag must be one of {', '.join(skincare_service.ACTIVE_FLAGS)} "
            "(or left out / cleared for a product no rule concerns)"
        )


async def get_skincare_routine(
    start_date: Optional[str] = None, end_date: Optional[str] = None
) -> dict:
    """The skincare routine as the app runs it: the product catalog and the plan
    for a day or a range of days (YYYY-MM-DD, default today; ``start_date`` alone
    runs to today; at most 31 days), with what was ticked done. Call this first for anything about the routine —
    "what do I put on tonight", "did I do the morning", "add Х to Tuesdays".

    ``today`` is the owner's routine day, not the calendar: until the day ends
    (``day_end`` in the settings, 05:00 by default) it is still the evening before
    — at 01:00 "tonight" means the date ``today`` says.

    ``products`` — the whole catalog, products in use and switched off, in the
    order of application: ``id``, ``name``, ``type``, ``active_ingredient``,
    ``description``, ``usage_instructions`` (how to apply it) and
    ``usage_morning`` / ``usage_evening`` (how in that slot, when different),
    ``step`` (place in the order of application), ``default_time`` (morning /
    evening / both), ``schedule_days`` (weekday numbers: Monday=1 … Saturday=6,
    Sunday=0), ``active`` (false = switched off: kept in the catalog, never
    planned) and ``active_flag`` (the conflict-engine key ticking it sets — one of
    ``flags``; absent = a product no rule concerns, like a cleanser).

    ``days`` — newest first, each with ``morning`` and ``evening`` lists of
    ``{product_id, name, flag, how, planned, done, done_at}`` and ``notes``
    (``{slot: text}`` for the slots with a ``set_skincare_note``); ``planned:
    false`` marks a product ticked on a day it wasn't scheduled. The
    ``product_id`` here is what ``set_skincare_check`` and
    ``update_skincare_product`` take. READ tool."""
    from vitals.services import skincare_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        today = await skincare_service.today(session)
    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")
    if start is None and end is None:
        start = end = today
    elif end is None:  # "since Monday" reads up to today
        end = max(start, today)
    elif start is None:
        start = end
    if end < start:
        return {"error": "end_date is before start_date"}
    if (end - start).days >= SKINCARE_RANGE_MAX_DAYS:
        return {"error": f"at most {SKINCARE_RANGE_MAX_DAYS} days per call — narrow the range"}

    async with session_factory() as session:
        products = await skincare_service.list_products(session)
        return {
            "today": today.isoformat(),
            "products": [serialize_row(p) for p in products],
            "days": await skincare_service.plans_between(session, start, end),
            "flags": list(skincare_service.ACTIVE_FLAGS),
        }


@gated("skincare")
async def add_skincare_product(
    name: str,
    type: str,
    default_time: str = "evening",
    schedule_days: Optional[list[int]] = None,
    active_ingredient: Optional[str] = None,
    active_flag: Optional[str] = None,
    description: Optional[str] = None,
    usage_instructions: Optional[str] = None,
    usage_morning: Optional[str] = None,
    usage_evening: Optional[str] = None,
    step: Optional[int] = None,
    active: bool = True,
) -> dict:
    """Adds a product to the skincare catalog — from then on it is planned on its
    days and shows on the checklist (app and Telegram).

    ``usage_instructions`` is how to apply it, one short line («горошина на сухую
    кожу, через 20 мин после умывания») — printed under the product in the
    reminder. ``usage_morning`` / ``usage_evening`` replace it in that slot for a
    product applied differently morning and evening. ``step`` is its place in
    the order of application, 1..99 (cleanser 1, active 2, cream 3).

    ``type`` is a short free-text kind ("Ретиноид", "Крем", "Умывалка").
    ``default_time`` is morning, evening or both. ``schedule_days`` are weekday
    numbers, Monday=1 … Saturday=6, Sunday=0; left out = every day.
    ``active_flag`` ties the product to the conflict rules — one of retinoid,
    azelaic, peel, niacinamide_spf, moisturizer, vitamin_c, benzoyl_peroxide; set
    it for anything containing that active (adapalene and tretinoin are
    ``retinoid``), leave it out for products no rule concerns. ``active=False``
    adds it switched off. WRITE tool — saved immediately."""
    from vitals.services import skincare_service

    name, type = (name or "").strip(), (type or "").strip()
    if not name or not type:
        return {"error": "name and type are required"}
    days = list(range(7)) if schedule_days is None else sorted(set(schedule_days))
    try:
        _skincare_schedule(default_time, days, active_flag, step)
    except ValueError as e:
        return {"error": str(e)}

    session_factory = get_session_factory()
    async with session_factory() as session:
        row = await skincare_service.add_product(
            session, name=name, type=type, active_ingredient=active_ingredient,
            description=description, usage_instructions=usage_instructions,
            usage_morning=usage_morning, usage_evening=usage_evening, step=step,
            default_time=default_time, schedule_days=days, active=active,
            active_flag=active_flag,
        )
        await session.commit()
        return await serialize_written(session, row)


@gated("skincare")
async def update_skincare_product(
    product_id: int,
    name: Optional[str] = None,
    type: Optional[str] = None,
    default_time: Optional[str] = None,
    schedule_days: Optional[list[int]] = None,
    active_ingredient: Optional[str] = None,
    active_flag: Optional[str] = None,
    description: Optional[str] = None,
    usage_instructions: Optional[str] = None,
    usage_morning: Optional[str] = None,
    usage_evening: Optional[str] = None,
    step: Optional[int] = None,
    active: Optional[bool] = None,
    clear: Optional[list[str]] = None,
) -> dict:
    """Edits a catalog product by ``product_id`` (from ``get_skincare_routine``).
    Only the fields you pass change. Use it to reschedule (``schedule_days`` is
    the full new list, Monday=1 … Sunday=0; ``default_time`` morning / evening /
    both), to switch a product off or back on (``active=False`` / ``True`` — it
    stays in the catalog with its history, just is no longer planned; prefer this
    over deleting), to correct its conflict flag, or to say how and in what order
    it is applied: ``usage_instructions`` (one line, shown under it in the
    reminder), ``usage_morning`` / ``usage_evening`` (that slot only, when it
    differs), ``step`` (1..99, place in the order of application). For something
    about one day only («сегодня пропусти»), use ``set_skincare_note`` instead.

    To empty a field or remove the conflict flag, name it in ``clear`` (any of
    active_ingredient, description, usage_instructions, usage_morning,
    usage_evening, step, active_flag). Ticks already recorded keep the flag they
    were made with. WRITE tool."""
    from vitals.services import skincare_service

    clear = list(clear or [])
    unknown = sorted(set(clear) - set(_SKINCARE_CLEARABLE))
    if unknown:
        return {"error": f"cannot clear {unknown} — clearable: {', '.join(_SKINCARE_CLEARABLE)}"}
    days = sorted(set(schedule_days)) if schedule_days is not None else None
    try:
        _skincare_schedule(default_time, days, active_flag, step)
    except ValueError as e:
        return {"error": str(e)}
    if name is not None and not name.strip() or type is not None and not type.strip():
        return {"error": "name and type cannot be empty"}

    session_factory = get_session_factory()
    async with session_factory() as session:
        merged = await _merged(
            session, SkincareProduct, product_id,
            name=name.strip() if name else None, type=type.strip() if type else None,
            default_time=default_time, schedule_days=days,
            active_ingredient=active_ingredient, active_flag=active_flag,
            description=description, usage_instructions=usage_instructions,
            usage_morning=usage_morning, usage_evening=usage_evening, step=step, active=active,
        )
        if merged is None:
            return {"error": f"Skincare product {product_id} not found"}
        for field in clear:
            merged[field] = None
        merged["schedule_days"] = merged["schedule_days"] or []
        row = await skincare_service.update_product(session, product_id, **merged)
        await session.commit()
        return await serialize_written(session, row)


@gated("skincare")
async def set_skincare_check(
    slot: str,
    product_id: Optional[int] = None,
    done: bool = True,
    on_date: Optional[str] = None,
    override: bool = False,
) -> dict:
    """Records that a skincare product was applied — or takes the mark back.
    The same tick as a tap on the app's checklist or the button under the Telegram
    reminder (a reminder already in the chat is redrawn to match). This is THE
    way to log skincare; it replaced the old seven-checkbox ``log_skincare``.

    ``slot`` is morning or evening. ``product_id`` comes from
    ``get_skincare_routine``; leave it out (with ``done=True``) to tick everything
    still open in that slot — the "all done" button. ``done=False`` unticks one
    product. ``on_date`` defaults to the routine day (at 01:00, the evening
    before); any past date works for catching up.
    A product can be ticked on a day it isn't scheduled — it then shows as
    ``planned: false``. Idempotent: ticking twice records one tick.

    Ticking a product whose conflict flag a blocking rule forbids (e.g. a
    retinoid and a peel the same evening) returns ``{"blocked": true, ...}`` and
    saves nothing; retry with ``override=True`` only when the owner confirms it
    was actually done. Returns the day's plan as it now stands plus any
    non-blocking ``warnings``. WRITE tool."""
    from vitals.services import skincare_service
    from vitals.services.proactive import channels
    from vitals.services.proactive import skincare as skincare_reminders

    if slot not in skincare_service.SLOTS:
        return {"error": f"slot must be one of {', '.join(skincare_service.SLOTS)}"}
    if product_id is None and not done:
        return {"error": "a whole slot can only be ticked, not unticked — pass product_id"}

    session_factory = get_session_factory()
    async with session_factory() as session:
        parsed_date = _parse_date(on_date, await skincare_service.today(session), field="on_date")
        try:
            if product_id is None:
                violations = await skincare_service.complete_slot(
                    session, on_date=parsed_date, slot=slot, override=override,
                    source=Source.MCP.value,
                )
            else:
                violations = await skincare_service.set_check(
                    session, on_date=parsed_date, product_id=product_id, slot=slot,
                    done=done, override=override, source=Source.MCP.value,
                )
        except ConflictBlocked as e:
            return _conflict_payload(e)
        except LookupError:
            return {"error": f"Skincare product {product_id} not found"}
        await session.commit()

        # Best-effort, as in the app: the tick is committed, and a slow or
        # refused Telegram edit must not turn it into an error.
        try:
            await skincare_reminders.sync_sent(
                session, channels.build_notifier(), parsed_date, slot
            )
        except Exception:  # noqa: BLE001
            logger.warning("mcp: could not sync the skincare reminder", exc_info=True)

        result = {
            "date": parsed_date.isoformat(),
            **await skincare_service.plan_for(session, parsed_date),
        }
        if violations:
            result["warnings"] = [v.to_dict() for v in violations]
        return result


@gated("skincare")
async def set_skincare_note(slot: str, text: str, on_date: Optional[str] = None) -> dict:
    """Leaves a note on one slot of one day — what to do differently that time:
    «щёки раздражены — ретиноид только на лоб», «после пилинга без кислот». Shown
    above that slot's checklist in the app and at the top of its Telegram
    reminder (a reminder already sent is redrawn). One note per slot and day:
    writing again replaces it, empty ``text`` removes it. ``slot`` is morning or
    evening; ``on_date`` (YYYY-MM-DD) defaults to the routine day. How a product
    is applied every time belongs in its ``usage_instructions`` instead. WRITE
    tool. Returns the day's plan with its notes."""
    from vitals.services import skincare_service
    from vitals.services.proactive import channels
    from vitals.services.proactive import skincare as skincare_reminders

    if slot not in skincare_service.SLOTS:
        return {"error": f"slot must be one of {', '.join(skincare_service.SLOTS)}"}

    session_factory = get_session_factory()
    async with session_factory() as session:
        parsed_date = _parse_date(on_date, await skincare_service.today(session), field="on_date")
        try:
            await skincare_service.set_note(
                session, on_date=parsed_date, slot=slot, text=text, source=Source.MCP.value
            )
        except ValueError as e:
            return {"error": str(e)}
        await session.commit()

        try:
            await skincare_reminders.sync_sent(
                session, channels.build_notifier(), parsed_date, slot
            )
        except Exception:  # noqa: BLE001
            logger.warning("mcp: could not sync the skincare reminder", exc_info=True)

        return {
            "date": parsed_date.isoformat(),
            **await skincare_service.plan_for(session, parsed_date),
        }


# ── Skincare observations ─────────────────────────────────────────────────────
@gated("skincare")
async def log_skincare_observation(
    on_date: Optional[str] = None,
    inflammation: Optional[int] = None,
    pih: Optional[int] = None,
    zone: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    """Records a skin-status observation — inflammation and PIH (post-inflammatory
    hyperpigmentation) scores, an optional face ``zone``, and a note: how the skin
    looks, not what was applied (that is ``set_skincare_check``). WRITE tool —
    saved immediately."""
    from vitals.services import skincare_service

    session_factory = get_session_factory()
    parsed_date = _parse_date(on_date, today_local(), field="on_date")
    async with session_factory() as session:
        row = await skincare_service.add_observation(
            session, on_date=parsed_date, inflammation=inflammation,
            pih=pih, zone=zone, note=note,
        )
        await session.commit()
        return await serialize_written(session, row)


# ── Consolidated tools ───────────────────────────────────────────────────────
_SKINCARE_VIEWS = {
    ("routine", False): (get_skincare_routine, None),
    ("history", False): (get_skincare_logs, None),
}


@tool(READ, module="skincare")
async def get_skincare(
    view: str = "routine",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: Optional[int] = None,
) -> dict:
    """Skincare reads (dates YYYY-MM-DD).

    ``view="routine"`` (default): the product catalog (ids for ``save_skincare``)
    and the morning/evening plan with ticks for a day or a range (default today;
    max 31 days), plus the active-ingredient flags in play. ``view="history"``:
    the skincare history for a range, newest first (``limit`` default 100) —
    ticks, slot notes, skin observations."""
    args = dict(start_date=start_date, end_date=end_date, limit=limit)
    return await dispatch("get_skincare", "view", view, _SKINCARE_VIEWS, args)


_SKINCARE_ENTRIES = {
    ("product", False): (add_skincare_product, None),
    ("product", True): (update_skincare_product, "product_id"),
    ("check", False): (set_skincare_check, None),
    ("note", False): (set_skincare_note, None),
    ("observation", False): (log_skincare_observation, None),
}


@tool(WRITE, module="skincare")
@gated("skincare")
async def save_skincare(
    entry: str = "check",
    product_id: Optional[int] = None,
    slot: Optional[str] = None,
    done: Optional[bool] = None,
    on_date: Optional[str] = None,
    text: Optional[str] = None,
    name: Optional[str] = None,
    type: Optional[str] = None,
    default_time: Optional[str] = None,
    schedule_days: Optional[list[int]] = None,
    active_ingredient: Optional[str] = None,
    active_flag: Optional[str] = None,
    description: Optional[str] = None,
    usage_instructions: Optional[str] = None,
    usage_morning: Optional[str] = None,
    usage_evening: Optional[str] = None,
    step: Optional[int] = None,
    active: Optional[bool] = None,
    clear: Optional[list[str]] = None,
    inflammation: Optional[int] = None,
    pih: Optional[int] = None,
    zone: Optional[str] = None,
    note: Optional[str] = None,
    override: Optional[bool] = None,
) -> dict:
    """Writes to the skincare routine (product ids from ``get_skincare``).

    ``entry``:
      * ``check`` (default) — ticks ``product_id`` as applied in ``slot``
        (morning | evening) on ``on_date`` (default the routine day: until
        ``day_end``, 05:00 by default, it is still the evening before). Leave
        ``product_id`` out to tick everything still open in the slot;
        ``done=false`` unticks one product. Same tick as the app checklist and
        the Telegram button; idempotent.
      * ``note`` — a note ``text`` on one ``slot`` of one day (what to do
        differently that time); an empty ``text`` removes it.
      * ``observation`` — skin status: ``inflammation`` and ``pih`` scores, an
        optional face ``zone``, ``note``.
      * ``product`` — without ``product_id`` adds a catalog product: ``name``,
        ``type``, ``default_time`` (morning | evening | both), ``schedule_days``
        (Monday=1 … Saturday=6, Sunday=0; default every day), ``active_ingredient``, ``active_flag``
        (conflict flag such as "retinoid"), usage texts, ``step`` (order 1–99),
        ``active``. With ``product_id`` edits only the fields passed; ``clear``
        lists optional fields to empty.

    A hard conflict block on a tick returns ``{"blocked": true, ...}``; repeat
    with ``override=true`` only if the owner insists."""
    args = dict(
        slot=slot, done=done, on_date=on_date, text=text, name=name, type=type,
        default_time=default_time, schedule_days=schedule_days,
        active_ingredient=active_ingredient, active_flag=active_flag,
        description=description, usage_instructions=usage_instructions,
        usage_morning=usage_morning, usage_evening=usage_evening, step=step,
        active=active, clear=clear, inflammation=inflammation, pih=pih, zone=zone,
        note=note, override=override,
    )
    if entry == "product":
        return await dispatch(
            "save_skincare", "entry", entry, _SKINCARE_ENTRIES, args, product_id
        )
    return await dispatch(
        "save_skincare", "entry", entry, _SKINCARE_ENTRIES, {**args, "product_id": product_id}
    )
