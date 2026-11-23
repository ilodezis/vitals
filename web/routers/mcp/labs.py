"""Lab results and the marker catalog."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from vitals.enums import Source
from vitals.models import (
    LabResult,
)
from vitals.services.conflict_engine import ConflictBlocked
from vitals.utils.timeutils import today_local
from web.routers.mcp._core import (
    READ, WRITE, _conflict_payload, _parse_date, get_session_factory, choice_error, dispatch, route, serialize_row, serialize_written, tool,
)

# ── Labs tools ──────────────────────────────────────────────────────────────
async def get_lab_results(
    marker: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    """Retrieves lab results (biomarker, value, unit, reference range, computed
    out-of-range flag), optionally filtered by marker name and/or date range
    (YYYY-MM-DD). Defaults to the most recent 100 rows across all markers.
    ``flag`` is judged now against the result's own range (the catalog's when the
    lab printed none); ``suspect`` marks a value no person can have in that unit
    — a misread document, not a finding."""
    from vitals.services import labs_service

    session_factory = get_session_factory()
    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")

    async with session_factory() as session:
        stmt = select(LabResult)
        if marker:
            stmt = stmt.where(LabResult.marker == labs_service.normalize_marker(marker))
        if start:
            stmt = stmt.where(LabResult.date >= start)
        if end:
            stmt = stmt.where(LabResult.date <= end)
        stmt = stmt.order_by(LabResult.date.desc(), LabResult.id.desc()).limit(limit)
        results = (await session.execute(stmt)).scalars().all()
        catalog = {m.name: m for m in await labs_service.list_markers(session)}
        out = []
        for r in results:
            ref_low, ref_high = labs_service.effective_range(r, catalog.get(r.marker))
            out.append({
                **serialize_row(r),
                "ref_low": ref_low,
                "ref_high": ref_high,
                "flag": labs_service.effective_flag(r, catalog.get(r.marker)),
            })
        return out


async def get_lab_markers(marker: Optional[str] = None) -> dict:
    """The lab-marker catalog the alerts are computed from: per marker its
    ``unit``, reference range (``ref_low``/``ref_high``), ``category``, ``tier``
    (1 = key marker … 3), ``retest_interval_days`` (when an "overdue retest"
    alert fires) and ``defer_until`` (retest alert paused until then). With
    ``marker`` (any spelling — normalized like the results) it returns that one
    marker plus its full value history. READ tool; change with
    ``update_lab_marker``."""
    from vitals.services import labs_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        if marker is None:
            return {"markers": [serialize_row(m) for m in await labs_service.list_markers(session)]}
        row = await labs_service.get_marker(session, labs_service.normalize_marker(marker))
        if row is None:
            return {"error": f"No marker '{marker}' in the catalog"}
        return {
            **serialize_row(row),
            "history": await labs_service.marker_history(session, row.name),
        }


async def update_lab_marker(
    marker: str,
    ref_low: Optional[float] = None,
    ref_high: Optional[float] = None,
    category: Optional[str] = None,
    tier: Optional[int] = None,
    retest_interval_days: Optional[int] = None,
    defer_until: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    """Edits a catalog marker — the marker card on the Labs screen. Only what you
    pass changes. ``ref_low``/``ref_high`` is the catalog's reference range (used
    when a result comes without one); ``tier`` 1–3; ``retest_interval_days``
    drives the "overdue retest" alert; ``defer_until`` (YYYY-MM-DD) is "remind me
    later": it pauses that alert until the date and closes the open one. Alerts
    are re-derived after the save. WRITE tool."""
    from vitals.services import labs_service

    parsed_defer = _parse_date(defer_until, field="defer_until")
    if tier is not None and not 1 <= tier <= 3:
        return {"error": "tier must be 1, 2 or 3"}
    if retest_interval_days is not None and retest_interval_days <= 0:
        return {"error": "retest_interval_days must be positive"}
    session_factory = get_session_factory()
    async with session_factory() as session:
        row = await labs_service.get_marker(session, labs_service.normalize_marker(marker))
        if row is None:
            return {"error": f"No marker '{marker}' in the catalog"}
        for field, value in {
            "ref_low": ref_low, "ref_high": ref_high, "category": category, "tier": tier,
            "retest_interval_days": retest_interval_days, "note": note,
        }.items():
            if value is not None:
                setattr(row, field, value)
        await session.flush()
        if parsed_defer is not None:
            await labs_service.defer_retest(session, row.name, until=parsed_defer)
        await labs_service.refresh_alerts(session)
        await session.commit()
        return await serialize_written(session, row)


async def log_lab_result(
    marker: str,
    value: float,
    on_date: Optional[str] = None,
    unit: Optional[str] = None,
    ref_low: Optional[float] = None,
    ref_high: Optional[float] = None,
    lab_name: Optional[str] = None,
    note: Optional[str] = None,
    override: bool = False,
) -> dict:
    """Records a single lab marker value (one biomarker from a blood/urine test).
    The out-of-range flag is computed automatically; a range left out here falls
    back to the marker's catalog range if one is already on file. WRITE tool —
    saved immediately. Defaults: on_date = today. A hard conflict rule (e.g. a
    hyperkalemic potassium result while a potassium supplement is active) returns
    ``{"blocked": true, ...}``; retry with ``override=True`` to save anyway."""
    from vitals.services import labs_service

    session_factory = get_session_factory()
    parsed_date = _parse_date(on_date, today_local(), field="on_date")

    async with session_factory() as session:
        try:
            row = await labs_service.add_result(
                session,
                on_date=parsed_date,
                marker=marker,
                value=value,
                unit=unit,
                ref_low=ref_low,
                ref_high=ref_high,
                lab_name=lab_name,
                note=note,
                source=Source.MCP.value,
                override=override,
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
        except ValueError as e:
            return {"error": str(e)}
        # The app re-derives the out-of-range / retest alerts after every save.
        await labs_service.refresh_alerts(session)
        await session.commit()
        return await serialize_written(session, row)


async def update_lab_result(
    result_id: int,
    value: Optional[float] = None,
    marker: Optional[str] = None,
    on_date: Optional[str] = None,
    unit: Optional[str] = None,
    ref_low: Optional[float] = None,
    ref_high: Optional[float] = None,
    lab_name: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    """Corrects an existing lab result by ID — a mistyped value, a range read off
    the wrong column. Only the fields you pass are changed; the out-of-range flag
    is recomputed and the alerts derived from it refreshed. Use this instead of
    delete + re-add: a measurement is never thrown away here. WRITE tool."""
    from vitals.services import labs_service

    session_factory = get_session_factory()
    parsed_date = _parse_date(on_date, field="on_date")

    async with session_factory() as session:
        try:
            row = await labs_service.update_result(
                session,
                result_id,
                on_date=parsed_date,
                marker=marker,
                value=value,
                unit=unit,
                ref_low=ref_low,
                ref_high=ref_high,
                lab_name=lab_name,
                note=note,
            )
        except ValueError as e:
            return {"error": str(e)}
        if row is None:
            return {"error": f"Lab result {result_id} not found"}
        await session.commit()
        return await serialize_written(session, row)


async def log_lab_results(
    results: list[dict],
    on_date: Optional[str] = None,
    lab_name: Optional[str] = None,
    override: bool = False,
) -> dict:
    """Records every marker from one lab report at once (e.g. a full blood panel
    read from a photo/PDF shared in the conversation) — the natural way to push a
    whole report in one call instead of calling log_lab_result per marker.

    Each item in ``results`` is ``{"marker": str, "value": number, "unit": str?,
    "ref_low": number?, "ref_high": number?}``. Identical (date, marker, value)
    rows are deduped, so retrying a call is safe. The verbatim payload is kept in
    raw_payloads, same as a document uploaded through the web UI. WRITE tool —
    saved immediately. Defaults: on_date = today. A hard conflict rule on any
    marker in the panel returns ``{"blocked": true, ...}`` and saves nothing;
    retry with ``override=True`` to save the whole panel anyway."""
    from vitals.services import labs_service

    session_factory = get_session_factory()
    parsed_date = _parse_date(on_date, today_local(), field="on_date")

    async with session_factory() as session:
        extracted = {
            "date": parsed_date.isoformat(),
            "lab_name": lab_name,
            "results": results,
        }
        try:
            summary = await labs_service.ingest_extracted(
                session, extracted, override=override
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
        await labs_service.refresh_alerts(session)
        await session.commit()
        return {
            "created": summary["created"],
            "skipped": summary["skipped"],
            "results": [await serialize_written(session, r) for r in summary["results"]],
        }


# ── Consolidated tools ───────────────────────────────────────────────────────
@tool(READ)
async def get_labs(
    view: str = "results",
    marker: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: Optional[int] = None,
) -> dict:
    """Lab reads. ``view="results"`` (default): ``{"results": [...]}`` — biomarker
    values with unit, reference range and the computed out-of-range flag, newest
    first (``limit`` default 100), optionally for one ``marker`` and/or a date
    range (YYYY-MM-DD); ids for ``save_lab`` edits. ``view="markers"``: the marker
    catalog the alerts are computed from — per marker its unit, reference range,
    category, tier (1 = key marker), retest interval and deferral — optionally
    one ``marker``."""
    if view == "results":
        rows = await route(
            get_lab_results, "get_labs(view='results')",
            dict(marker=marker, start_date=start_date, end_date=end_date, limit=limit),
        )
        return rows if isinstance(rows, dict) else {"results": rows}
    if view == "markers":
        return await route(
            get_lab_markers, "get_labs(view='markers')",
            dict(marker=marker, start_date=start_date, end_date=end_date, limit=limit),
        )
    return choice_error("view", view, ("results", "markers"))


_LAB_ENTRIES = {
    ("result", False): (log_lab_result, None),
    ("result", True): (update_lab_result, "result_id"),
    ("results", False): (log_lab_results, None),
    ("marker", False): (update_lab_marker, None),
}


@tool(WRITE)
async def save_lab(
    entry: str = "result",
    record_id: Optional[int] = None,
    marker: Optional[str] = None,
    value: Optional[float] = None,
    on_date: Optional[str] = None,
    unit: Optional[str] = None,
    ref_low: Optional[float] = None,
    ref_high: Optional[float] = None,
    lab_name: Optional[str] = None,
    results: Optional[list[dict]] = None,
    category: Optional[str] = None,
    tier: Optional[int] = None,
    retest_interval_days: Optional[int] = None,
    defer_until: Optional[str] = None,
    note: Optional[str] = None,
    override: Optional[bool] = None,
) -> dict:
    """Records or corrects lab data.

    ``entry``:
      * ``result`` — one ``marker`` ``value`` for ``on_date``, with optional
        ``unit``, ``ref_low``/``ref_high`` (left out: the catalog range),
        ``lab_name``, ``note``; the out-of-range flag is computed. With
        ``record_id`` (from ``get_labs``) corrects only the fields passed.
      * ``results`` — a whole report at once: ``results`` is a list of
        ``{marker, value, unit?, ref_low?, ref_high?}`` sharing ``on_date`` and
        ``lab_name`` (e.g. a panel read from a photo or PDF in the chat).
        Identical (date, marker, value) rows are deduped, so a retry is safe; a
        block on any marker saves nothing.
      * ``marker`` — edits the catalog card of ``marker``: ``ref_low``/``ref_high``,
        ``category``, ``tier``, ``retest_interval_days``, ``defer_until``
        (YYYY-MM-DD, silences the retest reminder until then), ``note``.

    A hard conflict block returns ``{"blocked": true, ...}``; repeat with
    ``override=true`` only if the owner insists."""
    args = dict(
        marker=marker, value=value, on_date=on_date, unit=unit, ref_low=ref_low,
        ref_high=ref_high, lab_name=lab_name, results=results, category=category,
        tier=tier, retest_interval_days=retest_interval_days, defer_until=defer_until,
        note=note, override=override,
    )
    return await dispatch("save_lab", "entry", entry, _LAB_ENTRIES, args, record_id)
