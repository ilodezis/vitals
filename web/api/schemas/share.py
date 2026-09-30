"""Pydantic schemas for the Share API (/api/v1/share)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class SharedReportItem(CamelModel):
    id: int
    token: str
    title: str
    preset: Optional[str] = None
    domains: list[str] = []
    period_start: str
    period_end: str
    expires_at: str
    created_at: Optional[str] = None
    revoked_at: Optional[str] = None
    opened_count: int = 0
    last_opened_at: Optional[str] = None
    state: str = "live"
    url: str
    has_snapshot: bool = False


class SharePresetSpec(CamelModel):
    domains: list[str] = []
    labs_flagged_only: bool = False


class ShareView(CamelModel):
    reports: list[SharedReportItem] = []
    available_domains: list[str] = []
    presets: dict[str, SharePresetSpec] = {}
    period_choices: list[int] = []
    expiry_choices: list[int] = []
    default_expiry: int = 14
    default_start: str
    default_end: str
    today: str


class CreateShareRequest(CamelModel):
    title: str
    preset: Optional[str] = None
    domains: list[str] = []
    period: str = "90"
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    expires_days: int = 14
    labs_flagged_only: bool = False
    note: Optional[str] = None


class CreatedShareResponse(CamelModel):
    id: int
    token: str
    password: str
    url: str
    expires_at: str
