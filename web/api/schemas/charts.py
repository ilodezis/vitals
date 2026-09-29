"""Pydantic schemas for the Charts API (/api/v1/charts)."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class ChartPoint(CamelModel):
    date: str
    value: float


class ChartResolvedSeries(CamelModel):
    label: str
    unit: Optional[str] = None
    color_slot: int = 0
    points: list[ChartPoint] = []


class ChartOverlay(CamelModel):
    start: str
    end: Optional[str] = None
    label: str
    tone: str = ""
    kind: str = ""


class CustomChartItem(CamelModel):
    id: str
    name: str
    normalize: bool = False
    series: list[ChartResolvedSeries] = []
    overlays: list[ChartOverlay] = []


class ChartsView(CamelModel):
    charts: list[CustomChartItem] = []
    catalog: dict[str, Any] = {}
    count: int = 0
    empty: bool = True


class ChartSeriesInput(CamelModel):
    domain: str
    metric_key: str
    param: Optional[str] = None
    label: Optional[str] = None


class ChartCreateRequest(CamelModel):
    name: str
    series: list[ChartSeriesInput] = []
    normalize: bool = False


class ChartCreated(BaseModel):
    id: str
