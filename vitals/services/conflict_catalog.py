"""Conflict-engine data normalization + curated rule catalog.

Two independent responsibilities that both read from ``vitals/data/*.yaml``
(open-source, hand-curated, checked into the repo — not a DB-only catalog):

  * :func:`normalize_ingredient` — turn a free-text supplement/drug name (RU or
    EN, any casing) into the stable ``key`` conflict_rules match on, via the
    alias dictionary in ``ingredients.yaml``, falling back to a transliterating
    slug for anything not in the dictionary (so a Cyrillic name never silently
    collapses to the useless ``"supplement"`` slug — see
    ``supplements_service.slugify``).
  * :func:`sync_catalog` — idempotent upsert of ``conflict_rules.yaml`` into the
    ``conflict_rules`` table (added in Phase 3 alongside the migration that
    gives rows a stable ``code``).
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import Domain, Evidence, RuleType, Severity
from vitals.models.conflict_rule import ConflictRule

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_INGREDIENTS_PATH = _DATA_DIR / "ingredients.yaml"
_RULES_PATH = _DATA_DIR / "conflict_rules.yaml"

_VALID_RULE_TYPES = {v.value for v in RuleType}
_VALID_SEVERITIES = {v.value for v in Severity}
_VALID_DOMAINS = {v.value for v in Domain}
_VALID_EVIDENCE = {v.value for v in Evidence}
_REQUIRED_KEYS = (
    "code", "rule_type", "domain_a", "condition_a", "domain_b", "condition_b",
    "severity", "message",
)

_PUNCT_RE = re.compile(r"[^a-zа-я0-9]+")


def _normalize_text(text: str) -> str:
    """Lowercase, ё->е, drop apostrophes, collapse remaining punctuation/
    whitespace to single spaces. Shared by ingredient names and their aliases so
    both sides of the comparison go through the same folding."""
    cleaned = (text or "").strip().lower().replace("ё", "е")
    cleaned = cleaned.replace("'", "").replace("’", "")
    return _PUNCT_RE.sub(" ", cleaned).strip()


@lru_cache(maxsize=1)
def _ingredient_index() -> tuple[frozenset, tuple]:
    """Load ``ingredients.yaml`` once per process: the set of canonical keys,
    plus a ``(normalized_alias, key)`` list sorted by alias length descending —
    so a longer, more specific alias (``"vitamin d3"``) is tried before a
    shorter one that would also substring-match (``"vitamin d"``)."""
    with open(_INGREDIENTS_PATH, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    keys = frozenset(raw.keys())
    pairs: list[tuple[str, str]] = []
    for key, aliases in raw.items():
        for alias in aliases or []:
            normalized = _normalize_text(alias)
            if normalized:
                pairs.append((normalized, key))
    pairs.sort(key=lambda pair: len(pair[0]), reverse=True)
    return keys, tuple(pairs)


def normalize_ingredient(name: str) -> str:
    """Resolve a free-text ingredient/drug name to its stable canonical key.

    Whole-word/phrase match against ``ingredients.yaml`` (space-padded
    substring, so ``"Fe"`` matches the standalone word but not inside
    "coffee"). Falls back to :func:`supplements_service.slugify` — still
    stable and unique, just not linked to any curated rule — when nothing in
    the dictionary matches."""
    cleaned = _normalize_text(name)
    if cleaned:
        keys, alias_pairs = _ingredient_index()
        if cleaned in keys:
            return cleaned
        padded = f" {cleaned} "
        for alias, key in alias_pairs:
            if f" {alias} " in padded:
                return key

    from vitals.services.supplements_service import slugify

    return slugify(name or "")


# ── Curated rule catalog (vitals/data/conflict_rules.yaml) ─────────────────────


def _validate_entry(entry: dict, seen_codes: set) -> None:
    # condition_a/condition_b are allowed to be `{}` (an empty condition matches
    # any item — a domain-presence rule), so presence is checked by key, not by
    # truthiness, unlike the other required fields.
    missing = [
        k for k in _REQUIRED_KEYS
        if k not in entry or (entry[k] in (None, "") and k not in ("condition_a", "condition_b"))
    ]
    if missing:
        raise ValueError(f"conflict_rules.yaml: entry missing {missing}: {entry!r}")
    code = entry["code"]
    if code in seen_codes:
        raise ValueError(f"conflict_rules.yaml: duplicate code {code!r}")
    if entry["rule_type"] not in _VALID_RULE_TYPES:
        raise ValueError(f"{code}: invalid rule_type {entry['rule_type']!r}")
    if entry["severity"] not in _VALID_SEVERITIES:
        raise ValueError(f"{code}: invalid severity {entry['severity']!r}")
    if entry["domain_a"] not in _VALID_DOMAINS:
        raise ValueError(f"{code}: invalid domain_a {entry['domain_a']!r}")
    if entry["domain_b"] not in _VALID_DOMAINS:
        raise ValueError(f"{code}: invalid domain_b {entry['domain_b']!r}")
    if not isinstance(entry["condition_a"], dict) or not isinstance(entry["condition_b"], dict):
        raise ValueError(f"{code}: condition_a/condition_b must be objects")
    evidence = entry.get("evidence")
    if evidence is not None and evidence not in _VALID_EVIDENCE:
        raise ValueError(f"{code}: invalid evidence {evidence!r}")


@lru_cache(maxsize=1)
def load_rule_catalog() -> tuple[dict, ...]:
    """Parse + validate ``conflict_rules.yaml`` once per process. Raises
    ``ValueError`` on the first malformed entry (missing field, unknown
    rule_type/severity/domain, duplicate code) — a bad catalog entry should
    fail loudly at startup, not silently mis-evaluate."""
    with open(_RULES_PATH, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or []
    seen: set = set()
    for entry in raw:
        _validate_entry(entry, seen)
        seen.add(entry["code"])
    return tuple(raw)


_CATALOG_FIELDS = (
    "rule_type", "domain_a", "condition_a", "domain_b", "condition_b",
    "severity", "message", "params", "category", "source", "evidence",
)


async def sync_catalog(session: AsyncSession) -> dict[str, int]:
    """Idempotent upsert of ``conflict_rules.yaml`` into ``conflict_rules``,
    keyed on ``code``. Every catalog-owned field is refreshed on an existing
    row (so editing a rule's message/severity/source in the YAML takes effect
    on the next sync) — **except** ``active``, which is the user's toggle on
    ``/interactions`` and is never touched once a row exists. Safe to call on
    every startup and from the standalone script; running it twice in a row
    inserts nothing the second time and leaves ``active`` alone."""
    catalog = load_rule_catalog()
    result = await session.execute(
        select(ConflictRule).where(ConflictRule.code.isnot(None))
    )
    existing = {row.code: row for row in result.scalars().all()}

    inserted = 0
    updated = 0
    for entry in catalog:
        values = {field: entry.get(field) for field in _CATALOG_FIELDS}
        row = existing.get(entry["code"])
        if row is None:
            session.add(ConflictRule(code=entry["code"], **values))
            inserted += 1
        else:
            for field, value in values.items():
                setattr(row, field, value)
            updated += 1

    await session.flush()
    logger.info(
        "conflict_catalog.sync_catalog: %d inserted, %d updated (of %d total)",
        inserted, updated, len(catalog),
    )
    return {"inserted": inserted, "updated": updated, "total": len(catalog)}
