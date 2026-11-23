"""Meals and nutrition summaries."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from vitals.config import load_config
from vitals.enums import Source
from vitals.models import (
    MealLog,
)
from vitals.services.conflict_engine import ConflictBlocked
from vitals.utils.timeutils import today_local
from web.routers.mcp._core import (
    READ, WRITE, _conflict_payload, _merged, _parse_date, _parse_time, gated, get_session_factory, choice_error, dispatch, route, serialize_row, serialize_written, tool,
)

# ── Nutrition tools ──────────────────────────────────────────────────────────

@gated("nutrition")
async def log_meal(
    name: str,
    calories: Optional[float] = None,
    protein_g: Optional[float] = None,
    fat_g: Optional[float] = None,
    carbs_g: Optional[float] = None,
    eaten_at: Optional[str] = None,
    note: Optional[str] = None,
    on_date: Optional[str] = None,
    override: bool = False,
) -> dict:
    """Records a meal or snack with optional macros (KCAL, protein, fat, carbs).

    This is a WRITE tool — the meal is saved to the database immediately.
    Defaults: on_date = today, eaten_at = None (unspecified meal time). If a hard conflict rule
    blocks the save, returns ``{"blocked": true, "violations": [...]}`` instead
    of saving; call again with ``override=True`` to save anyway.
    """
    from vitals.services import nutrition_service

    session_factory = get_session_factory()
    parsed_date = _parse_date(on_date, today_local(), field="on_date")
    parsed_time = _parse_time(eaten_at, field="eaten_at")

    async with session_factory() as session:
        try:
            row = await nutrition_service.log_meal(
                session,
                on_date=parsed_date,
                name=name,
                eaten_at=parsed_time,
                calories=calories,
                protein_g=protein_g,
                fat_g=fat_g,
                carbs_g=carbs_g,
                note=note,
                source=Source.MCP.value,
                override=override,
            )
        except ConflictBlocked as e:
            return _conflict_payload(e)
        await session.commit()
        return await serialize_written(session, row)


async def get_nutrition_summary(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    """Returns a nutrition summary with total KCAL/protein/fat/carbs, meal counts,
    per-day breakdown, and goal tracking. Defaults to today if no dates given."""
    from vitals.services import nutrition_service

    cfg = load_config()
    session_factory = get_session_factory()
    today = today_local()

    start = _parse_date(start_date, today, field="start_date")
    end = _parse_date(end_date, today, field="end_date")

    if start == end:
        async with session_factory() as session:
            return await nutrition_service.daily_summary(session, start, cfg)
    else:
        async with session_factory() as session:
            return await nutrition_service.nutrition_summary(session, start, end, cfg)


# ── Meal CRUD tools ─────────────────────────────────────────────────────────
_MEAL_CLEARABLE = ("eaten_at", "calories", "protein_g", "fat_g", "carbs_g", "note")


@gated("nutrition")
async def update_meal(
    meal_id: int,
    name: Optional[str] = None,
    calories: Optional[float] = None,
    protein_g: Optional[float] = None,
    fat_g: Optional[float] = None,
    carbs_g: Optional[float] = None,
    eaten_at: Optional[str] = None,
    note: Optional[str] = None,
    on_date: Optional[str] = None,
    clear: Optional[list[str]] = None,
) -> dict:
    """Updates an existing meal by ID. Returns the updated meal or an error.

    Only the fields you pass are changed — anything left out keeps its stored
    value, including ``on_date``, which stays the meal's own date rather than
    moving the meal to today. To empty a field (an unknown macro, a wrong time,
    a note) name it in ``clear``: any of eaten_at, calories, protein_g, fat_g,
    carbs_g, note. WRITE tool — changes are saved immediately.
    """
    from vitals.services import nutrition_service

    session_factory = get_session_factory()
    parsed_date = _parse_date(on_date, field="on_date")
    parsed_time = _parse_time(eaten_at, field="eaten_at")

    async with session_factory() as session:
        merged = await _merged(
            session,
            MealLog,
            meal_id,
            date=parsed_date,
            name=name,
            eaten_at=parsed_time,
            calories=calories,
            protein_g=protein_g,
            fat_g=fat_g,
            carbs_g=carbs_g,
            note=note,
        )
        if merged is None:
            return {"error": f"Meal {meal_id} not found"}
        unknown = sorted(set(clear or []) - set(_MEAL_CLEARABLE))
        if unknown:
            return {"error": f"cannot clear {unknown} — clearable: {', '.join(_MEAL_CLEARABLE)}"}
        for field in clear or []:
            merged[field] = None
        row = await nutrition_service.update_meal(
            session, meal_id, on_date=merged.pop("date"), **merged
        )
        await session.commit()
        return await serialize_written(session, row)


async def search_meals(
    query: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """Searches meals by name substring and/or date range. Returns matching meals
    ordered by date descending."""
    session_factory = get_session_factory()
    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")

    async with session_factory() as session:
        stmt = select(MealLog)
        if query:
            stmt = stmt.where(MealLog.name.ilike(f"%{query}%"))
        if start:
            stmt = stmt.where(MealLog.date >= start)
        if end:
            stmt = stmt.where(MealLog.date <= end)
        stmt = stmt.order_by(MealLog.date.desc(), MealLog.eaten_at.desc().nulls_last())
        stmt = stmt.limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        return [serialize_row(r) for r in rows]


# ── Consolidated tools ───────────────────────────────────────────────────────
@tool(READ, module="nutrition")
async def get_nutrition(
    view: str = "summary",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    query: Optional[str] = None,
    limit: Optional[int] = None,
) -> dict:
    """Nutrition reads (dates YYYY-MM-DD).

    ``view="summary"`` (default): total kcal/protein/fat/carbs, meal counts, a
    per-day breakdown and tracking against the protein target and calorie
    corridor; defaults to today. ``view="meals"``: the meals themselves, newest
    first, filtered by a name substring ``query`` and/or the date range (``limit``
    default 50) — ids for ``save_meal`` edits."""
    if view == "summary":
        return await route(
            get_nutrition_summary, "get_nutrition(view='summary')",
            dict(start_date=start_date, end_date=end_date, query=query, limit=limit),
        )
    if view == "meals":
        rows = await route(
            search_meals, "get_nutrition(view='meals')",
            dict(start_date=start_date, end_date=end_date, query=query, limit=limit),
        )
        return rows if isinstance(rows, dict) else {"meals": rows}
    return choice_error("view", view, ("summary", "meals"))


_MEAL_ENTRIES = {
    ("meal", False): (log_meal, None),
    ("meal", True): (update_meal, "meal_id"),
}


@tool(WRITE, module="nutrition")
@gated("nutrition")
async def save_meal(
    record_id: Optional[int] = None,
    name: Optional[str] = None,
    calories: Optional[float] = None,
    protein_g: Optional[float] = None,
    fat_g: Optional[float] = None,
    carbs_g: Optional[float] = None,
    eaten_at: Optional[str] = None,
    on_date: Optional[str] = None,
    note: Optional[str] = None,
    clear: Optional[list[str]] = None,
    override: Optional[bool] = None,
) -> dict:
    """Records a meal or snack, or edits one. Without ``record_id``: a new entry
    — ``name`` plus optional macros (``calories`` kcal, ``protein_g``, ``fat_g``,
    ``carbs_g``), ``eaten_at`` HH:MM, ``on_date`` (default today), ``note``.
    With ``record_id`` (from ``get_nutrition(view="meals")``): changes only the
    fields passed; ``clear`` lists fields to empty (eaten_at, calories, protein_g,
    fat_g, carbs_g, note). A hard conflict block on a new meal returns
    ``{"blocked": true, ...}``; repeat with ``override=true`` only if the owner
    insists."""
    args = dict(
        name=name, calories=calories, protein_g=protein_g, fat_g=fat_g, carbs_g=carbs_g,
        eaten_at=eaten_at, on_date=on_date, note=note, clear=clear, override=override,
    )
    return await dispatch("save_meal", "entry", "meal", _MEAL_ENTRIES, args, record_id)
