"""MCP milestones tools (A3) — get/create/update/delete goal cards through the
MCP surface. Same import-skip guard as the other MCP tool tests."""
from __future__ import annotations

import pytest

mcp_router = pytest.importorskip("web.routers.mcp")


async def test_create_get_update_delete_milestone(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)

    created = await mcp_router.create_milestone(
        name="Reach 85 kg",
        domain="weight",
        target_value=85.0,
        target_unit="kg",
        deadline="2026-12-31",
    )
    assert created["id"] > 0
    assert created["status"] == "active"
    mid = created["id"]

    listed = await mcp_router.get_milestones()
    assert any(m["id"] == mid and m["name"] == "Reach 85 kg" for m in listed)
    # Progress payload carries the goal target + a days_left field for the deadline.
    card = next(m for m in listed if m["id"] == mid)
    assert card["target_value"] == 85.0
    assert "days_left" in card

    updated = await mcp_router.update_milestone(mid, status="achieved", note="done")
    assert updated["status"] == "achieved"
    assert updated["note"] == "done"

    # Status filter reflects the change.
    assert await mcp_router.get_milestones(status="active") == []
    assert len(await mcp_router.get_milestones(status="achieved")) == 1

    deleted = await mcp_router.delete_milestone(mid)
    assert deleted == {"deleted": True, "milestone_id": mid}
    assert await mcp_router.get_milestones() == []


async def test_update_milestone_rejects_bad_status(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    created = await mcp_router.create_milestone(name="Goal", domain="weight")

    result = await mcp_router.update_milestone(created["id"], status="not_a_status")
    assert "error" in result
    assert "Unknown status" in result["error"]


async def test_update_milestone_not_found(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    result = await mcp_router.update_milestone(9999, name="x")
    assert result == {"error": "Milestone 9999 not found"}
