"""MCP resources and prompts."""
from __future__ import annotations



from web.routers.mcp.profile import get_user_profile
from web.routers.mcp._core import (
    get_session_factory, mcp,
)

# ── Resources & prompts ───────────────────────────────────────────────────────
@mcp.resource("vitals://profile")
async def profile_resource() -> dict:
    """The user's physical profile, goals, and program — attachable as lightweight
    context without spending a tool call."""
    return await get_user_profile()


@mcp.resource("vitals://digest/latest")
async def latest_digest_resource() -> dict:
    """The most recent weekly AI digest (narrative + date) for conversation
    continuity."""
    from vitals.services import digest_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        row = await digest_service.latest_digest(session)
        if row is None:
            return {"error": "No digests yet"}
        return {"date": row.date.isoformat(), "content": row.content, "model": row.model}


@mcp.prompt()
async def weekly_review() -> str:
    """A ready-made prompt that drives a full cross-domain weekly review."""
    return (
        "Review my last 7 days across every domain. First call get_full_snapshot "
        "for the aligned cross-domain picture (weight trend, GLP-1 state, recent "
        "labs, activity/recovery, workouts, nutrition, skincare, goals). Then pull "
        "get_trend for weight and any lab marker that looks off. Summarize what "
        "changed, call out cross-domain correlations (e.g. sleep vs training load, "
        "dose changes vs side effects), surface anything from get_alerts, and "
        "give at most three concrete, non-alarmist suggestions. This is decision "
        "support, not medical advice."
    )
