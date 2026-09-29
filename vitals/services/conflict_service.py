"""Conflict rules browsing & toggle service."""
from __future__ import annotations

from typing import Any, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.models.conflict_rule import ConflictRule
from vitals.models.system_alert import SystemAlert

_CATEGORY_ORDER = (
    "absorption",
    "pharmacogenomics",
    "dermatology",
    "lab_safety",
    "glp1",
    "contraindication",
)


async def get_firing_rule_ids(session: AsyncSession) -> set[int]:
    """Rule ids with an active (unresolved) alert right now — the conflict engine
    stamps ``alert_key = f"conflict:{rule_id}"`` (see conflict_engine.enforce)."""
    result = await session.execute(
        select(SystemAlert.alert_key).where(
            SystemAlert.resolved_at.is_(None),
            SystemAlert.alert_key.like("conflict:%"),
        )
    )
    ids: set[int] = set()
    for (alert_key,) in result.all():
        _, _, raw_id = alert_key.partition(":")
        if raw_id.isdigit():
            ids.add(int(raw_id))
    return ids


async def list_rules(
    session: AsyncSession,
    *,
    domain: Optional[str] = None,
    severity: Optional[str] = None,
) -> Sequence[ConflictRule]:
    stmt = select(ConflictRule).order_by(ConflictRule.category, ConflictRule.code)
    rules = list((await session.execute(stmt)).scalars().all())
    if domain:
        rules = [r for r in rules if r.domain_a == domain or r.domain_b == domain]
    if severity:
        rules = [r for r in rules if r.severity == severity]
    return rules


async def toggle_rule(
    session: AsyncSession, rule_id: int, active: bool
) -> Optional[ConflictRule]:
    row = await session.get(ConflictRule, rule_id)
    if row is None:
        return None
    row.active = active
    await session.flush()
    return row


async def collect(
    session: AsyncSession,
    *,
    domain: Optional[str] = None,
    severity: Optional[str] = None,
) -> dict[str, Any]:
    """Collect interactions view data in one round-trip."""
    all_rules_rows = (await session.execute(select(ConflictRule))).scalars().all()
    firing_ids = await get_firing_rule_ids(session)

    # All unique domains across the entire catalog for filtering
    all_domains = sorted(
        {d for r in all_rules_rows for d in (r.domain_a, r.domain_b) if d}
    )

    filtered_rules = list(all_rules_rows)
    if domain and domain != "all":
        filtered_rules = [
            r for r in filtered_rules if r.domain_a == domain or r.domain_b == domain
        ]
    if severity and severity != "all":
        filtered_rules = [r for r in filtered_rules if r.severity == severity]

    rule_items: list[dict[str, Any]] = []
    for r in filtered_rules:
        hours = None
        if r.rule_type == "timing_separation" and isinstance(r.params, dict):
            hours = r.params.get("hours")

        rule_items.append(
            {
                "id": r.id,
                "code": r.code,
                "rule_type": r.rule_type,
                "type": "hard" if r.rule_type == "hard_block" else "timing" if r.rule_type == "timing_separation" else "soft",
                "domain_a": r.domain_a,
                "domain_b": r.domain_b,
                "a": r.domain_a,
                "b": r.domain_b,
                "severity": r.severity,
                "sev": r.severity,
                "message": r.message,
                "msg": r.message,
                "category": r.category or "other",
                "cat": r.category or "other",
                "source": r.source,
                "src": r.source,
                "evidence": r.evidence,
                "ev": r.evidence,
                "active": r.active,
                "on": r.active,
                "firing": r.id in firing_ids,
                "hours": hours,
                "h": hours,
            }
        )

    by_category: dict[str, list[dict[str, Any]]] = {}
    for item in rule_items:
        by_category.setdefault(item["category"], []).append(item)

    ordered_categories = [c for c in _CATEGORY_ORDER if c in by_category]
    ordered_categories += sorted(c for c in by_category if c not in _CATEGORY_ORDER)

    return {
        "rules": rule_items,
        "by_category": by_category,
        "ordered_categories": ordered_categories,
        "firing_ids": sorted(firing_ids),
        "all_domains": all_domains,
        "total_count": len(rule_items),
        "firing_count": sum(1 for r in rule_items if r["firing"]),
    }
