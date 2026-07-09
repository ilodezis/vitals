"""Endpoints for module 10: goal cards (milestones) and the weekly AI digest."""
from __future__ import annotations

import logging
from datetime import date as date_type
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.config import load_config
from vitals.enums import Domain
from vitals.integrations.llm_client import LLMClient, LLMNotConfigured
from vitals.services import digest_service, milestones_service
from vitals.utils.timeutils import today_local
from web.deps import get_session, require_auth
from web.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])

# Domains a goal can relate to (for the create form select).
GOAL_DOMAINS = [
    Domain.WEIGHT.value, Domain.BODY_COMPOSITION.value, Domain.GLP1.value, Domain.WORKOUTS.value,
    Domain.GARMIN.value, Domain.LABS.value, Domain.SKINCARE.value,
]


@router.get("", response_class=HTMLResponse)
async def reports_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    """Goal cards + the latest weekly digest and its history."""
    cards = await milestones_service.dashboard_cards(db)
    latest = await digest_service.latest_digest(db)
    history = await digest_service.list_digests(db, limit=12)

    return templates.TemplateResponse(
        request,
        "reports/index.html",
        {
            "username": username,
            "cards": cards,
            "latest_digest": latest,
            "history": history,
            "goal_domains": GOAL_DOMAINS,
            "llm_configured": bool(load_config().openrouter_api_key),
            "today": today_local().isoformat(),
            "digest": request.query_params.get("digest"),
        },
    )


@router.post("/milestone")
async def create_milestone(
    request: Request,
    name: str = Form(...),
    domain: str = Form(Domain.WEIGHT.value),
    target_value: Optional[float] = Form(None),
    target_unit: Optional[str] = Form(None),
    deadline: Optional[str] = Form(None),
    note: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    await milestones_service.create_milestone(
        db,
        name=name.strip(),
        domain=domain,
        target_value=target_value,
        target_unit=target_unit,
        deadline=date_type.fromisoformat(deadline) if deadline else None,
        note=note,
    )
    await db.commit()
    return _redirect(request)


@router.post("/milestone/{milestone_id}/status")
async def set_milestone_status(
    request: Request,
    milestone_id: int,
    status_value: str = Form(..., alias="status"),
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    await milestones_service.set_status(db, milestone_id, status_value)
    await db.commit()
    return _redirect(request)


@router.post("/milestone/{milestone_id}/delete")
async def delete_milestone(
    request: Request,
    milestone_id: int,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    await milestones_service.delete_milestone(db, milestone_id)
    await db.commit()
    return _redirect(request)


@router.post("/digest")
async def generate_digest_now(
    request: Request,
    period_days: int = Form(7),
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    """Generate this week's digest on demand."""
    try:
        await digest_service.generate_digest(db, LLMClient(), period_days=period_days)
        await db.commit()
    except LLMNotConfigured:
        return _redirect(request, "?digest=not_configured")
    except Exception as e:  # noqa: BLE001 — surface generation failures softly
        logger.warning("Digest generation failed: %s", e)
        return _redirect(request, "?digest=error")
    return _redirect(request, "?digest=ok")


def _redirect(request: Request, suffix: str = "") -> RedirectResponse:
    url = f"/reports{suffix}"
    response = RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)
    if "hx-request" in request.headers:
        response.headers["HX-Redirect"] = url
    return response
