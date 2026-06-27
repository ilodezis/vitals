"""``raw_payloads`` — the central JSONB store (the "единая структура").

Every external fetch (Garmin, Hevy, a parsed lab) writes its **full** response
here, in parallel to the normalized rows it produces. Nothing is lost when an
upstream API changes shape, and re-parsing is always possible from the raw row.
Normalized rows link back via ``raw_payload_id`` (FK) and/or ``external_id``.

Manual single entries do **not** need a raw row — for them the normalized row is
itself the source of truth.

The ``payload`` column is real ``JSONB`` on Postgres (GIN-indexed for containment
queries); on the SQLite fast-test path it degrades to generic ``JSON``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, DateTime, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from vitals.models.base import Base

# JSONB on Postgres, JSON on SQLite (fast tests). The GIN index below is a no-op
# on SQLite (the dialect kwarg is ignored), so create_all still succeeds there.
_JSON_TYPE = JSONB().with_variant(JSON(), "sqlite")


class RawPayload(Base):
    __tablename__ = "raw_payloads"
    __table_args__ = (
        # Containment / key-existence queries over arbitrary upstream shapes
        # (``payload @> '{...}'``) — Postgres GIN. Built here so both create_all
        # (tests) and the Alembic migration agree on the schema.
        Index("ix_raw_payloads_payload_gin", "payload", postgresql_using="gin"),
        # The natural lookup key when reconciling a fetch against what we already
        # stored for a source.
        Index("ix_raw_payloads_domain_source_external", "domain", "source", "external_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    domain: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    # Upstream identifier (Garmin activity id, Hevy workout id, lab document id…).
    # Null for payloads that have no stable external id.
    external_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    payload: Mapped[Any] = mapped_column(_JSON_TYPE, nullable=False)
    # Stamped once the parser has turned this raw row into normalized rows. Null =
    # not yet processed (a re-parse / backfill can sweep ``processed_at IS NULL``).
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
