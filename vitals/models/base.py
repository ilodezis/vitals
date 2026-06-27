"""Declarative base + a reusable ``created_at``/``updated_at`` mixin.

Ported from Boxly's ``bot/models/base.py`` (which was a bare ``DeclarativeBase``)
and extended with ``TimestampMixin`` — Vitals is a long-history data lake, so
every row records when it was written and last touched. Timestamps use server
defaults (``now()`` / ``ON UPDATE``) so they're correct regardless of which
process inserts the row (web request vs scheduler job vs importer).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    """Adds ``created_at`` and ``updated_at`` to a model.

    ``created_at`` is stamped once on insert; ``updated_at`` is refreshed by
    SQLAlchemy's ``onupdate`` on every flush that changes the row.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
