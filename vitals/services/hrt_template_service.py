"""HRT cycle templates — save a cycle's plan as a reusable, shareable recipe.

A template is a **date-free, relative** snapshot of a cycle: kind + one row per
compound holding ``start_offset_days`` and the segment ``schedule``, nothing
anchored to a calendar. Three flows:

  * **Save** — :func:`save_cycle_as_template` snapshots an existing cycle's
    items verbatim.
  * **Apply** — :func:`create_cycle_from_template` materializes a template into
    a real cycle at a chosen start date (delegating to ``hrt_cycle_service`` so
    auto-close / catalog resolution behave exactly like a hand-built cycle).
  * **Share** — :func:`export_template` / :func:`import_template` round-trip a
    template through portable JSON. Portable because items reference compounds
    by the shared catalog slug (``hrt_compounds.yaml`` — identical on every
    instance); import re-validates everything (keys against the local catalog,
    schedules via ``validate_schedule``) since pasted JSON bypasses the form.

Harm-reduction stance: a template is structure the *user* authored — the app
never ships built-in dose protocols and never recommends one.
"""
from __future__ import annotations

import json
from datetime import date as date_type
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import CycleKind, DoseUnit, Source
from vitals.models.hrt import DOMAIN, HrtCycle, HrtCycleTemplate, HrtCycleTemplateItem
from vitals.services import hrt_cycle_service, hrt_service

# Portable-JSON envelope. Bump the version if the item shape ever changes so an
# importer can tell an old payload from a malformed one.
EXPORT_FORMAT = "vitals.hrt_cycle_template"
EXPORT_VERSION = 1

_VALID_KINDS = {k.value for k in CycleKind}
_VALID_UNITS = {u.value for u in DoseUnit}
_MAX_ITEMS = 50  # no real protocol stacks this many compounds


# ── CRUD ──────────────────────────────────────────────────────────────────────
async def list_templates(session: AsyncSession) -> Sequence[HrtCycleTemplate]:
    result = await session.execute(
        select(HrtCycleTemplate)
        .where(HrtCycleTemplate.domain == DOMAIN)
        .order_by(HrtCycleTemplate.name)
    )
    return result.scalars().all()


async def get_template(
    session: AsyncSession, template_id: int
) -> Optional[HrtCycleTemplate]:
    # populate_existing: the instance may sit expired in the identity map after
    # a commit — a lazy .items load on it would MissingGreenlet under asyncio.
    return await session.get(HrtCycleTemplate, template_id, populate_existing=True)


async def delete_template(session: AsyncSession, template_id: int) -> bool:
    template = await session.get(HrtCycleTemplate, template_id)
    if template is None:
        return False
    await session.delete(template)
    await session.flush()
    return True


# ── Save / apply ──────────────────────────────────────────────────────────────
async def save_cycle_as_template(
    session: AsyncSession,
    cycle_id: int,
    *,
    name: str,
    note: Optional[str] = None,
) -> Optional[HrtCycleTemplate]:
    """Snapshot a cycle's plan into a new template. The snapshot is by value —
    later edits to the cycle don't touch the template."""
    cycle = await session.get(HrtCycle, cycle_id, populate_existing=True)
    if cycle is None:
        return None
    name = (name or "").strip()
    if not name:
        raise ValueError("template name is required")
    if not cycle.items:
        raise ValueError("cycle has no compounds to save")
    template = HrtCycleTemplate(
        domain=DOMAIN,
        source=Source.MANUAL.value,
        name=name,
        kind=cycle.kind,
        note=note,
    )
    session.add(template)
    await session.flush()
    for item in cycle.items:
        session.add(
            HrtCycleTemplateItem(
                template_id=template.id,
                compound_key=item.compound_key,
                unit=item.unit,
                start_offset_days=item.start_offset_days or 0,
                schedule=item.schedule,
                note=item.note,
            )
        )
    await session.flush()
    return template


async def create_cycle_from_template(
    session: AsyncSession,
    template_id: int,
    *,
    start_date: date_type,
    name: Optional[str] = None,
) -> Optional[HrtCycle]:
    """Materialize a template into a real cycle starting on ``start_date``.
    Goes through ``hrt_cycle_service`` item-by-item so compound resolution and
    the open-cycle auto-close behave exactly as if built by hand."""
    template = await session.get(HrtCycleTemplate, template_id, populate_existing=True)
    if template is None:
        return None
    cycle = await hrt_cycle_service.add_cycle(
        session,
        kind=template.kind,
        start_date=start_date,
        name=(name or "").strip() or template.name,
        note=template.note,
    )
    for item in template.items:
        await hrt_cycle_service.add_cycle_item(
            session,
            cycle.id,
            compound_key=item.compound_key,
            schedule=item.schedule,
            unit=item.unit,
            start_offset_days=item.start_offset_days or 0,
            note=item.note,
        )
    await session.flush()
    return cycle


def _signature(kind: str, items: Sequence[HrtCycleTemplateItem]) -> tuple:
    """Content identity of a template — what makes two imports 'the same'."""
    return (
        kind,
        tuple(
            (
                it.compound_key,
                it.unit,
                int(it.start_offset_days or 0),
                json.dumps(it.schedule, sort_keys=True),
            )
            for it in items
        ),
    )


# ── Share: portable JSON ──────────────────────────────────────────────────────
def export_template(template: HrtCycleTemplate) -> dict:
    """A template as a portable dict — self-describing envelope, relative items
    only. ``json.dumps(..., ensure_ascii=False, indent=2)`` of this is the
    copy-paste share payload."""
    return {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "name": template.name,
        "kind": template.kind,
        "note": template.note,
        "items": [
            {
                "compound_key": item.compound_key,
                "unit": item.unit,
                "start_offset_days": item.start_offset_days or 0,
                "schedule": item.schedule,
                "note": item.note,
            }
            for item in template.items
        ],
    }


def export_template_json(template: HrtCycleTemplate) -> str:
    return json.dumps(export_template(template), ensure_ascii=False, indent=2)


async def import_template(
    session: AsyncSession, payload: dict | str
) -> HrtCycleTemplate:
    """Validate a pasted share payload and save it as a new local template.
    Rejects (with a message naming the problem) rather than half-importing:
    unknown envelope, bad kind/unit/offset, malformed schedule, or a compound
    key missing from the local catalog."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as e:
            raise ValueError(f"not valid JSON: {e.msg}") from None
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    if payload.get("format") != EXPORT_FORMAT:
        raise ValueError(f"unrecognized format — expected '{EXPORT_FORMAT}'")
    try:
        version = int(payload.get("version") or 0)
    except (TypeError, ValueError):
        raise ValueError("version must be a number") from None
    if version < 1 or version > EXPORT_VERSION:
        raise ValueError(f"unsupported version {version} (this app reads up to {EXPORT_VERSION})")

    name = str(payload.get("name") or "").strip()[:128]
    if not name:
        raise ValueError("template name is required")
    kind = str(payload.get("kind") or "").strip()
    if kind not in _VALID_KINDS:
        raise ValueError(f"unknown cycle kind '{kind}'")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise ValueError("items must be a non-empty list")
    if len(raw_items) > _MAX_ITEMS:
        raise ValueError(f"too many items (max {_MAX_ITEMS})")

    clean_items: list[HrtCycleTemplateItem] = []
    missing: list[str] = []
    for idx, raw in enumerate(raw_items):
        where = f"item {idx + 1}"
        if not isinstance(raw, dict):
            raise ValueError(f"{where}: must be an object")
        key = str(raw.get("compound_key") or "").strip()
        if not key:
            raise ValueError(f"{where}: compound_key is required")
        compound = await hrt_service.get_compound(session, key)
        if compound is None:
            missing.append(key)
            continue
        unit = str(raw.get("unit") or compound.dose_unit or DoseUnit.MG.value)
        if unit not in _VALID_UNITS:
            raise ValueError(f"{where}: unknown unit '{unit}'")
        try:
            offset = int(raw.get("start_offset_days") or 0)
        except (TypeError, ValueError):
            raise ValueError(f"{where}: start_offset_days must be an integer") from None
        if offset < 0:
            raise ValueError(f"{where}: start_offset_days must be >= 0")
        try:
            schedule = hrt_cycle_service.validate_schedule(raw.get("schedule"))
        except ValueError as e:
            raise ValueError(f"{where}: {e}") from None
        note = raw.get("note")
        clean_items.append(
            HrtCycleTemplateItem(
                compound_key=key,
                unit=unit,
                start_offset_days=offset,
                schedule=schedule,
                note=str(note) if note is not None else None,
            )
        )
    if missing:
        raise ValueError(
            "unknown compound keys (not in this instance's catalog): " + ", ".join(missing)
        )

    # Duplicate handling: pasting the same share code twice is a mistake, not a
    # request for a copy — reject an exact duplicate. A mere name clash with
    # different content gets a numbered name instead of silently shadowing.
    existing = await list_templates(session)
    new_sig = _signature(kind, clean_items)
    for tp in existing:
        if tp.name == name and _signature(tp.kind, tp.items) == new_sig:
            raise ValueError(f"an identical template '{name}' is already imported")
    taken = {tp.name for tp in existing}
    if name in taken:
        base = name[:118]
        n = 2
        while f"{base} ({n})" in taken:
            n += 1
        name = f"{base} ({n})"

    note = payload.get("note")
    template = HrtCycleTemplate(
        domain=DOMAIN,
        source=Source.MANUAL.value,
        name=name,
        kind=kind,
        note=str(note) if note is not None else None,
    )
    session.add(template)
    await session.flush()
    for item in clean_items:
        item.template_id = template.id
        session.add(item)
    await session.flush()
    return template
