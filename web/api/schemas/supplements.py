"""Pydantic schemas for the Supplements API (/api/v1/supplements)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class SupplementItem(CamelModel):
    id: int
    name: str
    key: str
    dose: Optional[str] = None
    timing: Optional[str] = None
    timing_slot: Optional[str] = None
    timing_bucket: Optional[str] = None
    evidence: Optional[str] = None
    active: bool = True
    contraindications: Optional[str] = None
    contra: Optional[str] = None
    note: Optional[str] = None


class SupplementGroup(CamelModel):
    key: str
    label: str
    sub: str = ""
    tone: str = ""
    items: list[SupplementItem] = []


class SupplementAlertItem(CamelModel):
    id: int
    domain: str
    severity: str
    alert_key: str
    message: str
    created_at: Optional[str] = None


class SupplementsView(CamelModel):
    groups: list[SupplementGroup]
    active: list[SupplementItem] = []
    archived: list[SupplementItem] = []
    active_count: int
    total_count: int
    alerts: list[SupplementAlertItem] = []


class SupplementCreate(CamelModel):
    name: str
    key: Optional[str] = None
    dose: Optional[str] = None
    timing: Optional[str] = None
    evidence: Optional[str] = None
    active: bool = True
    contraindications: Optional[str] = None
    note: Optional[str] = None
    override: bool = False


class SupplementUpdate(CamelModel):
    name: Optional[str] = None
    key: Optional[str] = None
    dose: Optional[str] = None
    timing: Optional[str] = None
    evidence: Optional[str] = None
    active: Optional[bool] = None
    contraindications: Optional[str] = None
    note: Optional[str] = None
    override: bool = False


class SupplementToggle(CamelModel):
    active: bool
    override: bool = False


class SupplementCreated(BaseModel):
    id: int
