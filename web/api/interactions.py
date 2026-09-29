"""``/api/v1/interactions`` — Conflict rules and interactions browser endpoints."""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.services import conflict_service
from web.api.errors import ApiRouter, not_found
from web.api.schemas.interactions import ConflictRuleItem, InteractionsView, RuleToggleRequest
from web.deps import get_session, require_auth

router = ApiRouter(prefix="/interactions", dependencies=[Depends(require_auth)])


@router.get("", response_model=InteractionsView)
async def read_interactions(
    domain: Optional[str] = None,
    severity: Optional[str] = None,
    db: AsyncSession = Depends(get_session),
) -> InteractionsView:
    """List conflict engine rules, active state, and firing alerts."""
    data = await conflict_service.collect(db, domain=domain, severity=severity)
    return InteractionsView.model_validate(data)


@router.post("/{rule_id}/toggle")
async def toggle_conflict_rule(
    rule_id: int,
    body: RuleToggleRequest,
    db: AsyncSession = Depends(get_session),
):
    """Toggle a conflict rule on or off."""
    row = await conflict_service.toggle_rule(db, rule_id, body.active)
    if row is None:
        return not_found()
    await db.commit()
    return {"ok": True, "id": row.id, "active": row.active}
