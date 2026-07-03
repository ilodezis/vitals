"""``conflict_rules`` — data-driven cross-domain rules.

A rule connects a condition in ``domain_a`` to a condition in ``domain_b`` (e.g.
an active catalog supplement vs a genetics variant, or a skincare actives clash).
Rules are **data**, not code: the engine in ``services/conflict_engine.py``
evaluates whatever rows are ``active``. The bulk of the catalog is curated in
``vitals/data/conflict_rules.yaml`` and upserted by ``conflict_catalog.sync_catalog``
(keyed on ``code``) — see the ``/interactions`` browser.

``condition_a`` / ``condition_b`` are JSON predicates the engine matches against
proposed state (the rich predicate grammar — ``$gt``/``$in``/``$any``/etc. — lives
in ``conflict_engine._matches``, kept generic here on purpose). ``params`` carries
rule-type-specific config — e.g. ``{"hours": 12}`` for a ``timing_separation`` rule.
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import JSON, Boolean, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from vitals.models.base import Base, TimestampMixin

_JSON_TYPE = JSONB().with_variant(JSON(), "sqlite")


class ConflictRule(Base, TimestampMixin):
    __tablename__ = "conflict_rules"
    __table_args__ = (Index("ix_conflict_rules_code", "code", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)

    # Stable slug for the curated YAML catalog (vitals/data/conflict_rules.yaml)
    # to upsert against — see conflict_catalog.sync_catalog. Null for any row
    # created outside the catalog flow (e.g. ad-hoc via the API/tests).
    code: Mapped[Optional[str]] = mapped_column(String(96), nullable=True)

    # One of vitals.enums.RuleType: hard_block | soft_warn | timing_separation.
    rule_type: Mapped[str] = mapped_column(String(32), nullable=False)

    domain_a: Mapped[str] = mapped_column(String(32), nullable=False)
    condition_a: Mapped[Any] = mapped_column(_JSON_TYPE, nullable=False)
    domain_b: Mapped[str] = mapped_column(String(32), nullable=False)
    condition_b: Mapped[Any] = mapped_column(_JSON_TYPE, nullable=False)

    # Severity this rule raises when it fires (vitals.enums.Severity). For
    # hard_block this is typically `block`; soft_warn → `warn`.
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    # Rule-type-specific knobs (e.g. {"hours": 12} for timing_separation).
    params: Mapped[Optional[Any]] = mapped_column(_JSON_TYPE, nullable=True)

    # Catalog metadata (vitals/data/conflict_rules.yaml) — grouping + citation
    # for the /interactions browser. Null for non-catalog rows.
    category: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Evidence tier A/B/C (vitals.enums.Evidence) — reused from the supplements
    # catalog's strength-of-evidence convention.
    evidence: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)

    # Only `active` rules are evaluated. Lets a rule be authored/disabled without
    # deletion (keeps history for the open-source rule catalog). This is the one
    # field sync_catalog never overwrites on an existing row — it's the user's.
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
