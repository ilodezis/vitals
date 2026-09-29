"""``/api/v1/nutrition`` — schemas for nutrition view, meals and macros."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from pydantic import BaseModel


class MealItem(BaseModel):
    id: int
    date: dt.date
    time: Optional[str] = None
    name: str
    calories: Optional[float] = None
    protein_g: Optional[float] = None
    fat_g: Optional[float] = None
    carbs_g: Optional[float] = None
    note: Optional[str] = None


class MacroTotals(BaseModel):
    calories: float
    protein_g: float
    fat_g: float
    carbs_g: float


class MacroSplit(BaseModel):
    protein_pct: float
    fat_pct: float
    carbs_pct: float


class NutritionGoals(BaseModel):
    calories_min: float
    calories_max: float
    protein_target_g: float
    fat_target_g: float
    carbs_target_g: float


class NutritionDayMini(BaseModel):
    date: dt.date
    calories: float
    protein_g: float
    meal_count: int


class NutritionView(BaseModel):
    date: dt.date
    today_date: dt.date
    is_today: bool
    prev_date: dt.date
    next_date: dt.date
    totals: MacroTotals
    goals: NutritionGoals
    calories_pct: float
    protein_pct: float
    macro_split: MacroSplit
    meals: list[MealItem] = []
    recent_days: list[NutritionDayMini] = []


class MealCreate(BaseModel):
    date: dt.date
    name: str
    time: Optional[str] = None
    calories: Optional[float] = None
    protein_g: Optional[float] = None
    fat_g: Optional[float] = None
    carbs_g: Optional[float] = None
    note: Optional[str] = None
    override: bool = False


class MealPatch(BaseModel):
    date: Optional[dt.date] = None
    name: Optional[str] = None
    time: Optional[str] = None
    calories: Optional[float] = None
    protein_g: Optional[float] = None
    fat_g: Optional[float] = None
    carbs_g: Optional[float] = None
    note: Optional[str] = None
    override: bool = False


class MealRef(BaseModel):
    id: int
