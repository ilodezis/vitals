"""Weekly digests, doctor reports and saved charts."""
from __future__ import annotations

from typing import Optional


from vitals.services import modules_service
from vitals.utils.timeutils import format_iso
from web.routers.mcp._core import (
    READ, WRITE, _pkg, get_redis_client, get_session_factory, choice_error, dispatch, route, serialize_row, serialize_written, tool,
)

async def get_weekly_digests(limit: int = 5) -> list[dict]:
    """Retrieves historical Claude-generated weekly summaries for continuity."""
    from vitals.services import digest_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        # Through the service, so this stays weekly-only: the same table now also
        # holds the daily Telegram briefs.
        digests = await digest_service.list_digests(session, limit=limit)
        return [serialize_row(d) for d in digests]


# ── Weekly digest generation ──────────────────────────────────────────────────
async def generate_digest_now(period_days: int = 7) -> dict:
    """Generates a fresh weekly AI digest right now (assembles the cross-domain
    context, asks the configured LLM for the narrative, saves it) and returns it.
    Errors cleanly if no OpenRouter key is configured. WRITE tool."""
    from vitals.integrations.llm_client import LLMClient, LLMNotConfigured
    from vitals.services import digest_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            row = await digest_service.generate_digest(
                session, LLMClient(), period_days=period_days
            )
        except LLMNotConfigured:
            return {"error": "LLM not configured — set VITALS_OPENROUTER_API_KEY"}
        except ValueError as exc:
            return {"error": str(exc)}
        await session.commit()
        return await serialize_written(session, row)


# ── Doctor reports (shared links) ─────────────────────────────────────────────
async def get_shared_reports() -> dict:
    """Lists the doctor reports the owner has published — the Share screen: each
    with ``id``, ``title``, ``domains``, the period, ``state`` (live / expired /
    revoked), ``expires_at``, how many times it was opened and when last, and its
    ``url`` (a path on the owner's Vitals host; the visitor also needs the
    password, which is shown only once, at creation, and is not stored). Also
    ``available_domains``, ``presets``, ``period_choices`` and ``expiry_choices``
    for ``create_shared_report``. READ tool."""
    from vitals.services import share_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        enabled = await modules_service.get_enabled_modules(session)
        data = await share_service.collect(session, enabled)
        for r in data["reports"]:
            r.pop("token", None)  # the url carries it; once is enough
        return data


async def create_shared_report(
    title: str,
    domains: Optional[list[str]] = None,
    preset: Optional[str] = None,
    period: str = "90",
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
    expires_days: int = 30,
    labs_flagged_only: bool = False,
    note: Optional[str] = None,
    confirm: bool = False,
) -> dict:
    """Publishes a doctor report — a frozen, password-protected page with the
    chosen domains for a period, exactly like "New report" on the Share screen.
    OUTWARD-FACING: anyone holding the link and the password can read that
    medical data until it expires or is revoked. Create one only when the owner
    explicitly asks for it. Requires two-step confirmation: calling without
    confirm=True returns a preview. Call with confirm=True to create.

    ``domains`` from ``get_shared_reports().available_domains``, or a ``preset``
    from its ``presets`` instead. ``period`` is a number of days back ("30",
    "90", "180"), "all", or "custom" with ``period_start``/``period_end``
    (YYYY-MM-DD). ``expires_days`` — link lifetime (7, 30, 90; defaults to 30).
    ``labs_flagged_only`` keeps only out-of-range lab results.

    Returns the ``url`` path and the ``password`` — the password exists only in
    this answer (only its hash is stored): give both to the owner right away.
    WRITE tool."""
    from vitals.i18n import t
    from vitals.services import share_service

    title = (title or "").strip()
    if not title:
        return {"error": "title is required"}

    session_factory = get_session_factory()
    async with session_factory() as session:
        enabled = await modules_service.get_enabled_modules(session)
        wanted = list(domains or [])
        if preset:
            spec = share_service.PRESETS.get(preset)
            if spec is None:
                return {"error": f"unknown preset '{preset}' — use {', '.join(share_service.PRESETS)}"}
            wanted += list(spec["domains"])
            labs_flagged_only = labs_flagged_only or spec["labs_flagged_only"]
        chosen = share_service.resolve_domains(wanted, enabled)
        if not chosen:
            return {
                "error": "at least one available domain is required — choose from "
                + ", ".join(share_service.available_domains(enabled))
            }
        try:
            start, end = await share_service.resolve_period(
                session, period, period_start, period_end
            )
        except ValueError as e:
            return {"error": str(e)}

        if not confirm:
            return {
                "preview": True,
                "confirm_required": True,
                "action": "create_shared_report",
                "title": title,
                "domains": chosen,
                "preset": preset,
                "period_start": start.isoformat(),
                "period_end": end.isoformat(),
                "expires_days": expires_days,
                "labs_flagged_only": labs_flagged_only,
                "warning": "Publishes an outward-facing report containing medical data. Call with confirm=True to create.",
                "hint": f"To publish this shared report, call create_shared_report(title={title!r}, domains={chosen!r}, confirm=True).",
            }

        row, password = await share_service.create_report(
            session, title=title, domains=chosen, period_start=start, period_end=end,
            expires_days=expires_days, note=note, labs_flagged_only=labs_flagged_only,
            preset=preset, enabled=enabled,
        )
        if not (row.snapshot or {}).get("blocks"):
            await session.rollback()
            return {"error": t("share.error.empty")}
        await session.commit()
        return {
            "id": row.id,
            "url": f"/r/{row.token}",
            "password": password,
            "domains": chosen,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "expires_at": format_iso(row.expires_at),
        }


async def revoke_shared_report(report_id: int) -> dict:
    """Kills a doctor report's link now — it stops opening for anyone and its
    frozen copy of the data is erased; the record of what was shared, with whom
    and when stays on the Share screen. Irreversible: a revoked link can't be
    revived (publish a new one instead). To also remove the record use
    ``delete_record("shared_report", id)``. WRITE tool."""
    from vitals.services import share_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        row = await share_service.get_report(session, report_id)
        if row is None:
            return {"error": f"Shared report {report_id} not found"}
        if row.revoked_at is not None:
            return {"error": f"Shared report {report_id} is already revoked"}
        await share_service.revoke(session, report_id)
        await session.commit()
        return {"revoked": True, "id": report_id}


# ── Saved charts (the Charts screen) ──────────────────────────────────────────
async def get_saved_charts(
    chart_id: Optional[str] = None, include_catalog: bool = False
) -> dict:
    """The owner's saved charts from the Charts screen. Without ``chart_id``:
    every chart's configuration — ``id``, ``name``, ``normalize`` and its
    ``series`` (``metric_key``, ``param``, ``label``). With ``chart_id``: that
    chart with its data resolved — each series' points ``{date, value}`` as the
    screen draws them, plus the timeline flags laid over it. ``include_catalog``
    adds the metric catalog (every ``metric_key`` a chart can plot, with the
    ``param`` it needs) — what ``create_saved_chart`` takes. READ tool."""
    from vitals.services import (
        chart_data_service, charts_service, custom_charts_service, language_service,
    )

    redis = _pkg()._redis_or_none()
    session_factory = get_session_factory()
    async with session_factory() as session:
        enabled = await modules_service.get_enabled_modules(session)
        lang = await language_service.get_language(session, redis)
        result: dict = {}
        if chart_id is None:
            result["charts"] = await custom_charts_service.list_charts(session, redis)
        else:
            chart = await custom_charts_service.get_chart(session, chart_id, redis)
            if chart is None:
                return {"error": f"Chart '{chart_id}' not found"}
            overlays = await charts_service._overlays_by_chart(
                session, [chart], with_supplements=bool(enabled.get("supplements"))
            ) if enabled.get("timeline") else {}
            result["chart"] = {
                "id": chart["id"],
                "name": chart["name"],
                "normalize": chart.get("normalize", False),
                "series": await chart_data_service.resolve_chart_series(session, chart, lang=lang),
                "overlays": overlays.get(chart["id"], []),
            }
        if include_catalog:
            result["catalog"] = await chart_data_service.build_catalog(session, enabled, lang=lang)
        return result


def _redis_or_none():
    """The shared Redis client, or ``None`` — the caches it serves only accelerate."""
    try:
        return get_redis_client()
    except Exception:
        return None


@tool(WRITE)
async def create_saved_chart(
    name: str, series: list[dict], normalize: bool = False
) -> dict:
    """Saves a new chart on the Charts screen. ``series`` is 1–8 items of
    ``{"metric_key": str, "param": str?, "label": str?}`` — keys from
    ``get_saved_charts(include_catalog=True)`` (or the ``get_trend`` registry,
    e.g. ``weight.weight_kg``, ``garmin.hrv_avg``; ``labs.marker`` needs
    ``param`` = marker name). ``normalize=True`` draws every series on a shared
    0–100 scale, for comparing shapes of different units. WRITE tool."""
    from vitals.services import custom_charts_service
    from vitals.services.analytics import chart_registry

    clean = []
    for s in series or []:
        if not isinstance(s, dict) or not s.get("metric_key"):
            return {"error": "every series needs a metric_key"}
        try:
            domain = chart_registry.get(s["metric_key"]).domain
        except KeyError:
            return {"error": f"unknown metric_key '{s['metric_key']}'"}
        clean.append({
            "domain": s.get("domain") or domain, "metric_key": s["metric_key"],
            "param": s.get("param"), "label": s.get("label"),
        })

    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            chart = await custom_charts_service.create_chart(
                session, name=name, series=clean, normalize=normalize, redis=_pkg()._redis_or_none()
            )
        except custom_charts_service.ChartConfigError as e:
            return {"error": str(e)}
        await session.commit()
        return chart


async def delete_saved_chart(chart_id: str) -> dict:
    """Deletes a saved chart from the Charts screen (only the chart — the data it
    plots is untouched). Permanent. WRITE tool."""
    from vitals.services import custom_charts_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        ok = await custom_charts_service.delete_chart(session, chart_id, redis=_pkg()._redis_or_none())
        await session.commit()
        return {"deleted": ok, "chart_id": chart_id}


# ── Consolidated report tools ────────────────────────────────────────────────
@tool(READ)
async def get_reports(
    view: str = "digests",
    limit: Optional[int] = None,
    chart_id: Optional[str] = None,
    include_catalog: Optional[bool] = None,
) -> dict:
    """Digests, published doctor reports and saved charts.

    ``view``:
      * ``digests`` (default) — ``{"digests": [...]}``, historical AI weekly
        summaries for continuity (``limit`` default 5).
      * ``shared`` — published doctor reports (Share screen): id, title, domains,
        period, state (live / expired / revoked), url, view counts, plus
        ``available_domains``, ``presets``, ``period_choices`` and
        ``expiry_choices`` for ``create_report(kind="shared")``.
      * ``charts`` — saved charts from the Charts screen; pass ``chart_id`` to
        resolve one chart's plotted series and overlays, or
        ``include_catalog=true`` for every plottable ``metric_key``."""
    if view == "digests":
        rows = await route(
            get_weekly_digests, "get_reports(view='digests')",
            dict(limit=limit, chart_id=chart_id, include_catalog=include_catalog),
        )
        return rows if isinstance(rows, dict) else {"digests": rows}
    if view == "shared":
        return await route(
            get_shared_reports, "get_reports(view='shared')",
            dict(limit=limit, chart_id=chart_id, include_catalog=include_catalog),
        )
    if view == "charts":
        return await route(
            get_saved_charts, "get_reports(view='charts')",
            dict(limit=limit, chart_id=chart_id, include_catalog=include_catalog),
        )
    return choice_error("view", view, ("digests", "shared", "charts"))


_REPORT_KINDS = {
    ("digest", False): (generate_digest_now, None),
    ("shared", False): (create_shared_report, None),
}


@tool(WRITE, open_world=True)
async def create_report(
    kind: str = "digest",
    period_days: Optional[int] = None,
    title: Optional[str] = None,
    domains: Optional[list[str]] = None,
    preset: Optional[str] = None,
    period: Optional[str] = None,
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
    expires_days: Optional[int] = None,
    labs_flagged_only: Optional[bool] = None,
    note: Optional[str] = None,
    confirm: Optional[bool] = None,
) -> dict:
    """Generates a weekly AI digest or publishes a password-protected doctor report.

    ``kind``:
      * ``digest`` (default) — runs the configured LLM over ``period_days``
        (default 7) and saves the narrative.
      * ``shared`` — OUTWARD-FACING: publishes a frozen, password-protected
        doctor page for ``title`` + ``domains`` (or ``preset`` from
        ``get_reports(view="shared")``), ``period`` ("30"/"90"/"180"/"all"/
        "custom" with ``period_start``/``period_end``), ``expires_days``
        (7/30/90, default 30), ``labs_flagged_only``, ``note``. Two-step: call
        without ``confirm=true`` first to preview, then repeat with
        ``confirm=true`` once the owner agrees. Give both ``url`` and the
        one-time ``password`` to the owner immediately."""
    args = dict(
        period_days=period_days, title=title, domains=domains, preset=preset,
        period=period, period_start=period_start, period_end=period_end,
        expires_days=expires_days, labs_flagged_only=labs_flagged_only,
        note=note, confirm=confirm,
    )
    return await dispatch("create_report", "kind", kind, _REPORT_KINDS, args)
