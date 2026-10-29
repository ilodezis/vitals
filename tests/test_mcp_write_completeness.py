"""MCP write-completeness tools — the second half of the write surface: GLP-1
edit/delete + side effects + dose phases, skincare observations, supplements
catalog CRUD, measurement edit/delete, noise markers, module toggles, digest
trigger, and get_trend analytics.

Same import-skip guard as the other MCP tool tests; all run on the fast SQLite path."""
from __future__ import annotations

from datetime import date

import pytest

from vitals.services import weight_service

mcp_router = pytest.importorskip("web.routers.mcp")


@pytest.fixture(autouse=True)
def _use_test_factory(session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)


@pytest.fixture(autouse=True)
async def _optional_modules_on(session_factory):
    """Optional modules default to off, and the MCP write tools honour that
    (web/routers/mcp.gated). These tests write to optional domains — switch them on."""
    from vitals.services import modules_service

    async with session_factory() as session:
        for key in sorted(modules_service.OPTIONAL_KEYS):
            await modules_service.set_module_enabled(session, key=key, enabled=True)
        await session.commit()


# ── GLP-1 ─────────────────────────────────────────────────────────────────────
async def test_glp1_injection_update_and_delete():
    created = await mcp_router.log_glp1(drug="semaglutide", dose_mg=1.0, on_date="2026-07-01")
    iid = created["id"]

    updated = await mcp_router.update_glp1(iid, drug="semaglutide", dose_mg=2.0, on_date="2026-07-01")
    assert updated["dose_mg"] == 2.0

    assert await mcp_router.update_glp1(9999, drug="semaglutide", dose_mg=1.0) == {
        "error": "Injection 9999 not found"
    }

    assert await mcp_router.delete_record("glp1", iid, confirm=True) == {
        "deleted": True, "domain": "glp1", "record_id": iid
    }


async def test_side_effect_log_and_delete():
    row = await mcp_router.log_side_effect(effect_type="nausea", severity=3, on_date="2026-07-02")
    assert row["effect_type"] == "nausea"
    assert row["severity"] == 3
    assert await mcp_router.delete_record("glp1_side_effect", row["id"], confirm=True) == {
        "deleted": True, "domain": "glp1_side_effect", "record_id": row["id"]
    }


async def test_dose_phase_add_and_delete():
    row = await mcp_router.add_dose_phase(start_date="2026-06-01", drug="tirzepatide", dose_mg=5.0)
    assert row["dose_mg"] == 5.0
    assert await mcp_router.delete_record("glp1_dose_phase", row["id"], confirm=True) == {
        "deleted": True, "domain": "glp1_dose_phase", "record_id": row["id"]
    }


# ── skincare observation ──────────────────────────────────────────────────────
async def test_skincare_observation_log_and_delete():
    row = await mcp_router.log_skincare_observation(on_date="2026-07-03", inflammation=2, pih=1, zone="cheeks")
    assert row["inflammation"] == 2
    assert row["zone"] == "cheeks"
    assert await mcp_router.delete_record("skincare_observation", row["id"], confirm=True) == {
        "deleted": True, "domain": "skincare_observation", "record_id": row["id"]
    }


# ── supplements CRUD ──────────────────────────────────────────────────────────
async def test_supplement_crud():
    created = await mcp_router.add_supplement(name="Creatine", dose="5 g", evidence="A")
    sid = created["id"]
    assert created["key"]  # derived slug
    assert created["active"] is True

    toggled = await mcp_router.set_supplement_active(sid, active=False)
    assert toggled["active"] is False

    updated = await mcp_router.update_supplement(sid, name="Creatine Monohydrate", dose="5 g")
    assert updated["name"] == "Creatine Monohydrate"

    assert "error" in await mcp_router.update_supplement(9999, name="x")
    assert await mcp_router.delete_record("supplements", sid, confirm=True) == {
        "deleted": True, "domain": "supplements", "record_id": sid
    }


# ── measurement edit/delete ───────────────────────────────────────────────────
async def test_measurement_update_and_delete():
    created = await mcp_router.log_measurement(on_date="2026-07-04", waist_cm=85.0)
    mid = created["id"]

    updated = await mcp_router.update_measurement(mid, on_date="2026-07-04", waist_cm=84.0)
    assert updated["waist_cm"] == 84.0

    assert "error" in await mcp_router.update_measurement(9999, on_date="2026-07-04", waist_cm=80.0)
    assert await mcp_router.delete_record("measurement", mid, confirm=True) == {
        "deleted": True, "domain": "measurement", "record_id": mid
    }


# ── noise markers ─────────────────────────────────────────────────────────────
async def test_noise_marker_add_and_delete():
    row = await mcp_router.add_noise_marker(start_date="2026-06-10", end_date="2026-06-12", reason="sick", direction="down")
    mid = row["id"]

    logs = await mcp_router.get_weight_logs()
    assert any(m["id"] == mid for m in logs["noise_markers"])

    assert await mcp_router.delete_record("noise_marker", mid, confirm=True) == {
        "deleted": True, "domain": "noise_marker", "record_id": mid
    }


# ── modules ───────────────────────────────────────────────────────────────────
async def test_modules_get_and_toggle():
    state = await mcp_router.get_modules()
    assert "weight" in state["core"]
    assert state["enabled"]["weight"] is True

    # An optional module toggles both ways. (That optional modules *default* to
    # off is pinned in test_mcp_module_gate, which needs that default intact —
    # this file's fixture switches them on so its write tools can run.)
    off = await mcp_router.set_module(key="body_comp", enabled=False)
    assert off["enabled"]["body_comp"] is False
    toggled = await mcp_router.set_module(key="body_comp", enabled=True)
    assert toggled["enabled"]["body_comp"] is True

    # Core modules are locked.
    err = await mcp_router.set_module(key="weight", enabled=False)
    assert "error" in err


# ── digest trigger ────────────────────────────────────────────────────────────
async def test_generate_digest_without_llm_key_errors():
    # Test env clears VITALS_OPENROUTER_API_KEY, so the LLM is not configured.
    result = await mcp_router.generate_digest_now()
    assert "error" in result
    assert "LLM not configured" in result["error"]


# ── get_trend ─────────────────────────────────────────────────────────────────
async def test_get_trend_weight_slope_and_projection(db_session):
    await weight_service.log_weight(db_session, on_date=date(2026, 6, 1), weight_kg=92.0)
    await weight_service.log_weight(db_session, on_date=date(2026, 6, 8), weight_kg=91.0)
    await weight_service.log_weight(db_session, on_date=date(2026, 6, 15), weight_kg=90.0)
    await db_session.commit()

    trend = await mcp_router.get_trend("weight.weight_kg", target=88.0)
    assert trend["points"] == 3
    assert trend["trend"]["slope_per_week"] < 0  # losing weight
    assert trend["unit"] == "кг"
    # Projection to 88 kg is a future date on this downward line.
    assert trend["projection"]["date"] is not None
    assert trend["projection"]["date"] > "2026-06-15"


async def test_get_trend_excludes_noise(db_session):
    await weight_service.log_weight(db_session, on_date=date(2026, 6, 1), weight_kg=92.0)
    await weight_service.log_weight(db_session, on_date=date(2026, 6, 8), weight_kg=91.0)
    await weight_service.add_noise_marker(
        db_session, start_date=date(2026, 6, 8), end_date=date(2026, 6, 8), reason="creatine"
    )
    await db_session.commit()

    trend = await mcp_router.get_trend("weight.weight_kg")
    assert trend["points"] == 1  # the 06-08 point is excluded
    assert trend["noise_excluded"] is True


async def test_get_trend_unknown_metric_errors():
    result = await mcp_router.get_trend("not.a_metric")
    assert "error" in result
