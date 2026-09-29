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
    type: str
    domain_a: str
    domain_b: str
    a: str
    b: str
    severity: str
    sev: str
    message: str
    msg: str
    category: str
    cat: str
    source: Optional[str] = None
    src: Optional[str] = None
    evidence: Optional[str] = None
    ev: Optional[str] = None
    active: bool = True
    on: bool = True
    firing: bool = False
    hours: Optional[int] = None
    h: Optional[int] = None


class RuleToggleRequest(CamelModel):
    active: bool


class InteractionsView(CamelModel):
    rules: list[ConflictRuleItem] = []
    by_category: dict[str, list[ConflictRuleItem]] = {}
    ordered_categories: list[str] = []
    firing_ids: list[int] = []
    all_domains: list[str] = []
    total_count: int = 0
    firing_count: int = 0
