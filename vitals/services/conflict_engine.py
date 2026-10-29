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
from datetime import date as date_type, datetime
from typing import Any, Awaitable, Callable, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import Domain, RuleType, Severity
from vitals.models.conflict_rule import ConflictRule
from vitals.services import alerts_service
from vitals.utils.timeutils import today_local

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
    # Refs ("supplement:zinc") of the catalog entities the rule matched, sorted.
    # Empty when the matched items carry no ref (event-style domains).
    entity_refs: tuple[str, ...] = ()

    @property
    def is_blocking(self) -> bool:
        return self.severity == Severity.BLOCK.value

    @property
    def alert_key(self) -> str:
        return f"conflict:{self.rule_id}"

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
    the same domain, e.g. retinoid + peel the same evening).

    A proposed item carrying an ``id`` is an edit of an existing row: it replaces
    the resolver item with that ``id``, so the rules see the state after the save
    rather than the old and the new version of the row side by side."""
    items: list[dict] = []
    resolver = _resolvers.get(domain)
    if resolver is not None:
        items.extend(await resolver(session))
    if domain == changed_domain:
        edited = {p["id"] for p in proposed_items if p.get("id") is not None}
        if edited:
            items = [i for i in items if i.get("id") not in edited]
        items.extend(proposed_items)
    return items


def _side_satisfied(condition: dict, items: list[dict]) -> bool:
    return any(_matches(condition, item) for item in items)


def _matching_items(condition: dict, items: list[dict]) -> list[dict]:
    return [item for item in items if _matches(condition, item)]


def _firing_pairs(rule_type: str, matches_a: list[dict], matches_b: list[dict]) -> list[tuple]:
    """Every (side A item, side B item) pair that makes the rule fire.

    A timing_separation rule is about two items taken *together*: a pair counts
    only when both carry the same declared AM/PM/MEAL/DAY slot. Different (or
    unknown) slots mean they're already separated in practice. Only the
    supplements resolver sets ``timing_slot`` (see
    ``supplements_service._parse_slot``); other domains' items have none, which
    safely excludes them here."""
    timing = _is_timing_rule(rule_type)
    pairs = []
    for a in matches_a:
        for b in matches_b:
            if timing and not (a.get("timing_slot") and a.get("timing_slot") == b.get("timing_slot")):
                continue
            pairs.append((a, b))
    return pairs


def _entity_refs(pairs: list[tuple]) -> tuple[str, ...]:
    refs = {item["ref"] for pair in pairs for item in pair if isinstance(item.get("ref"), str)}
    return tuple(sorted(refs))


# Matches the length of ``system_alerts.entity_ref``.
_ENTITY_REF_MAX = 128


def alert_entity_ref(violation: Violation, fallback: str = "") -> str:
    """The ``entity_ref`` a violation's alert is stored under: the rule's matched
    entities when it has any (so the alert is the same row whichever of them was
    being saved), else ``fallback``."""
    if not violation.entity_refs:
        return fallback
    return ",".join(violation.entity_refs)[:_ENTITY_REF_MAX]


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

    With a ``proposed_state`` only the rules the proposed item itself takes part
    in are returned: a rule that is true of the rest of the catalog (ashwagandha
    while cortisol is low) is not a consequence of saving zinc, so it neither
    blocks nor gets reported for that save. Without one, the current state of
    every domain is evaluated as is.

    Rules whose ``params`` carry ``day_end_only: true`` are skipped unless
    ``include_day_end`` is set. Those rules compare a same-day running total
    against a lower-bound threshold (e.g. "today's calories < 800") which is
    trivially true early in the day — they're only meaningful once the day is
    essentially over, so a once-daily scheduled job (not the live save path)
    passes ``include_day_end=True`` to evaluate them. Every other caller is
    unaffected by default.
    """
    proposed_items = _normalize_proposed(proposed_state)
    proposed_ids = {id(item) for item in proposed_items}

    rules = await _rules_touching(session, domain)

    violations: list[Violation] = []
    for rule in rules:
        if not include_day_end and (rule.params or {}).get("day_end_only"):
            continue
        items_a = await _domain_items(session, rule.domain_a, domain, proposed_items)
        items_b = await _domain_items(session, rule.domain_b, domain, proposed_items)

        matches_a = _matching_items(rule.condition_a or {}, items_a)
        matches_b = _matching_items(rule.condition_b or {}, items_b)
        pairs = _firing_pairs(rule.rule_type, matches_a, matches_b)
        if not pairs:
            continue
        if proposed_ids and not any(
            id(a) in proposed_ids or id(b) in proposed_ids for a, b in pairs
        ):
            continue

        message = rule.message
        severity = rule.severity
        lab_markers = []
        for a, b in pairs:
            if rule.domain_a == Domain.LABS.value and a.get("marker"):
                lab_markers.append(a["marker"])
            if rule.domain_b == Domain.LABS.value and b.get("marker"):
                lab_markers.append(b["marker"])

        if lab_markers:
            from vitals.models.labs import LabResult
            stmt = (
                select(LabResult.date)
                .where(LabResult.marker.in_(lab_markers))
                .order_by(LabResult.date.desc())
                .limit(1)
            )
            matched_date = (await session.execute(stmt)).scalars().first()
            if matched_date:
                days_old = (today_local() - matched_date).days
                if days_old > 180:
                    severity = Severity.NOTE.value
                    date_str = matched_date.strftime("%d.%m.%Y")
                    if "по анализу от" not in message:
                        message = f"{message} (по анализу от {date_str})"

        violations.append(
            Violation(
                rule_id=rule.id,
                rule_type=rule.rule_type,
                severity=severity,
                message=message,
                domain_a=rule.domain_a,
                domain_b=rule.domain_b,
                params=dict(rule.params or {}),
                category=rule.category,
                source=rule.source,
                evidence=rule.evidence,
                entity_refs=_entity_refs(pairs),
            )
        )
    return violations


async def _rules_touching(session: AsyncSession, domain: str) -> Sequence[ConflictRule]:
    result = await session.execute(
        select(ConflictRule).where(
            ConflictRule.active.is_(True),
            (ConflictRule.domain_a == domain) | (ConflictRule.domain_b == domain),
        )
    )
    return result.scalars().all()


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

    An alert for a rule that matched catalog entities is stored under those
    entities (see :func:`alert_entity_ref`) and replaces any other active row of
    the same rule, so one rule is one alert however many saves touched it.
    ``entity_ref`` is used only for rules whose items carry no entity.
    """
    violations = await evaluate(session, domain, proposed_state, include_day_end=include_day_end)
    blocking = [v for v in violations if v.is_blocking]

    if blocking and not override:
        raise ConflictBlocked(violations)

    for v in violations:
        overridden = v.is_blocking and override
        ref = alert_entity_ref(v, entity_ref)
        if v.entity_refs:
            await alerts_service.resolve_superseded(session, alert_key=v.alert_key, keep_entity=ref)
        await alerts_service.raise_alert(
            session,
            domain=domain,
            severity=v.severity,
            message=v.message,
            alert_key=v.alert_key,
            entity_ref=ref,
            overridden=overridden,
        )
    return violations


async def reconcile(session: AsyncSession, domain: str) -> None:
    """Bring the conflict alerts of rules touching ``domain`` in line with the
    current state, after a write to it has been flushed.

    * A rule that no longer fires (its supplement switched off or deleted) has
      its active alerts resolved.
    * A rule that still fires keeps exactly one active alert, bound to the
      entities it matches now; rows raised under another ref are merged into it.
    * A rule with no active alert is left alone — a dismissal sticks until a
      save the rule is about raises it again (see :func:`enforce`).

    ``day_end_only`` rules are owned by :func:`enforce_day_end` and skipped.
    """
    fired = {v.rule_id: v for v in await evaluate(session, domain)}
    for rule in await _rules_touching(session, domain):
        if (rule.params or {}).get("day_end_only"):
            continue
        key = f"conflict:{rule.id}"
        rows = [a for a in await alerts_service.list_active(session) if a.alert_key == key]
        if not rows:
            continue
        v = fired.get(rule.id)
        if v is None:
            await alerts_service.resolve_superseded(session, alert_key=key, keep_entity=None)
            continue
        if not v.entity_refs:
            continue
        ref = alert_entity_ref(v)
        if not any(r.entity_ref == ref for r in rows):
            await alerts_service.raise_alert(
                session,
                domain=rows[0].domain,
                severity=v.severity,
                message=v.message,
                alert_key=key,
                entity_ref=ref,
                overridden=any(r.override_at is not None for r in rows),
            )
        await alerts_service.resolve_superseded(session, alert_key=key, keep_entity=ref)


async def enforce_day_end(
    session: AsyncSession, domain: str, *, entity_ref: str = ""
) -> list[Violation]:
    """Like :func:`enforce`, but for ``day_end_only`` rules specifically —
    call once daily (see ``nutrition_service.day_end_job``), never from a live
    save path.

    Unlike ``enforce()``, this also *resolves* the alert for any day_end_only
    rule touching ``domain`` that is **not** currently violated. Plain
    ``enforce()`` only ever raises — it has no notion of a rule "clearing" —
    which is fine for rules re-evaluated on every save (an unrelated later
    save naturally re-raises or leaves it alone), but wrong here: each day's
    check uses a fresh ``entity_ref`` (today's date), so a rule that stops
    matching would otherwise leave yesterday's alert active forever, needing
    a manual dismiss even after the day's numbers are actually fine.
    """
    violations = await evaluate(session, domain, include_day_end=True)
    fired = {v.rule_id: v for v in violations if (v.params or {}).get("day_end_only")}

    day_end_rules = [
        r for r in await _rules_touching(session, domain) if (r.params or {}).get("day_end_only")
    ]

    for rule in day_end_rules:
        key = f"conflict:{rule.id}"
        v = fired.get(rule.id)
        if v is None:
            # No longer violated — clear whatever entity_ref it was last
            # raised under (could be an earlier day), not just today's.
            await alerts_service.resolve_superseded(session, alert_key=key, keep_entity=None)
            continue
        # Still/newly violated — supersede a stale earlier-day row, then
        # raise (or refresh) today's.
        await alerts_service.resolve_superseded(session, alert_key=key, keep_entity=entity_ref)
        await alerts_service.raise_alert(
            session,
            domain=domain,
            severity=v.severity,
            message=v.message,
            alert_key=key,
            entity_ref=entity_ref,
        )
    return violations


def _is_timing_rule(rule_type: str) -> bool:
    return rule_type == RuleType.TIMING_SEPARATION.value
