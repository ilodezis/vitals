"""Custom chart builder — data access layer.

Bridges the declarative registry (``chart_registry``) to actual rows: builds
the picklist catalog for the builder UI, resolves one metric+param to a plain
time series, and resolves a whole saved chart config to render-ready series
(label/unit/points) for ``tojson`` embedding — same SSR pattern as the
existing weight/hevy/labs charts (no client-side fetch).
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.services import body_scan_service, hevy_service, labs_service
from vitals.services.analytics import body_metrics, chart_registry
from vitals.services.analytics.chart_registry import MetricField

_AGGREGATORS = {"avg": func.avg, "sum": func.sum, "max": func.max, "min": func.min}


async def build_catalog(
    session: AsyncSession, enabled_modules: dict[str, bool], *, lang: str = "ru"
) -> dict:
    """Nested {domain: {label, metrics: [{key, label, unit, param_kind, params}]}}
    for the chart-builder UI, embedded once via ``tojson`` on page load. Domains
    gated behind a disabled Optional module are omitted entirely."""
    catalog: dict = {}
    for domain in chart_registry.all_domains():
        fields = chart_registry.metrics_for_domain(domain)
        gate_key = next((f.module_key for f in fields if f.module_key), None)
        if gate_key is not None and not enabled_modules.get(gate_key, False):
            continue

        label_ru, label_en = chart_registry.DOMAIN_LABELS.get(domain, (domain, domain))
        metrics = []
        for field in fields:
            entry = {
                "key": field.key,
                "label": field.label_ru if lang == "ru" else field.label_en,
                "unit": field.unit,
                "param_kind": field.param_kind,
            }
            if field.param_kind == "labs_marker":
                markers = await labs_service.list_markers(session)
                entry["params"] = [{"value": m.name, "label": m.name} for m in markers]
            elif field.param_kind == "hevy_exercise":
                exercises = await hevy_service.exercise_catalog(session)
                entry["params"] = [
                    {"value": e["exercise_template_id"], "label": e["title"]}
                    for e in exercises
                ]
            elif field.param_kind == "body_scan_metric":
                entry["params"] = await body_scan_service.available_metrics(session)
            metrics.append(entry)

        catalog[domain] = {"label": label_ru if lang == "ru" else label_en, "metrics": metrics}
    return catalog


async def _simple_series(session: AsyncSession, field: MetricField) -> list[dict]:
    """Generic ``GROUP BY date`` + aggregate for a plain-column metric."""
    agg_fn = _AGGREGATORS[field.aggregate]
    col = getattr(field.model, field.column)
    stmt = select(field.model.date, agg_fn(col)).where(col.is_not(None))
    if field.extra_filter is not None:
        stmt = field.extra_filter(stmt)
    stmt = stmt.group_by(field.model.date).order_by(field.model.date)
    rows = (await session.execute(stmt)).all()

    points: list[dict] = []
    for on_date, raw_value in rows:
        if raw_value is None:
            continue
        value = float(raw_value)
        if field.transform is not None:
            value = field.transform(value)
        points.append({"date": on_date.isoformat(), "value": round(value, 3)})
    return points


async def series_for(
    session: AsyncSession, *, metric_key: str, param: Optional[str] = None
) -> list[dict]:
    """Resolve one metric (+ optional param) to ``[{"date": iso, "value": float}]``,
    dispatching by ``param_kind``. Raises ``KeyError`` for an unknown metric key
    and ``ValueError`` when a required param is missing."""
    field = chart_registry.get(metric_key)

    if field.param_kind == "none":
        return await _simple_series(session, field)

    if not param:
        raise ValueError(f"metric '{metric_key}' requires a param")

    if field.param_kind == "labs_marker":
        rows = await labs_service.marker_history(session, param)
        return [
            {"date": r["date"], "value": r["value"]}
            for r in rows
            if r.get("value") is not None
        ]

    if field.param_kind == "hevy_exercise":
        rows = await hevy_service.working_weight_series(session, param)
        return [
            {"date": r["date"], "value": r["weight_kg"]}
            for r in rows
            if r.get("weight_kg") is not None
        ]

    if field.param_kind == "body_scan_metric":
        metric_key_part, _, segment = param.partition(":")
        rows = await body_scan_service.metric_history(
            session, metric_key_part, segment=(segment or None)
        )
        return [
            {"date": r["date"], "value": r["value"]}
            for r in rows
            if r.get("value") is not None
        ]

    raise ValueError(f"unknown param_kind for metric '{metric_key}'")


async def _unit_for(
    session: AsyncSession, field: MetricField, param: Optional[str]
) -> Optional[str]:
    """The series's unit — a data-driven lookup for the two domains whose unit
    varies per parameter (a lab marker's unit, a BIA metric's unit); a constant
    from the registry for everything else."""
    if field.param_kind == "labs_marker" and param:
        marker = await labs_service.get_marker(session, param)
        return marker.unit if marker else None
    if field.param_kind == "body_scan_metric" and param:
        metric_key_part = param.split(":", 1)[0]
        spec = body_metrics.METRIC_REGISTRY.get(metric_key_part)
        return spec.unit if spec else None
    return field.unit


async def _auto_label(
    session: AsyncSession, field: MetricField, param: Optional[str], *, lang: str = "ru"
) -> str:
    """Human-readable default label for a series with no explicit ``label``."""
    if field.param_kind == "none":
        return field.label_ru if lang == "ru" else field.label_en
    if field.param_kind == "labs_marker":
        return param or field.label_ru
    if field.param_kind == "hevy_exercise":
        exercises = await hevy_service.exercise_catalog(session)
        for e in exercises:
            if e["exercise_template_id"] == param:
                return e["title"]
        return param or field.label_ru
    if field.param_kind == "body_scan_metric":
        metric_key_part, _, segment = (param or "").partition(":")
        label = body_metrics.display_name(metric_key_part) or metric_key_part or field.label_ru
        if segment:
            label = f"{label} — {body_scan_service.SEGMENT_LABELS_RU.get(segment, segment)}"
        return label
    return field.label_ru if lang == "ru" else field.label_en


async def resolve_chart_series(
    session: AsyncSession, config: dict, *, lang: str = "ru"
) -> list[dict]:
    """Resolve every series of one saved chart config to render-ready dicts
    (``label``/``unit``/``color_slot``/``points``). A series whose ``metric_key``
    no longer exists in the registry (a module was removed) is skipped rather
    than raising, so the chart still renders its remaining series."""
    resolved: list[dict] = []
    for entry in config.get("series", []):
        try:
            field = chart_registry.get(entry["metric_key"])
        except KeyError:
            continue
        param = entry.get("param")
        points = await series_for(session, metric_key=field.key, param=param)
        unit = await _unit_for(session, field, param)
        label = entry.get("label") or await _auto_label(session, field, param, lang=lang)
        resolved.append({
            "label": label,
            "unit": unit,
            "color_slot": entry.get("color_slot", 0),
            "points": points,
        })
    return resolved
