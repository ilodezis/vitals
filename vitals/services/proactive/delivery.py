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

   Environment alerts are exempt from it too (see ``CATEGORY_ENVIRONMENT``).

   Answers to the owner (``reply``, ``echo``) are deliberately exempt as well.
   Counting them would mean that after the fourth thing you logged, the bot stops replying
   to you — which reads as a broken bot, not as a budget. This is the single
   easiest rule in the whole feature to get wrong, so it lives in one ``frozenset``
   right here rather than at each call site.

A send that fails at the transport is logged and swallowed: the caller's DB work
(the signals it just parsed, the digest it just stored) must not be rolled back
because Telegram had a bad minute, and an un-sent message writes no journal row,
so it costs nothing from the budget either.
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

INITIATIVE_CATEGORIES = frozenset({CATEGORY_BRIEF, CATEGORY_EVENING, CATEGORY_NUDGE})
# Held back by quiet hours. Wider than the budget set on purpose.
QUIET_HOURS_CATEGORIES = frozenset({CATEGORY_NUDGE, CATEGORY_ENVIRONMENT})

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
    session: AsyncSession, *, on_date: Optional[date_type] = None
) -> int:
    """How much of today's budget is spent (self-initiated messages only)."""
    on_date = on_date or now_local().date()
    result = await session.execute(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.category.in_(INITIATIVE_CATEGORIES),
            func.date(Notification.sent_at) == on_date,
        )
    )
    return result.scalar() or 0


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
) -> Optional[Notification]:
    """Send if allowed, and journal what was sent. ``None`` = nothing went out."""
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
        if category in INITIATIVE_CATEGORIES and await sent_today(
            session, on_date=now.date()
        ) >= budget:
            logger.info("skipping %s: daily budget of %s used", category, budget)
            return None

    try:
        external_id = await notifier.send(text, buttons=buttons, reply_to=reply_to)
    except Exception:
        logger.warning("delivery failed for %s; message dropped", category, exc_info=True)
        return None

    row = Notification(
        sent_at=now,
        category=category,
        dedupe_key=dedupe_key,
        channel=notifier.channel,
        external_id=external_id or None,
        payload={"text": text, "buttons": [list(b) for b in buttons] if buttons else None},
    )
    session.add(row)
    await session.flush()
    return row
