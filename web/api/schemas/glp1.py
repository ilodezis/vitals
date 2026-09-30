"""Pydantic schemas for the GLP-1 API (/api/v1/glp1)."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class Glp1Injection(CamelModel):
    id: Optional[int] = None
    date_iso: str
    site: Optional[str] = None
    dose_mg: float
    drug: Optional[str] = None
    note: Optional[str] = None


class Glp1CycleInfo(CamelModel):
    last_iso: Optional[str] = None
    # Both are ``None`` until the first injection: there is no cycle to count yet.
    next_iso: Optional[str] = None
    days_to_next: Optional[int] = None
    overdue: bool = False
    unscheduled: bool = False


class Glp1DosePhase(CamelModel):
    id: Optional[int] = None
    from_iso: str
    to_iso: str
    dose_mg: float
    drug: Optional[str] = None
    note: Optional[str] = None


class Glp1TrendPoint(CamelModel):
    date: str
    kg: float


class Glp1SideEffect(CamelModel):
    id: Optional[int] = None
    date_iso: str
    name: str
    severity: int
    note: Optional[str] = None


class Glp1View(CamelModel):
    # ``None`` before anything is logged; the screen shows a dash, not a default.
    drug: Optional[str] = None
    dose_mg: Optional[float] = None
    since_iso: Optional[str] = None
    day_on_dose: Optional[int] = None
    delta_on_dose_kg: Optional[float] = None
    cycle: Glp1CycleInfo
    dose_phases: list[Glp1DosePhase]
    trend: list[Glp1TrendPoint]
    site_labels: dict[str, str]
    injections: list[Glp1Injection]
    side_effects: list[Glp1SideEffect]


class Glp1InjectionCreate(CamelModel):
    date: dt.date
    dose_mg: float = Field(default=..., alias="doseMg")
    drug: Optional[str] = None
    site: Optional[str] = None
    note: Optional[str] = None
    override: bool = False


class Glp1InjectionCreated(BaseModel):
    id: int


class Glp1CycleCreate(CamelModel):
    start_date: Optional[dt.date] = None
    drug: Optional[str] = None
    dose_mg: Optional[float] = None
    end_date: Optional[dt.date] = None
    note: Optional[str] = None
    action: Optional[str] = None
    cycle_id: Optional[int] = None


class Glp1CycleResponse(BaseModel):
    id: Optional[int] = None
    ok: bool = True


class Glp1SideEffectCreate(CamelModel):
    date: dt.date
    effect_type: str = Field(default=..., alias="effectType")
    severity: int
    note: Optional[str] = None


class Glp1SideEffectCreated(BaseModel):
    id: int
