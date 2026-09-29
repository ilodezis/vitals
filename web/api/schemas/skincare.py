"""Pydantic schemas for the Skincare API (/api/v1/skincare)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class SkincareProductItem(CamelModel):
    id: int
    name: str
    type: str
    active_ingredient: Optional[str] = None
    ing: Optional[str] = None
    description: Optional[str] = None
    desc: Optional[str] = None
    usage_instructions: Optional[str] = None
    use: Optional[str] = None
    default_time: str = "evening"
    time: str = "evening"
    schedule_days: list[int] = []
    days: list[int] = []
    active: bool = True
    on: bool = True


class SkincareProductCreate(CamelModel):
    name: str
    type: str
    active_ingredient: Optional[str] = None
    description: Optional[str] = None
    usage_instructions: Optional[str] = None
    default_time: str = "evening"
    schedule_days: list[int] = []
    active: bool = True


class SkincareProductUpdate(CamelModel):
    name: Optional[str] = None
    type: Optional[str] = None
    active_ingredient: Optional[str] = None
    description: Optional[str] = None
    usage_instructions: Optional[str] = None
    default_time: Optional[str] = None
    schedule_days: Optional[list[int]] = None
    active: Optional[bool] = None


class SkincareProductCreated(BaseModel):
    id: int


class SkincareLogItem(CamelModel):
    id: int
    date: str
    retinoid: bool = False
    azelaic: bool = False
    peel: bool = False
    niacinamide_spf: bool = False
    moisturizer: bool = False
    vitamin_c: bool = False
    benzoyl_peroxide: bool = False
    note: Optional[str] = None


class SkincareLogCreate(CamelModel):
    date: str
    retinoid: bool = False
    azelaic: bool = False
    peel: bool = False
    niacinamide_spf: bool = False
    moisturizer: bool = False
    vitamin_c: bool = False
    benzoyl_peroxide: bool = False
    note: Optional[str] = None
    override: bool = False


class SkincareObservationItem(CamelModel):
    id: int
    date: str
    inflammation: Optional[int] = None
    inf: Optional[int] = None
    pih: Optional[int] = None
    zone: Optional[str] = None
    note: Optional[str] = None


class SkincareObservationCreate(CamelModel):
    date: str
    inflammation: Optional[int] = None
    pih: Optional[int] = None
    zone: Optional[str] = None
    note: Optional[str] = None


class SkincareObservationCreated(BaseModel):
    id: int


class SkincareRuleItem(CamelModel):
    id: int
    code: Optional[str] = None
    severity: str
    sev: str
    kind: str
    msg: str
    hard: bool = False


class SkincareAlertItem(CamelModel):
    id: int
    domain: str
    severity: str
    alert_key: str
    message: str
    created_at: Optional[str] = None


class SkincareView(CamelModel):
    products: list[SkincareProductItem] = []
    active_count: int = 0
    total_count: int = 0
    today_log: Optional[SkincareLogItem] = None
    logs: list[SkincareLogItem] = []
    observations: list[SkincareObservationItem] = []
    rules: list[SkincareRuleItem] = []
    alerts: list[SkincareAlertItem] = []
    today: str
