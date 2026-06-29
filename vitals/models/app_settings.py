"""``app_settings`` — a generic single-user key-value config store (JSONB).

Vitals has no ``users`` table (single user) and no schema-per-setting table. This
KV store holds small pieces of mutable app configuration that must change **at
runtime** (no container restart), keyed by a short string and carrying a JSONB
``value``. The first such setting is ``enabled_modules`` (dashboard modularity).

Why KV-JSONB and not a dedicated column: a new setting later is a new *row*, not
a migration; and a malformed value in one key can't break the others (row-level
isolation). The ``value`` column is real ``JSONB`` on Postgres and degrades to
generic ``JSON`` on the SQLite fast-test path (same trick as ``raw_payloads``).

This is config, not a domain log/metric — so it deliberately does **not** inherit
``InsightsMixin`` (which is reserved for ``(domain, date, source)`` rows).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from vitals.models.base import Base, TimestampMixin

# JSONB on Postgres, JSON on SQLite (fast tests).
_JSON_TYPE = JSONB().with_variant(JSON(), "sqlite")


class AppSetting(Base, TimestampMixin):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(_JSON_TYPE, nullable=False)
