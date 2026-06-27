"""Phase 1 — Weight & Body Composition models.

All log/metric tables carry ``domain = 'weight'`` via ``InsightsMixin``. The
``DOMAIN`` constant below is the single value the service stamps on writes.

Priority rule (enforced in ``weight_service``, not the DB alone): a **manual**
entry for a date supersedes a **Garmin**-imported weight for the same date. We
keep both rows (data-lake principle — never lose data) but mark the loser
``superseded = True``; a partial unique index guarantees at most one *active*
(non-superseded) weight per date.
"""
from __future__ import annotations

from datetime import date as date_type
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from vitals.enums import Domain
from vitals.models.base import Base, TimestampMixin
from vitals.models.mixins import InsightsMixin, insights_index

DOMAIN = Domain.WEIGHT.value


class WeightLog(Base, InsightsMixin, TimestampMixin):
    __tablename__ = "weight_logs"
    __table_args__ = (
        insights_index(__tablename__),
        # At most one *active* weight per date. The service supersedes the
        # previous active row (e.g. a Garmin import) before inserting a manual
        # one, so this invariant encodes "manual beats Garmin for the day".
        Index(
            "uq_active_weight_per_date",
            "date",
            unique=True,
            postgresql_where=text("superseded = false"),
            sqlite_where=text("superseded = 0"),
        ),
        # A weight is a physical mass — never zero or negative.
        CheckConstraint("weight_kg > 0", name="ck_weight_logs_weight_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    # Links back to the central JSONB store when the row came from an external
    # fetch (Garmin). Null for manual entries (the row is its own source of truth).
    raw_payload_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("raw_payloads.id", ondelete="SET NULL"), nullable=True, index=True
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # True once a higher-priority row for the same date supersedes this one.
    superseded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )


class BodyMeasurement(Base, InsightsMixin, TimestampMixin):
    __tablename__ = "body_measurements"
    __table_args__ = (
        insights_index(__tablename__),
        # One measurement set per day (the service upserts).
        UniqueConstraint("date", name="uq_body_measurement_per_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    neck_cm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    waist_cm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Required only by the female Navy formula (gated behind config); nullable for
    # the male single-user default.
    hips_cm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Derived (Navy) and stored so charts/export don't recompute. body_fat_pct is
    # computable from measurements + height alone; lbm_kg also needs the day's
    # active weight, so it's null when no weight exists for the date.
    body_fat_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lbm_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class ProgressPhoto(Base, InsightsMixin, TimestampMixin):
    __tablename__ = "progress_photos"
    __table_args__ = (insights_index(__tablename__),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # Storage key / path of the image. Files live outside the DB (gitignored
    # web/static/uploads or, later, object storage); this is the reference.
    file_key: Mapped[str] = mapped_column(String(512), nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class NoiseMarker(Base, TimestampMixin):
    """A date range to **exclude** from trend & regression (creatine loading,
    sodium spike, training start → water-weight noise). Not a point metric, so it
    carries ``start_date``/``end_date`` instead of ``InsightsMixin.date`` — but it
    keeps ``domain``/``source`` for uniform filtering/export.
    """

    __tablename__ = "noise_markers"
    __table_args__ = (
        Index("ix_noise_markers_domain_range", "domain", "start_date", "end_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    domain: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=DOMAIN
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False, server_default="manual")
    start_date: Mapped[date_type] = mapped_column(Date, nullable=False)
    # Null end = open-ended (the noise period is still ongoing).
    end_date: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
