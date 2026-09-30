"""Pydantic schemas for the Interactions API (/api/v1/interactions)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class ConflictRuleItem(CamelModel):
    id: int
    code: Optional[str] = None
    rule_type: str
    domain_a: str
    domain_b: str
    severity: str
    message: str
    category: str
    source: Optional[str] = None
    evidence: Optional[str] = None
    active: bool = True
    firing: bool = False
    hours: Optional[int] = None


class RuleToggleRequest(CamelModel):
    active: bool


class InteractionsView(CamelModel):
    rules: list[ConflictRuleItem] = []
    ordered_categories: list[str] = []
    firing_ids: list[int] = []
    all_domains: list[str] = []
    total_count: int = 0
    firing_count: int = 0
