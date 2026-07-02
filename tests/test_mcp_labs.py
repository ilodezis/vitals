"""MCP labs tools — read/write/delete for lab results, plus notes wiring.
Skipped where FastMCP can't import (the read-only MCP tests share this
constraint); runs in the real environment / Postgres CI."""
from __future__ import annotations

import pytest

mcp_router = pytest.importorskip("web.routers.mcp")


async def test_log_get_delete_lab_result(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)

    res = await mcp_router.log_lab_result(
        marker="TSH",
        value=5.5,
        on_date="2026-06-10",
        unit="mIU/L",
        ref_low=0.4,
        ref_high=4.0,
        lab_name="Synevo",
    )
    assert "error" not in res
    assert res["marker"] == "TSH"
    assert res["flag"] == "high"
    assert res["lab_name"] == "Synevo"
    result_id = res["id"]

    # A different marker on a different date, so the filters have something to exclude.
    await mcp_router.log_lab_result(marker="Ferritin", value=95, on_date="2026-05-01")

    by_marker = await mcp_router.get_lab_results(marker="TSH")
    assert len(by_marker) == 1 and by_marker[0]["id"] == result_id

    by_range = await mcp_router.get_lab_results(start_date="2026-06-01", end_date="2026-06-30")
    assert len(by_range) == 1 and by_range[0]["id"] == result_id

    assert await mcp_router.get_lab_results(start_date="2026-07-01", end_date="2026-07-31") == []

    deleted = await mcp_router.delete_lab_result(result_id)
    assert deleted == {"deleted": True, "result_id": result_id}
    assert await mcp_router.get_lab_results(marker="TSH") == []


async def test_log_lab_results_batch_creates_and_dedupes(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)

    payload = dict(
        results=[
            {"marker": "Ferritin", "value": 95, "unit": "ng/mL", "ref_low": 30, "ref_high": 400},
            {"marker": "TSH", "value": 5.5, "unit": "mIU/L", "ref_low": 0.4, "ref_high": 4.0},
        ],
        on_date="2026-06-10",
        lab_name="Synevo",
    )

    res = await mcp_router.log_lab_results(**payload)
    assert res["created"] == 2 and res["skipped"] == 0
    by_marker = {r["marker"]: r for r in res["results"]}
    assert set(by_marker) == {"Ferritin", "TSH"}
    assert by_marker["TSH"]["flag"] == "high"
    assert by_marker["Ferritin"]["lab_name"] == "Synevo"

    stored = await mcp_router.get_lab_results(start_date="2026-06-10", end_date="2026-06-10")
    assert len(stored) == 2

    # Retrying the exact same report is a safe no-op (dedup on date+marker+value).
    res2 = await mcp_router.log_lab_results(**payload)
    assert res2 == {"created": 0, "skipped": 2, "results": []}
    stored2 = await mcp_router.get_lab_results(start_date="2026-06-10", end_date="2026-06-10")
    assert len(stored2) == 2


async def test_notes_for_labs_domain(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)

    res = await mcp_router.log_lab_result(marker="Ferritin", value=95, on_date="2026-06-10")
    result_id = res["id"]

    noted = await mcp_router.log_note(domain="labs", record_id=result_id, note="повторить через 3 мес")
    assert "error" not in noted and noted["note"] == "повторить через 3 мес"

    notes = await mcp_router.get_notes(domain="labs")
    assert any(n.get("note") == "повторить через 3 мес" and n.get("_domain") == "labs" for n in notes)
