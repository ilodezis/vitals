"""Body-composition scans — InBody / МедАсс (BIA) printouts.

These analyzers print a sheet with *dozens* of metrics (skeletal muscle mass,
intra-/extra-cellular water, protein, minerals, visceral fat, per-segment lean
analysis, phase angle, the device score, …) — far more than the Navy tape
formula yields. We mirror that with a parent → child tree so **every** printed
value is captured generically, whatever the device:

  * ``body_scans``        — one row per uploaded/recorded measurement. Carries
    ``InsightsMixin`` (``domain='body_comp'``), the analyzer ``device`` name, an
    optional ``file_key`` (the original sheet photo, like a progress photo), and
    a link back to the raw vision payload.
  * ``body_scan_metrics`` — each printed parameter as a generic
    ``(metric_key, value, unit, ref_low, ref_high, segment)`` row. Unknown
    metrics are kept too (``category='other'``) — nothing is lost.

Following the Hevy convention: only the scan is an independent dated "log" row;
the metrics are its structural children (FK + cascade), so they don't repeat the
InsightsMixin trio — the scan's ``date`` is the time axis a join reads through.

The full upstream vision response is also kept verbatim in ``raw_payloads`` (the
re-parse safety net), so the owner's edits in the preview step never overwrite
the original extraction.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import (
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from vitals.enums import Domain
from vitals.models.base import Base, TimestampMixin
from vitals.models.mixins import InsightsMixin, insights_index

DOMAIN = Domain.BODY_COMPOSITION.value


class BodyScan(Base, InsightsMixin, TimestampMixin):
    """One body-composition measurement (an InBody / МедАсс sheet)."""

    __tablename__ = "body_scans"
    __table_args__ = (
        # Composite (domain, date) index from the mixin. No unique-per-date
        # constraint on purpose: two scans on the same day are possible (e.g. a
        # gym scale plus a clinic device).
        insights_index(__tablename__),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Analyzer model as printed/recognised (InBody 770, МедАсс, …). Null = unknown.
    device: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Storage key of the original sheet photo (web/static/uploads), like
    # ProgressPhoto.file_key. Null for an agent/manual scan with no image.
    file_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    # Link back to the verbatim vision payload (the re-parse safety net). Null for
    # a manually/agent-entered scan (the rows are then their own source of truth).
    raw_payload_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("raw_payloads.id", ondelete="SET NULL"), nullable=True, index=True
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    metrics: Mapped[list["BodyScanMetric"]] = relationship(
        back_populates="scan",
        cascade="all, delete-orphan",
        order_by="BodyScanMetric.id",
    )


class BodyScanMetric(Base, TimestampMixin):
    """A single parameter from a scan — generic key/value so any device fits."""

    __tablename__ = "body_scan_metrics"
    __table_args__ = (
        Index("ix_body_scan_metrics_scan", "scan_id"),
        # Per-metric history series (e.g. SMM or phase-angle over time) read by key.
        Index("ix_body_scan_metrics_key", "metric_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    scan_id: Mapped[int] = mapped_column(
        ForeignKey("body_scans.id", ondelete="CASCADE"), nullable=False
    )
    # Canonical key from the metric registry (e.g. "skeletal_muscle_mass",
    # "visceral_fat_area", "phase_angle"). Unknown labels get a slug + category
    # 'other' so they're still captured.
    metric_key: Mapped[str] = mapped_column(String(64), nullable=False)
    # The label exactly as printed on the sheet (source language — МедАсс is
    # Russian, InBody English/Korean), kept for provenance and display.
    label: Mapped[str] = mapped_column(String(256), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # Target / normal range printed on the sheet, when present.
    ref_low: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ref_high: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # For segmental analysis rows: right_arm | left_arm | trunk | right_leg |
    # left_leg. Null for whole-body metrics.
    segment: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    # Grouping for the UI: composition | water | segmental | score | derived | other.
    category: Mapped[str] = mapped_column(
        String(24), nullable=False, default="other", server_default="other"
    )

    scan: Mapped["BodyScan"] = relationship(back_populates="metrics")
