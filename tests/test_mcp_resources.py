"""MCP resources + canonical prompt (A13): vitals://profile,
vitals://digest/latest, and the weekly_review prompt."""
from __future__ import annotations

from datetime import date

import pytest

mcp_router = pytest.importorskip("web.routers.mcp")


@pytest.fixture(autouse=True)
def _use_test_factory(session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)


async def test_profile_resource_returns_profile():
    prof = await mcp_router.profile_resource()
    assert "height_cm" in prof
    assert "goals" in prof


async def test_latest_digest_resource_empty_then_populated(db_session):
    assert await mcp_router.latest_digest_resource() == {"error": "No digests yet"}

    from vitals.models import WeeklyDigest
    from vitals.enums import Domain, Source

    db_session.add(
        WeeklyDigest(
            date=date(2026, 7, 5),
            domain=Domain.MILESTONES.value,
            source=Source.MANUAL.value,
            content="Weekly narrative.",
            model="test-model",
        )
    )
    await db_session.commit()

    latest = await mcp_router.latest_digest_resource()
    assert latest["date"] == "2026-07-05"
    assert latest["content"] == "Weekly narrative."


async def test_weekly_review_prompt():
    text = await mcp_router.weekly_review()
    assert isinstance(text, str)
    assert "get_full_snapshot" in text
