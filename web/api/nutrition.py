"""``/api/v1/nutrition`` — nutrition dashboard, macro tracking, meal logging (optional module)."""
from __future__ import annotations

import datetime as dt
import logging
from typing import Optional

from fastapi import Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.config import load_config
from vitals.models.nutrition import MealLog
from vitals.services import nutrition_service
from vitals.utils.timeutils import today_local
from web.api.errors import MUTATION_ERRORS, ApiRouter, not_found
from web.api.schemas.nutrition import (
    MacroSplit,
    MacroTotals,
    MealCreate,
    MealItem,
    MealPatch,
    MealRef,
    NutritionDayMini,
    NutritionGoals,
    NutritionView,
)
from web.deps import get_session, require_auth

logger = logging.getLogger(__name__)

router = ApiRouter(prefix="/nutrition", dependencies=[Depends(require_auth)])


@router.get("", response_model=NutritionView)
async def read_nutrition(
    date: Optional[dt.date] = None,
    db: AsyncSession = Depends(get_session),
) -> NutritionView:
    """The Nutrition screen: daily KBJU totals against goals, macro split, meals list,
    and 30-day mini bars."""
    cfg = load_config()
    today = today_local()
    selected_date = date or today

    day_meals = await nutrition_service.list_meals_for_date(db, selected_date)
    summary = await nutrition_service.daily_summary(db, selected_date, cfg)
    recent = await nutrition_service.nutrition_summary(
        db, today - dt.timedelta(days=29), today, cfg
    )
    goals_data = nutrition_service.get_goals(cfg)

    totals = summary.get("totals", {})
    cal = float(totals.get("calories", 0))
    prot = float(totals.get("protein_g", 0))
    fat = float(totals.get("fat_g", 0))
    carbs = float(totals.get("carbs_g", 0))

    cal_max = float(goals_data.get("calories_max", 2000))
    prot_target = float(goals_data.get("protein_target_g", 150))

    cal_pct = round(cal / cal_max * 100, 1) if cal_max else 0.0
    prot_pct = round(prot / prot_target * 100, 1) if prot_target else 0.0

    split = nutrition_service.macro_energy_shares(totals)

    meals_out = [
        MealItem(
            id=m.id,
            date=m.date,
            time=m.eaten_at.strftime("%H:%M") if m.eaten_at else None,
            name=m.name,
            calories=m.calories,
            protein_g=m.protein_g,
            fat_g=m.fat_g,
            carbs_g=m.carbs_g,
            note=m.note,
        )
        for m in day_meals
    ]

    recent_days = [
        NutritionDayMini(
            date=dt.date.fromisoformat(d["date"]),
            calories=float(d.get("calories", 0)),
            protein_g=float(d.get("protein_g", 0)),
            meal_count=int(d.get("meal_count", 0)),
        )
        for d in recent.get("per_day", [])
    ]

    return NutritionView(
        date=selected_date,
        today_date=today,
        is_today=selected_date == today,
        prev_date=selected_date - dt.timedelta(days=1),
        next_date=selected_date + dt.timedelta(days=1),
        totals=MacroTotals(calories=cal, protein_g=prot, fat_g=fat, carbs_g=carbs),
        goals=NutritionGoals(
            calories_min=float(goals_data.get("calories_min", 1800)),
            calories_max=cal_max,
            protein_target_g=prot_target,
            fat_target_g=float(goals_data.get("fat_target_g", 65)),
            carbs_target_g=float(goals_data.get("carbs_target_g", 200)),
        ),
        calories_pct=cal_pct,
        protein_pct=prot_pct,
        macro_split=MacroSplit(
            protein_pct=float(split.get("protein") or split.get("protein_pct", 0)),
            fat_pct=float(split.get("fat") or split.get("fat_pct", 0)),
            carbs_pct=float(split.get("carbs") or split.get("carbs_pct", 0)),
        ),
        meals=meals_out,
        recent_days=recent_days,
    )


@router.post(
    "/meals",
    status_code=status.HTTP_201_CREATED,
    response_model=MealRef,
    responses=MUTATION_ERRORS,
)
async def create_meal(
    body: MealCreate, db: AsyncSession = Depends(get_session)
) -> MealRef:
    """Log a meal."""
    parsed_time = None
    if body.time:
        try:
            parsed_time = dt.time.fromisoformat(body.time)
        except (ValueError, TypeError):
            pass

    meal = await nutrition_service.log_meal(
        db,
        on_date=body.date,
        name=body.name,
        eaten_at=parsed_time,
        calories=body.calories,
        protein_g=body.protein_g,
        fat_g=body.fat_g,
        carbs_g=body.carbs_g,
        note=body.note,
        override=body.override,
    )
    await db.commit()
    return MealRef(id=meal.id)


@router.patch("/meals/{meal_id}", response_model=MealRef, responses=MUTATION_ERRORS)
async def update_meal(
    meal_id: int, body: MealPatch, db: AsyncSession = Depends(get_session)
) -> MealRef:
    """Edit a logged meal."""
    row = await db.get(MealLog, meal_id)
    if row is None:
        return not_found()

    parsed_time = row.eaten_at
    if "time" in body.model_fields_set:
        if body.time:
            try:
                parsed_time = dt.time.fromisoformat(body.time)
            except (ValueError, TypeError):
                parsed_time = None
        else:
            parsed_time = None

    updated = await nutrition_service.update_meal(
        db,
        meal_id,
        on_date=body.date if body.date is not None else row.date,
        name=body.name if body.name is not None else row.name,
        eaten_at=parsed_time,
        calories=body.calories if "calories" in body.model_fields_set else row.calories,
        protein_g=body.protein_g if "protein_g" in body.model_fields_set else row.protein_g,
        fat_g=body.fat_g if "fat_g" in body.model_fields_set else row.fat_g,
        carbs_g=body.carbs_g if "carbs_g" in body.model_fields_set else row.carbs_g,
        note=body.note if "note" in body.model_fields_set else row.note,
    )
    if updated is None:
        return not_found()
    await db.commit()
    return MealRef(id=updated.id)


@router.delete("/meals/{meal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_meal(meal_id: int, db: AsyncSession = Depends(get_session)):
    """Delete a meal entry."""
    if not await nutrition_service.delete_meal(db, meal_id):
        return not_found()
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
