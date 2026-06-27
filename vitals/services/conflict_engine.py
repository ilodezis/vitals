"""Cross-domain conflict engine (framework).

``conflict_rules`` are **data** (see models/conflict_rule.py). This module
evaluates the active rules against proposed state and the current state of other
domains, producing :class:`Violation`s, and enforces the override flow:

    1. A mutating service calls :func:`enforce(session, domain, proposed_state,
       override=...)` before it persists.
    2. Any ``block`` violation with ``override=False`` → raises
       :class:`ConflictBlocked` (the router turns this into HTTP 409 + the
       violations payload; the UI offers "Save anyway (Override)").
    3. On override → the write proceeds and each overridden block is recorded as
       an alert with ``override_at`` stamped.
    4. ``soft_warn`` / ``timing_separation`` / ``info`` violations never block —
       they're written as passive alert rows.

How a domain's *current* state is known is module-specific, so modules register a
resolver via :func:`register_domain_resolver`. The foundation ships only the
framework + a subset-equality matcher; Supplements / Genetics / Skincare register
real resolvers and seed real rules.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import RuleType, Severity
from vitals.models.conflict_rule import ConflictRule
from vitals.services import alerts_service

logger = logging.getLogger(__name__)

# A resolver returns the current "active items" of a domain as a list of dicts
# (e.g. active supplement catalog rows, genetics variants present). Conditions
# are matched against these items.
DomainResolver = Callable[[AsyncSession], Awaitable[Sequence[dict]]]

_resolvers: dict[str, DomainResolver] = {}


def register_domain_resolver(domain: str, resolver: DomainResolver) -> None:
    """Register how to read a domain's current active state. Modules call this at
    import/startup. Re-registering replaces the previous resolver."""
    _resolvers[domain] = resolver


def clear_domain_resolvers() -> None:
    """Drop all registered resolvers (test isolation)."""
    _resolvers.clear()


@dataclass(frozen=True)
class Violation:
    rule_id: Optional[int]
    rule_type: str
    severity: str
    message: str
    domain_a: str
    domain_b: str
    params: dict = field(default_factory=dict)

    @property
    def is_blocking(self) -> bool:
        return self.severity == Severity.BLOCK.value

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "rule_type": self.rule_type,
            "severity": self.severity,
            "message": self.message,
            "domain_a": self.domain_a,
            "domain_b": self.domain_b,
            "params": self.params,
        }


class ConflictBlocked(Exception):
    """Raised when a ``block`` rule fires and the caller did not override.

    Carries the full violation list so the router can render the warning panel
    and the override button.
    """

    def __init__(self, violations: Sequence[Violation]):
        self.violations = list(violations)
        blocking = [v.message for v in self.violations if v.is_blocking]
        super().__init__("; ".join(blocking) or "Conflict")


def _normalize_proposed(proposed_state: Any) -> list[dict]:
    if proposed_state is None:
        return []
    if isinstance(proposed_state, dict):
        return [proposed_state]
    return [item for item in proposed_state if isinstance(item, dict)]


def _matches(condition: dict, item: dict) -> bool:
    """Subset-equality match: every key/value in ``condition`` must be present and
    equal in ``item``. Deliberately simple — modules with richer predicates wrap
    their own logic in a resolver/condition shape. An empty condition matches any
    item (a domain-presence rule)."""
    if not isinstance(condition, dict):
        return False
    for key, expected in condition.items():
        if item.get(key) != expected:
            return False
    return True


async def _domain_items(
    session: AsyncSession,
    domain: str,
    changed_domain: str,
    proposed_items: list[dict],
) -> list[dict]:
    """Current items of ``domain``, plus the proposed items when ``domain`` is the
    one being changed (so a new item can clash with something already present in
    the same domain, e.g. retinoid + peel the same evening)."""
    items: list[dict] = []
    resolver = _resolvers.get(domain)
    if resolver is not None:
        items.extend(await resolver(session))
    if domain == changed_domain:
        items.extend(proposed_items)
    return items


def _side_satisfied(condition: dict, items: list[dict]) -> bool:
    return any(_matches(condition, item) for item in items)


async def evaluate(
    session: AsyncSession,
    domain: str,
    proposed_state: Any = None,
) -> list[Violation]:
    """Evaluate active rules touching ``domain`` against ``proposed_state`` and the
    current state of the other domains. Pure read — returns the firing violations,
    writes nothing."""
    proposed_items = _normalize_proposed(proposed_state)

    result = await session.execute(
        select(ConflictRule).where(
            ConflictRule.active.is_(True),
            (ConflictRule.domain_a == domain) | (ConflictRule.domain_b == domain),
        )
    )
    rules = result.scalars().all()

    violations: list[Violation] = []
    for rule in rules:
        items_a = await _domain_items(session, rule.domain_a, domain, proposed_items)
        items_b = await _domain_items(session, rule.domain_b, domain, proposed_items)

        if _side_satisfied(rule.condition_a or {}, items_a) and _side_satisfied(
            rule.condition_b or {}, items_b
        ):
            violations.append(
                Violation(
                    rule_id=rule.id,
                    rule_type=rule.rule_type,
                    severity=rule.severity,
                    message=rule.message,
                    domain_a=rule.domain_a,
                    domain_b=rule.domain_b,
                    params=dict(rule.params or {}),
                )
            )
    return violations


async def enforce(
    session: AsyncSession,
    domain: str,
    proposed_state: Any = None,
    *,
    override: bool = False,
    entity_ref: str = "",
) -> list[Violation]:
    """Evaluate + apply the override flow.

    Raises :class:`ConflictBlocked` when a ``block`` violation fires without
    ``override``. Otherwise writes an alert row per violation (stamping
    ``override_at`` on overridden blocks) and returns all violations so the caller
    can surface the non-blocking ones.
    """
    violations = await evaluate(session, domain, proposed_state)
    blocking = [v for v in violations if v.is_blocking]

    if blocking and not override:
        raise ConflictBlocked(violations)

    for v in violations:
        overridden = v.is_blocking and override
        await alerts_service.raise_alert(
            session,
            domain=domain,
            severity=v.severity,
            message=v.message,
            alert_key=f"conflict:{v.rule_id}",
            entity_ref=entity_ref,
            overridden=overridden,
        )
    return violations


def _is_timing_rule(rule_type: str) -> bool:
    return rule_type == RuleType.TIMING_SEPARATION.value
