"""Helpers for the central ``raw_payloads`` JSONB store.

Every external fetch (Hevy workout, Garmin daily metric, an activity) keeps its
full upstream response here parallel to the normalized rows it produces, so a
later schema/parse change never loses data. Both the Hevy and Garmin services
reconcile against existing rows by ``(domain, source, external_id)`` — the
natural lookup key the table is indexed for — so re-syncing refreshes one raw row
per upstream object instead of piling up duplicates.
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.models.raw_payload import RawPayload
from vitals.utils.timeutils import now_local


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
    result = await session.execute(
        select(RawPayload).where(
            RawPayload.domain == domain,
            RawPayload.source == source,
            RawPayload.external_id == external_id,
        )
    )
    row: Optional[RawPayload] = result.scalars().first()
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
