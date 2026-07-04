"""Phase 3 — Skincare daily logs (the one *log* domain of this phase).

Two daily tables, both ``InsightsMixin`` (domain='skincare'):
  * ``skincare_logs`` — the evening checklist (which actives were applied). The
    boolean flags double as conflict-engine match keys: ``{"retinoid": true}`` /
    ``{"peel": true}`` — so "retinoid + peel same evening" is a same-domain rule
    that fires off the proposed checklist itself.
  * ``skincare_observations`` — graded skin state (inflammation 1-5, PIH 1-5),
    zone map + notes.
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import Boolean, Integer, JSON, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from vitals.enums import Domain
from vitals.models.base import Base, TimestampMixin
from vitals.models.mixins import InsightsMixin, insights_index

DOMAIN = Domain.SKINCARE.value


class SkincareLog(Base, InsightsMixin, TimestampMixin):
    """Evening routine checklist for a date (one per day — the service upserts)."""

    __tablename__ = "skincare_logs"
    __table_args__ = (insights_index(__tablename__),)

    id: Mapped[int] = mapped_column(primary_key=True)
    retinoid: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    azelaic: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    peel: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    niacinamide_spf: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    moisturizer: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # Added for the dermatology conflict-rule catalog (retinoid/peel vs. these —
    # the checklist previously had no way to represent either active).
    vitamin_c: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    benzoyl_peroxide: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class SkincareObservation(Base, InsightsMixin, TimestampMixin):
    """Graded skin-state observation for a date."""

    __tablename__ = "skincare_observations"
    __table_args__ = (insights_index(__tablename__),)

    id: Mapped[int] = mapped_column(primary_key=True)
    inflammation: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 1-5
    pih: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 1-5 (post-inflammatory hyperpigmentation)
    zone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class SkincareProduct(Base, TimestampMixin):
    """Reference catalog of active skincare products and their schedules."""

    __tablename__ = "skincare_products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g., "Ретиноид", "Азелаин"
    active_ingredient: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    usage_instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    default_time: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'evening'")
    )  # morning, evening, both
    schedule_days: Mapped[Any] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=False, server_default=text("'[]'")
    )  # array of integers e.g. [1, 2, 3] (Monday=1, Sunday=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

