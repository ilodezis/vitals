"""Reports service — milestones/goals, AI digests, and daily briefs."""
from __future__ import annotations

from datetime import date as date_type
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from vitals.config import load_config
from vitals.enums import DigestKind, Domain
from vitals.integrations.llm_client import LLMClient
from vitals.services import digest_service, milestones_service
from vitals.services.proactive import brief, delivery
from vitals.utils.timeutils import today_local

GOAL_DOMAINS = [
    Domain.WEIGHT.value,
    Domain.BODY_COMPOSITION.value,
    Domain.GLP1.value,
    Domain.WORKOUTS.value,
    Domain.GARMIN.value,
    Domain.LABS.value,
    Domain.SKINCARE.value,
]


def _format_digest(d) -> Optional[dict[str, Any]]:
    if d is None:
        return None
    ctx = d.context_json or {}
    period = ctx.get("period") or {}
    start = period.get("start")
    end = period.get("end")
    return {
        "id": d.id,
        "date": d.date.isoformat() if d.date else None,
        "kind": d.kind,
        "content": d.content,
        "model": d.model,
        "period_start": start,
        "period_end": end,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


async def collect(session: AsyncSession) -> dict[str, Any]:
    """Collect everything needed by the Reports dashboard in one round-trip."""
    cards = await milestones_service.dashboard_cards(session)
    latest_dig = await digest_service.latest_digest(session, kind=DigestKind.WEEKLY.value)
    history = await digest_service.list_digests(
        session, kind=DigestKind.WEEKLY.value, limit=12
    )
    latest_brf = await digest_service.latest_digest(
        session, kind=DigestKind.DAILY_BRIEF.value
    )
    config = load_config()

    active_goals = [c for c in cards if c.get("status") == "active"]
    closed_goals = [c for c in cards if c.get("status") != "active"]

    return {
        "active_goals": active_goals,
        "closed_goals": closed_goals,
        "active_goals_count": len(active_goals),
        "closed_goals_count": len(closed_goals),
        "latest_digest": _format_digest(latest_dig),
        "digest_history": [_format_digest(h) for h in history],
        "digests_count": len(history),
        "latest_brief": _format_digest(latest_brf),
        "goal_domains": GOAL_DOMAINS,
        "llm_configured": bool(config.openrouter_api_key),
        "channel_configured": bool(
            config.telegram_bot_token and config.telegram_chat_id
        ),
        "today": today_local().isoformat(),
    }


async def generate_digest(
    session: AsyncSession, *, period_days: int = 7
) -> dict[str, Any]:
    """Generate a weekly digest on demand."""
    row = await digest_service.generate_digest(
        session, LLMClient(), period_days=period_days
    )
    await session.commit()
    return _format_digest(row) or {}


async def build_brief(session: AsyncSession) -> Optional[dict[str, Any]]:
    """Assemble today's morning brief on demand."""
    row = await brief.generate_brief(session, LLMClient())
    await session.commit()
    return _format_digest(row)


async def send_test_brief(session: AsyncSession, notifier) -> Optional[dict[str, Any]]:
    """Generate today's brief and send it via Telegram."""
    if notifier is None:
        raise ValueError("telegram_bot_not_configured")
    row = await brief.generate_brief(session, LLMClient())
    if row is None:
        await session.commit()
        return None
    sent = await delivery.send(
        session,
        notifier,
        text=row.content,
        category=delivery.CATEGORY_TEST,
        dedupe_key=f"brief_test:{today_local().isoformat()}",
    )
    await session.commit()
    return {"sent": sent is not None, "brief": _format_digest(row)}
