"""Alerts and the conflict-rule engine."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from vitals.enums import Domain
from vitals.services import conflict_engine
from web.routers.mcp._core import (
    READ, WRITE, gated, get_session_factory, choice_error, dispatch, route, serialize_row, serialize_written, tool,
)

async def get_active_alerts(domain: Optional[str] = None) -> list[dict]:
    """Returns the currently active (unresolved) alerts — warnings, conflict
    blocks, overdue retests, the station's air — newest first, optionally for one
    ``domain``. ``override_at`` marks a block the owner already answered with
    "doing it anyway". Transient recovery observations (such as Garmin sleep/load advice)
    appear on the day in get_today().attention rather than persistent system alerts."""
    from vitals.services import alerts_service, labs_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        if domain is None or domain == Domain.LABS.value:
            await labs_service.refresh_alerts(session)
            await session.commit()
        alerts = await alerts_service.list_active(session, domain=domain)
        return [serialize_row(a) for a in alerts]


async def resolve_alert(alert_id: int) -> dict:
    """Marks one alert resolved — it disappears from ``get_active_alerts`` and
    from the dashboard. Use it once the thing the alert is about has actually been
    dealt with in the conversation, so the discussion and the closing are the same
    step instead of leaving the owner a button to press afterwards. WRITE tool."""
    from vitals.services import alerts_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        row = await alerts_service.resolve_alert(session, alert_id)
        if row is None:
            return {"error": f"Alert {alert_id} not found"}
        await session.commit()
        return await serialize_written(session, row)


async def resolve_all_alerts(domain: Optional[str] = None, confirm: bool = False) -> dict:
    """Resolves every active alert at once — the app's "dismiss all" — or, with
    ``domain`` (e.g. "labs", "skincare", "environment"), every alert of that
    domain. Bulk and irreversible. Requires two-step confirmation: calling without
    confirm=True returns a preview with the count and sample alerts. Call with
    confirm=True to execute. Returns how many were resolved. WRITE tool."""
    from vitals.services import alerts_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        active = await alerts_service.list_active(session, domain=domain)
        count = len(active)
        if not confirm:
            return {
                "preview": True,
                "confirm_required": True,
                "action": "resolve_all_alerts",
                "domain": domain,
                "count": count,
                "sample_messages": [a.message for a in active[:5]],
                "hint": f"To resolve all {count} active alerts, call resolve_all_alerts(domain={domain!r}, confirm=True).",
            }
        await alerts_service.resolve_all(session, domain=domain)
        await session.commit()
        return {"resolved": count, "domain": domain}


async def override_alert(alert_id: int) -> dict:
    """Marks a blocking alert overridden — "noted, doing it anyway". The alert
    stays active and visible; only the block it represents stops being treated as
    unanswered. Call this ONLY when the user explicitly instructs to proceed despite
    the warning (e.g. "save anyway", "override", "я знаю, сохрани"). Never call this
    autonomously on the model's own initiative. For resolving an alert instead, use
    ``resolve_alert``. WRITE tool."""
    from vitals.services import alerts_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        row = await alerts_service.override_alert(session, alert_id)
        if row is None:
            return {"error": f"Alert {alert_id} not found"}
        await session.commit()
        return await serialize_written(session, row)


async def check_supplement_conflicts(supplement_name: str) -> list[dict]:
    """Evaluates a proposed supplement (by free-text name) against the curated
    conflict-rule catalog — active supplements, genetics, skincare routine,
    labs, and GLP-1 state. The name is normalized to the same stable ``key``
    the catalog matches rules on (e.g. "Железо" -> "iron"), so this works
    regardless of spelling/language. Read-only — never writes, never blocks."""
    from vitals.services import conflict_catalog

    session_factory = get_session_factory()
    key = conflict_catalog.normalize_ingredient(supplement_name)
    async with session_factory() as session:
        violations = await conflict_engine.evaluate(
            session,
            Domain.SUPPLEMENTS.value,
            {"key": key, "name": supplement_name, "active": True, "ref": f"supplement:{key}"},
        )
        return [_violation_view(v) for v in violations]


_VALID_CONFLICT_DOMAINS = {d.value for d in Domain}


def _violation_view(v) -> dict:
    """A dry-run violation plus the catalog entities the rule matched."""
    return {**v.to_dict(), "entities": list(v.entity_refs)}


async def list_conflict_rules(
    domain: Optional[str] = None, category: Optional[str] = None
) -> list[dict]:
    """Lists the curated cross-domain conflict rules (vitals/data/conflict_rules.yaml),
    optionally filtered by ``domain`` (matches either side of the rule) and/or
    ``category`` (absorption, pharmacogenomics, dermatology, lab_safety, glp1,
    contraindication). ``active`` is the owner's on/off switch for the rule
    (``set_conflict_rule_active``); ``firing`` is true while the rule has an
    unresolved alert right now. Switched-off rules are included so the whole
    catalog is visible."""
    from vitals.models.conflict_rule import ConflictRule
    from vitals.services import conflict_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(ConflictRule)
        if category:
            stmt = stmt.where(ConflictRule.category == category)
        rows = (await session.execute(stmt)).scalars().all()
        if domain:
            rows = [r for r in rows if r.domain_a == domain or r.domain_b == domain]
        firing = await conflict_service.get_firing_rule_ids(session)
        return [{**serialize_row(r), "firing": r.id in firing} for r in rows]


@gated("interactions")
async def set_conflict_rule_active(rule_id: int, active: bool) -> dict:
    """Switches one conflict rule on or off — the toggle on the app's
    Interactions screen. A rule switched off is never evaluated: its warnings and
    blocks stop for every write (the app's and yours) until it is switched back
    on. ``rule_id`` from ``list_conflict_rules``. Turning off a ``block`` rule
    removes a safety check, so do it only on the owner's explicit request, and
    say which rule it was. WRITE tool."""
    from vitals.services import conflict_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        row = await conflict_service.toggle_rule(session, rule_id, active)
        if row is None:
            return {"error": f"Conflict rule {rule_id} not found"}
        await session.commit()
        return await serialize_written(session, row)


async def check_conflicts(domain: str, payload: dict) -> list[dict]:
    """Evaluates an arbitrary proposed state against the active conflict rules
    for ``domain`` (one of: weight, glp1, supplements, genetics, skincare,
    labs, nutrition, workouts, garmin, milestones, system, body_comp). E.g.
    ``check_conflicts("labs", {"marker": "Калий", "value": 5.5})`` or
    ``check_conflicts("supplements", {"key": "iron", "active": True})``.
    Read-only — never writes, never blocks; returns the violations the proposed
    item itself would take part in if saved (``key`` and ``active`` count: an
    inactive supplement clashes with nothing). Rules already true of the rest of
    the catalog are not repeated here — those are in ``get_active_alerts``.
    Each violation lists the catalog ``entities`` it matched."""
    if domain not in _VALID_CONFLICT_DOMAINS:
        return [{"error": f"Unknown domain '{domain}'. Use one of: {', '.join(sorted(_VALID_CONFLICT_DOMAINS))}"}]

    session_factory = get_session_factory()
    async with session_factory() as session:
        if (
            domain == Domain.SUPPLEMENTS.value
            and isinstance(payload, dict)
            and payload.get("key")
            and "ref" not in payload
        ):
            payload = {**payload, "ref": f"supplement:{payload['key']}"}
        violations = await conflict_engine.evaluate(session, domain, payload)
        return [_violation_view(v) for v in violations]


# ── Consolidated tools ───────────────────────────────────────────────────────
_ALERT_ACTIONS = {
    ("resolve", False): (resolve_alert, None),
    ("override", False): (override_alert, None),
    ("resolve_all", False): (resolve_all_alerts, None),
}


@tool(WRITE, destructive=True, idempotent=True)
async def manage_alerts(
    action: str,
    alert_id: Optional[int] = None,
    domain: Optional[str] = None,
    confirm: Optional[bool] = None,
) -> dict:
    """Acts on alerts from ``get_alerts(view="active")``.

    ``action``:
      * ``resolve`` — closes ``alert_id``; it leaves the list and the dashboard.
        Use it once the thing the alert is about has been dealt with in the
        conversation.
      * ``override`` — marks a blocking ``alert_id`` "noted, doing it anyway": it
        stays visible, only the block stops counting as unanswered. ONLY when the
        owner explicitly says to proceed despite it — never on your own initiative.
      * ``resolve_all`` — the app's "dismiss all", optionally for one ``domain``
        ("labs", "skincare", "environment"). Bulk and irreversible: without
        ``confirm=true`` it returns a preview with the count and samples."""
    args = dict(alert_id=alert_id, domain=domain, confirm=confirm)
    return await dispatch("manage_alerts", "action", action, _ALERT_ACTIONS, args)


@tool(READ)
async def get_alerts(
    view: str = "active",
    domain: Optional[str] = None,
    category: Optional[str] = None,
    payload: Optional[dict] = None,
    supplement_name: Optional[str] = None,
) -> list[dict]:
    """Alerts and the cross-domain conflict-rule engine. Read-only — never writes
    or blocks.

    ``view``:
      * ``active`` (default) — currently unresolved alerts (warnings, conflict
        blocks, overdue retests, bedroom air), newest first, optionally for one
        ``domain``. ``override_at`` marks a block already answered with "doing it
        anyway". Transient recovery advice appears in ``get_today().attention``.
      * ``rules`` — the curated conflict-rule catalog, optionally by ``domain``
        (either side of a rule) and/or ``category`` (absorption,
        pharmacogenomics, dermatology, lab_safety, glp1, contraindication).
        ``active`` is the owner's toggle (``update_settings(
        section="conflict_rule")``); ``firing`` means an unresolved alert now.
      * ``check`` — evaluates a proposed ``payload`` for ``domain`` (weight, glp1,
        supplements, genetics, skincare, labs, nutrition, workouts, garmin,
        milestones, system, body_comp), e.g. ``{"marker": "Potassium", "value":
        5.5}`` for labs or ``{"key": "iron", "active": true}`` for supplements;
        returns the violations the item itself would take part in if saved.
      * ``supplement`` — checks a supplement by free-text ``supplement_name``
        (RU or EN) against active supplements, genetics, skincare, labs and
        GLP-1 state."""
    if view == "active":
        result = await route(
            get_active_alerts, "get_alerts(view='active')",
            dict(domain=domain, category=category, payload=payload, supplement_name=supplement_name),
        )
    elif view == "rules":
        result = await route(
            list_conflict_rules, "get_alerts(view='rules')",
            dict(domain=domain, category=category, payload=payload, supplement_name=supplement_name),
        )
    elif view == "check":
        result = await route(
            check_conflicts, "get_alerts(view='check')",
            dict(domain=domain, payload=payload, category=category, supplement_name=supplement_name),
        )
    elif view == "supplement":
        result = await route(
            check_supplement_conflicts, "get_alerts(view='supplement')",
            dict(supplement_name=supplement_name, domain=domain, category=category, payload=payload),
        )
    else:
        result = choice_error("view", view, ("active", "rules", "check", "supplement"))
    return [result] if isinstance(result, dict) else result
