"""Module 7 — Lab results & parser.

Two tables, ``domain='labs'``:

  * ``lab_results`` — one row per (date, marker) measurement. Carries
    ``InsightsMixin`` (the panel's collection ``date``, ``source`` =
    ``manual`` | ``lab_parser``), the value + unit + the reference range as a
    **snapshot** (labs differ, so we store the range that came with the result),
    the computed out-of-range ``flag``, and a link to the uploaded document's raw
    payload. This is what the per-marker history charts read.
  * ``lab_markers`` — a lean per-marker catalog holding the things that are a
    property of the *marker*, not of any single result: importance ``tier``
    (1 critical / 2 deferrable), an optional ``retest_interval_days``, and a
    ``defer_until`` date set by "Defer Retest" to pause an overdue alert. Rows are
    auto-created the first time a marker is seen.
"""
from __future__ import annotations

from datetime import date as date_type
from typing import Optional

from sqlalchemy import Date, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from vitals.enums import Domain
from vitals.models.base import Base, TimestampMixin
from vitals.models.mixins import InsightsMixin, insights_index

DOMAIN = Domain.LABS.value


class LabResult(Base, InsightsMixin, TimestampMixin):
    """A single measured marker value on a date."""

    __tablename__ = "lab_results"
    __table_args__ = (
        insights_index(__tablename__),
        # Per-marker history scans (charts) hit this constantly.
        Index("ix_lab_results_marker_date", "marker", "date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    marker: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # Reference range snapshot as reported on this result (a lab's range can
    # differ from the catalog default).
    ref_low: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ref_high: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Computed classification (vitals.enums.LabFlag); null until range is known.
    flag: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    lab_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    raw_payload_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("raw_payloads.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class LabMarker(Base, TimestampMixin):
    """Per-marker reference/config (catalog). No per-day date → no InsightsMixin,
    just ``domain``/``source`` for uniform export (like the supplements catalog)."""

    __tablename__ = "lab_markers"
    __table_args__ = (Index("ix_lab_markers_name", "name", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    domain: Mapped[str] = mapped_column(String(32), nullable=False, server_default=DOMAIN)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    ref_low: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ref_high: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Importance tier: 1 = critical (alert promptly), 2 = deferrable.
    tier: Mapped[int] = mapped_column(Integer, nullable=False, server_default="2")
    # How often this marker should be retested; null = no schedule.
    retest_interval_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # "Defer Retest" — suppress the overdue alert until this date.
    defer_until: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
