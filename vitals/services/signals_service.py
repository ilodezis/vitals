"""Signals service — capture free text, keep the original, fold keys on read.

Three things this module is responsible for, in the order they matter:

1. **Nothing is lost.** ``ingest_text`` writes the incoming message to
   ``raw_payloads`` *before* it tries to parse it. If the parser throws, times
   out, or returns junk, the raw row is already committed-able — the message is
   still there to re-parse later. This is the same data-lake rule the Garmin/Hevy
   importers follow, just with the LLM as the "upstream API".
2. **One phrase can be several facts.** «Голова раскалывается, спал 4 часа, кофе
   в 22» is three rows. They share a ``batch_id``, which is the unit the "не то"
   button cancels — a model that misread the sentence usually misread all of it,
   and picking one row out of three inside Telegram is misery. Pinpoint edits
   live on the ``/signals`` page instead.
3. **Keys stay free — for now.** The owner's call: collect a month of real
   phrasings, then consolidate. ``KEY_ALIASES`` is what keeps that
   from being a migration: keys are stored as the parser wrote them and folded to
   a canonical name **on read**, so adding an alias silently fixes every chart and
   export at once. Nothing here needs to know the final registry.

``misparse`` rows are excluded from chart/analysis reads but never deleted: they
are the actual evidence the key registry gets built from.
"""
from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from datetime import date as date_type, time as time_type, timedelta
from typing import Any, Awaitable, Callable, Optional, Sequence, Union
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import Domain, Severity, SignalKind, Source
from vitals.i18n import t
from vitals.models.raw_payload import RawPayload
from vitals.models.signals import DayContext, Signal
from vitals.services.raw_payload_service import upsert_raw_payload
from vitals.utils.timeutils import now_local, today_local

logger = logging.getLogger(__name__)

DOMAIN = Domain.SIGNALS.value

# One unresolved row while the parser is down, not one per message he sends.
PARSER_FAILED_ALERT_KEY = "signal_parser_failed"

_VALID_KINDS = {k.value for k in SignalKind}

# ── Key aliases ───────────────────────────────────────────────────────────────
# alias (as some parse once wrote it) → canonical key. Applied on **read** only.
# Grow this dict during the shake-out month; once consolidation happens the registry
# gets closed and the parser is forbidden from inventing new keys. Until then the
# stored value is left exactly as written so the drift stays visible.
KEY_ALIASES: dict[str, str] = {
    "sleepy": "sleepiness",
    "sleepy_af": "sleepiness",
    "drowsiness": "sleepiness",
    "head_ache": "headache",
    "headaches": "headache",
    "coffee_late": "caffeine_late",
    "late_coffee": "caffeine_late",
    "energy": "energy_level",
    # How the day went. The parser is told to reach for these five anchors, and
    # these are the spellings it reaches for instead when it forgets.
    "computer_day": "sedentary",
    "desk_day": "sedentary",
    "inactive": "sedentary",
    "low_activity": "sedentary",
    "walking_day": "on_feet",
    "on_the_move": "on_feet",
    "worked_late": "long_work_day",
    "overtime": "long_work_day",
    "busy_day": "workload_high",
    "work_overload": "workload_high",
    "stressful_day": "stress",
}


def normalize_key(key: str) -> str:
    """Canonical form of a stored key. Cheap slug hygiene + the alias table."""
    slug = slug_key(key)
    return KEY_ALIASES.get(slug, slug)


def slug_key(key: str) -> str:
    """Write-side hygiene: lowercase, trimmed, spaces/dashes → underscore.

    Keeps the column tidy without deciding anything about *which* key it is —
    that is ``normalize_key``'s job, and it happens on read.
    """
    return "_".join(str(key).strip().lower().replace("-", " ").split())


def _stored_keys_for(canonical: str) -> set[str]:
    """Every stored spelling that folds to ``canonical`` — for WHERE key IN (…)."""
    canonical = normalize_key(canonical)
    return {canonical} | {a for a, c in KEY_ALIASES.items() if c == canonical}


# ── Capture ───────────────────────────────────────────────────────────────────
Parser = Callable[[str], Union[Sequence[dict], Awaitable[Sequence[dict]]]]


async def store_raw_text(
    session: AsyncSession,
    *,
    text: str,
    external_id: Optional[str] = None,
    source: str = Source.TELEGRAM.value,
    processed: bool = False,
) -> RawPayload:
    """Park the incoming message in ``raw_payloads`` before anything can fail.

    ``external_id`` is the channel's own message id when there is one, so a
    webhook retry refreshes the same raw row instead of adding a duplicate.

    ``processed`` is for text that is not a message waiting to become signals —
    a question, a slash command — so the re-parse sweep never hands it to the
    parser. Stamped here rather than by the caller because it has to land in the
    same commit as the row itself.

    Committed here rather than at the end of the request, which is the only
    thing that makes "parked" true: the very next step is a model call of 5-20
    seconds, and Telegram re-sends an update it hasn't been answered about. An
    uncommitted row is invisible to that retry, so it finds no trace of the first
    attempt and pays for a second parse and a second reply to the same message.
    """
    raw = await upsert_raw_payload(
        session,
        domain=DOMAIN,
        source=source,
        external_id=external_id or uuid4().hex,
        payload={"text": text, "received_at": now_local().isoformat(timespec="seconds")},
    )
    if processed:
        raw.processed_at = now_local()
    await session.commit()
    return raw


def _coerce_item(item: dict) -> Optional[dict]:
    """Validate one parsed fact. ``None`` = unusable, drop it (raw still has it).

    The parser is an LLM, so this is a trust boundary: a bad ``kind`` or a missing
    ``key`` means the row would be unreadable downstream, and inventing a default
    would quietly poison the charts.
    """
    kind = str(item.get("kind") or "").strip().lower()
    if kind not in _VALID_KINDS:
        return None
    key = slug_key(item.get("key") or "")
    if not key:
        return None

    value_num = item.get("value_num")
    try:
        value_num = float(value_num) if value_num is not None else None
    except (TypeError, ValueError):
        value_num = None

    at_time = item.get("at_time")
    if isinstance(at_time, str):
        try:
            at_time = time_type.fromisoformat(at_time)
        except ValueError:
            at_time = None
    elif not isinstance(at_time, time_type):
        at_time = None

    unit = item.get("unit")
    note = item.get("note")
    return {
        "kind": kind,
        "key": key[:64],
        "value_num": value_num,
        "unit": str(unit)[:16] if unit else None,
        "note": str(note) if note else None,
        "at_time": at_time,
    }


async def create_signals(
    session: AsyncSession,
    *,
    items: Sequence[dict],
    on_date: Optional[date_type] = None,
    source: str = Source.TELEGRAM.value,
    raw_id: Optional[int] = None,
    batch_id: Optional[str] = None,
) -> list[Signal]:
    """Persist a parsed batch. Every row of one message shares a ``batch_id``."""
    on_date = on_date or today_local()
    batch_id = batch_id or uuid4().hex
    rows: list[Signal] = []
    for item in items:
        fields = _coerce_item(item)
        if fields is None:
            continue
        row = Signal(
            date=on_date,
            domain=DOMAIN,
            source=source,
            raw_id=raw_id,
            batch_id=batch_id,
            **fields,
        )
        session.add(row)
        rows.append(row)
    if rows:
        await session.flush()
    return rows


async def ingest_text(
    session: AsyncSession,
    *,
    text: str,
    parse: Parser,
    external_id: Optional[str] = None,
    on_date: Optional[date_type] = None,
    source: str = Source.TELEGRAM.value,
) -> list[Signal]:
    """The one entry point for incoming free text.

    Raw first, parse second — deliberately in that order and in *this* function
    rather than at the call site, so no future caller can get the order wrong.
    A parser that raises costs the batch, never the message.
    """
    raw = await store_raw_text(session, text=text, external_id=external_id, source=source)

    from vitals.services import alerts_service

    try:
        parsed = parse(text)
        if inspect.isawaitable(parsed):
            parsed = await parsed
    except Exception:
        # The message survives in raw_payloads and stays ``processed_at IS NULL``,
        # which is what :func:`reparse_unparsed` sweeps. Nothing to salvage here —
        # but a dead parser must not be silent: swallowed whole, a week of "no
        # model, no key, no balance" is indistinguishable from a week of messages
        # that simply held no facts.
        logger.warning("signal parser failed; message kept raw", exc_info=True)
        await alerts_service.raise_alert(
            session,
            domain=DOMAIN,
            severity=Severity.WARN.value,
            message=t("alert.signal_parser_failed"),
            alert_key=PARSER_FAILED_ALERT_KEY,
        )
        return []

    # The model answered — whatever it returned, the parser itself is back up.
    await alerts_service.resolve_by_key(session, alert_key=PARSER_FAILED_ALERT_KEY)

    rows = await create_signals(
        session,
        items=parsed or [],
        on_date=on_date,
        source=source,
        raw_id=raw.id,
    )
    if rows:
        # Same bookkeeping every other importer does — and it is what tells the
        # re-parse sweep "this one is done" from "this one never became anything".
        raw.processed_at = now_local()
        await session.flush()
    return rows


# How far back a second attempt is worth making, and how many messages one sweep
# may cost. A phrase still unparseable after a few days is material for the key
# registry, not something to keep paying a model for.
REPARSE_WINDOW_DAYS = 7
REPARSE_BATCH = 20


async def reparse_unparsed(
    session: AsyncSession,
    *,
    parse: Parser,
    limit: int = REPARSE_BATCH,
    since_days: int = REPARSE_WINDOW_DAYS,
) -> list[Signal]:
    """Second pass over messages that never became rows (R3).

    Which is the promise the echo already makes out loud — «Сохранил как есть —
    разобрать не смог. Посмотрю позже» — and that nothing was keeping until now.

    A candidate is a stored message with **no signals of its own**: the model was
    down, timed out, or returned junk. Rows that already produced signals are
    excluded in SQL, so running this twice cannot duplicate anything. A second
    failure leaves the row pending rather than burning it — the model being down
    is not the message's fault — and the window is what stops that from being
    forever.
    """
    from vitals.services import alerts_service

    cutoff = now_local() - timedelta(days=since_days)
    has_signals = select(Signal.id).where(Signal.raw_id == RawPayload.id).exists()
    stmt = (
        select(RawPayload)
        .where(
            RawPayload.domain == DOMAIN,
            RawPayload.processed_at.is_(None),
            RawPayload.fetched_at >= cutoff,
            ~has_signals,
        )
        .order_by(RawPayload.id)
        .limit(limit)
    )

    made: list[Signal] = []
    for raw in (await session.execute(stmt)).scalars().all():
        payload = raw.payload if isinstance(raw.payload, dict) else {}
        text = (payload.get("text") or "").strip()
        if not text:
            continue  # a button tap, not something anyone said
        try:
            parsed = parse(text)
            if inspect.isawaitable(parsed):
                parsed = await parsed
        except Exception:
            logger.warning("re-parse failed for raw %s", raw.id, exc_info=True)
            continue
        # Same as ingest_text: the model answered, so the outage alert clears.
        await alerts_service.resolve_by_key(session, alert_key=PARSER_FAILED_ALERT_KEY)
        rows = await create_signals(
            session,
            items=parsed or [],
            on_date=raw.fetched_at.date(),
            source=raw.source,
            raw_id=raw.id,
        )
        if rows:
            raw.processed_at = now_local()
            made.extend(rows)
    if made:
        await session.flush()
    return made


async def delete_signal(session: AsyncSession, signal_id: int) -> bool:
    """Pinpoint removal from the ``/signals`` page — the counterpart of the "не то"
    button, which cancels a whole batch.

    A real delete, unlike ``misparse``: this is for a row that is simply *wrong*
    and shouldn't feed the key registry either. The raw message stays in
    ``raw_payloads`` regardless, so nothing said is ever lost.
    """
    row = await session.get(Signal, signal_id)
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


async def mark_misparse(session: AsyncSession, batch_id: str) -> int:
    """"Не то" — drop the whole batch out of charts, keep the rows and the raw text."""
    result = await session.execute(
        update(Signal).where(Signal.batch_id == batch_id).values(misparse=True)
    )
    await session.flush()
    return result.rowcount or 0


# ── Read ──────────────────────────────────────────────────────────────────────
async def list_signals(
    session: AsyncSession,
    *,
    key: Optional[str] = None,
    kind: Optional[str] = None,
    start: Optional[date_type] = None,
    end: Optional[date_type] = None,
    include_misparse: bool = False,
    limit: int = 200,
) -> list[Signal]:
    """Newest first. ``key`` matches every stored spelling that folds to it."""
    stmt = select(Signal).where(Signal.domain == DOMAIN)
    if not include_misparse:
        stmt = stmt.where(Signal.misparse.is_(False))
    if key is not None:
        stmt = stmt.where(Signal.key.in_(_stored_keys_for(key)))
    if kind is not None:
        stmt = stmt.where(Signal.kind == kind)
    if start is not None:
        stmt = stmt.where(Signal.date >= start)
    if end is not None:
        stmt = stmt.where(Signal.date <= end)
    stmt = stmt.order_by(Signal.date.desc(), Signal.id.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars().all())


@dataclass(frozen=True)
class KeyStat:
    """One canonical key, as the revision screen needs to see it (R1).

    ``count`` alone cannot answer "is this the same thing as that?" — that call is
    made by reading the phrasings the key came from, and by seeing which stored
    spellings already fold into it. So all three travel together.
    """

    key: str
    count: int
    variants: tuple[str, ...]   # stored spellings that fold into ``key``
    examples: tuple[str, ...]   # his own wording, newest first


EXAMPLES_PER_KEY = 3

# Everything folds in Python (aliases can't be expressed in a GROUP BY), so the
# scan is bounded rather than unbounded. A year of one person's messages is well
# under this.
# ponytail: full scan of the recent window, per-key SQL aggregates if it ever grows.
_SCAN_LIMIT = 3000


async def key_frequency(
    session: AsyncSession,
    *,
    start: Optional[date_type] = None,
    end: Optional[date_type] = None,
    include_misparse: bool = True,
) -> list[KeyStat]:
    """Canonical keys, most-used first — the raw material for consolidating them.

    Counts default to **including** misparses: the point of this list is to see
    what the parser actually emits, mistakes included.
    """
    stmt = select(Signal.key, Signal.note).where(Signal.domain == DOMAIN)
    if not include_misparse:
        stmt = stmt.where(Signal.misparse.is_(False))
    if start is not None:
        stmt = stmt.where(Signal.date >= start)
    if end is not None:
        stmt = stmt.where(Signal.date <= end)
    stmt = stmt.order_by(Signal.id.desc()).limit(_SCAN_LIMIT)

    counts: dict[str, int] = {}
    variants: dict[str, set[str]] = {}
    examples: dict[str, list[str]] = {}
    for stored_key, note in (await session.execute(stmt)).all():
        canonical = normalize_key(stored_key)
        counts[canonical] = counts.get(canonical, 0) + 1
        if stored_key != canonical:
            variants.setdefault(canonical, set()).add(stored_key)
        seen = examples.setdefault(canonical, [])
        if note and note not in seen and len(seen) < EXAMPLES_PER_KEY:
            seen.append(note)

    return sorted(
        (
            KeyStat(
                key=key,
                count=count,
                variants=tuple(sorted(variants.get(key, ()))),
                examples=tuple(examples.get(key, ())),
            )
            for key, count in counts.items()
        ),
        key=lambda s: (-s.count, s.key),
    )


# ── Day context ───────────────────────────────────────────────────────────────
async def set_day_context(
    session: AsyncSession,
    on_date: date_type,
    *,
    answers: dict,
    planned: Optional[dict] = None,
    source: str = Source.MANUAL.value,
) -> DayContext:
    """Upsert the day's context — the latest answer wins, nothing is versioned.

    ``planned`` (what the week template had guessed) is kept alongside so the
    template can later learn from where it was wrong; passing ``None`` leaves any
    existing guess in place rather than erasing it.
    """
    row = await get_day_context(session, on_date)
    if row is None:
        row = DayContext(date=on_date, domain=DOMAIN, source=source, answers=answers)
        session.add(row)
    else:
        row.answers = answers
        row.source = source
    if planned is not None:
        row.planned = planned
    await session.flush()
    return row


async def get_day_context(
    session: AsyncSession, on_date: date_type
) -> Optional[DayContext]:
    result = await session.execute(select(DayContext).where(DayContext.date == on_date))
    return result.scalars().first()


# ── Full view collection for API / UI ─────────────────────────────────────────
async def collect(session: AsyncSession, limit: int = 200) -> dict[str, Any]:
    """Collect everything needed by the Signals screen in one round-trip."""
    signals = await list_signals(session, include_misparse=True, limit=limit)
    freq = await key_frequency(session, include_misparse=True)

    sig_items = []
    for s in signals:
        sig_items.append({
            "id": s.id,
            "date": s.date.isoformat(),
            "time": s.at_time.isoformat() if s.at_time else None,
            "kind": s.kind,
            "key": normalize_key(s.key),
            "raw_key": s.key,
            "value": s.value_num,
            "unit": s.unit,
            "note": s.note,
            "misparse": s.misparse,
            "batch_id": s.batch_id,
        })

    freq_items = [
        {
            "key": f.key,
            "count": f.count,
            "n": f.count,
            "variants": list(f.variants),
            "alias": list(f.variants),
            "examples": list(f.examples),
            "ex": list(f.examples),
        }
        for f in freq
    ]

    misparse_count = sum(1 for s in signals if s.misparse)

    return {
        "signals": sig_items,
        "frequency": freq_items,
        "kinds": [k.value for k in SignalKind],
        "misparse_count": misparse_count,
        "total_count": len(signals),
        "keys_count": len(freq_items),
    }

