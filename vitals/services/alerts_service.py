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

    For status alerts recomputed from fast-moving data (a new weigh-in lands
    most days), binding entity_ref to "the latest triggering row" would barely
    change anything, and binding it to something coarser (e.g. the active
    noise period) could suppress a still-relevant status for weeks. So these
    keep the daily-nag contract: dismissing hides the alert for the rest of
    today; it becomes raiseable again the next calendar day. Used by the
    weight noise-period alert and the GLP-1 plateau alert — contrast with
    :func:`_was_ever_dismissed`, used where the alert is bound to a specific,
    infrequently-arriving row (lab results, body scans).
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


async def _was_ever_dismissed(
    session: AsyncSession, alert_key: str, entity_ref: str
) -> bool:
    """Return True if this exact (alert_key, entity_ref) was ever dismissed.

    Callers bind ``entity_ref`` to the specific row that triggered the alert
    (e.g. ``f"{marker}:{lab_result_id}"``), so once dismissed it never comes
    back for that row — only a new triggering row (new entity_ref) can raise
    it again. See :func:`resolve_superseded` for cleaning up alerts tied to a
    row that's no longer the current one.
    """
    result = await session.execute(
        select(func.count()).where(
            SystemAlert.alert_key == alert_key,
            SystemAlert.entity_ref == entity_ref,
            SystemAlert.resolved_at.is_not(None),
        )
    )
    return (result.scalar() or 0) > 0


async def resolve_superseded(
    session: AsyncSession,
    *,
    alert_key: str,
    keep_entity: Optional[str],
    marker: Optional[str] = None,
) -> None:
    """Resolve active ``alert_key`` rows that no longer correspond to the
    current triggering row, so they don't linger as orphaned duplicates once
    ``entity_ref`` starts varying per row instead of staying fixed per marker.

    If ``marker`` is given, only rows for that marker are touched — either the
    bare legacy ``entity_ref == marker`` form or the ``f"{marker}:"``-prefixed
    form — since multiple markers share one ``alert_key``. If ``marker`` is
    ``None``, every active row for ``alert_key`` other than ``keep_entity`` is
    resolved (the singleton case, e.g. body-scan alerts, where only one entity
    is ever current). ``keep_entity=None`` resolves everything for the key.
    """
    result = await session.execute(
        select(SystemAlert).where(
            SystemAlert.alert_key == alert_key,
            SystemAlert.resolved_at.is_(None),
        )
    )
    now = now_local()
    changed = False
    for row in result.scalars().all():
        if row.entity_ref == keep_entity:
            continue
        if marker is not None and not (
            row.entity_ref == marker or row.entity_ref.startswith(f"{marker}:")
        ):
            continue
        row.resolved_at = now
        changed = True
    if changed:
        await session.flush()


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
