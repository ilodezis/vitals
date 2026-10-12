"""Helpers for the central ``raw_payloads`` JSONB store.

Every external fetch (Hevy workout, Garmin daily metric, an activity) keeps its
full upstream response here parallel to the normalized rows it produces, so a
later schema/parse change never loses data. Both the Hevy and Garmin services
reconcile against existing rows by ``(domain, source, external_id)`` — the
natural lookup key the table is indexed for — so re-syncing refreshes one raw row
per upstream object instead of piling up duplicates.

:func:`upsert_raw_payload` resets ``processed_at`` to ``None`` whenever it
refreshes an existing row ("re-parse pending") — the promise being that
something later sweeps rows still sitting at ``processed_at IS NULL`` and
re-derives their normalized rows from the raw copy. :func:`sweep_domain` is
that sweep, generic over any domain. ``signals_service.reparse_unparsed`` is
the original, domain-specific version of the same idea (predates this one and
stays special-cased — it piggybacks on the morning brief instead of a
schedule of its own; see its docstring).
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.models.raw_payload import RawPayload
from vitals.utils.timeutils import now_local

logger = logging.getLogger(__name__)

# How far back a sweep looks, and how many rows one pass may cost. Same values
# as signals_service's REPARSE_WINDOW_DAYS/REPARSE_BATCH; kept as separate
# constants because that one predates this and stays domain-specific.
REPARSE_WINDOW_DAYS = 14
REPARSE_BATCH = 20


async def find_raw_payload(
    session: AsyncSession, *, domain: str, source: str, external_id: str
) -> Optional[RawPayload]:
    """The stored raw payload for ``(domain, source, external_id)``, if any."""
    result = await session.execute(
        select(RawPayload).where(
            RawPayload.domain == domain,
            RawPayload.source == source,
            RawPayload.external_id == external_id,
        )
    )
    return result.scalars().first()


async def upsert_raw_payload(
    session: AsyncSession,
    *,
    domain: str,
    source: str,
    external_id: str,
    payload: Any,
) -> RawPayload:
    """Insert or refresh the raw payload for ``(domain, source, external_id)``.

    Flushes so the returned row has an ``id`` the normalized row can link to.
    Does not commit — the caller owns the transaction.
    """
    row = await find_raw_payload(session, domain=domain, source=source, external_id=external_id)
    if row is None:
        row = RawPayload(
            domain=domain,
            source=source,
            external_id=external_id,
            payload=payload,
            fetched_at=now_local(),
        )
        session.add(row)
    else:
        row.payload = payload
        row.fetched_at = now_local()
        row.processed_at = None  # re-parse pending
    await session.flush()
    return row


async def sweep_domain(
    session: AsyncSession,
    *,
    domain: str,
    reparse: Callable[[AsyncSession, RawPayload], Awaitable[Any]],
    has_normalized: Any,
    limit: int = REPARSE_BATCH,
    since_days: int = REPARSE_WINDOW_DAYS,
) -> int:
    """Generic re-parse sweep, modeled on ``signals_service.reparse_unparsed`` —
    extended here so every domain can reuse the same query instead of each
    re-implementing it.

    Picks up to ``limit`` rows for ``domain`` still at ``processed_at IS NULL``
    (what :func:`upsert_raw_payload` leaves behind whenever it refreshes a row)
    within ``since_days`` of ``fetched_at``, excluding rows that already have a
    normalized child. ``has_normalized`` is a caller-built ``EXISTS`` clause
    correlated to ``RawPayload.id`` (e.g. ``select(Model.id).where(Model.
    raw_payload_id == RawPayload.id).exists()``) — passed in rather than
    hard-coded so this function stays domain-agnostic; it never imports a
    domain's own models. ``reparse`` does the actual re-derivation, reusing
    that domain's existing ingest logic.

    A raising ``reparse`` call is logged and skipped so one bad row can't abort
    the batch; ``processed_at`` is stamped only after a row's ``reparse`` call
    returns without raising. Flushes once at the end of the batch, not per row.
    Does not commit — the caller owns the transaction.

    ponytail: a reparse that raises *after* partially writing (e.g. midway
    through a multi-step ingest) leaves ``processed_at IS NULL`` but may
    already have a partial child row, which would make ``has_normalized`` skip
    it on every later sweep too — stuck rather than retried. Narrow edge case
    (most failures here are validation, which happens before any write); add a
    per-row SAVEPOINT (``session.begin_nested()``) around the ``reparse`` call
    if this shows up for real.
    """
    cutoff = now_local() - timedelta(days=since_days)
    stmt = (
        select(RawPayload)
        .where(
            RawPayload.domain == domain,
            RawPayload.processed_at.is_(None),
            RawPayload.fetched_at >= cutoff,
            ~has_normalized,
        )
        .order_by(RawPayload.id)
        .limit(limit)
    )
    done = 0
    for raw in (await session.execute(stmt)).scalars().all():
        try:
            await reparse(session, raw)
        except Exception:
            logger.warning("re-parse failed for %s raw payload %s", domain, raw.id, exc_info=True)
            continue
        raw.processed_at = now_local()
        done += 1
    if done:
        await session.flush()
    return done


async def sweep_pending_job(session_factory, redis=None) -> None:
    """Nightly sweep for garmin/hevy/labs/body_comp raw payloads still pending a
    normalized row (registered in vitals/scheduler/jobs.py).

    Signals' own reparse instead piggybacks on the morning brief (see
    proactive/inbound.py, called from brief.py) because it has to finish before
    that message goes out. These four domains have no such deadline — they're
    fed by a periodic poll (garmin/hevy) or an owner upload (labs/body_comp),
    not a message that's about to be sent — so one shared nightly pass covers
    all of them instead of four separate jobs. Each domain commits (and rolls
    back on failure) on its own so one domain's trouble can't lose or block
    another's completed work.
    """
    from vitals.services import body_scan_service, garmin_service, hevy_service, labs_service

    async with session_factory() as session:
        for name, sweep in (
            ("garmin", garmin_service.reparse_pending),
            ("hevy", hevy_service.reparse_pending),
            ("labs", labs_service.reparse_pending),
            ("body_comp", body_scan_service.reparse_pending),
        ):
            try:
                await sweep(session)
                await session.commit()
            except Exception:
                logger.warning("raw payload sweep failed for domain %s", name, exc_info=True)
                await session.rollback()
