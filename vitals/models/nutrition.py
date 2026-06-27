"""Nutrition domain — meal logging with macro tracking.

Multiple entries per day (unlike weight). Each row records a single meal or snack
with optional KCAL / protein / fat / carbs. ``date`` (from ``InsightsMixin``) is
the calendar day; ``eaten_at`` is the wall-clock time within that day (nullable).
"""
from __future__ import annotations

from datetime import time as time_type
from typing import Optional

from sqlalchemy import CheckConstraint, Float, String, Text, Time
from sqlalchemy.orm import Mapped, mapped_column

from vitals.enums import Domain
from vitals.models.base import Base, TimestampMixin
from vitals.models.mixins import InsightsMixin, insights_index

DOMAIN = Domain.NUTRITION.value


class MealLog(Base, InsightsMixin, TimestampMixin):
    """A single meal / snack entry."""

    __tablename__ = "meal_logs"
    __table_args__ = (
        insights_index(__tablename__),
        CheckConstraint(
            "calories IS NULL OR calories >= 0",
            name="ck_meal_logs_calories_nonneg",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    eaten_at: Mapped[Optional[time_type]] = mapped_column(Time, nullable=True)
    calories: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    protein_g: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fat_g: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    carbs_g: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
