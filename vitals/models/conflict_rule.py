"""``conflict_rules`` — data-driven cross-domain rules.

A rule connects a condition in ``domain_a`` to a condition in ``domain_b`` (e.g.
an active catalog supplement vs a genetics variant, or a skincare actives clash).
Rules are **data**, not code: the engine in ``services/conflict_engine.py``
evaluates whatever rows are ``active``. Foundation ships the table + engine
framework; real rule sets land with their owning modules (Supplements /
Genetics / Skincare).

``condition_a`` / ``condition_b`` are JSON predicates the engine matches against
proposed state (shape is defined by the engine; kept generic here on purpose).
``params`` carries rule-type-specific config — e.g. ``{"hours": 12}`` for a
``timing_separation`` rule.
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import JSON, Boolean, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from vitals.models.base import Base, TimestampMixin

_JSON_TYPE = JSONB().with_variant(JSON(), "sqlite")


class ConflictRule(Base, TimestampMixin):
    __tablename__ = "conflict_rules"

    id: Mapped[int] = mapped_column(primary_key=True)

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

    # Only `active` rules are evaluated. Lets a rule be authored/disabled without
    # deletion (keeps history for the open-source rule catalog).
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
