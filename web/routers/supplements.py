"""Endpoints for the supplements catalog (reference, no daily logging)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import Domain, Evidence
from vitals.services import alerts_service, supplements_service
from vitals.services.conflict_engine import ConflictBlocked
from web.deps import get_session, require_auth
from web.templating import templates

router = APIRouter(prefix="/supplements", tags=["supplements"])


def _redirect(request: Request) -> RedirectResponse:
    response = RedirectResponse(url="/supplements", status_code=status.HTTP_303_SEE_OTHER)
    if "hx-request" in request.headers:
        response.headers["HX-Redirect"] = "/supplements"
    return response


@router.get("", response_class=HTMLResponse)
async def supplements_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    supplements = await supplements_service.list_supplements(db)
    alerts = await alerts_service.list_active(db, domain=Domain.SUPPLEMENTS.value)
    return templates.TemplateResponse(
        request,
        "supplements/index.html",
        {
            "username": username,
            "supplements": supplements,
            "alerts": alerts,
            "evidence_tiers": [e.value for e in Evidence],
        },
    )


@router.post("/save")
async def save_supplement(
    request: Request,
    id: Optional[int] = Form(None),
    name: str = Form(...),
    dose: Optional[str] = Form(None),
    timing: Optional[str] = Form(None),
    evidence: Optional[str] = Form(None),
    active: bool = Form(False),
    contraindications: Optional[str] = Form(None),
    note: Optional[str] = Form(None),
    override: bool = Form(False),
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    try:
        if id is not None:
            await supplements_service.update_supplement(
                db,
                id,
                name=name,
                dose=dose,
                timing=timing,
                evidence=evidence or None,
                active=active,
                contraindications=contraindications,
                note=note,
                override=override,
            )
        else:
            await supplements_service.add_supplement(
                db,
                name=name,
                dose=dose,
                timing=timing,
                evidence=evidence or None,
                active=active,
                contraindications=contraindications,
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


@router.post("/{id}/toggle")
async def toggle_supplement(
    request: Request,
    id: int,
    active: bool = Form(...),
    override: bool = Form(False),
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    try:
        await supplements_service.set_active(db, id, active, override=override)
        await db.commit()
    except ConflictBlocked as e:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"violations": [v.to_dict() for v in e.violations]},
        )
    return _redirect(request)


@router.post("/{id}/delete")
async def delete_supplement(
    request: Request,
    id: int,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    await supplements_service.delete_supplement(db, id)
    await db.commit()
    return _redirect(request)
