"""``/api/v1/alerts`` — Active system alerts lifecycle endpoints."""
from __future__ import annotations

from typing import Optional

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.services import alerts_service
from web.api.errors import ApiRouter
from web.api.schemas.alerts import AlertsListView, SystemAlertItem
from web.deps import get_session, require_auth

router = ApiRouter(prefix="/alerts", dependencies=[Depends(require_auth)])


@router.get("", response_model=AlertsListView)
async def read_alerts(
    domain: Optional[str] = None,
    db: AsyncSession = Depends(get_session),
) -> AlertsListView:
    """List active system alerts, optionally filtered by domain."""
    rows = await alerts_service.list_active(db, domain=domain)
    items = [
        SystemAlertItem(
            id=a.id,
            domain=a.domain,
            severity=a.severity,
            alert_key=a.alert_key,
            entity_ref=a.entity_ref,
            message=a.message,
            created_at=a.created_at.isoformat() if a.created_at else None,
            resolved_at=a.resolved_at.isoformat() if a.resolved_at else None,
        )
        for a in rows
    ]
    return AlertsListView(alerts=items, count=len(items))


@router.post("/{alert_id}/resolve")
async def resolve_alert(
    alert_id: int,
    db: AsyncSession = Depends(get_session),
):
    """Mark an alert resolved."""
    await alerts_service.resolve_alert(db, alert_id)
    await db.commit()
    return {"ok": True, "id": alert_id}


@router.post("/{alert_id}/override")
async def override_alert(
    alert_id: int,
    db: AsyncSession = Depends(get_session),
):
    """Mark a block alert overridden."""
    await alerts_service.override_alert(db, alert_id)
    await db.commit()
    return {"ok": True, "id": alert_id}


@router.post("/resolve-all")
async def resolve_all_alerts(
    domain: Optional[str] = None,
    db: AsyncSession = Depends(get_session),
):
    """Mark all active alerts resolved, optionally by domain."""
    await alerts_service.resolve_all(db, domain=domain)
    await db.commit()
    return {"ok": True}
