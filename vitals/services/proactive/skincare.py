"""The skincare routine in Telegram — what is due this morning / tonight, ticked
off right under the message.

Deterministic on purpose: the list *is* the catalog's schedule for the day
(``skincare_service.plan_for``), so there is nothing for a model to add. One
message per slot, each at its own time from the settings card, each with one
button per product:

    Вечерний уход · ср 21.10
    ✅ Дифферин (Ретиноид)
    ⬜ Увлажняющий крем

A tap toggles that product (``sk:<iso date>:<slot>:<product id>``), «Всё
сделал» ticks whatever is still open (``…:all``). Like the day-context buttons,
the payload carries its own date, so a tap after midnight still lands on the
evening it was asked about. The message is then redrawn from the database, not
patched from the tap — a tick made in the app meanwhile shows up too, and two
quick taps can't overwrite each other.

**Off the budget, outside quiet hours.** These go out at a time the owner typed
in, for a routine the owner set up — the same reasoning that exempts the brief
from quiet hours, taken one step further: a reminder that a busy day of nudges
could silently cancel is not a reminder. So the category is in neither set
``delivery`` enforces; the module switch and the per-category toggle still apply.

A tap on a product with a conflict-engine flag is recorded even when a blocking
rule fires. This is a record of what was done, not a plan to approve: refusing
it would only make the diary lie. The rule still raises its (overridden) alert,
and the tap's toast says which rule it was.
"""
from __future__ import annotations

import logging
from datetime import date as date_type, datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import Source
from vitals.models.proactive import Notification
from vitals.services import skincare_service
from vitals.services.proactive import channels, delivery, prefs
from vitals.services.proactive.channels import Notifier
from vitals.utils.timeutils import now_local

logger = logging.getLogger(__name__)

CB_PREFIX = "sk:"  # sk:<iso date>:<slot>:<product id | all>
CB_ALL = "all"

MODULE_KEY = "skincare"

TITLES = {
    skincare_service.SLOT_MORNING: "Утренний уход",
    skincare_service.SLOT_EVENING: "Вечерний уход",
}
_WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
MARK_DONE = "✅"
MARK_OPEN = "⬜"
ALL_DONE_LINE = "Всё сделано."
ALL_BUTTON = "Всё сделал"

# Telegram's toast is capped at 200 characters; a long rule message is cut.
_TOAST_MAX = 200


def dedupe_key(on_date: date_type, slot: str) -> str:
    return f"skincare:{on_date.isoformat()}:{slot}"


def render(on_date: date_type, slot: str, items: list[dict]) -> tuple[str, list[tuple[str, str]]]:
    """The message and its keyboard for one slot of one day."""
    header = f"{TITLES[slot]} · {_WEEKDAYS[on_date.weekday()]} {on_date:%d.%m}"
    lines = [header]
    buttons: list[tuple[str, str]] = []
    for item in items:
        mark = MARK_DONE if item["done"] else MARK_OPEN
        lines.append(f"{mark} {item['name']}")
        if item["product_id"] is not None:
            buttons.append(
                (f"{mark} {item['name']}", f"{CB_PREFIX}{on_date.isoformat()}:{slot}:{item['product_id']}")
            )
    open_items = [i for i in items if not i["done"]]
    if items and not open_items:
        lines.append("")
        lines.append(ALL_DONE_LINE)
    elif len(open_items) > 1:
        buttons.append((ALL_BUTTON, f"{CB_PREFIX}{on_date.isoformat()}:{slot}:{CB_ALL}"))
    return "\n".join(lines), buttons


async def reminders_on(session: AsyncSession) -> bool:
    """The skincare module is on and its reminder toggle hasn't been switched off."""
    from vitals.services import modules_service

    modules = await modules_service.get_enabled_modules(session)
    if not modules.get(MODULE_KEY):
        return False
    return bool((await prefs.get_prefs(session))["nudges"].get(prefs.CATEGORY_SKINCARE, True))


async def send_slot(
    session: AsyncSession,
    notifier: Optional[Notifier],
    slot: str,
    *,
    now: Optional[datetime] = None,
) -> Optional[Notification]:
    """Send today's list for ``slot``. Nothing goes out when nothing is planned,
    or when all of it was already ticked in the app before the reminder's time."""
    if notifier is None or not await reminders_on(session):
        return None
    now = now or now_local()
    on_date = now.date()
    items = (await skincare_service.plan_for(session, on_date))[slot]
    if not any(not i["done"] for i in items):
        return None
    text, buttons = render(on_date, slot, items)
    return await delivery.send(
        session,
        notifier,
        text=text,
        category=delivery.CATEGORY_SKINCARE,
        dedupe_key=dedupe_key(on_date, slot),
        buttons=buttons,
        now=now,
    )


# ── Taps ──────────────────────────────────────────────────────────────────────
def parse(data: str) -> Optional[tuple[date_type, str, Optional[int]]]:
    """``sk:<date>:<slot>:<id|all>`` → ``(date, slot, product id or None for all)``."""
    try:
        _, iso_date, slot, target = data.split(":", 3)
        on_date = date_type.fromisoformat(iso_date)
    except ValueError:
        return None
    if slot not in skincare_service.SLOTS:
        return None
    if target == CB_ALL:
        return on_date, slot, None
    try:
        return on_date, slot, int(target)
    except ValueError:
        return None


async def apply_tap(
    session: AsyncSession, data: str
) -> Optional[tuple[date_type, str, str]]:
    """Apply one tap. Returns ``(date, slot, toast)``, or ``None`` for a payload
    that can't be applied (malformed, or a product deleted since the message)."""
    parsed = parse(data)
    if parsed is None:
        logger.warning("unparseable skincare payload: %s", data)
        return None
    on_date, slot, product_id = parsed
    source = Source.TELEGRAM.value

    if product_id is None:
        violations = await skincare_service.complete_slot(
            session, on_date=on_date, slot=slot, override=True, source=source
        )
        toast = "Отмечено всё"
    else:
        items = (await skincare_service.plan_for(session, on_date))[slot]
        done = any(i["product_id"] == product_id and i["done"] for i in items)
        try:
            violations = await skincare_service.set_check(
                session,
                on_date=on_date,
                product_id=product_id,
                slot=slot,
                done=not done,
                override=True,
                source=source,
            )
        except LookupError:
            logger.info("tap on a product that no longer exists: %s", data)
            return None
        toast = "Снял отметку" if done else "Отмечено"

    if violations:
        toast = f"{toast}. ⚠ {violations[0].message}"
    return on_date, slot, toast[:_TOAST_MAX]


async def redraw(
    session: AsyncSession,
    notifier: Notifier,
    message_id: str,
    on_date: date_type,
    slot: str,
) -> None:
    """Rebuild one sent reminder from what is stored for its day. Never raises:
    the tick is already saved, and a refused edit (the text didn't change, the
    message is too old) is not worth failing the update over."""
    items = (await skincare_service.plan_for(session, on_date))[slot]
    text, buttons = render(on_date, slot, items)
    try:
        await notifier.edit(message_id, text, buttons=buttons or None)
    except Exception:
        logger.warning("could not redraw skincare message %s", message_id, exc_info=True)


async def sync_sent(
    session: AsyncSession, notifier: Optional[Notifier], on_date: date_type, slot: str
) -> None:
    """After a tick in the app: bring the reminder already in the chat up to date,
    if one was sent for that slot. A no-op without a channel or a message."""
    if notifier is None:
        return
    result = await session.execute(
        select(Notification.external_id).where(
            Notification.dedupe_key == dedupe_key(on_date, slot)
        )
    )
    message_id = result.scalars().first()
    if message_id:
        await redraw(session, notifier, message_id, on_date, slot)


# ── The jobs ──────────────────────────────────────────────────────────────────
async def _run(session_factory, slot: str) -> None:
    notifier = channels.build_notifier()
    if notifier is None:
        return
    async with session_factory() as session:
        await send_slot(session, notifier, slot)
        await session.commit()


async def morning_job(session_factory, redis=None) -> None:
    """At the morning time from the settings card."""
    await _run(session_factory, skincare_service.SLOT_MORNING)


async def evening_job(session_factory, redis=None) -> None:
    """At the evening time from the settings card."""
    await _run(session_factory, skincare_service.SLOT_EVENING)
