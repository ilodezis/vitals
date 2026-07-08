"""Timeline — cross-domain event feed + manual chart annotations (optional
module; the annotation *rows* it manages, plus derived events read from every
other domain, are the data behind the flags drawn on the weight chart and
custom charts)."""
from __future__ import annotations

from datetime import date as date_type
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import AnnotationKind, Domain
from vitals.services import timeline_service
from vitals.utils.timeutils import today_local
from web.deps import get_session, require_auth
from web.templating import templates

router = APIRouter(prefix="/timeline", tags=["timeline"])

# Domains the owner can tag an annotation to — global (every chart) first.
ANNOTATION_DOMAINS = [
    Domain.TIMELINE.value,
    Domain.WEIGHT.value,
    Domain.GLP1.value,
    Domain.GARMIN.value,
    Domain.WORKOUTS.value,
    Domain.LABS.value,
    Domain.NUTRITION.value,
    Domain.SKINCARE.value,
    Domain.SUPPLEMENTS.value,
    Domain.GENETICS.value,
    Domain.BODY_COMPOSITION.value,
]

ANNOTATION_KINDS = [k.value for k in AnnotationKind]


@router.get("", response_class=HTMLResponse)
async def timeline_feed(
    request: Request,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    events = await timeline_service.list_events(db)

    return templates.TemplateResponse(
        request,
        "timeline/index.html",
        {
            "username": username,
            "events": events,
            "manual_count": sum(1 for e in events if e.source == "manual"),
            "domains": ANNOTATION_DOMAINS,
            "kinds": ANNOTATION_KINDS,
            "today": today_local().isoformat(),
        },
    )


@router.post("")
async def create_annotation_entry(
    request: Request,
    title: str = Form(...),
    date: str = Form(...),
    end_date: Optional[str] = Form(None),
    kind: str = Form(AnnotationKind.NOTE.value),
    domain: str = Form(Domain.TIMELINE.value),
    note: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    on_date = date_type.fromisoformat(date)
    end = date_type.fromisoformat(end_date) if end_date else None

    await timeline_service.create_annotation(
        db,
        title=title.strip(),
        on_date=on_date,
        end_date=end,
        kind=kind,
        domain=domain,
        note=note,
    )
    await db.commit()

    if "hx-request" in request.headers:
        response = RedirectResponse(url="/timeline", status_code=status.HTTP_303_SEE_OTHER)
        response.headers["HX-Redirect"] = "/timeline"
        return response
    return RedirectResponse(url="/timeline", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{annotation_id}/delete")
async def delete_annotation_entry(
    request: Request,
    annotation_id: int,
    db: AsyncSession = Depends(get_session),
    username: str = Depends(require_auth),
):
    await timeline_service.delete_annotation(db, annotation_id)
    await db.commit()

    if "hx-request" in request.headers:
        response = RedirectResponse(url="/timeline", status_code=status.HTTP_303_SEE_OTHER)
        response.headers["HX-Redirect"] = "/timeline"
        return response
    return RedirectResponse(url="/timeline", status_code=status.HTTP_303_SEE_OTHER)
