"""Timeline — manual annotations (life events, illness, travel, protocol
changes) that show up as flags on every domain's chart and as rows in the
cross-domain event feed.

``Annotation`` uses ``InsightsMixin.date`` as the event's start; ``end_date`` is
null for a point-in-time event or set for a range (a trip, an illness). Its
``domain`` (from the mixin) names which chart the flag belongs to —
``Domain.TIMELINE`` for a global flag shown on every chart, or a specific domain
(``weight``, ``glp1``, …) to scope it to just that one.
"""
from __future__ import annotations

from datetime import date as date_type
from typing import Optional

from sqlalchemy import Date, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from vitals.enums import AnnotationKind, Domain
from vitals.models.base import Base, TimestampMixin
from vitals.models.mixins import InsightsMixin, insights_index

DOMAIN = Domain.TIMELINE.value


class Annotation(Base, InsightsMixin, TimestampMixin):
    __tablename__ = "annotations"
    __table_args__ = (
        insights_index(__tablename__),
        Index("ix_annotations_date_range", "date", "end_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Null end = a point-in-time event; set = a range (trip, illness).
    end_date: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    kind: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default=AnnotationKind.NOTE.value
    )
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
