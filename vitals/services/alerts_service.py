"""system_alerts lifecycle: raise / resolve / override / list_active.

Raising is **idempotent** while an alert stays active: the partial-unique index
``uq_active_alert_per_key_entity`` guarantees one unresolved row per
``(alert_key, entity_ref)``, and :func:`raise_alert` first looks for that active
row and updates it instead of inserting a duplicate.

These functions ``flush`` (so a freshly inserted row gets its id) but do **not**
``commit`` — the caller owns the transaction boundary. In the web layer the
``get_session`` dependency commits on success; tests/scheduler commit explicitly.
"""
from __future__ import annotations

from datetime import date as date_type
from typing import Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import Severity
from vitals.models.system_alert import SystemAlert
from vitals.utils.timeutils import now_local, today_local


async def _find_active(
    session: AsyncSession, alert_key: str, entity_ref: str
) -> Optional[SystemAlert]:
    result = await session.execute(
        select(SystemAlert).where(
            SystemAlert.alert_key == alert_key,
            SystemAlert.entity_ref == entity_ref,
            SystemAlert.resolved_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def _was_dismissed_today(
    session: AsyncSession, alert_key: str, entity_ref: str, on_date: Optional[date_type] = None
) -> bool:
    """Return True if this alert was already dismissed (resolved) today.

    This prevents the noise-period alert (and similar auto-raised alerts) from
    reappearing on every page-load after the user hits 'Hide'. The alert will
    become raiseable again the next calendar day.
    """
    today = on_date or today_local()
    result = await session.execute(
        select(func.count()).where(
            SystemAlert.alert_key == alert_key,
            SystemAlert.entity_ref == entity_ref,
            SystemAlert.resolved_at.is_not(None),
            func.date(SystemAlert.resolved_at) == today,
        )
    )
    return (result.scalar() or 0) > 0


async def raise_alert(
    session: AsyncSession,
    *,
    domain: str,
    severity: str,
    message: str,
    alert_key: str,
    entity_ref: str = "",
    overridden: bool = False,
) -> SystemAlert:
    """Raise (or refresh) an active alert.

    If an unresolved alert with the same ``(alert_key, entity_ref)`` already
    exists, its ``severity``/``message`` are refreshed and it is returned — so
    re-raising the same condition never piles up duplicate rows. ``overridden``
    stamps ``override_at`` immediately (used by the conflict-engine override flow
    when a ``block`` is saved anyway).
    """
    existing = await _find_active(session, alert_key, entity_ref)
    if existing is not None:
        existing.severity = severity
        existing.message = message
        if overridden and existing.override_at is None:
            existing.override_at = now_local()
        await session.flush()
        return existing

    alert = SystemAlert(
        domain=domain,
        severity=severity,
        message=message,
        alert_key=alert_key,
        entity_ref=entity_ref,
        override_at=now_local() if overridden else None,
    )
    session.add(alert)
    await session.flush()
    return alert


async def resolve_alert(session: AsyncSession, alert_id: int) -> Optional[SystemAlert]:
    """Mark a single alert (and any of its duplicates with the same normalized message)
    resolved. Returns the target row, or None if it doesn't exist."""
    alert = await session.get(SystemAlert, alert_id)
    if alert is None:
        return None
    if alert.resolved_at is None:
        now = now_local()
        alert.resolved_at = now

        # Also resolve active duplicates (same normalized message)
        import re
        target_norm = re.sub(r'\s+', ' ', alert.message.lower().replace("ё", "е")).strip()

        stmt = select(SystemAlert).where(SystemAlert.resolved_at.is_(None))
        result = await session.execute(stmt)
        active_alerts = result.scalars().all()

        for other in active_alerts:
            if other.id == alert.id:
                continue
            other_norm = re.sub(r'\s+', ' ', other.message.lower().replace("ё", "е")).strip()
            if other_norm == target_norm:
                other.resolved_at = now

        await session.flush()
    return alert


async def resolve_by_key(
    session: AsyncSession, *, alert_key: str, entity_ref: str = ""
) -> Optional[SystemAlert]:
    """Resolve the active alert for a ``(key, entity)`` — used when the condition
    that raised it clears (e.g. a noisy-weight period ends). No-op if none active."""
    existing = await _find_active(session, alert_key, entity_ref)
    if existing is None:
        return None
    existing.resolved_at = now_local()
    await session.flush()
    return existing


async def override_alert(session: AsyncSession, alert_id: int) -> Optional[SystemAlert]:
    """Stamp ``override_at`` on an existing alert (the user chose 'Save anyway')."""
    alert = await session.get(SystemAlert, alert_id)
    if alert is None:
        return None
    if alert.override_at is None:
        alert.override_at = now_local()
        await session.flush()
    return alert


async def resolve_all(session: AsyncSession, *, domain: Optional[str] = None) -> None:
    """Resolve all active alerts, optionally filtered by domain."""
    stmt = select(SystemAlert).where(SystemAlert.resolved_at.is_(None))
    if domain is not None:
        stmt = stmt.where(SystemAlert.domain == domain)
    result = await session.execute(stmt)
    active = result.scalars().all()
    now = now_local()
    for alert in active:
        alert.resolved_at = now
    await session.flush()


async def list_active(
    session: AsyncSession, *, domain: Optional[str] = None
) -> Sequence[SystemAlert]:
    """Active (unresolved) alerts, newest first, optionally filtered by domain,
    with duplicates (by normalized message) filtered out."""
    stmt = select(SystemAlert).where(SystemAlert.resolved_at.is_(None))
    if domain is not None:
        stmt = stmt.where(SystemAlert.domain == domain)
    stmt = stmt.order_by(SystemAlert.created_at.desc(), SystemAlert.id.desc())
    result = await session.execute(stmt)
    alerts = result.scalars().all()

    import re
    seen = set()
    deduped = []
    for alert in alerts:
        norm = re.sub(r'\s+', ' ', alert.message.lower().replace("ё", "е")).strip()
        if norm not in seen:
            seen.add(norm)
            deduped.append(alert)
    return deduped



def is_blocking(severity: str) -> bool:
    """True when a severity should stop a save unless overridden."""
    return severity == Severity.BLOCK.value
