"""Pydantic schemas for the HRT API (/api/v1/hrt)."""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class HrtCyclePlanItem(CamelModel):
    id: int
    compound_key: str
    name: str
    dose: float
    unit: str
    every: Optional[float] = None
    from_: int = Field(alias="from")
    duration_days: Optional[int] = None
    # False for a ramp or a multi-segment schedule: only its start week is editable.
    flat: bool = True
    note: Optional[str] = None


class HrtActiveCycle(CamelModel):
    id: int
    kind: str
    name: str
    start: str
    end: Optional[str] = None
    note: Optional[str] = None
    cadence: int
    week: Optional[int] = None
    weeks: Optional[int] = None
    pct: Optional[int] = None
    items: list[HrtCyclePlanItem]


class HrtDoseItem(CamelModel):
    id: int
    date: str
    name: str
    compound_key: str
    dose: str
    dose_val: float
    unit: str
    ml: Optional[float] = None
    conc_mg_ml: Optional[float] = None
    brand: Optional[str] = None
    lab: Optional[str] = None
    batch: Optional[str] = None
    site: Optional[str] = None
    note: Optional[str] = None


class HrtSideEffectItem(CamelModel):
    id: int
    date: str
    name: str
    sev: int
    note: Optional[str] = None


class HrtTemplateItem(CamelModel):
    id: int
    name: str
    kind: str
    items: list[Any]
    export_json: str


class HrtPlannedItem(CamelModel):
    date: str
    name: str
    compound_key: str = ""
    dose: str
    dose_val: Optional[float] = None
    unit: str = "mg"


class HrtReleasePoint(CamelModel):
    date: str
    total_mg: float


class HrtCompoundItem(CamelModel):
    id: int
    key: str
    name: str
    compound_class: Optional[str] = None
    ester: Optional[str] = None
    route: Optional[str] = None
    dose_unit: Optional[str] = None
    conc_mg_ml: Optional[float] = None


class HrtLastDose(CamelModel):
    date: str
    name: str
    dose: str


class HrtView(CamelModel):
    cycle: Optional[HrtActiveCycle] = None
    doses: list[HrtDoseItem]
    side_effects: list[HrtSideEffectItem]
    templates: list[HrtTemplateItem]
    planned: list[HrtPlannedItem]
    release: list[dict[str, Any]]
    catalog: int
    compounds: list[HrtCompoundItem]
    site_labels: dict[str, str]
    site_counts: dict[str, int]
    last: Optional[HrtLastDose] = None
    # What the forms may choose from: the dose units and the cycle kinds the service accepts.
    units: list[str] = []
    cycle_kinds: list[str] = []


class HrtDoseCreate(CamelModel):
    date: dt.date
    compound_key: str
    dose: Optional[float] = None
    unit: Optional[str] = None
    volume_ml: Optional[float] = None
    concentration_mg_ml: Optional[float] = None
    brand: Optional[str] = None
    lab: Optional[str] = None
    batch: Optional[str] = None
    site: Optional[str] = None
    note: Optional[str] = None
    override: bool = False


class HrtDosePatch(CamelModel):
    date: Optional[dt.date] = None
    compound_key: Optional[str] = None
    dose: Optional[float] = None
    unit: Optional[str] = None
    volume_ml: Optional[float] = None
    concentration_mg_ml: Optional[float] = None
    brand: Optional[str] = None
    lab: Optional[str] = None
    batch: Optional[str] = None
    site: Optional[str] = None
    note: Optional[str] = None
    override: bool = False


class HrtDoseCreated(BaseModel):
    id: int


class HrtCycleCreate(CamelModel):
    kind: str
    start_date: dt.date
    name: Optional[str] = None
    end_date: Optional[dt.date] = None
    note: Optional[str] = None


class HrtCycleClose(CamelModel):
    end_date: Optional[dt.date] = None


class HrtCycleCreated(BaseModel):
    id: int


class HrtCycleItemCreate(CamelModel):
    compound_key: str
    dose: float
    interval_days: float
    duration_days: Optional[int] = None
    start_week: Optional[float] = None
    unit: Optional[str] = None
    note: Optional[str] = None


class HrtCycleItemPatch(CamelModel):
    dose: Optional[float] = None
    interval_days: Optional[float] = None
    duration_days: Optional[int] = None
    start_week: Optional[float] = None


class HrtCycleItemCreated(BaseModel):
    id: int


class HrtTemplateSave(CamelModel):
    name: str


class HrtTemplateCreateCycle(CamelModel):
    start_date: dt.date
    name: Optional[str] = None


class HrtTemplateImport(CamelModel):
    payload: str


class HrtSideEffectCreate(CamelModel):
    date: dt.date
    effect_type: str = Field(default=..., alias="effectType")
    severity: int
    note: Optional[str] = None


class HrtSideEffectCreated(BaseModel):
    id: int


class HrtReleaseResponse(BaseModel):
    series: list[dict[str, Any]]
    today: str
