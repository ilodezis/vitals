"""The gate every outgoing message passes through: may this be sent, and was it.

Five rules, in the order they're checked:

1. **No channel** → nothing happens (the app before the bot exists).
2. **Module off** → nothing happens either: switching ``signals`` off in Settings
   is the emergency switch, and it has to silence the bot without a deploy.
3. **Dedupe.** A ``dedupe_key`` that's already in the journal means this exact
   message went out; a re-run of the job is a no-op, not a second ping.
4. **Quiet hours** hold back *nudges* and *environment* alerts — the bot's own idea
   of a good moment. The brief and the evening block go out at a time the owner
   typed by hand into the same settings card, so silencing them by quiet hours is
   one field quietly cancelling another with no way to see which won.
5. **The daily budget** (also from the settings card) covers all three
   self-initiated categories — the brief, the evening block, nudges.

   The evening block is two messages (the recap, then tomorrow's plan with its
   one-tap buttons) and it comes last, at a fixed hour. Without help it is what a
   busy day cuts: brief + two nudges + recap fills a budget of four and the plan
   is dropped, so the next brief plans from the week template's guess. So the
   block's slots are *reserved*: a nudge may only use what is left after the
   evening messages still due today, and once the block has started its second
   half is not re-checked — a recap without its plan is the worst of both.

   Environment alerts are exempt from it too (see ``CATEGORY_ENVIRONMENT``), and
   so is the skincare checklist (``CATEGORY_SKINCARE``).

   Answers to the owner (``reply``, ``echo``) are deliberately exempt as well.
   Counting them would mean that after the fourth thing you logged, the bot stops replying
   to you — which reads as a broken bot, not as a budget. This is the single
   easiest rule in the whole feature to get wrong, so it lives in one ``frozenset``
   right here rather than at each call site.

A send that fails at the transport is swallowed: the caller's DB work (the
signals it just parsed, the digest it just stored) must not be rolled back
because Telegram had a bad minute, and an un-sent message writes no journal row,
so it costs nothing from the budget either. It is not silent, though: it raises a
``warn`` alert per channel, which the next message that does go out clears.
"""
from __future__ import annotations

import logging
from datetime import date as date_type, datetime, time as time_type
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.models.proactive import Notification
from vitals.services.proactive import prefs
from vitals.services.proactive.channels import Buttons, Notifier
from vitals.utils.timeutils import now_local

logger = logging.getLogger(__name__)

# Categories. Only the first three are the bot talking first.
CATEGORY_BRIEF = "brief"
CATEGORY_EVENING = "evening"
CATEGORY_NUDGE = "nudge"
CATEGORY_REPLY = "reply"
CATEGORY_ECHO = "echo"
# A send the owner asked for from the web ("Отправить тестовое"): it exists to
# catch broken formatting, so it must go out even when today's brief already did,
# and it is not the bot talking first — hence off-budget and outside quiet hours.
CATEGORY_TEST = "test"
# The bedroom-air station telling the owner something is wrong with the room. It is
# the bot speaking first, but about a condition that is *happening*, not a good
# moment of its own choosing — so it neither spends nor is blocked by the daily
# budget (a stuffy room is not less stuffy because three other messages went
# out), yet it still stays quiet at night.
CATEGORY_ENVIRONMENT = "environment"
# The morning / evening skincare checklist (``proactive.skincare``). Sent at a
# time the owner typed in, about a routine the owner set up: like the brief it ignores
# quiet hours, and unlike it it does not spend the budget either — a checklist a
# busy day of nudges could cancel is not a checklist.
CATEGORY_SKINCARE = "skincare"

INITIATIVE_CATEGORIES = frozenset({CATEGORY_BRIEF, CATEGORY_EVENING, CATEGORY_NUDGE})
# Messages the evening block sends (recap + tomorrow's plan, see
# ``day_plan.evening_job``) — what nudges must leave room for.
EVENING_BLOCK_MESSAGES = 2
# Held back by quiet hours. Wider than the budget set on purpose.
QUIET_HOURS_CATEGORIES = frozenset({CATEGORY_NUDGE, CATEGORY_ENVIRONMENT})

# One alert per channel while its sends fail (entity = the channel name).
DELIVERY_ALERT_KEY = "proactive.delivery_failed"

# Fallbacks only — the live values come from ``prefs`` (the settings card), which
# is why they are read per send rather than captured at import.
DAILY_BUDGET = prefs.DEFAULTS["daily_budget"]
QUIET_START = prefs.as_time(prefs.DEFAULTS["quiet_start"])
QUIET_END = prefs.as_time(prefs.DEFAULTS["quiet_end"])


def in_quiet_hours(
    at: time_type, *, start: time_type = QUIET_START, end: time_type = QUIET_END
) -> bool:
    """Is ``at`` inside the quiet window? Handles a window that wraps midnight,
    because the settings card lets the owner set exactly that."""
    if start == end:
        return False
    if start < end:
        return start <= at < end
    return at >= start or at < end


async def sent_today(
    session: AsyncSession,
    *,
    on_date: Optional[date_type] = None,
    categories: frozenset[str] = INITIATIVE_CATEGORIES,
) -> int:
    """How much of today's budget is spent (self-initiated messages only), or how
    many of ``categories`` went out today."""
    on_date = on_date or now_local().date()
    result = await session.execute(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.category.in_(categories),
            func.date(Notification.sent_at) == on_date,
        )
    )
    return result.scalar() or 0


async def _within_budget(
    session: AsyncSession, category: str, *, on_date: date_type, budget: int
) -> bool:
    """May one more ``category`` message go out today? See rule 5 above."""
    evening_sent = await sent_today(
        session, on_date=on_date, categories=frozenset({CATEGORY_EVENING})
    )
    if category == CATEGORY_EVENING and evening_sent:
        # The block was admitted with its first message; its second half rides on it.
        return True
    spent = await sent_today(session, on_date=on_date)
    if category == CATEGORY_NUDGE:
        spent += max(0, EVENING_BLOCK_MESSAGES - evening_sent)
    return spent < budget


async def find_sent(session: AsyncSession, external_id: str) -> Optional[Notification]:
    """The journal row for a message id — how an incoming reply finds the context
    it is replying to."""
    result = await session.execute(
        select(Notification)
        .where(Notification.external_id == str(external_id))
        .order_by(Notification.id.desc())
    )
    return result.scalars().first()


async def recent_sent(session: AsyncSession, *, limit: int = 3) -> list[Notification]:
    """The last few messages we sent, oldest first — the context a question typed
    without Telegram's Reply has to be read against.

    Almost nothing is typed as a reply on mobile, so «что за ключ странный на
    второе» arrived with no message attached and was answered against the morning
    brief's JSON: the bot could not see the echo it had sent a minute earlier and
    guessed the owner meant the 2nd of the month.
    """
    result = await session.execute(
        select(Notification).order_by(Notification.id.desc()).limit(limit)
    )
    return list(reversed(result.scalars().all()))


async def find_by_key(session: AsyncSession, dedupe_key: str) -> Optional[Notification]:
    """The journal row a keyed message left, if it went out."""
    result = await session.execute(
        select(Notification).where(Notification.dedupe_key == dedupe_key)
    )
    return result.scalars().first()


async def already_sent(session: AsyncSession, dedupe_key: str) -> bool:
    result = await session.execute(
        select(Notification.id).where(Notification.dedupe_key == dedupe_key)
    )
    return result.scalars().first() is not None


async def send(
    session: AsyncSession,
    notifier: Optional[Notifier],
    *,
    text: str,
    category: str,
    dedupe_key: Optional[str] = None,
    buttons: Optional[Buttons] = None,
    reply_to: Optional[str] = None,
    now: Optional[datetime] = None,
    meta: Optional[dict] = None,
) -> Optional[Notification]:
    """Send if allowed, and journal what was sent. ``None`` = nothing went out.
    ``meta`` is journalled beside the text for a later message to read back —
    numbers, so nobody has to parse them out of the wording."""
    if notifier is None:
        return None
    if not text.strip():
        return None
    # The emergency switch. Checked here because *every* outgoing message —
    # brief, evening block, nudge, echo, reply, the test send from /reports —
    # passes through this one function; a guard per job would leak the ones that
    # aren't jobs.
    if not await prefs.bot_enabled(session):
        logger.info("skipping %s: the signals module is switched off", category)
        return None

    if dedupe_key and await already_sent(session, dedupe_key):
        logger.info("skipping %s: already sent (%s)", category, dedupe_key)
        return None

    now = now or now_local()
    if category in INITIATIVE_CATEGORIES or category in QUIET_HOURS_CATEGORIES:
        settings = await prefs.get_prefs(session)
        # Quiet hours hold back nudges and environment alerts, never the brief: one
        # scheduled for 09:00 inside a 02:00-10:00 quiet window must still arrive.
        # Both times came from the same card, and the one he set for the brief is
        # the more specific instruction.
        if category in QUIET_HOURS_CATEGORIES and in_quiet_hours(
            now.time(),
            start=prefs.as_time(settings["quiet_start"]),
            end=prefs.as_time(settings["quiet_end"]),
        ):
            logger.info("skipping %s: quiet hours (%s)", category, now.time())
            return None
        budget = settings["daily_budget"]
        if category in INITIATIVE_CATEGORIES and not await _within_budget(
            session, category, on_date=now.date(), budget=budget
        ):
            logger.info("skipping %s: daily budget of %s used", category, budget)
            return None

    from vitals.enums import Domain, Severity
    from vitals.i18n import t
    from vitals.services import alerts_service

    try:
        external_id = await notifier.send(text, buttons=buttons, reply_to=reply_to)
    except Exception:
        logger.warning("delivery failed for %s; message dropped", category, exc_info=True)
        await alerts_service.raise_alert(
            session,
            domain=Domain.SYSTEM.value,
            severity=Severity.WARN.value,
            message=t("alert.delivery_failed", channel=notifier.channel),
            alert_key=DELIVERY_ALERT_KEY,
            entity_ref=notifier.channel,
        )
        return None
    await alerts_service.resolve_by_key(
        session, alert_key=DELIVERY_ALERT_KEY, entity_ref=notifier.channel
    )

    row = Notification(
        sent_at=now,
        category=category,
        dedupe_key=dedupe_key,
        channel=notifier.channel,
        external_id=external_id or None,
        payload={
            "text": text,
            "buttons": [list(b) for b in buttons] if buttons else None,
            **({"meta": meta} if meta else {}),
        },
    )
    session.add(row)
    await session.flush()
    return row
