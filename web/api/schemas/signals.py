"""Pydantic schemas for the Signals API (/api/v1/signals)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class SignalItem(CamelModel):
    id: int
    date: str
    time: Optional[str] = None
    kind: str
    key: str
    raw_key: str
    value: Optional[float] = None
    unit: Optional[str] = None
    note: Optional[str] = None
    misparse: bool = False
    batch_id: Optional[str] = None


class KeyFrequencyItem(CamelModel):
    key: str
    count: int
    n: int
    variants: list[str] = []
    alias: list[str] = []
    examples: list[str] = []
    ex: list[str] = []


class SignalsView(CamelModel):
    signals: list[SignalItem] = []
    frequency: list[KeyFrequencyItem] = []
    kinds: list[str] = []
    misparse_count: int = 0
    total_count: int = 0
    keys_count: int = 0
