"""``/api/v1/workouts`` — schemas for the Hevy workouts view and sync."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from pydantic import BaseModel


class HevySetItem(BaseModel):
    set_index: int
    set_type: str
    weight_kg: Optional[float] = None
    reps: Optional[int] = None
    rpe: Optional[float] = None


class HevyExerciseItem(BaseModel):
    exercise_index: int
    title: str
    exercise_template_id: Optional[str] = None
    notes: Optional[str] = None
    sets: list[HevySetItem] = []


class HevyWorkoutItem(BaseModel):
    id: str
    date: dt.date
    title: str
    program: Optional[str] = None
    start_time: Optional[str] = None
    duration_min: Optional[int] = None
    working_sets: int = 0
    volume_kg: Optional[float] = None
    exercises: list[HevyExerciseItem] = []


class WorkingWeightPoint(BaseModel):
    date: dt.date
    weight_kg: float
    top_reps: Optional[int] = None
    sets: int = 0


class ExerciseCatalogItem(BaseModel):
    exercise_template_id: str
    title: str
    sessions_count: int
    last_date: Optional[dt.date] = None
    working_weight_series: list[WorkingWeightPoint] = []
    progression_verdict: Optional[str] = None
    latest_notes: Optional[str] = None


class WorkoutsView(BaseModel):
    workout_count: int
    last_workout_date: Optional[dt.date] = None
    exercise_count: int
    is_configured: bool
    last_sync: Optional[str] = None
    workouts: list[HevyWorkoutItem] = []
    catalog: list[ExerciseCatalogItem] = []


class HevySyncResponse(BaseModel):
    ok: bool
    synced: int = 0
    error: Optional[str] = None
