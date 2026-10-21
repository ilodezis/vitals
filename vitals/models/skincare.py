"""Phase 3 — Skincare daily logs (the one *log* domain of this phase).

Daily tables, all ``InsightsMixin`` (domain='skincare'):
  * ``skincare_checks`` — what was actually done: one row per product, slot
    (morning / evening) and day, written by a tap in the app or under the
    Telegram reminder. A row is "done"; no row is "not done".
  * ``skincare_logs`` — the day's actives as conflict-engine flags. Since the
    checks exist it is *derived* from them (a checked product sets its
    ``active_flag``), so the engine, the digest and MCP keep reading the shape
    they always read. The boolean flags double as match keys:
    ``{"retinoid": true}`` / ``{"peel": true}`` — so "retinoid + peel same
    evening" is a same-domain rule that fires off the proposed checklist itself.
  * ``skincare_observations`` — graded skin state (inflammation 1-5, PIH 1-5),
    zone map + notes.
  * ``skincare_photos`` — the face photo diary, like the weight's progress photos.
"""
from __future__ import annotations

from typing import Any, Optional

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)
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
    # Which ``SkincareLog`` flag ticking this product sets — how a free-text
    # catalog entry reaches the conflict engine. Null = nothing the rules know
    # (a cleanser, say): it is tracked, it just never conflicts.
    active_flag: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)


class SkincareCheck(Base, InsightsMixin, TimestampMixin):
    """One product done in one slot on one day."""

    __tablename__ = "skincare_checks"
    __table_args__ = (
        insights_index(__tablename__),
        UniqueConstraint("date", "product_id", "slot", name="uq_skincare_checks_day_product_slot"),
        Index("ix_skincare_checks_product_id", "product_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # SET NULL rather than CASCADE: deleting a product from the catalog must not
    # rewrite the history of the days it was used. The name below keeps the row
    # readable once the product is gone.
    product_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("skincare_products.id", ondelete="SET NULL"), nullable=True
    )
    product_name: Mapped[str] = mapped_column(String(128), nullable=False)
    slot: Mapped[str] = mapped_column(String(16), nullable=False)  # morning | evening
    # The product's flag at the time of the tap, so unticking clears the flag it
    # set even if the catalog entry has been re-typed since.
    active_flag: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    done_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class SkincarePhoto(Base, InsightsMixin, TimestampMixin):
    """A face photo for a date. The file lives on disk; this is the reference."""

    __tablename__ = "skincare_photos"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_key: Mapped[str] = mapped_column(String(512), nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

