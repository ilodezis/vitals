"""Module 5 — Hevy workouts.

Hevy's public REST API returns a tree: workout → exercises → sets. We mirror that
tree in three tables so nothing is flattened away (maximal data capture), while
the full upstream response is also kept in ``raw_payloads`` (re-parse safety net).

  * ``hevy_workouts``  — one row per logged session. Carries ``InsightsMixin``
    (``domain='workouts'``), the Hevy workout id as ``external_id`` (the upsert
    key), a link back to the raw payload, and the mapped training ``program``.
  * ``hevy_exercises`` — the exercises inside a workout, keyed by Hevy's stable
    ``exercise_template_id`` (what ties "the same lift" across sessions for the
    progression engine and the working-weight history chart).
  * ``hevy_sets``      — each set's weight / reps / RPE / distance / duration.

Only the workout is an independent dated "log" row; exercises and sets are its
structural children (FK + cascade), so they don't repeat the InsightsMixin trio —
the workout's ``date`` is the time axis a join reads through.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from vitals.enums import Domain
from vitals.models.base import Base, TimestampMixin
from vitals.models.mixins import InsightsMixin, insights_index

DOMAIN = Domain.WORKOUTS.value


class HevyWorkout(Base, InsightsMixin, TimestampMixin):
    """A single training session pulled from Hevy."""

    __tablename__ = "hevy_workouts"
    __table_args__ = (
        insights_index(__tablename__),
        # The Hevy workout id is globally unique and is our upsert key on re-sync.
        UniqueConstraint("external_id", name="uq_hevy_workouts_external_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Full upstream payload for this workout (re-parse safety net). Nullable so a
    # manually constructed test/backfill row can exist without one.
    raw_payload_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("raw_payloads.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    start_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Hevy's own last-modified stamp — lets a re-sync tell a changed workout from
    # an unchanged one without diffing the whole tree.
    hevy_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Mapped training program (e.g. "A" / "B") from template matching; null when
    # the session doesn't match a known program.
    program: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    exercises: Mapped[list["HevyExercise"]] = relationship(
        back_populates="workout",
        cascade="all, delete-orphan",
        order_by="HevyExercise.exercise_index",
    )


class HevyExercise(Base, TimestampMixin):
    """One exercise within a workout."""

    __tablename__ = "hevy_exercises"
    __table_args__ = (
        Index("ix_hevy_exercises_template", "exercise_template_id"),
        Index("ix_hevy_exercises_workout", "workout_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workout_id: Mapped[int] = mapped_column(
        ForeignKey("hevy_workouts.id", ondelete="CASCADE"), nullable=False
    )
    exercise_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    # Hevy's stable id for the movement — the key that links the same lift across
    # sessions (progression + working-weight history group by it).
    exercise_template_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    superset_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    workout: Mapped["HevyWorkout"] = relationship(back_populates="exercises")
    sets: Mapped[list["HevySet"]] = relationship(
        back_populates="exercise",
        cascade="all, delete-orphan",
        order_by="HevySet.set_index",
    )


class HevySet(Base, TimestampMixin):
    """A single set: weight / reps / RPE (plus distance/duration for cardio)."""

    __tablename__ = "hevy_sets"
    __table_args__ = (Index("ix_hevy_sets_exercise", "exercise_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    exercise_id: Mapped[int] = mapped_column(
        ForeignKey("hevy_exercises.id", ondelete="CASCADE"), nullable=False
    )
    set_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Hevy set type: normal | warmup | dropset | failure. Only "normal" working
    # sets feed the progression engine.
    set_type: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    weight_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reps: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rpe: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    distance_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    exercise: Mapped["HevyExercise"] = relationship(back_populates="sets")
