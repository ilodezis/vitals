"""Pydantic schemas for the Labs API (/api/v1/labs)."""
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


class LabHistoryPoint(CamelModel):
    date_iso: str
    value: float


class LabMarker(CamelModel):
    id: str
    name: str
    group_key: str
    group: str
    unit: str
    value: float
    lo: float
    hi: float
    min: float
    max: float
    decimals: int
    history: list[LabHistoryPoint]


class LabsView(CamelModel):
    collected_iso: str
    lab: str
    source: str
    markers: list[LabMarker]


class LabExtractedMarker(CamelModel):
    marker: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    ref_low: Optional[float] = None
    ref_high: Optional[float] = None


class LabExtractedPreview(CamelModel):
    date: str
    lab_name: Optional[str] = None
    file_key: Optional[str] = None
    raw_payload_id: Optional[int] = None
    markers: list[LabExtractedMarker] = []


class LabUploadResponse(CamelModel):
    ok: bool
    reason: Optional[str] = None
    message: Optional[str] = None
    lab: Optional[LabExtractedPreview] = None


class LabConfirm(CamelModel):
    date: str
    lab_name: Optional[str] = None
    file_key: Optional[str] = None
    raw_payload_id: Optional[int] = None
    markers: list[LabExtractedMarker] = []
    override: bool = False


class LabConfirmResponse(CamelModel):
    ok: bool
    created: int


class LabResultCreate(CamelModel):
    date: dt.date
    marker: str
    value: float
    unit: Optional[str] = None
    ref_low: Optional[float] = None
    ref_high: Optional[float] = None
    lab_name: Optional[str] = None
    note: Optional[str] = None
    override: bool = False


class LabResultCreated(BaseModel):
    id: int


class LabMarkerDetail(CamelModel):
    id: str
    name: str
    unit: Optional[str] = None
    ref_low: Optional[float] = None
    ref_high: Optional[float] = None
    category: Optional[str] = None
    tier: int = 2
    defer_until: Optional[str] = None
    history: list[dict[str, Any]]


class LabMarkerDefer(CamelModel):
    until: dt.date
    note: Optional[str] = None


class LabMarkerPatch(CamelModel):
    category: Optional[str] = None
    tier: Optional[int] = None
    retest_interval_days: Optional[int] = None
    ref_low: Optional[float] = None
    ref_high: Optional[float] = None
    note: Optional[str] = None


class LabMarkerResponse(CamelModel):
    id: int
    name: str
