"""Cross-cutting model mixins — the heart of the "Insights Layer".

``InsightsMixin`` is **mandatory on every log/metric table in every module**. It
gives each row an indexed ``date``, an indexed ``domain``, and a ``source``, plus
a composite ``(domain, date)`` index. That uniformity is what makes mass export,
analytical filtering, and future LLM tool-calling work the same way across weight,
labs, Garmin, workouts, etc. without per-module special-casing.

``domain`` / ``source`` values come from ``vitals.enums`` (``Domain`` / ``Source``).
"""
from __future__ import annotations

from datetime import date as date_type

from sqlalchemy import Date, Index, String
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from vitals.enums import Source


def insights_index(tablename: str) -> Index:
    """The composite ``(domain, date)`` index for a table using ``InsightsMixin``.

    Concrete models that need *additional* ``__table_args__`` (unique constraints,
    partial indexes) must define ``__table_args__`` themselves and include this
    call, because a subclass-level ``__table_args__`` shadows the mixin's. Models
    with no extra args get it automatically from the mixin (see below).
    """
    return Index(f"ix_{tablename}_domain_date", "domain", "date")


class InsightsMixin:
    # Calendar date the row pertains to (NOT created_at). Indexed for range scans
    # and per-day lookups; the main axis of every chart and export.
    date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)

    # Module the row belongs to — one of vitals.enums.Domain. Indexed so a single
    # domain can be sliced out of the data lake cheaply.
    domain: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    # Provenance — one of vitals.enums.Source (manual | garmin_api | hevy_api | …).
    source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=Source.MANUAL.value,
        server_default=Source.MANUAL.value,
    )

    @declared_attr.directive
    def __table_args__(cls) -> tuple:  # noqa: N805
        return (insights_index(cls.__tablename__),)
