from datetime import date, timedelta
import pytest
from web.routers import mcp as mcp_router
from vitals.models import WeightLog
from vitals.services import alerts_service, modules_service


@pytest.fixture(autouse=True)
async def _setup_session(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)


async def test_delete_record_two_step_confirmation(db_session):
    row = WeightLog(date=date(2026, 7, 10), weight_kg=88.5, domain="weight", source="manual")
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)

    # 1. Without confirm=True -> preview only, record not deleted
    preview = await mcp_router.delete_record("weight", row.id)
    assert preview["preview"] is True
    assert preview["confirm_required"] is True
    assert preview["action"] == "delete"
    assert preview["domain"] == "weight"
    assert preview["record_id"] == row.id
    assert "confirm=True" in preview["hint"]

    # Verify still in DB
    existing = await db_session.get(WeightLog, row.id)
    assert existing is not None

    # 2. With confirm=True -> deleted
    result = await mcp_router.delete_record("weight", row.id, confirm=True)
    assert result == {"deleted": True, "domain": "weight", "record_id": row.id}

    # Verify gone from DB
    existing_after = await db_session.get(WeightLog, row.id)
    assert existing_after is None


async def test_resolve_all_alerts_two_step_confirmation(db_session):
    for i in range(3):
        await alerts_service.raise_alert(
            db_session,
            domain="labs",
            severity="warn",
            alert_key=f"test_alert_{i}",
            message=f"Test alert message {i}",
        )
    await db_session.commit()

    active_before = await alerts_service.list_active(db_session, domain="labs")
    assert len(active_before) == 3

    # 1. Without confirm=True -> preview only, alerts stay active
    preview = await mcp_router.resolve_all_alerts(domain="labs")
    assert preview["preview"] is True
    assert preview["confirm_required"] is True
    assert preview["action"] == "resolve_all_alerts"
    assert preview["count"] == 3
    assert len(preview["sample_messages"]) == 3
    assert "confirm=True" in preview["hint"]

    active_still = await alerts_service.list_active(db_session, domain="labs")
    assert len(active_still) == 3

    # 2. With confirm=True -> resolved
    result = await mcp_router.resolve_all_alerts(domain="labs", confirm=True)
    assert result == {"resolved": 3, "domain": "labs"}

    active_after = await alerts_service.list_active(db_session, domain="labs")
    assert len(active_after) == 0


async def test_create_shared_report_two_step_confirmation(db_session):
    # Add weight records so there is data to share
    for i in range(3):
        db_session.add(
            WeightLog(
                date=date.today() - timedelta(days=i + 1),
                weight_kg=90.0 - i,
                domain="weight",
                source="manual",
            )
        )
    await db_session.commit()

    # 1. Without confirm=True -> preview only, report not created
    preview = await mcp_router.create_shared_report(
        title="Тестовый отчёт", domains=["weight"], period="30"
    )
    assert preview["preview"] is True
    assert preview["confirm_required"] is True
    assert preview["action"] == "create_shared_report"
    assert preview["title"] == "Тестовый отчёт"
    assert preview["domains"] == ["weight"]
    assert "expires_days" in preview
    assert "confirm=True" in preview["hint"]

    reports_list = await mcp_router.get_shared_reports()
    assert reports_list["reports"] == []

    # 2. With confirm=True -> created
    created = await mcp_router.create_shared_report(
        title="Тестовый отчёт", domains=["weight"], period="30", confirm=True
    )
    assert created["id"] > 0
    assert created["url"].startswith("/r/")
    assert created["password"]

    reports_list_after = await mcp_router.get_shared_reports()
    assert len(reports_list_after["reports"]) == 1


async def test_set_module_returns_note_and_status(db_session):
    res_off = await mcp_router.set_module(key="body_comp", enabled=False)
    assert res_off["status"] == "disabled"
    assert res_off["module"] == "body_comp"
    assert "hidden from" in res_off["note"]
    assert res_off["enabled"]["body_comp"] is False

    res_on = await mcp_router.set_module(key="body_comp", enabled=True)
    assert res_on["status"] == "enabled"
    assert res_on["module"] == "body_comp"
    assert "now visible in" in res_on["note"]
    assert res_on["enabled"]["body_comp"] is True


def test_dangerous_tools_docstrings_warn():
    assert "explicitly instructs" in mcp_router.override_alert.__doc__
    assert "autonomously on the model's own initiative" in mcp_router.override_alert.__doc__
    assert "Heavy response payload" in mcp_router.export_everything.__doc__
    assert "Requires two-step confirmation" in mcp_router.delete_record.__doc__
    assert "Requires two-step confirmation" in mcp_router.resolve_all_alerts.__doc__
    assert "Requires two-step confirmation" in mcp_router.create_shared_report.__doc__
