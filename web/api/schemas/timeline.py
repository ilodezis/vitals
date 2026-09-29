"""Pydantic schemas for the Timeline API (/api/v1/timeline)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class TimelineEventItem(CamelModel):
    id: Optional[int] = None
    date: str
    end_date: Optional[str] = None
    domain: str
    dom: str
    kind: str
    title: str
    detail: Optional[str] = None
    tone: str = ""
    source: str = "manual"
    manual: bool = False
    ref: str


class AnnotationCreate(CamelModel):
    title: str
    date: str
    end_date: Optional[str] = None
    kind: str = "note"
    domain: str = "timeline"
    note: Optional[str] = None


class AnnotationUpdate(CamelModel):
    title: Optional[str] = None
    date: Optional[str] = None
    end_date: Optional[str] = None
    kind: Optional[str] = None
    domain: Optional[str] = None
    note: Optional[str] = None


class AnnotationCreated(BaseModel):
    id: int


class TimelineView(CamelModel):
    events: list[TimelineEventItem] = []
    manual_count: int = 0
    total_count: int = 0
    domains: list[str] = []
    kinds: list[str] = []
    today: str
