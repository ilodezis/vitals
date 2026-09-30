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


class AlertBook:
    """The alerts of a few keys read once, for a refresh pass that walks many entities.

    A pass that asks :func:`resolve_superseded` / :func:`_was_ever_dismissed` /
    :func:`raise_alert` / :func:`resolve_by_key` once per entity pays several
    queries per entity. The book answers the same questions from two reads —
    the active rows and the dismissed identities of its keys — and keeps itself
    current as the pass changes them, so the outcome is the same row for row.
    Only valid for the keys it was loaded with, within one session."""

    def __init__(self, session: AsyncSession, keys: Sequence[str]) -> None:
        self._session = session
        self._keys = frozenset(keys)
        self._active: dict[tuple[str, str], SystemAlert] = {}
        self._dismissed: set[tuple[str, str]] = set()

    @classmethod
    async def load(cls, session: AsyncSession, keys: Sequence[str]) -> AlertBook:
        book = cls(session, keys)
        active = await session.execute(
            select(SystemAlert).where(
                SystemAlert.alert_key.in_(book._keys), SystemAlert.resolved_at.is_(None)
            )
        )
        for row in active.scalars().all():
            book._active[(row.alert_key, row.entity_ref)] = row
        dismissed = await session.execute(
            select(SystemAlert.alert_key, SystemAlert.entity_ref)
            .where(SystemAlert.alert_key.in_(book._keys), SystemAlert.resolved_at.is_not(None))
            .distinct()
        )
        book._dismissed = {(k, e) for k, e in dismissed.all()}
        return book

    def _check(self, alert_key: str) -> None:
        if alert_key not in self._keys:
            raise KeyError(f"alert key {alert_key!r} was not loaded into this book")

    def _resolve(self, row: SystemAlert, now) -> None:
        row.resolved_at = now
        del self._active[(row.alert_key, row.entity_ref)]
        self._dismissed.add((row.alert_key, row.entity_ref))

    async def resolve_superseded(
        self, *, alert_key: str, keep_entity: Optional[str], marker: Optional[str] = None
    ) -> None:
        """:func:`resolve_superseded` against the book."""
        self._check(alert_key)
        now = now_local()
        changed = False
        for (key, entity), row in list(self._active.items()):
            if key != alert_key or entity == keep_entity:
                continue
            if marker is not None and not (entity == marker or entity.startswith(f"{marker}:")):
                continue
            self._resolve(row, now)
            changed = True
        if changed:
            await self._session.flush()

    def was_ever_dismissed(self, alert_key: str, entity_ref: str) -> bool:
        """:func:`_was_ever_dismissed` against the book."""
        self._check(alert_key)
        return (alert_key, entity_ref) in self._dismissed

    async def raise_alert(
        self, *, domain: str, severity: str, message: str, alert_key: str, entity_ref: str = ""
    ) -> SystemAlert:
        """:func:`raise_alert` against the book."""
        self._check(alert_key)
        existing = self._active.get((alert_key, entity_ref))
        if existing is not None:
            if existing.severity != severity or existing.message != message:
                existing.severity = severity
                existing.message = message
                await self._session.flush()
            return existing
        alert = SystemAlert(
            domain=domain, severity=severity, message=message, alert_key=alert_key, entity_ref=entity_ref
        )
        self._session.add(alert)
        await self._session.flush()
        self._active[(alert_key, entity_ref)] = alert
        return alert

    async def resolve_by_key(self, *, alert_key: str, entity_ref: str = "") -> Optional[SystemAlert]:
        """:func:`resolve_by_key` against the book."""
        self._check(alert_key)
        existing = self._active.get((alert_key, entity_ref))
        if existing is None:
            return None
        self._resolve(existing, now_local())
        await self._session.flush()
        return existing


async def resolve_alert(session: AsyncSession, alert_id: int) -> Optional[SystemAlert]:
    """Mark exactly the one alert identified by ``alert_id`` resolved. Returns the
    target row, or None if it doesn't exist.

    Alert identity is ``(alert_key, entity_ref)`` — two rows that merely share
    message text (e.g. the same templated message for two different lab markers,
    or two conflict rules with identical wording) are distinct alerts and must
    NOT be collapsed. Stale per-row duplicates from a re-imported source are
    cleaned up structurally by :func:`resolve_superseded`, never by fuzzy text
    matching (which previously could resolve an unrelated alert — even in another
    domain — that happened to read the same)."""
    alert = await session.get(SystemAlert, alert_id)
    if alert is None:
        return None
    if alert.resolved_at is None:
        alert.resolved_at = now_local()
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
    """Active (unresolved) alerts, newest first, optionally filtered by domain.

    The ``uq_active_alert_per_key_entity`` partial-unique index already guarantees
    one active row per ``(alert_key, entity_ref)``, so there are no true duplicates
    to filter — every active row is a distinct alert and is returned as-is. (The
    old normalized-message dedup hid legitimately different alerts that shared
    templated wording and made the result nondeterministic.)"""
    stmt = select(SystemAlert).where(SystemAlert.resolved_at.is_(None))
    if domain is not None:
        stmt = stmt.where(SystemAlert.domain == domain)
    stmt = stmt.order_by(SystemAlert.created_at.desc(), SystemAlert.id.desc())
    result = await session.execute(stmt)
    return result.scalars().all()



def is_blocking(severity: str) -> bool:
    """True when a severity should stop a save unless overridden."""
    return severity == Severity.BLOCK.value
