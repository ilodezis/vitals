"""Cross-domain records: notes, deletes, the timeline and goals."""
from __future__ import annotations

import importlib
import os
from typing import Optional

from sqlalchemy import select

from vitals.enums import Domain, MilestoneStatus
from vitals.models import (
    Annotation, BodyMeasurement, BodyScan, Injection, LabResult,
    MealLog, SkincareLog, WeightLog,
)
from vitals.services import photo_derivatives
from vitals.utils.timeutils import today_local
from web.routers.mcp._core import (
    READ, WRITE, _merged, _module_enabled,
    _parse_date, gated, get_session_factory, dispatch, serialize_row, serialize_written, tool,
)

# ── Notes tools ─────────────────────────────────────────────────────────────

# Domains whose per-row ``note`` field the note tools can read/write, mapped to
# their model. Single source of truth for both log_note and get_notes so the two
# never drift out of sync.
_NOTE_MODELS = {
    "weight": WeightLog,
    "nutrition": MealLog,
    "glp1": Injection,
    "skincare": SkincareLog,
    "measurement": BodyMeasurement,
    "body_comp": BodyScan,
    "labs": LabResult,
}


@tool(WRITE, idempotent=True)
async def log_note(
    domain: str,
    record_id: int,
    note: str,
) -> dict:
    """Adds or updates the note field on any domain record by its ID.
    Supported domains: weight, nutrition, glp1, skincare, measurement, body_comp, labs.
    WRITE tool — saved immediately."""
    model = _NOTE_MODELS.get(domain)
    if model is None:
        return {"error": f"Unknown domain '{domain}'. Use: {', '.join(_NOTE_MODELS)}"}

    session_factory = get_session_factory()
    async with session_factory() as session:
        row = await session.get(model, record_id)
        if row is None:
            return {"error": f"{domain} record {record_id} not found"}
        row.note = note
        await session.flush()
        await session.commit()
        return await serialize_written(session, row)


@tool(READ)
async def get_notes(
    domain: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """Retrieves records that have non-empty notes, optionally filtered by domain
    and date range. Returns records from: weight, nutrition, glp1, skincare,
    measurement, body_comp, labs."""
    if domain and domain not in _NOTE_MODELS:
        return [{"error": f"Unknown domain '{domain}'. Use: {', '.join(_NOTE_MODELS)}"}]

    targets = {domain: _NOTE_MODELS[domain]} if domain else _NOTE_MODELS
    session_factory = get_session_factory()
    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")

    results = []
    async with session_factory() as session:
        for d_name, model in targets.items():
            stmt = select(model).where(model.note.isnot(None), model.note != "")
            if start:
                stmt = stmt.where(model.date >= start)
            if end:
                stmt = stmt.where(model.date <= end)
            stmt = stmt.order_by(model.date.desc()).limit(limit)
            rows = (await session.execute(stmt)).scalars().all()
            for r in rows:
                entry = serialize_row(r)
                entry["_domain"] = d_name
                results.append(entry)

    results.sort(key=lambda x: x.get("date", ""), reverse=True)
    return results[:limit]


# ── Deletion (one tool, every domain) ─────────────────────────────────────────

# domain → (module key gating the write, service module, delete function).
# Every delete service takes ``(session, id)`` and reports whether there was a row —
# a bool, or for a photo the stored file's key (truthy) so the file can go once the
# row is committed. That shared shape is what lets a single tool stand in for the
# near-identical ones that used to live here, each differing only in the noun it
# echoed back. The tool list is re-read at the top of every conversation, so a
# fifth of it was spent spelling out delete_meal / delete_glp1 / delete_hrt_cycle_item.
_DELETE_TARGETS: dict[str, tuple[Optional[str], str, str]] = {
    "weight": (None, "weight_service", "delete_weight_log"),
    "measurement": (None, "weight_service", "delete_body_measurement"),
    "noise_marker": (None, "weight_service", "delete_noise_marker"),
    "progress_photo": (None, "weight_service", "delete_progress_photo"),
    "labs": (None, "labs_service", "delete_result"),
    "milestones": (None, "milestones_service", "delete_milestone"),
    "shared_report": (None, "share_service", "delete_report"),
    "nutrition": ("nutrition", "nutrition_service", "delete_meal"),
    "glp1": ("glp1", "glp1_service", "delete_injection"),
    "glp1_side_effect": ("glp1", "glp1_service", "delete_side_effect"),
    "glp1_dose_phase": ("glp1", "glp1_service", "delete_dose_phase"),
    "hrt_dose": ("hrt", "hrt_service", "delete_dose"),
    "hrt_cycle": ("hrt", "hrt_cycle_service", "delete_cycle"),
    "hrt_cycle_item": ("hrt", "hrt_cycle_service", "delete_cycle_item"),
    "body_comp": ("body_comp", "body_scan_service", "delete_scan"),
    "timeline": ("timeline", "timeline_service", "delete_annotation"),
    "skincare_product": ("skincare", "skincare_service", "delete_product"),
    "skincare_photo": ("skincare", "skincare_service", "delete_photo"),
    "skincare_observation": ("skincare", "skincare_service", "delete_observation"),
    "skincare_day_flags": ("skincare", "skincare_service", "delete_log"),
    "supplements": ("supplements", "supplements_service", "delete_supplement"),
    "genetics": ("genetics", "genetics_service", "delete_variant"),
    "signals": ("signals", "signals_service", "delete_signal"),
}

# The domains whose rows feed passive alerts: the app re-derives those alerts after
# a delete, so a removed out-of-range result can't leave its warning behind.
_DELETE_REFRESHES: dict[str, str] = {
    "labs": "labs_service",
    "body_comp": "body_scan_service",
}


def _remove_upload(rel_path: Optional[str]) -> None:
    """Delete a stored upload once its row is gone — best-effort, like the app."""
    from web.templating import STATIC_DIR

    if not rel_path:
        return
    path = os.path.join(STATIC_DIR, rel_path)
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass
    # A photo's tile and screen copies go with it; anything else has none.
    photo_derivatives.remove_derivatives(STATIC_DIR, rel_path)


# Targets that are not a row delete through ``_DELETE_TARGETS``: killing a doctor
# report's link (the record of what was shared stays) and a saved chart, whose id
# is a string. Both were tools of their own; they share the two-step confirm here.
_DELETE_EXTRAS = ("shared_report_link", "saved_chart")


@tool(WRITE, destructive=True, idempotent=True)
async def delete_record(domain: str, record_id: int | str, confirm: bool = False) -> dict:
    """Deletes one record from any domain by its ID — permanently; there is no
    undo, so delete only what the owner asked to remove. Requires two-step confirmation:
    calling without ``confirm=true`` returns a preview; repeat with ``confirm=true``
    once the owner agrees.

    ``domain`` is one of: weight, measurement (body tape), noise_marker,
    progress_photo (a weight progress photo and its file), labs (one result),
    milestones (a goal card), shared_report (a doctor report's record),
    shared_report_link (kills a doctor report's link now and erases its frozen
    data; the record of what was shared stays), saved_chart (a Charts-screen
    chart by its string id; the data it plots is untouched), nutrition (a meal),
    glp1 (an injection), glp1_side_effect, glp1_dose_phase, hrt_dose, hrt_cycle
    (with its compound plans), hrt_cycle_item (one plan, cycle kept), body_comp (a
    scan with its metrics and file), timeline (a manual event), skincare_product
    (removes it from the catalog; past ticks keep its name — to stop using a
    product prefer ``save_skincare(entry="product", active=false)``),
    skincare_photo (a face photo and its file), skincare_observation,
    skincare_day_flags (one day's conflict-flag row — the old hand-filled
    checklist; ticks are taken back with ``save_skincare(entry="check",
    done=false)``, not here), supplements (a catalog entry), genetics (a variant),
    signals (one parsed signal — the raw message stays in the lake; for a whole
    batch parsed wrongly use ``save_signal(entry="misparse")`` instead).

    Deleting a weight log reactivates the next-highest-priority log for that date.
    Returns ``{"deleted": false, ...}`` when nothing has that id."""
    target = _DELETE_TARGETS.get(domain)
    if target is None and domain not in _DELETE_EXTRAS:
        valid = ", ".join([*_DELETE_TARGETS, *_DELETE_EXTRAS])
        return {"error": f"Unknown domain '{domain}'. Use: {valid}"}
    if domain != "saved_chart":
        try:
            record_id = int(record_id)
        except (TypeError, ValueError):
            return {"error": f"record_id for {domain} must be an integer, got {record_id!r}"}
    if not confirm:
        if target is not None and target[0]:
            session_factory = get_session_factory()
            async with session_factory() as session:
                if not await _module_enabled(session, target[0]):
                    return {"error": f"module '{target[0]}' is disabled"}
        return {
            "preview": True,
            "confirm_required": True,
            "action": "delete",
            "domain": domain,
            "record_id": record_id,
            "hint": f"To permanently delete {domain} record {record_id}, call delete_record(domain='{domain}', record_id={record_id!r}, confirm=True).",
        }
    if domain == "shared_report_link":
        from web.routers.mcp.sharing import revoke_shared_report

        result = await revoke_shared_report(record_id)
        if "error" in result:
            return result
        return {"deleted": bool(result.get("revoked", True)), "domain": domain, "record_id": record_id}
    if domain == "saved_chart":
        from web.routers.mcp.sharing import delete_saved_chart

        result = await delete_saved_chart(str(record_id))
        return {"deleted": bool(result.get("deleted")), "domain": domain, "record_id": record_id}
    module_key, service_name, fn_name = target

    session_factory = get_session_factory()
    async with session_factory() as session:
        if module_key and not await _module_enabled(session, module_key):
            return {"error": f"module '{module_key}' is disabled"}
        service = importlib.import_module(f"vitals.services.{service_name}")
        upload = None
        if domain == "body_comp":
            # The scan's file key is relative to uploads/, unlike the photos'.
            scan = await session.get(BodyScan, record_id)
            upload = f"uploads/{scan.file_key}" if scan is not None and scan.file_key else None
        result = await getattr(service, fn_name)(session, record_id)
        if isinstance(result, str):  # a photo: the service hands back its file key
            upload = result
        refresher = _DELETE_REFRESHES.get(domain)
        if result and refresher:
            await importlib.import_module(f"vitals.services.{refresher}").refresh_alerts(session)
        await session.commit()
        if result:
            _remove_upload(upload)
        return {"deleted": bool(result), "domain": domain, "record_id": record_id}


# ── Timeline tools ───────────────────────────────────────────────────────────
@tool(READ, module='timeline')
async def get_timeline(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    domain: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    """Retrieves the cross-domain event feed — manual annotations (trips,
    illness, protocol changes) plus derived events (GLP-1 dose changes, lab
    draws, BIA scans, achieved milestones, noisy weight periods), newest first.
    Optionally filtered by date range (YYYY-MM-DD) and/or domain (weight, glp1,
    garmin, workouts, labs, nutrition, skincare, supplements, genetics,
    body_comp, or "timeline" for global flags)."""
    from vitals.services import timeline_service

    session_factory = get_session_factory()
    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")
    domains = [domain] if domain else None

    async with session_factory() as session:
        events = await timeline_service.list_events(
            session, domains=domains, start=start, end=end, limit=limit
        )
        return [e.to_dict() for e in events]


@gated("timeline")
async def log_event(
    title: str,
    on_date: Optional[str] = None,
    end_date: Optional[str] = None,
    kind: str = "note",
    domain: str = "timeline",
    note: Optional[str] = None,
) -> dict:
    """Records a manual Timeline annotation — a flag shown on every chart and
    in the event feed (a trip, an illness, a protocol change, a free-form
    note). ``kind`` is one of: life_event, illness, travel, protocol_change,
    note. ``domain`` scopes the flag to one chart (weight, glp1, ...) or
    "timeline" (default) to show it on every chart. ``end_date`` makes it a
    range (e.g. a week-long trip); omit it for a single-day event. WRITE tool —
    saved immediately. No-op with an error if the timeline module is disabled."""
    from vitals.services import timeline_service

    session_factory = get_session_factory()
    parsed_date = _parse_date(on_date, today_local(), field="on_date")
    parsed_end = _parse_date(end_date, field="end_date")

    async with session_factory() as session:
        row = await timeline_service.create_annotation(
            session,
            title=title,
            on_date=parsed_date,
            end_date=parsed_end,
            kind=kind,
            domain=domain,
            note=note,
        )
        await session.commit()
        return await serialize_written(session, row)


@gated("timeline")
async def update_event(
    event_id: int,
    title: Optional[str] = None,
    on_date: Optional[str] = None,
    end_date: Optional[str] = None,
    kind: Optional[str] = None,
    domain: Optional[str] = None,
    note: Optional[str] = None,
    clear: Optional[list[str]] = None,
) -> dict:
    """Updates a manual Timeline annotation by ID — the ``id`` of a row from
    ``get_timeline`` whose source is manual (derived events are computed and
    cannot be edited). Only the fields you pass are changed; everything left out
    keeps its stored value, including the event's own date. ``clear`` empties
    fields: ``end_date`` (a range back to a single day) and/or ``note``.
    WRITE tool."""
    from vitals.services import timeline_service

    session_factory = get_session_factory()
    parsed_date = _parse_date(on_date, field="on_date")
    parsed_end = _parse_date(end_date, field="end_date")

    async with session_factory() as session:
        merged = await _merged(
            session,
            Annotation,
            event_id,
            title=title,
            date=parsed_date,
            end_date=parsed_end,
            kind=kind,
            domain=domain,
            note=note,
        )
        if merged is None:
            return {"error": f"Event {event_id} not found"}
        unknown = sorted(set(clear or []) - {"end_date", "note"})
        if unknown:
            return {"error": f"cannot clear {unknown} — clearable: end_date, note"}
        for field in clear or []:
            merged[field] = None
        row = await timeline_service.update_annotation(
            session, event_id, on_date=merged.pop("date"), **merged
        )
        await session.commit()
        return await serialize_written(session, row)


# ── Milestones / goals tools ──────────────────────────────────────────────────
_MILESTONE_STATUSES = {s.value for s in MilestoneStatus}


@tool(READ)
async def get_milestones(status: Optional[str] = None) -> list[dict]:
    """Returns goal cards with live progress (current value, remaining, days left)
    computed for weight/body-comp goals. Optionally filtered by ``status`` (active,
    achieved, missed, paused). Read-only."""
    from vitals.services import milestones_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        rows = await milestones_service.list_milestones(session, status=status)
        return [await milestones_service.progress(session, m) for m in rows]


async def create_milestone(
    name: str,
    domain: str = Domain.WEIGHT.value,
    target_value: Optional[float] = None,
    target_unit: Optional[str] = None,
    deadline: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    """Creates a goal card (e.g. "reach 85 kg by 2026-12-31"). ``domain`` is the
    related health area (weight, glp1, labs, body_comp, ...); ``deadline`` is
    YYYY-MM-DD. WRITE tool — saved immediately."""
    from vitals.services import milestones_service

    session_factory = get_session_factory()
    parsed_deadline = _parse_date(deadline, field="deadline")
    async with session_factory() as session:
        row = await milestones_service.create_milestone(
            session, name=name, domain=domain, target_value=target_value,
            target_unit=target_unit, deadline=parsed_deadline, note=note,
        )
        await session.commit()
        return await serialize_written(session, row)


async def update_milestone(
    milestone_id: int,
    name: Optional[str] = None,
    domain: Optional[str] = None,
    target_value: Optional[float] = None,
    target_unit: Optional[str] = None,
    deadline: Optional[str] = None,
    status: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    """Updates a goal card by ID. Only the fields you pass are changed. Use
    ``status`` to mark a goal achieved/missed/paused/active. WRITE tool."""
    from vitals.services import milestones_service

    if status is not None and status not in _MILESTONE_STATUSES:
        return {"error": f"Unknown status '{status}'. Use: {', '.join(sorted(_MILESTONE_STATUSES))}"}

    session_factory = get_session_factory()
    async with session_factory() as session:
        kwargs: dict = {}
        if name is not None:
            kwargs["name"] = name
        if domain is not None:
            kwargs["domain"] = domain
        if target_value is not None:
            kwargs["target_value"] = target_value
        if target_unit is not None:
            kwargs["target_unit"] = target_unit
        if deadline is not None:
            kwargs["deadline"] = _parse_date(deadline, field="deadline")
        if status is not None:
            kwargs["status"] = status
        if note is not None:
            kwargs["note"] = note
        row = await milestones_service.update_milestone(session, milestone_id, **kwargs)
        if row is None:
            return {"error": f"Milestone {milestone_id} not found"}
        await session.commit()
        return await serialize_written(session, row)


# ── Consolidated write tools ─────────────────────────────────────────────────
_EVENT_ENTRIES = {
    ("event", False): (log_event, None),
    ("event", True): (update_event, "event_id"),
}


@tool(WRITE, module="timeline")
@gated("timeline")
async def save_event(
    record_id: Optional[int] = None,
    title: Optional[str] = None,
    on_date: Optional[str] = None,
    end_date: Optional[str] = None,
    kind: Optional[str] = None,
    domain: Optional[str] = None,
    note: Optional[str] = None,
    clear: Optional[list[str]] = None,
) -> dict:
    """Records or edits a manual Timeline annotation (shown on charts and in the
    event feed: a trip, an illness, a protocol change, a free-form note).

    Without ``record_id``: creates one (``title`` required; ``kind`` one of
    life_event | illness | travel | protocol_change | note; ``domain`` scopes the
    flag to one chart or "timeline" for every chart; ``end_date`` makes it a
    range). With ``record_id`` (a manual row from ``get_timeline``; derived
    events cannot be edited): changes only the fields passed; ``clear`` lists
    fields to empty (end_date, note)."""
    args = dict(
        title=title, on_date=on_date, end_date=end_date, kind=kind,
        domain=domain, note=note, clear=clear,
    )
    return await dispatch("save_event", "entry", "event", _EVENT_ENTRIES, args, record_id)


_MILESTONE_ENTRIES = {
    ("milestone", False): (create_milestone, None),
    ("milestone", True): (update_milestone, "milestone_id"),
}


@tool(WRITE)
async def save_milestone(
    record_id: Optional[int] = None,
    name: Optional[str] = None,
    domain: Optional[str] = None,
    target_value: Optional[float] = None,
    target_unit: Optional[str] = None,
    deadline: Optional[str] = None,
    status: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    """Creates or edits a goal card (e.g. "reach 85 kg by 2026-12-31").

    Without ``record_id``: creates one (``name`` required; ``domain`` defaults to
    weight; ``deadline`` YYYY-MM-DD). With ``record_id`` (from
    ``get_milestones``): changes only the fields passed; use ``status``
    (active | achieved | missed | paused) to close or pause a goal."""
    args = dict(
        name=name, domain=domain, target_value=target_value,
        target_unit=target_unit, deadline=deadline, status=status, note=note,
    )
    return await dispatch(
        "save_milestone", "entry", "milestone", _MILESTONE_ENTRIES, args, record_id
    )
