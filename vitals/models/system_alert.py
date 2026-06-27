"""``system_alerts`` — the unified alert ladder across every module.

Severity (``vitals.enums.Severity``):
  * ``info``  — passive UI badge.
  * ``warn``  — non-intrusive UI status only (never popups/modals).
  * ``block`` — surfaced as a pre-save validation error; overridable through the
    conflict-engine flow, which stamps ``override_at`` when the user proceeds.

Dedupe: ``(alert_key, entity_ref)`` is unique **among unresolved rows** via a
partial unique index (the Boxly partial-unique pattern). ``entity_ref`` defaults
to ``''`` (not NULL) so the dedupe also covers entity-less global alerts — NULLs
would never collide. Raising the same alert twice is therefore idempotent while
it stays active; once ``resolved_at`` is set the slot frees for a fresh raise.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from vitals.models.base import Base


class SystemAlert(Base):
    __tablename__ = "system_alerts"
    __table_args__ = (
        # At most one active (unresolved) alert per (key, entity). Mirrors Boxly's
        # uq_active_* partial indexes; declared here so create_all (tests) and the
        # Alembic migration build the same constraint.
        Index(
            "uq_active_alert_per_key_entity",
            "alert_key",
            "entity_ref",
            unique=True,
            postgresql_where=text("resolved_at IS NULL"),
            sqlite_where=text("resolved_at IS NULL"),
        ),
        # Dashboard query: list active alerts, newest first, filterable by domain.
        Index("ix_system_alerts_domain_resolved", "domain", "resolved_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    domain: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    # Stable identifier for the *kind* of alert (e.g. "weight.noisy_period_active",
    # "garmin.mfa_required"). Together with entity_ref it dedupes active rows.
    alert_key: Mapped[str] = mapped_column(String(128), nullable=False)
    # Optional reference to the entity the alert is about ("weight_log:123",
    # "noise_marker:5"). '' = a global alert not tied to a single row.
    entity_ref: Mapped[str] = mapped_column(
        String(128), nullable=False, server_default=text("''")
    )

    # Set when a `block` alert was overridden by the user (the product always
    # leaves the final choice to the user). Distinct from resolved_at.
    override_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Set when the alert is no longer active (condition cleared or acknowledged).
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
