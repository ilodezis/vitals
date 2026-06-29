"""Phase 2 — GLP-1 Protocol models.

All rows carry ``domain = 'glp1'`` via ``InsightsMixin`` (point metrics) or an
explicit ``domain`` column (``DosePhase`` is a date range, like ``NoiseMarker``).

Three tables:
  * ``glp1_injections`` — each shot (date, drug, dose mg, body-map site).
  * ``glp1_dose_phases`` — date ranges of "on dose X" that paint the weight chart
    overlay and define the window the plateau check evaluates.
  * ``glp1_side_effects`` — symptom log (date, type, severity 1-5).

Nothing here blocks: the product is a navigator. The plateau detector raises a
passive ``warn`` alert (no auto-escalation) — that lives in ``glp1_service``.
"""
from __future__ import annotations

from datetime import date as date_type
from typing import Optional

from sqlalchemy import CheckConstraint, Date, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from vitals.enums import Domain
from vitals.models.base import Base, TimestampMixin
from vitals.models.mixins import InsightsMixin, insights_index

DOMAIN = Domain.GLP1.value


class Injection(Base, InsightsMixin, TimestampMixin):
    """A single subcutaneous injection event."""

    __tablename__ = "glp1_injections"
    __table_args__ = (
        insights_index(__tablename__),
        CheckConstraint("dose_mg > 0", name="ck_glp1_injections_dose_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    drug: Mapped[str] = mapped_column(String(32), nullable=False)
    dose_mg: Mapped[float] = mapped_column(Float, nullable=False)
    # Body-map rotation site (vitals.enums.InjectionSite); nullable so a shot can
    # be logged without recording where.
    site: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class DosePhase(Base, TimestampMixin):
    """A date range the user spent on a given drug/dose. Like ``NoiseMarker`` it
    spans ``start_date``/``end_date`` (open-ended when ``end_date`` is null) rather
    than the single ``InsightsMixin.date``, but keeps ``domain``/``source`` for
    uniform filtering/export. Feeds the weight chart's GLP-1 colour overlay and
    bounds the plateau check.
    """

    __tablename__ = "glp1_dose_phases"
    __table_args__ = (
        Index("ix_glp1_dose_phases_range", "domain", "start_date", "end_date"),
        CheckConstraint("dose_mg > 0", name="ck_glp1_dose_phases_dose_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    domain: Mapped[str] = mapped_column(String(32), nullable=False, server_default=DOMAIN)
    source: Mapped[str] = mapped_column(String(32), nullable=False, server_default="manual")
    start_date: Mapped[date_type] = mapped_column(Date, nullable=False)
    # Null end = the phase is still ongoing (the current dose).
    end_date: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    drug: Mapped[str] = mapped_column(String(32), nullable=False)
    dose_mg: Mapped[float] = mapped_column(Float, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class SideEffect(Base, InsightsMixin, TimestampMixin):
    """A reported side effect on a date, graded 1-5."""

    __tablename__ = "glp1_side_effects"
    __table_args__ = (
        insights_index(__tablename__),
        CheckConstraint(
            "severity >= 1 AND severity <= 5",
            name="ck_glp1_side_effects_severity_range",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Free-text-ish type (nausea, fatigue, constipation, ...); UI offers presets.
    effect_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
