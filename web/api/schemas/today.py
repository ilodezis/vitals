"""``GET /api/v1/today`` — the screen the app opens on, as values.

Numbers are numbers and dates are ISO strings; the client phrases both in the
reader's language. The narrative is the one sentence that arrives ready to print
(the morning brief's prose, or the deterministic line that stands in for it), and
so are the messages of alerts, which are the rules' own words.
"""
from __future__ import annotations

import datetime as dt
from typing import Literal, Optional

from pydantic import BaseModel


class Corridor(BaseModel):
    """A band a value is read against."""

    lo: float
    hi: float


class SyncStamp(BaseModel):
    """An integration that last put something in the lake, and the day it did."""

    source: str
    date: dt.date


class TodayFigure(BaseModel):
    """One of the key figures. Only the fields of its own ``key`` are filled; the rest
    are null. ``value`` is null until there is a reading, and the row stays."""

    key: Literal["weight", "sleep_score", "hrv_avg", "body_battery_high", "calories"]
    value: Optional[float]
    # Weight: kg per week, from the regression the weight chart draws.
    trend: Optional[float]
    # Recovery: his own mean over the fortnight before today, and that mean ± one
    # standard deviation. Null until there are enough days to mean anything.
    # Calories: the daily goal (``lo`` to ``hi``) as the corridor; no baseline.
    baseline: Optional[float]
    corridor: Optional[Corridor]
    # Sleep: how long the night was.
    sleep_seconds: Optional[int]
    # Body Battery: what the night charged it by.
    gained: Optional[int]


class WeekChange(BaseModel):
    """A metric this week against last: the two seven-day values, on the corridor of
    his own norm where there is one."""

    key: Literal["weight", "sleep_score", "hrv_avg", "body_battery_high", "calories"]
    # The module the row belongs to; the row opens its screen.
    domain_key: Literal["weight", "garmin", "nutrition"]
    before: float
    after: float
    # The corridor; null for a metric with none (weight, calories).
    lo: Optional[float]
    hi: Optional[float]
    # Was it a change in the right direction: "good", "bad", or blank when it
    # carries no verdict.
    tone: Literal["", "good", "bad"]


class FeedRow(BaseModel):
    """One line of the day. ``text`` and ``detail`` are the owner's own words where
    ``kind`` is an event or a signal; for the rest the client writes them from
    ``kind`` and ``value``."""

    # "HH:MM" local, or blank when the row has no time of its own.
    time: str
    kind: Literal["event", "meal", "signal", "brief", "weight"]
    dot: Literal["good", "cool", "violet", "amber"]
    text: str
    detail: str
    # Meal: calories. Weight: kg.
    value: Optional[float]


class AttentionItem(BaseModel):
    severity: Literal["note", "info", "warn", "block"]
    message: str
    # The domain the finding is about, so the row can open it.
    domain: Optional[str]


class GoalForecast(BaseModel):
    """Where the present trend meets the goal."""

    date: dt.date
    # Days between that date and the deadline, positive when it is ahead of it;
    # null when the goal has no deadline.
    days_ahead: Optional[int]


class Goal(BaseModel):
    """The first active weight goal, with where he started."""

    name: str
    # The first weight ever logged; the bar is distance covered from here.
    start_kg: float
    current_kg: float
    target_kg: float
    pct: Optional[int] = None
    deadline: Optional[dt.date]
    forecast: Optional[GoalForecast]


class LatestWeight(BaseModel):
    kg: float
    # The day it was measured: not always today.
    date: dt.date


class TodayView(BaseModel):
    date: dt.date
    narrative: str
    narrative_source: Literal["digest", "computed"]
    sync: list[SyncStamp]
    figures: list[TodayFigure]
    changes: list[WeekChange]
    feed: list[FeedRow]
    attention: list[AttentionItem]
    goal: Optional[Goal]
    latest_weight: Optional[LatestWeight]
