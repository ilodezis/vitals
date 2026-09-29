"""Pydantic schemas for the Reports API (/api/v1/reports)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class MilestoneItem(CamelModel):
    id: int
    name: str
    domain: str
    status: str
    target_value: Optional[float] = None
    target_unit: Optional[str] = None
    deadline: Optional[str] = None
    days_left: Optional[int] = None
    current: Optional[float] = None
    remaining: Optional[float] = None
    pct: Optional[float] = None
    closed_on: Optional[str] = None
    deadline_margin_days: Optional[int] = None


class MilestoneCreate(CamelModel):
    name: str
    domain: str = "weight"
    target_value: Optional[float] = None
    target_unit: Optional[str] = None
    deadline: Optional[str] = None
    note: Optional[str] = None


class MilestoneStatusUpdate(CamelModel):
    status: str


class MilestoneCreated(BaseModel):
    id: int


class DigestItem(CamelModel):
    id: int
    date: Optional[str] = None
    kind: str
    content: str
    model: Optional[str] = None
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    created_at: Optional[str] = None


class DigestGenerateRequest(CamelModel):
    period_days: int = 7


class ReportsView(CamelModel):
    active_goals: list[MilestoneItem] = []
    closed_goals: list[MilestoneItem] = []
    active_goals_count: int = 0
    closed_goals_count: int = 0
    latest_digest: Optional[DigestItem] = None
    digest_history: list[DigestItem] = []
    digests_count: int = 0
    latest_brief: Optional[DigestItem] = None
    goal_domains: list[str] = []
    llm_configured: bool = False
    channel_configured: bool = False
    today: str
