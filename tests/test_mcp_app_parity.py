"""Everything the owner can do in the app, Claude can do over MCP — through the
same services, so with the same checks.

The skincare routine is the case that started it: the app moved to a product
catalog with morning/evening ticks, while the tool surface still wrote the old
seven-checkbox log nobody looked at any more. The rest are the screens that had
no tools at all (Today, Share, Charts, the photo galleries, the settings cards)
or only half of them (rules readable but not switchable, a weight that could be
logged but not corrected).

Same import-skip guard as the other MCP tool tests; all on the fast SQLite path.
"""
from __future__ import annotations

import base64
import io
import json
import os
from datetime import date, timedelta

import pytest

mcp_router = pytest.importorskip("web.routers.mcp")

from vitals.models.conflict_rule import ConflictRule  # noqa: E402
from vitals.services import skincare_service  # noqa: E402
from vitals.utils.timeutils import today_local  # noqa: E402

WED = date(2026, 10, 21)  # weekday 3 in the catalog's numbering


@pytest.fixture(autouse=True)
def _use_test_factory(session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(mcp_router, "_redis_or_none", lambda: None)


@pytest.fixture(autouse=True)
async def _optional_modules_on(session_factory):
    from vitals.services import modules_service

    async with session_factory() as session:
        for key in sorted(modules_service.OPTIONAL_KEYS):
            await modules_service.set_module_enabled(session, key=key, enabled=True)
        await session.commit()


@pytest.fixture
def static_dir(tmp_path, monkeypatch):
    import web.templating

    monkeypatch.setattr(web.templating, "STATIC_DIR", str(tmp_path))
    return tmp_path


def _png_b64(color: str = "red") -> str:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


# ── Skincare: catalog, plan, ticks ────────────────────────────────────────────
async def test_the_old_checklist_tool_is_gone():
    """Two ways to record skincare, one of which nobody reads, is how the diary
    went stale — the retired tool must not come back."""
    listed = {t.name for t in await mcp_router.mcp.list_tools()}
    assert "log_skincare" not in listed
    assert {"get_skincare_routine", "set_skincare_check", "add_skincare_product"} <= listed


async def test_product_is_added_and_planned_on_its_days():
    added = await mcp_router.add_skincare_product(
        name="Адапален 0,1%", type="Ретиноид", default_time="evening",
        schedule_days=[3, 1, 3], active_flag="retinoid",
    )
    assert added["schedule_days"] == [1, 3] and added["active_flag"] == "retinoid"

    routine = await mcp_router.get_skincare_routine(start_date=WED.isoformat(), end_date=WED.isoformat())
    assert [p["name"] for p in routine["products"]] == ["Адапален 0,1%"]
    day = routine["days"][0]
    assert day["date"] == WED.isoformat()
    assert [i["name"] for i in day["evening"]] == ["Адапален 0,1%"] and day["morning"] == []
    assert "retinoid" in routine["flags"]


async def test_product_without_days_is_planned_every_day():
    added = await mcp_router.add_skincare_product(name="Крем", type="Крем", default_time="both")
    assert added["schedule_days"] == list(range(7))


@pytest.mark.parametrize(
    "kwargs,needle",
    [
        ({"default_time": "noon"}, "default_time"),
        ({"schedule_days": [7]}, "schedule_days"),
        ({"active_flag": "adapalene"}, "active_flag"),
        ({"name": "  "}, "name and type"),
    ],
)
async def test_product_fields_the_form_cannot_produce_are_refused(kwargs, needle):
    args = {"name": "X", "type": "Y", **kwargs}
    result = await mcp_router.add_skincare_product(**args)
    assert needle in result["error"]


async def test_update_changes_only_what_is_passed_and_clears_on_request():
    p = await mcp_router.add_skincare_product(
        name="Клиндовит", type="Гель", default_time="morning", schedule_days=[1, 2],
        active_flag="benzoyl_peroxide", active_ingredient="BPO 5%",
    )
    off = await mcp_router.update_skincare_product(p["id"], active=False)
    assert off["active"] is False
    assert off["schedule_days"] == [1, 2] and off["active_flag"] == "benzoyl_peroxide"

    cleared = await mcp_router.update_skincare_product(p["id"], clear=["active_flag", "active_ingredient"])
    assert "active_flag" not in cleared and "active_ingredient" not in cleared
    assert cleared["name"] == "Клиндовит"

    bad = await mcp_router.update_skincare_product(p["id"], clear=["name"])
    assert "cannot clear" in bad["error"]
    assert "not found" in (await mcp_router.update_skincare_product(9999, name="x"))["error"]


async def test_a_tick_is_the_apps_tick(db_session):
    p = await mcp_router.add_skincare_product(
        name="Адапален", type="Ретиноид", schedule_days=[3], active_flag="retinoid",
    )
    result = await mcp_router.set_skincare_check("evening", p["id"], on_date=WED.isoformat())
    item = result["evening"][0]
    assert item["done"] and item["planned"]

    # The conflict engine reads the derived day flags — the tick set it.
    log = await skincare_service.get_log(db_session, WED)
    assert log is not None and log.retinoid is True

    history = await mcp_router.get_skincare_logs(start_date=WED.isoformat(), end_date=WED.isoformat())
    assert [c["product_name"] for c in history["checks"]] == ["Адапален"]
    assert history["checks"][0]["source"] == "mcp"
    assert history["day_flags"][0]["retinoid"] is True

    undone = await mcp_router.set_skincare_check(
        "evening", p["id"], done=False, on_date=WED.isoformat()
    )
    assert not undone["evening"][0]["done"]
    db_session.expire_all()
    assert await skincare_service.get_log(db_session, WED) is None


async def test_all_done_ticks_the_open_slot_and_a_slot_cannot_be_unticked_whole():
    for name in ("Умывалка", "Крем"):
        await mcp_router.add_skincare_product(name=name, type="x", default_time="morning")
    result = await mcp_router.set_skincare_check("morning", on_date=WED.isoformat())
    assert all(i["done"] for i in result["morning"]) and len(result["morning"]) == 2

    refused = await mcp_router.set_skincare_check("morning", done=False, on_date=WED.isoformat())
    assert "product_id" in refused["error"]
    assert "slot" in (await mcp_router.set_skincare_check("noon"))["error"]
    assert "not found" in (await mcp_router.set_skincare_check("morning", 9999))["error"]


async def test_a_blocking_rule_blocks_the_tick_until_override(db_session):
    db_session.add(ConflictRule(
        rule_type="hard_block", domain_a="skincare", condition_a={"retinoid": True},
        domain_b="skincare", condition_b={"peel": True}, severity="block",
        message="Ретиноид и пилинг в один вечер.", active=True,
    ))
    await db_session.commit()
    ret = await mcp_router.add_skincare_product(name="Ретиноид", type="x", active_flag="retinoid")
    peel = await mcp_router.add_skincare_product(name="Пилинг", type="x", active_flag="peel")
    await mcp_router.set_skincare_check("evening", ret["id"], on_date=WED.isoformat())

    blocked = await mcp_router.set_skincare_check("evening", peel["id"], on_date=WED.isoformat())
    assert blocked["blocked"] is True

    saved = await mcp_router.set_skincare_check(
        "evening", peel["id"], on_date=WED.isoformat(), override=True
    )
    assert {i["name"] for i in saved["evening"] if i["done"]} == {"Ретиноид", "Пилинг"}


async def test_deleting_a_product_keeps_its_history():
    p = await mcp_router.add_skincare_product(name="Старый крем", type="x")
    await mcp_router.set_skincare_check("evening", p["id"], on_date=WED.isoformat())
    assert (await mcp_router.delete_record("skincare_product", p["id"]))["deleted"] is True

    history = await mcp_router.get_skincare_logs(start_date=WED.isoformat())
    # The tick stays readable by name (on Postgres its product_id goes null — the
    # FK is SET NULL; SQLite here doesn't enforce foreign keys).
    assert history["checks"][0]["product_name"] == "Старый крем"


async def test_routine_range_is_bounded():
    result = await mcp_router.get_skincare_routine(start_date="2026-01-01", end_date="2026-03-01")
    assert "31 days" in result["error"]
    assert "before" in (await mcp_router.get_skincare_routine(
        start_date="2026-03-02", end_date="2026-03-01"))["error"]


# ── Photos ────────────────────────────────────────────────────────────────────
async def test_face_photo_round_trip(static_dir):
    added = await mcp_router.add_photo("face", _png_b64(), on_date=WED.isoformat(), note="день 3")
    assert added["date"] == WED.isoformat() and added["url"].startswith("/static/uploads/")
    assert (static_dir / added["file_key"]).exists()

    listed = await mcp_router.list_photos("face")
    assert [p["id"] for p in listed] == [added["id"]]
    assert await mcp_router.list_photos("progress") == []

    shown = await mcp_router.get_photo("face", added["id"], max_px=300)
    kinds = [c.type for c in shown.content]
    assert kinds == ["text", "image"]
    assert json.loads(shown.content[0].text)["note"] == "день 3"
    assert shown.content[1].mime_type == "image/jpeg"

    gone = await mcp_router.delete_record("skincare_photo", added["id"])
    assert gone["deleted"] is True
    assert not (static_dir / added["file_key"]).exists()


async def test_photo_and_today_survive_the_protocol(static_dir):
    """Called through a real MCP client, not as a function: the image arrives as
    image content and the Today screen's dates serialize."""
    from fastmcp import Client

    added = await mcp_router.add_photo("face", _png_b64())
    async with Client(mcp_router.mcp) as client:
        shown = await client.call_tool("get_photo", {"kind": "face", "photo_id": added["id"]})
        assert [c.type for c in shown.content] == ["text", "image"]
        today = await client.call_tool("get_today", {})
        assert json.loads(today.content[0].text)["date"] == today_local().isoformat()


async def test_progress_photo_lives_in_the_weight_gallery(static_dir):
    added = await mcp_router.add_photo("progress", "data:image/png;base64," + _png_b64("blue"))
    assert added["date"] == today_local().isoformat()
    assert [p["id"] for p in await mcp_router.list_photos("progress")] == [added["id"]]
    assert (await mcp_router.delete_record("progress_photo", added["id"]))["deleted"] is True
    assert not (static_dir / added["file_key"]).exists()


async def test_photos_refuse_what_is_not_an_image(static_dir):
    assert "base64" in (await mcp_router.add_photo("face", "%%%"))["error"]
    not_image = base64.b64encode(b"<svg onload=alert(1)>").decode()
    assert "image" in (await mcp_router.add_photo("face", not_image))["error"]
    assert "kind" in (await mcp_router.add_photo("selfie", _png_b64()))["error"]
    assert not list(static_dir.rglob("*.*"))


async def test_face_photos_follow_the_skincare_module(static_dir):
    await mcp_router.set_module("skincare", False)
    assert await mcp_router.add_photo("face", _png_b64()) == {"error": "module 'skincare' is disabled"}
    assert (await mcp_router.add_photo("progress", _png_b64()))["id"]


async def test_a_missing_file_is_reported_not_raised(static_dir):
    added = await mcp_router.add_photo("face", _png_b64())
    os.remove(static_dir / added["file_key"])
    result = await mcp_router.get_photo("face", added["id"])
    assert "missing" in result["error"] and result["id"] == added["id"]


# ── Profile and nutrition goals ───────────────────────────────────────────────
@pytest.fixture
def env_file(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("VITALS_HEIGHT_CM=190\nVITALS_NUTRITION_CALORIES_MIN=1300\n", encoding="utf-8")
    monkeypatch.setenv("VITALS_ENV_FILE", str(path))
    return path


async def test_profile_is_written_where_settings_writes_it(env_file):
    result = await mcp_router.update_user_profile(
        height_cm=188.5, age=31, goals=["снижение жира", "сила"],
        protein_target_g=160, calories_min=1500, calories_max=1900,
    )
    text = env_file.read_text(encoding="utf-8")
    assert "VITALS_HEIGHT_CM=188.5" in text and "VITALS_USER_AGE=31" in text
    assert "VITALS_USER_GOALS=снижение жира, сила" in text
    assert "VITALS_NUTRITION_CALORIES_MAX=1900" in text

    assert result["height_cm"] == 188.5 and result["age"] == 31
    assert result["goals"] == ["снижение жира", "сила"]
    assert result["nutrition_goals"] == {
        "protein_target_g": 160.0, "calories_min": 1500, "calories_max": 1900,
    }
    # Saved, but the running process reads .env at start — say so instead of
    # pretending the Navy formula already uses the new height.
    assert "height_cm" in result["pending_restart"]


@pytest.mark.parametrize(
    "kwargs,needle",
    [
        ({"height_cm": 30}, "height_cm"),
        ({"sex": "other"}, "sex"),
        ({"timezone": "Mars/Olympus"}, "timezone"),
        ({"goals": ["a, b"]}, "comma"),
        ({"calories_min": 2500}, "calories_min"),  # above the stored max (default 1700)
        ({}, "nothing to change"),
    ],
)
async def test_profile_rejects_what_settings_would_never_store(env_file, kwargs, needle):
    before = env_file.read_text(encoding="utf-8")
    result = await mcp_router.update_user_profile(**kwargs)
    assert needle in result["error"]
    assert env_file.read_text(encoding="utf-8") == before


async def test_settings_screen_and_mcp_read_the_same_profile(env_file, auth_client):
    await mcp_router.update_user_profile(height_cm=181, sex="female")
    view = (await auth_client.get("/api/v1/settings")).json()
    assert view["profile"]["height_cm"] == "181" and view["profile"]["sex"] == "female"


# ── Bot and station settings ──────────────────────────────────────────────────
async def test_proactive_settings_change_only_what_is_named():
    result = await mcp_router.set_proactive_settings(
        skincare_evening_time="22:00", nudges={"activity": False}
    )
    prefs = result["prefs"]
    assert prefs["skincare_evening_time"] == "22:00"
    assert prefs["nudges"]["activity"] is False and prefs["nudges"]["skincare"] is True
    assert result["adjusted"] is False

    state = await mcp_router.get_proactive_state()
    assert state["prefs"]["skincare_evening_time"] == "22:00"


async def test_proactive_settings_clamp_like_the_app_and_say_so():
    result = await mcp_router.set_proactive_settings(daily_budget=50)
    assert result["prefs"]["daily_budget"] == 12 and result["adjusted"] is True
    assert "unknown nudge" in (await mcp_router.set_proactive_settings(nudges={"spam": True}))["error"]


async def test_environment_thresholds_round_trip():
    saved = await mcp_router.set_environment_settings(co2_warn=1100, night_start="23:00")
    assert saved["co2_warn"] == 1100 and saved["night_window"]["start"] == "23:00"
    assert (await mcp_router.get_environment_settings())["co2_warn"] == 1100
    # Out-of-order zones are repaired, not stored as nonsense.
    fixed = await mcp_router.set_environment_settings(co2_bad=500)
    assert fixed["co2_bad"] > fixed["co2_warn"]


# ── Alerts and conflict rules ─────────────────────────────────────────────────
async def test_resolve_all_alerts(db_session):
    from vitals.services import alerts_service

    for key in ("a", "b"):
        await alerts_service.raise_alert(
            db_session, domain="labs", severity="warn", alert_key=key, message=key,
        )
    await alerts_service.raise_alert(
        db_session, domain="weight", severity="warn", alert_key="c", message="c",
    )
    await db_session.commit()

    assert len(await mcp_router.get_active_alerts(domain="labs")) == 2
    assert await mcp_router.resolve_all_alerts(domain="labs") == {"resolved": 2, "domain": "labs"}
    assert [a["alert_key"] for a in await mcp_router.get_active_alerts()] == ["c"]


async def test_a_rule_switched_off_stops_blocking(db_session):
    db_session.add(ConflictRule(
        rule_type="hard_block", domain_a="skincare", condition_a={"retinoid": True},
        domain_b="skincare", condition_b={"peel": True}, severity="block",
        message="Ретиноид и пилинг.", active=True,
    ))
    await db_session.commit()
    rule = (await mcp_router.list_conflict_rules(domain="skincare"))[0]
    assert rule["active"] is True and rule["firing"] is False

    off = await mcp_router.set_conflict_rule_active(rule["id"], False)
    assert off["active"] is False

    ret = await mcp_router.add_skincare_product(name="R", type="x", active_flag="retinoid")
    peel = await mcp_router.add_skincare_product(name="P", type="x", active_flag="peel")
    await mcp_router.set_skincare_check("evening", ret["id"], on_date=WED.isoformat())
    result = await mcp_router.set_skincare_check("evening", peel["id"], on_date=WED.isoformat())
    assert "blocked" not in result
    assert "not found" in (await mcp_router.set_conflict_rule_active(9999, True))["error"]


# ── Today, doctor reports, charts ─────────────────────────────────────────────
async def test_today_is_the_screen_as_json():
    await mcp_router.log_weight(weight_kg=90.0)
    today = await mcp_router.get_today()
    json.dumps(today)  # nothing left that a tool result can't carry
    assert today["date"] == today_local().isoformat()
    assert today["latest_weight"]["kg"] == 90.0
    assert {"narrative", "figures", "changes", "feed", "attention", "goal"} <= set(today)


async def test_doctor_report_lifecycle():
    for i in range(3):
        await mcp_router.log_weight(
            weight_kg=90.0 - i, on_date=(today_local() - timedelta(days=i + 1)).isoformat()
        )
    created = await mcp_router.create_shared_report(title="Эндокринолог", domains=["weight"], period="30")
    assert created["password"] and created["url"].startswith("/r/")
    assert created["domains"] == ["weight"]

    listed = await mcp_router.get_shared_reports()
    report = listed["reports"][0]
    assert report["id"] == created["id"] and report["state"] == "live"
    assert "token" not in report  # the url carries it already

    assert await mcp_router.revoke_shared_report(created["id"]) == {"revoked": True, "id": created["id"]}
    assert "already revoked" in (await mcp_router.revoke_shared_report(created["id"]))["error"]
    assert (await mcp_router.get_shared_reports())["reports"][0]["state"] == "revoked"

    assert (await mcp_router.delete_record("shared_report", created["id"]))["deleted"] is True
    assert (await mcp_router.get_shared_reports())["reports"] == []


async def test_doctor_report_refuses_empty_or_unknown_input():
    assert "domain" in (await mcp_router.create_shared_report(title="x", domains=["nope"]))["error"]
    assert "preset" in (await mcp_router.create_shared_report(title="x", preset="nope"))["error"]
    assert "custom period" in (
        await mcp_router.create_shared_report(title="x", domains=["weight"], period="custom")
    )["error"]
    # A window with nothing in it is not a document.
    assert "error" in await mcp_router.create_shared_report(title="x", domains=["weight"])


async def test_saved_chart_lifecycle():
    await mcp_router.log_weight(weight_kg=91.0, on_date="2026-10-01")
    chart = await mcp_router.create_saved_chart(
        name="Вес", series=[{"metric_key": "weight.weight_kg"}]
    )
    assert chart["series"][0]["domain"] == "weight"

    listed = await mcp_router.get_saved_charts()
    assert [c["id"] for c in listed["charts"]] == [chart["id"]]

    one = await mcp_router.get_saved_charts(chart_id=chart["id"], include_catalog=True)
    assert one["chart"]["series"][0]["points"][0]["value"] == 91.0
    assert "weight" in one["catalog"]

    assert await mcp_router.delete_saved_chart(chart["id"]) == {"deleted": True, "chart_id": chart["id"]}
    assert (await mcp_router.get_saved_charts())["charts"] == []
    assert "unknown metric_key" in (await mcp_router.create_saved_chart(
        name="x", series=[{"metric_key": "nope.nope"}]))["error"]


# ── Edits the app had and the tools didn't ────────────────────────────────────
async def test_weight_can_be_corrected():
    row = await mcp_router.log_weight(weight_kg=95.0, on_date="2026-10-01", note="после ужина")
    fixed = await mcp_router.update_weight(row["id"], weight_kg=90.5)
    assert fixed["weight_kg"] == 90.5 and fixed["date"] == "2026-10-01"
    assert fixed["note"] == "после ужина"
    moved = await mcp_router.update_weight(fixed["id"], on_date="2026-10-02", clear_note=True)
    assert moved["date"] == "2026-10-02" and "note" not in moved
    assert "between" in (await mcp_router.update_weight(moved["id"], weight_kg=900))["error"]


async def test_dose_phase_can_be_closed():
    phase = await mcp_router.add_dose_phase(
        start_date=(today_local() - timedelta(days=10)).isoformat(), drug="Тирзепатид", dose_mg=5,
    )
    closed = await mcp_router.close_dose_phase()
    assert closed["id"] == phase["id"] and closed["end_date"] == today_local().isoformat()
    assert "No such" in (await mcp_router.close_dose_phase(phase_id=9999))["error"]
    assert "before" in (await mcp_router.close_dose_phase(
        phase_id=phase["id"], end_date="2000-01-01"))["error"]
    assert "positive" in (await mcp_router.add_dose_phase(
        start_date="2026-10-01", drug="x", dose_mg=0))["error"]


async def test_lab_marker_catalog_can_be_read_and_edited():
    await mcp_router.log_lab_result(marker="Ферритин", value=40, unit="нг/мл", on_date="2026-09-01")
    catalog = await mcp_router.get_lab_markers()
    names = [m["name"] for m in catalog["markers"]]
    assert len(names) == 1

    edited = await mcp_router.update_lab_marker(
        names[0], ref_low=30, ref_high=300, tier=1, retest_interval_days=90,
        defer_until="2026-12-01",
    )
    assert edited["ref_low"] == 30 and edited["tier"] == 1
    assert edited["defer_until"] == "2026-12-01"

    one = await mcp_router.get_lab_markers(marker=names[0])
    assert one["history"][0]["value"] == 40
    assert "tier" in (await mcp_router.update_lab_marker(names[0], tier=7))["error"]
    assert "No marker" in (await mcp_router.update_lab_marker("Унобтаний"))["error"]


async def test_measurement_edit_keeps_its_date_and_fields():
    row = await mcp_router.log_measurement(on_date="2026-10-01", waist_cm=90, neck_cm=40)
    edited = await mcp_router.update_measurement(row["id"], waist_cm=88)
    assert edited["date"] == "2026-10-01" and edited["waist_cm"] == 88 and edited["neck_cm"] == 40


async def test_meal_fields_can_be_cleared():
    meal = await mcp_router.log_meal(name="Обед", calories=600, protein_g=40, on_date="2026-10-01")
    cleared = await mcp_router.update_meal(meal["id"], clear=["protein_g"])
    assert cleared["calories"] == 600 and "protein_g" not in cleared
    assert "cannot clear" in (await mcp_router.update_meal(meal["id"], clear=["name"]))["error"]


async def test_event_range_can_be_collapsed_to_one_day():
    event = await mcp_router.log_event(title="Поездка", on_date="2026-10-01", end_date="2026-10-05")
    edited = await mcp_router.update_event(event["id"], clear=["end_date"])
    assert "end_date" not in edited and edited["date"] == "2026-10-01"
