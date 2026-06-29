"""Nutrition domain: meal logging with macro tracking."""
from __future__ import annotations

from datetime import date as date_type, time as time_type
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.config import load_config
from vitals.enums import Domain
from vitals.services import alerts_service, nutrition_service
from vitals.services.conflict_engine import ConflictBlocked
from vitals.utils.timeutils import today_local
from web.deps import get_session, require_auth
from web.templating import templates

router = APIRouter(prefix="/nutrition", tags=["nutrition"])


def _redirect(request: Request) -> RedirectResponse:
    response = RedirectResponse(url="/nutrition", status_code=status.HTTP_303_SEE_OTHER)
    if "hx-request" in request.headers:
        response.headers["HX-Redirect"] = "/nutrition"
    return response


@router.get("", response_class=HTMLResponse)
async def nutrition_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    cfg = load_config()
    today = today_local()
    meals_today = await nutrition_service.list_meals_for_date(db, today)
    summary = await nutrition_service.daily_summary(db, today, cfg)
    history = await nutrition_service.list_meals(db, start=None, end=None)
    alerts = await alerts_service.list_active(db, domain=Domain.NUTRITION.value)
    goals = nutrition_service.get_goals(cfg)

    return templates.TemplateResponse(
        request,
        "nutrition/index.html",
        {
            "username": username,
            "meals_today": meals_today,
            "summary": summary,
            "history": history,
            "alerts": alerts,
            "goals": goals,
            "today": today.isoformat(),
            "today_date": today,
        },
    )


@router.post("/meal")
async def add_meal(
    request: Request,
    id: Optional[int] = Form(None),
    date: str = Form(...),
    name: str = Form(...),
    eaten_at: Optional[str] = Form(None),
    calories: Optional[float] = Form(None),
    protein_g: Optional[float] = Form(None),
    fat_g: Optional[float] = Form(None),
    carbs_g: Optional[float] = Form(None),
    note: Optional[str] = Form(None),
    override: bool = Form(False),
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    on_date = date_type.fromisoformat(date)
    parsed_time = time_type.fromisoformat(eaten_at) if eaten_at and eaten_at.strip() else None
    try:
        if id is not None:
            await nutrition_service.update_meal(
                db, id,
                on_date=on_date,
                name=name,
                eaten_at=parsed_time,
                calories=calories,
                protein_g=protein_g,
                fat_g=fat_g,
                carbs_g=carbs_g,
                note=note,
            )
        else:
            await nutrition_service.log_meal(
                db,
                on_date=on_date,
                name=name,
                eaten_at=parsed_time,
                calories=calories,
                protein_g=protein_g,
                fat_g=fat_g,
                carbs_g=carbs_g,
                note=note,
                override=override,
            )
        await db.commit()
    except ConflictBlocked as e:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"violations": [v.to_dict() for v in e.violations]},
        )
    return _redirect(request)


@router.post("/meal/{id}/delete")
async def delete_meal(
    request: Request,
    id: int,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    await nutrition_service.delete_meal(db, id)
    await db.commit()
    return _redirect(request)
