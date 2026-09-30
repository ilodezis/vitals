"""Pydantic schemas for the Alerts API (/api/v1/alerts)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class SystemAlertItem(CamelModel):
    id: int
    domain: str
    severity: str
    alert_key: str
    entity_ref: Optional[str] = None
    message: str
    created_at: Optional[str] = None
    resolved_at: Optional[str] = None
    # A block the owner saved past ("Save anyway"): still shown, marked as such.
    overridden: bool = False


class AlertsListView(CamelModel):
    alerts: list[SystemAlertItem] = []
    count: int = 0
