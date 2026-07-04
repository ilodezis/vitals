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


_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def _transliterate(text: str) -> str:
    """Cyrillic -> Latin, character by character. Non-Cyrillic characters pass
    through unchanged so mixed RU/EN names transliterate only the RU part."""
    return "".join(_TRANSLIT.get(ch, ch) for ch in text)


def slugify(name: str) -> str:
    """Stable conflict-match slug from a display name (ascii-ish, lowercase).

    Transliterates Cyrillic first so a Russian name (e.g. "Железо") yields a
    real, stable, non-empty slug ("zhelezo") instead of collapsing to the
    fallback "supplement" — the ascii-only regex used to strip Cyrillic
    entirely, silently breaking conflict-rule matching for RU-named rows."""
    s = name.strip().lower()
    s = _transliterate(s)
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_") or "supplement"


# Coarse timing slots a supplement's free-text `timing` field is parsed into.
# The conflict engine's timing_separation rules only fire when both sides of a
# rule share the same slot (see conflict_engine._slots) — taking iron in the
# morning and zinc at night are already separated, no warning needed.
_SLOT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("MEAL", ("с едой", "с пищей", "во время еды", "after food", "with food", "with meal", "with meals")),
    ("PM", ("вечер", "ночь", "перед сном", "evening", "night", "bedtime")),
    ("AM", ("утро", "morning")),
    ("DAY", ("день", "днем", "днём", "полдень", "day", "afternoon", "midday")),
)


def _parse_slot(timing: Optional[str]) -> Optional[str]:
    """Coarse AM/PM/MEAL/DAY timing slot from a free-text ``timing`` value
    (RU/EN), or ``None`` when it's blank or doesn't match a known keyword."""
    if not timing:
        return None
    text = timing.strip().lower().replace("ё", "е")
    for slot, keywords in _SLOT_KEYWORDS:
        if any(kw in text for kw in keywords):
            return slot
    return None


def _proposed(key: str, active: bool, timing_slot: Optional[str] = None) -> dict:
    return {"key": key, "active": active, "timing_slot": timing_slot}


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
    if key:
        resolved_key = key
    else:
        # Deferred import: conflict_catalog imports this module (slugify is its
        # dictionary-miss fallback), so importing it back at module level here
        # would be circular.
        from vitals.services import conflict_catalog

        resolved_key = conflict_catalog.normalize_ingredient(name)
    await conflict_engine.enforce(
        session,
        Domain.SUPPLEMENTS.value,
        _proposed(resolved_key, active, _parse_slot(timing)),
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
    if key:
        resolved_key = key
    else:
        # Deferred import: conflict_catalog imports this module (slugify is its
        # dictionary-miss fallback), so importing it back at module level here
        # would be circular.
        from vitals.services import conflict_catalog

        resolved_key = conflict_catalog.normalize_ingredient(name)
    await conflict_engine.enforce(
        session,
        Domain.SUPPLEMENTS.value,
        _proposed(resolved_key, active, _parse_slot(timing)),
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
            _proposed(row.key, True, _parse_slot(row.timing)),
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
    """Conflict-engine resolver: the catalog as match items (key + active flag +
    parsed timing slot, used by timing_separation rules)."""
    result = await session.execute(select(Supplement))
    return [
        {
            "key": s.key,
            "active": s.active,
            "name": s.name,
            "timing_slot": _parse_slot(s.timing),
        }
        for s in result.scalars().all()
    ]
