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
    category: Optional[str] = None
    source: Optional[str] = None
    evidence: Optional[str] = None

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
            "category": self.category,
            "source": self.source,
            "evidence": self.evidence,
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


# Recognized comparison/membership/presence operators for a field's expected
# value (e.g. ``condition_a = {"dose_mg": {"$gte": 2.0}}``). Any dict whose keys
# all start with "$" is treated as an operator dict rather than a literal value.
_OPERATOR_KEYS = frozenset({"$gt", "$gte", "$lt", "$lte", "$in", "$nin", "$exists", "$contains"})
# Top-level boolean combinators — these replace the implicit per-key AND with OR
# / explicit AND / negation over a list of *conditions* (not field values).
_LOGIC_KEYS = frozenset({"$any", "$all", "$not"})


def _looks_like_operator_dict(value: Any) -> bool:
    return isinstance(value, dict) and bool(value) and all(
        isinstance(k, str) and k.startswith("$") for k in value
    )


def _apply_operators(actual: Any, ops: dict) -> bool:
    """Evaluate an operator dict against one field's actual value. Every operator
    present must hold (implicit AND). A comparison against an incompatible type
    (e.g. ``$gt`` on a string) fails the match rather than raising — a malformed
    rule must never crash evaluation/save."""
    try:
        for op, expected in ops.items():
            if op == "$gt":
                if actual is None or not (actual > expected):
                    return False
            elif op == "$gte":
                if actual is None or not (actual >= expected):
                    return False
            elif op == "$lt":
                if actual is None or not (actual < expected):
                    return False
            elif op == "$lte":
                if actual is None or not (actual <= expected):
                    return False
            elif op == "$in":
                if actual not in expected:
                    return False
            elif op == "$nin":
                if actual in expected:
                    return False
            elif op == "$exists":
                if (actual is not None) != bool(expected):
                    return False
            elif op == "$contains":
                if actual is None or expected not in actual:
                    return False
            else:
                logger.warning("conflict_engine: unknown operator %r ignored", op)
        return True
    except TypeError:
        logger.warning(
            "conflict_engine: type mismatch evaluating %r against %r", ops, actual
        )
        return False


def _field_matches(actual: Any, expected: Any) -> bool:
    if _looks_like_operator_dict(expected):
        return _apply_operators(actual, expected)
    return actual == expected


def _matches(condition: dict, item: dict) -> bool:
    """Predicate match: every key in ``condition`` must hold against ``item``
    (implicit AND). A key's value is either a literal (equality, the original
    behavior — fully backward compatible) or an operator dict (``$gt``/``$gte``/
    ``$lt``/``$lte``/``$in``/``$nin``/``$exists``/``$contains``). The three
    top-level keys ``$any``/``$all``/``$not`` take a list of *conditions* (or, for
    ``$not``, a single condition) instead of matching a field, giving OR/AND/NOT
    over whole sub-conditions. An empty condition matches any item (a
    domain-presence rule)."""
    if not isinstance(condition, dict):
        return False
    for key, expected in condition.items():
        if key == "$any":
            if not (isinstance(expected, (list, tuple)) and any(_matches(c, item) for c in expected)):
                return False
        elif key == "$all":
            if not (isinstance(expected, (list, tuple)) and all(_matches(c, item) for c in expected)):
                return False
        elif key == "$not":
            if _matches(expected, item):
                return False
        elif not _field_matches(item.get(key), expected):
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


def _matching_items(condition: dict, items: list[dict]) -> list[dict]:
    return [item for item in items if _matches(condition, item)]


def _slots(items: list[dict]) -> set:
    """The distinct non-empty ``timing_slot`` values carried by matching items.
    Only the supplements resolver currently sets this key (see
    ``supplements_service._parse_slot``); other domains' items simply have no
    slot, which safely excludes them here."""
    return {item.get("timing_slot") for item in items if item.get("timing_slot")}


async def evaluate(
    session: AsyncSession,
    domain: str,
    proposed_state: Any = None,
    *,
    include_day_end: bool = False,
) -> list[Violation]:
    """Evaluate active rules touching ``domain`` against ``proposed_state`` and the
    current state of the other domains. Pure read — returns the firing violations,
    writes nothing.

    Rules whose ``params`` carry ``day_end_only: true`` are skipped unless
    ``include_day_end`` is set. Those rules compare a same-day running total
    against a lower-bound threshold (e.g. "today's calories < 800") which is
    trivially true early in the day — they're only meaningful once the day is
    essentially over, so a once-daily scheduled job (not the live save path)
    passes ``include_day_end=True`` to evaluate them. Every other caller is
    unaffected by default.
    """
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
        if not include_day_end and (rule.params or {}).get("day_end_only"):
            continue
        items_a = await _domain_items(session, rule.domain_a, domain, proposed_items)
        items_b = await _domain_items(session, rule.domain_b, domain, proposed_items)

        matches_a = _matching_items(rule.condition_a or {}, items_a)
        matches_b = _matching_items(rule.condition_b or {}, items_b)
        if not matches_a or not matches_b:
            continue

        if _is_timing_rule(rule.rule_type):
            # A timing_separation rule is about two items taken *together* — it
            # only fires when some matching item on each side shares the same
            # declared AM/PM/MEAL/DAY slot. Different (or unknown) slots mean
            # they're already separated in practice, so no warning is raised.
            if not (_slots(matches_a) & _slots(matches_b)):
                continue

        violations.append(
            Violation(
                rule_id=rule.id,
                rule_type=rule.rule_type,
                severity=rule.severity,
                message=rule.message,
                domain_a=rule.domain_a,
                domain_b=rule.domain_b,
                params=dict(rule.params or {}),
                category=rule.category,
                source=rule.source,
                evidence=rule.evidence,
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
    include_day_end: bool = False,
) -> list[Violation]:
    """Evaluate + apply the override flow.

    Raises :class:`ConflictBlocked` when a ``block`` violation fires without
    ``override``. Otherwise writes an alert row per violation (stamping
    ``override_at`` on overridden blocks) and returns all violations so the caller
    can surface the non-blocking ones. See :func:`evaluate` for ``include_day_end``.
    """
    violations = await evaluate(session, domain, proposed_state, include_day_end=include_day_end)
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
