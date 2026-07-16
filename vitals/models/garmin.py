"""Module 6 — Garmin activity & recovery.

Two tables, both ``domain='garmin'`` via ``InsightsMixin``:

  * ``garmin_daily`` — one wide row per calendar date holding the day's recovery
    and activity metrics (sleep, HRV, RHR, stress, Body Battery, steps, calories,
    HR, intensity minutes, training readiness, …). Every column is nullable — a
    given day may only have some metrics — and the full upstream JSON lives in
    ``raw_payloads`` so nothing is lost (maximal-parsing principle). One row per
    date regardless of source (``garmin_api`` or the ``health_auto_export`` backup
    channel), upserted by date.
  * ``garmin_activities`` — recorded sport sessions, keyed by Garmin's activity id
    (the upsert key), for correlation with Hevy workouts.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from vitals.enums import Domain
from vitals.models.base import Base, TimestampMixin
from vitals.models.mixins import InsightsMixin, insights_index

DOMAIN = Domain.GARMIN.value


class GarminDaily(Base, InsightsMixin, TimestampMixin):
    """The day's Garmin recovery + activity snapshot (one row per date)."""

    __tablename__ = "garmin_daily"
    __table_args__ = (
        insights_index(__tablename__),
        # One daily row per date; a re-sync (or the HAE backup) upserts it.
        UniqueConstraint("date", name="uq_garmin_daily_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    raw_payload_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("raw_payloads.id", ondelete="SET NULL"), nullable=True
    )

    # ── Sleep ───────────────────────────────────────────────────────────────────
    sleep_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sleep_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    deep_sleep_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    light_sleep_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rem_sleep_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    awake_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sleep_start: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    sleep_end: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    awake_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    restless_moments: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    avg_sleep_stress: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    avg_sleep_hr: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    spo2_lowest: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    respiration_lowest: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    respiration_highest: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    body_battery_change: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    breathing_disruption: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    sleep_need_actual: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # ── Heart / HRV / respiration ───────────────────────────────────────────────
    resting_hr: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    avg_hr: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_hr: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    min_hr: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    hrv_avg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hrv_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    avg_respiration: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    spo2_avg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # ── Stress / Body Battery ───────────────────────────────────────────────────
    avg_stress: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_stress: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    body_battery_high: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    body_battery_low: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # ── Activity / energy ───────────────────────────────────────────────────────
    steps: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    floors_climbed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    active_calories: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bmr_calories: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_calories: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    intensity_minutes_moderate: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    intensity_minutes_vigorous: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # ── Training ────────────────────────────────────────────────────────────────
    training_readiness: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    vo2max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class GarminActivity(Base, InsightsMixin, TimestampMixin):
    """A recorded sport activity (run, ride, strength, …)."""

    __tablename__ = "garmin_activities"
    __table_args__ = (
        insights_index(__tablename__),
        UniqueConstraint("external_id", name="uq_garmin_activities_external_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_payload_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("raw_payloads.id", ondelete="SET NULL"), nullable=True
    )
    activity_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    start_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    distance_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    calories: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    avg_hr: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_hr: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
