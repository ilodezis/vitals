"""Phase 3 — Supplements catalog (reference, not a daily log).

Per the product spec the supplement domain is **catalog/reference only** — daily
check-ins live in an external app (Ritual). So this is a reference table (like
``conflict_rules``/``genetic_variants``): it carries ``domain``/``source`` for
uniform export but **no** ``InsightsMixin.date`` (there's nothing per-day here).

``key`` is a stable slug used by the **conflict engine** to match rules
(``{"key": "iron", "active": true}``) independent of the human ``name``. Active
rows are what the supplements domain resolver exposes to cross-domain rules.

``SupplementPeriod`` is the history the ``active`` flag alone cannot keep: one row
per stretch a supplement was taken, ``date`` the day it started and ``end_date``
the day it stopped (``None`` while it is still being taken). Without it "did the
skin change after starting X" has no start date to look from.
"""
from __future__ import annotations

from datetime import date as date_type
from typing import Optional

from sqlalchemy import Boolean, Date, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from vitals.enums import Domain
from vitals.models.base import Base, TimestampMixin
from vitals.models.mixins import InsightsMixin, insights_index

DOMAIN = Domain.SUPPLEMENTS.value


class Supplement(Base, TimestampMixin):
    __tablename__ = "supplements"
    __table_args__ = (
        Index("ix_supplements_key", "key"),
        Index("ix_supplements_active", "active"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    domain: Mapped[str] = mapped_column(String(32), nullable=False, server_default=DOMAIN)
    source: Mapped[str] = mapped_column(String(32), nullable=False, server_default="manual")

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # Stable slug for conflict-rule matching (e.g. 'iron', 'isotretinoin').
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    dose: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    timing: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Evidence tier A/B/C (vitals.enums.Evidence).
    evidence: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    contraindications: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class SupplementPeriod(Base, InsightsMixin, TimestampMixin):
    """One stretch of taking a supplement: started ``date``, stopped ``end_date``."""

    __tablename__ = "supplement_periods"
    __table_args__ = (
        insights_index("supplement_periods"),
        Index("ix_supplement_periods_supplement", "supplement_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    supplement_id: Mapped[int] = mapped_column(
        ForeignKey("supplements.id", ondelete="CASCADE"), nullable=False
    )
    # Null while the supplement is still being taken.
    end_date: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
