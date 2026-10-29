"""Supplements catalog service (Phase 3).

Reference catalog only (no daily logging — Ritual owns that). The catalog's
**active** rows are exposed to the conflict engine via :func:`resolve_active`, so
e.g. activating an iron supplement while a hemochromatosis-carrier genetics row
exists raises a ``block`` (overridable).

Mutating fns run ``conflict_engine.enforce`` so the override flow is wired: the
router turns ``ConflictBlocked`` into a 409 + violations payload.

This service also owns the start/stop history (``SupplementPeriod``): every path
that switches a supplement on or off — create, edit, toggle, from the web or the
connector — goes through :func:`_record_switch`, so the history cannot drift from
the flag.
"""
from __future__ import annotations

import re
from datetime import date as date_type
from typing import Any, Optional, Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import Domain, Source
from vitals.i18n import t
from vitals.models.supplements import DOMAIN, Supplement, SupplementPeriod
from vitals.services import conflict_engine
from vitals.utils.timeutils import today_local


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


# The /supplements page groups active supplements into four display rows
# (morning/day/evening/night) — a finer split than _parse_slot's AM/DAY/MEAL/PM
# (which folds evening+night into one PM slot for the conflict engine's
# timing-separation rules). Keyed by the same RU bucket labels the template
# already uses, so an EN or RU free-text `timing` value lands in the right row.
_DISPLAY_BUCKET_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("утро", ("утро", "morning")),
    ("день", ("день", "днем", "day", "afternoon", "midday")),
    ("вечер", ("вечер", "evening")),
    ("ночь", ("ночь", "night", "bedtime", "перед сном")),
)


def timing_bucket(timing: Optional[str]) -> Optional[str]:
    """Canonical display-bucket key ('утро'/'день'/'вечер'/'ночь') a free-text
    ``timing`` value (RU or EN) belongs to on the /supplements page, or
    ``None`` when it matches none of them (renders under "Other")."""
    if not timing:
        return None
    text = timing.strip().lower().replace("ё", "е")
    for bucket, keywords in _DISPLAY_BUCKET_KEYWORDS:
        if any(kw in text for kw in keywords):
            return bucket
    return None


def _ref(key: str) -> str:
    """The entity ref conflict alerts about this supplement are bound to."""
    return f"supplement:{key}"


def _proposed(
    key: str,
    active: bool,
    timing_slot: Optional[str] = None,
    supplement_id: Optional[int] = None,
) -> dict:
    """A catalog row as the conflict engine will see it after the save. The ``id``
    of an existing row makes the engine evaluate it in place of its old state."""
    return {
        "id": supplement_id, "key": key, "active": active,
        "timing_slot": timing_slot, "ref": _ref(key),
    }


# ── Start/stop history ────────────────────────────────────────────────────────
async def _latest_period(session: AsyncSession, supplement_id: int) -> Optional[SupplementPeriod]:
    result = await session.execute(
        select(SupplementPeriod)
        .where(SupplementPeriod.supplement_id == supplement_id)
        .order_by(SupplementPeriod.date.desc(), SupplementPeriod.id.desc())
        .limit(1)
    )
    return result.scalars().first()


async def _record_switch(
    session: AsyncSession,
    row: Supplement,
    active: bool,
    *,
    source: str,
    on_date: Optional[date_type] = None,
) -> None:
    """Open or close the supplement's current period to match ``active``.

    Idempotent: switching on what is already running (or off what is already
    stopped) changes nothing. Switched off and back on the same day reopens that
    period rather than leaving a zero-length gap — a mis-tap is not a break.
    """
    on_date = on_date or today_local()
    latest = await _latest_period(session, row.id)
    if active:
        if latest is not None and latest.end_date is None:
            return
        if latest is not None and latest.end_date == on_date:
            latest.end_date = None
        else:
            session.add(SupplementPeriod(
                supplement_id=row.id, date=on_date, domain=DOMAIN, source=source,
            ))
    elif latest is not None and latest.end_date is None:
        latest.end_date = max(on_date, latest.date)
    await session.flush()


async def periods_by_supplement(
    session: AsyncSession, supplement_ids: Optional[Sequence[int]] = None
) -> dict[int, list[SupplementPeriod]]:
    """Every period, oldest first, keyed by supplement id."""
    stmt = select(SupplementPeriod).order_by(SupplementPeriod.date, SupplementPeriod.id)
    if supplement_ids is not None:
        stmt = stmt.where(SupplementPeriod.supplement_id.in_(list(supplement_ids)))
    out: dict[int, list[SupplementPeriod]] = {}
    for period in (await session.execute(stmt)).scalars().all():
        out.setdefault(period.supplement_id, []).append(period)
    return out


def current_since(periods: Sequence[SupplementPeriod]) -> Optional[date_type]:
    """Start of the open period (taken since), or ``None`` when not being taken."""
    if periods and periods[-1].end_date is None:
        return periods[-1].date
    return None


def last_stopped(periods: Sequence[SupplementPeriod]) -> Optional[date_type]:
    """When the last period ended, or ``None`` when one is still open or none exist."""
    if periods and periods[-1].end_date is not None:
        return periods[-1].end_date
    return None


def periods_view(periods: Sequence[SupplementPeriod]) -> list[dict[str, Any]]:
    """Compact history for a model or an export: ``start``, ``end`` when stopped,
    ``inferred`` when the start was reconstructed rather than recorded."""
    out = []
    for p in periods:
        item: dict[str, Any] = {"start": p.date.isoformat()}
        if p.end_date is not None:
            item["end"] = p.end_date.isoformat()
        if p.source == Source.INFERRED.value:
            item["inferred"] = True
        out.append(item)
    return out


async def switch_events(
    session: AsyncSession,
    *,
    start: Optional[date_type] = None,
    end: Optional[date_type] = None,
) -> list[dict[str, Any]]:
    """Start and stop events inside ``[start, end]``, oldest first: ``{date, kind
    ('started'|'stopped'), supplement_id, name, inferred}``. A start that was
    backfilled is still an event — flagged, so a reader can discount it."""
    supplements = {s.id: s for s in await list_supplements(session)}
    events: list[dict[str, Any]] = []

    def _within(day: date_type) -> bool:
        return (start is None or day >= start) and (end is None or day <= end)

    for supplement_id, periods in (await periods_by_supplement(session)).items():
        supp = supplements.get(supplement_id)
        if supp is None:
            continue
        for p in periods:
            inferred = p.source == Source.INFERRED.value
            if _within(p.date):
                events.append({"date": p.date, "kind": "started", "supplement_id": supp.id,
                               "name": supp.name, "inferred": inferred, "period_id": p.id})
            if p.end_date is not None and _within(p.end_date):
                events.append({"date": p.end_date, "kind": "stopped", "supplement_id": supp.id,
                               "name": supp.name, "inferred": False, "period_id": p.id})
    events.sort(key=lambda e: (e["date"], e["name"]))
    return events


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
    source: str = Source.MANUAL.value,
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
        entity_ref=_ref(resolved_key),
    )
    row = Supplement(
        domain=DOMAIN,
        source=source,
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
    if active:
        await _record_switch(session, row, True, source=source)
    await conflict_engine.reconcile(session, Domain.SUPPLEMENTS.value)
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
    source: str = Source.MANUAL.value,
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
        _proposed(resolved_key, active, _parse_slot(timing), supplement_id),
        override=override,
        entity_ref=_ref(resolved_key),
    )
    row.name = name
    row.key = resolved_key
    row.dose = dose
    row.timing = timing
    row.evidence = evidence
    switched = row.active != active
    row.active = active
    row.contraindications = contraindications
    row.note = note
    await session.flush()
    if switched:
        await _record_switch(session, row, active, source=source)
    await conflict_engine.reconcile(session, Domain.SUPPLEMENTS.value)
    return row


async def set_active(
    session: AsyncSession,
    supplement_id: int,
    active: bool,
    *,
    override: bool = False,
    source: str = Source.MANUAL.value,
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
            _proposed(row.key, True, _parse_slot(row.timing), row.id),
            override=override,
            entity_ref=_ref(row.key),
        )
    switched = row.active != active
    row.active = active
    await session.flush()
    if switched:
        await _record_switch(session, row, active, source=source)
    await conflict_engine.reconcile(session, Domain.SUPPLEMENTS.value)
    return row


async def delete_supplement(session: AsyncSession, supplement_id: int) -> bool:
    row = await session.get(Supplement, supplement_id)
    if row is None:
        return False
    # The FK cascades on Postgres; deleting explicitly keeps it true everywhere.
    await session.execute(
        delete(SupplementPeriod).where(SupplementPeriod.supplement_id == supplement_id)
    )
    await session.delete(row)
    await session.flush()
    await conflict_engine.reconcile(session, Domain.SUPPLEMENTS.value)
    return True


async def resolve_active(session: AsyncSession) -> list[dict]:
    """Conflict-engine resolver: the catalog as match items (key + active flag +
    parsed timing slot, used by timing_separation rules). ``id`` lets an edit
    replace its row's old state; ``ref`` is what a matching rule's alert is
    bound to."""
    result = await session.execute(select(Supplement))
    return [
        {
            "id": s.id,
            "ref": _ref(s.key),
            "key": s.key,
            "active": s.active,
            "name": s.name,
            "timing_slot": _parse_slot(s.timing),
        }
        for s in result.scalars().all()
    ]


# ── Full view collection for API / UI ─────────────────────────────────────────
def _item(s: Supplement, periods: Sequence[SupplementPeriod]) -> dict[str, Any]:
    return {
        "id": s.id,
        "name": s.name,
        "key": s.key,
        "dose": s.dose,
        "timing": s.timing,
        "timing_slot": _parse_slot(s.timing),
        "timing_bucket": timing_bucket(s.timing),
        "evidence": s.evidence,
        "active": s.active,
        "contraindications": s.contraindications,
        "contra": s.contraindications,
        "note": s.note,
        "since": current_since(periods),
        "stopped_on": last_stopped(periods),
    }


async def item_view(session: AsyncSession, row: Supplement) -> dict[str, Any]:
    """One catalog row as the dashboard shows it — what an edit or toggle returns."""
    history = await periods_by_supplement(session, [row.id])
    return _item(row, history.get(row.id, []))


async def collect(session: AsyncSession) -> dict[str, Any]:
    """Collect everything needed by the Supplements dashboard in one round-trip."""
    from vitals.services import alerts_service

    all_supps = await list_supplements(session)
    active_alerts = await alerts_service.list_active(session, domain=Domain.SUPPLEMENTS.value)
    history = await periods_by_supplement(session)

    active_items: list[dict[str, Any]] = []
    archived_items: list[dict[str, Any]] = []

    for s in all_supps:
        item = _item(s, history.get(s.id, []))
        if s.active:
            active_items.append(item)
        else:
            archived_items.append(item)

    morning_items = [s for s in active_items if s["timing_bucket"] == "утро"]
    day_items = [s for s in active_items if s["timing_bucket"] == "день"]
    evening_items = [s for s in active_items if s["timing_bucket"] in ("вечер", "ночь")]
    other_items = [s for s in active_items if s["timing_bucket"] not in ("утро", "день", "вечер", "ночь")]

    groups = [
        {"key": "morning", "label": t("app.supplements.timing.morning"), "sub": t("app.supplements.timing_sub.morning"), "tone": "cool", "items": morning_items},
        {"key": "day", "label": t("app.supplements.timing.day"), "sub": t("app.supplements.timing_sub.day"), "tone": "", "items": day_items},
        {"key": "evening", "label": t("app.supplements.timing.evening"), "sub": t("app.supplements.timing_sub.evening"), "tone": "violet", "items": evening_items},
    ]
    if other_items:
        groups.append({"key": "other", "label": t("app.supplements.timing.other"), "sub": "", "tone": "", "items": other_items})

    return {
        "groups": groups,
        "active": active_items,
        "archived": archived_items,
        "active_count": len(active_items),
        "total_count": len(all_supps),
        "alerts": [
            {
                "id": a.id,
                "domain": a.domain,
                "severity": a.severity,
                "alert_key": a.alert_key,
                "message": a.message,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in active_alerts
        ],
    }

