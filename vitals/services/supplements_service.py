"""Supplements catalog service (Phase 3).

Reference catalog only (no daily logging — Ritual owns that). The catalog's
**active** rows are exposed to the conflict engine via :func:`resolve_active`, so
e.g. activating an iron supplement while a hemochromatosis-carrier genetics row
exists raises a ``block`` (overridable).

Mutating fns run ``conflict_engine.enforce`` so the override flow is wired: the
router turns ``ConflictBlocked`` into a 409 + violations payload.
"""
from __future__ import annotations

import re
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import Domain, Source
from vitals.models.supplements import DOMAIN, Supplement
from vitals.services import conflict_engine


def slugify(name: str) -> str:
    """Stable conflict-match slug from a display name (ascii-ish, lowercase)."""
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_") or "supplement"


def _proposed(key: str, active: bool) -> dict:
    return {"key": key, "active": active}


async def list_supplements(
    session: AsyncSession, *, active_only: bool = False
) -> Sequence[Supplement]:
    stmt = select(Supplement)
    if active_only:
        stmt = stmt.where(Supplement.active.is_(True))
    stmt = stmt.order_by(Supplement.active.desc(), Supplement.name)
    result = await session.execute(stmt)
    return result.scalars().all()


async def add_supplement(
    session: AsyncSession,
    *,
    name: str,
    key: Optional[str] = None,
    dose: Optional[str] = None,
    timing: Optional[str] = None,
    evidence: Optional[str] = None,
    active: bool = True,
    contraindications: Optional[str] = None,
    note: Optional[str] = None,
    override: bool = False,
) -> Supplement:
    resolved_key = key or slugify(name)
    await conflict_engine.enforce(
        session,
        Domain.SUPPLEMENTS.value,
        _proposed(resolved_key, active),
        override=override,
        entity_ref=f"supplement:{resolved_key}",
    )
    row = Supplement(
        domain=DOMAIN,
        source=Source.MANUAL.value,
        name=name,
        key=resolved_key,
        dose=dose,
        timing=timing,
        evidence=evidence,
        active=active,
        contraindications=contraindications,
        note=note,
    )
    session.add(row)
    await session.flush()
    return row


async def update_supplement(
    session: AsyncSession,
    supplement_id: int,
    *,
    name: str,
    key: Optional[str] = None,
    dose: Optional[str] = None,
    timing: Optional[str] = None,
    evidence: Optional[str] = None,
    active: bool = True,
    contraindications: Optional[str] = None,
    note: Optional[str] = None,
    override: bool = False,
) -> Optional[Supplement]:
    row = await session.get(Supplement, supplement_id)
    if row is None:
        return None
    resolved_key = key or slugify(name)
    await conflict_engine.enforce(
        session,
        Domain.SUPPLEMENTS.value,
        _proposed(resolved_key, active),
        override=override,
        entity_ref=f"supplement:{resolved_key}",
    )
    row.name = name
    row.key = resolved_key
    row.dose = dose
    row.timing = timing
    row.evidence = evidence
    row.active = active
    row.contraindications = contraindications
    row.note = note
    await session.flush()
    return row


async def set_active(
    session: AsyncSession, supplement_id: int, active: bool, *, override: bool = False
) -> Optional[Supplement]:
    """Toggle a catalog row's active flag — runs the conflict check so activating
    a contraindicated supplement surfaces the block/override flow."""
    row = await session.get(Supplement, supplement_id)
    if row is None:
        return None
    if active:
        await conflict_engine.enforce(
            session,
            Domain.SUPPLEMENTS.value,
            _proposed(row.key, True),
            override=override,
            entity_ref=f"supplement:{row.key}",
        )
    row.active = active
    await session.flush()
    return row


async def delete_supplement(session: AsyncSession, supplement_id: int) -> bool:
    row = await session.get(Supplement, supplement_id)
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


async def resolve_active(session: AsyncSession) -> list[dict]:
    """Conflict-engine resolver: the catalog as match items (key + active flag)."""
    result = await session.execute(select(Supplement))
    return [
        {"key": s.key, "active": s.active, "name": s.name}
        for s in result.scalars().all()
    ]
