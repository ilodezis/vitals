"""``GET /api/v1/session`` — what the shell needs before it can draw anything."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class NavItem(BaseModel):
    """One section in the rail, in rail order. Its label is ``nav.<key>`` and its
    rubric's is ``masthead.rubric.<rubric>``; both live in the i18n dictionaries."""

    model_config = ConfigDict(from_attributes=True)

    key: str
    route: str
    rubric: str
    # Overrides the rubric's masthead eyebrow for this section; "" = use the rubric's.
    eyebrow: str


class NavSlot(BaseModel):
    """One of the three middle columns of the phone's bottom bar."""

    model_config = ConfigDict(from_attributes=True)

    key: str
    label_key: str
    icon: str
    route: str
    # Path prefixes that light this column up.
    routes: list[str]


class Nav(BaseModel):
    items: list[NavItem]
    bottom_slots: list[NavSlot]
    # Rubrics that got no bottom-bar column — the section list on the More screen.
    more_rubrics: list[str]
    # Path prefixes that light up the bar's More cell.
    more_routes: list[str]


class RailStat(BaseModel):
    """One row of the rail's status card, as values — the client phrases them.
    Only the fields of the row's own ``key`` are filled; the rest are null."""

    model_config = ConfigDict(from_attributes=True)

    key: Literal["weight", "recovery", "nutrition", "workouts"]
    tone: Literal["", "good", "bad", "warn"]
    weight_kg: Optional[float]
    # Change since a reading at least a week older; null before there is one.
    delta_kg: Optional[float]
    sleep_seconds: Optional[int]
    readiness: Optional[int]
    calories: Optional[float]
    # The daily ceiling, when one is set.
    calories_max: Optional[float]
    protein_g: Optional[float]
    # Days without data: the last session (workouts), or a source gone quiet
    # (recovery, with ``sleep_seconds`` null).
    days_since: Optional[int]


class SessionView(BaseModel):
    username: str
    lang: Literal["en", "ru"]
    # Every module key in the registry, on or off.
    enabled_modules: dict[str, bool]
    nav: Nav
    rail: list[RailStat]
