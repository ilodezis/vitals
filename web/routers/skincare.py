"""Endpoints for skincare daily checklist + observations."""
from __future__ import annotations

from datetime import date as date_type
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import Domain
from vitals.models.conflict_rule import ConflictRule
from vitals.services import alerts_service, skincare_service
from vitals.services.conflict_engine import ConflictBlocked
from vitals.utils.timeutils import today_local
from web.deps import get_session, require_auth
from web.templating import templates

router = APIRouter(prefix="/skincare", tags=["skincare"])


def _redirect(request: Request) -> RedirectResponse:
    response = RedirectResponse(url="/skincare", status_code=status.HTTP_303_SEE_OTHER)
    if "hx-request" in request.headers:
        response.headers["HX-Redirect"] = "/skincare"
    return response


@router.get("", response_class=HTMLResponse)
async def skincare_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    logs = await skincare_service.list_logs(db)
    observations = await skincare_service.list_observations(db)
    alerts = await alerts_service.list_active(db, domain=Domain.SKINCARE.value)
    today_log = await skincare_service.get_log(db, today_local())
    
    # Load products dynamically
    products = await skincare_service.list_products(db)
    
    # Load active skincare rules
    rules_stmt = select(ConflictRule).where(
        ConflictRule.active == True,
        or_(ConflictRule.domain_a == "skincare", ConflictRule.domain_b == "skincare")
    )
    rules_result = await db.execute(rules_stmt)
    conflict_rules = rules_result.scalars().all()
    
    return templates.TemplateResponse(
        request,
        "skincare/index.html",
        {
            "username": username,
            "logs": logs,
            "observations": observations,
            "alerts": alerts,
            "today_log": today_log,
            "today": today_local().isoformat(),
            "products": products,
            "conflict_rules": conflict_rules,
        },
    )


@router.post("/log")
async def save_log(
    request: Request,
    date: str = Form(...),
    retinoid: bool = Form(False),
    azelaic: bool = Form(False),
    peel: bool = Form(False),
    niacinamide_spf: bool = Form(False),
    moisturizer: bool = Form(False),
    vitamin_c: bool = Form(False),
    benzoyl_peroxide: bool = Form(False),
    note: Optional[str] = Form(None),
    override: bool = Form(False),
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    on_date = date_type.fromisoformat(date)
    try:
        await skincare_service.upsert_log(
            db,
            on_date=on_date,
            retinoid=retinoid,
            azelaic=azelaic,
            peel=peel,
            niacinamide_spf=niacinamide_spf,
            moisturizer=moisturizer,
            vitamin_c=vitamin_c,
            benzoyl_peroxide=benzoyl_peroxide,
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


@router.post("/observation")
async def save_observation(
    request: Request,
    date: str = Form(...),
    inflammation: Optional[int] = Form(None),
    pih: Optional[int] = Form(None),
    zone: Optional[str] = Form(None),
    note: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    on_date = date_type.fromisoformat(date)
    await skincare_service.add_observation(
        db, on_date=on_date, inflammation=inflammation, pih=pih, zone=zone, note=note
    )
    await db.commit()
    return _redirect(request)


@router.post("/log/{id}/delete")
async def delete_log(
    request: Request,
    id: int,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    await skincare_service.delete_log(db, id)
    await db.commit()
    return _redirect(request)


@router.post("/observation/{id}/delete")
async def delete_observation(
    request: Request,
    id: int,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    await skincare_service.delete_observation(db, id)
    await db.commit()
    return _redirect(request)


@router.post("/product/save")
async def save_product(
    request: Request,
    id: Optional[int] = Form(None),
    name: str = Form(...),
    type: str = Form(...),
    active_ingredient: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    usage_instructions: Optional[str] = Form(None),
    default_time: str = Form("evening"),
    schedule_days: list[str] = Form([]),
    active: bool = Form(False),
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    days = [int(x) for x in schedule_days if x.isdigit()]
    if id is not None:
        await skincare_service.update_product(
            db,
            id,
            name=name,
            type=type,
            active_ingredient=active_ingredient or None,
            description=description or None,
            usage_instructions=usage_instructions or None,
            default_time=default_time,
            schedule_days=days,
            active=active,
        )
    else:
        await skincare_service.add_product(
            db,
            name=name,
            type=type,
            active_ingredient=active_ingredient or None,
            description=description or None,
            usage_instructions=usage_instructions or None,
            default_time=default_time,
            schedule_days=days,
            active=active,
        )
    await db.commit()
    return _redirect(request)


@router.post("/product/{id}/delete")
async def delete_product(
    request: Request,
    id: int,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    await skincare_service.delete_product(db, id)
    await db.commit()
    return _redirect(request)
