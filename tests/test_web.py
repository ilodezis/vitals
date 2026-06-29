"""Integration tests for the Vitals FastAPI web panel and router endpoints."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from vitals.models.app_settings import AppSetting
from vitals.models.conflict_rule import ConflictRule
from vitals.models.system_alert import SystemAlert
from vitals.models.weight import WeightLog
from vitals.services.modules_service import SETTINGS_KEY

pytestmark = pytest.mark.asyncio


async def test_health_endpoint(client, redis):
    """Test health check route returns OK when DB and Redis are connected."""
    import time
    await redis.set("scheduler:last_run:keepalive", str(int(time.time())))

    response = await client.get("/health")
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["status"] == "ok"
    assert res_data["database"] == "ok"
    assert res_data["redis"] == "ok"


async def test_unauthorized_redirects(client):
    """GET requests to authed pages redirect to login, while JSON endpoints return 401."""
    # Navigation GET request should redirect to /login
    response = await client.get("/weight", headers={"Accept": "text/html"})
    assert response.status_code == 302
    assert response.headers["location"].startswith("/login?next=/weight")

    # API POST request should return 401 Unauthorized
    response = await client.post("/weight/log", data={"weight_kg": 80.0, "date": "2026-06-22"})
    assert response.status_code == 401


async def test_login_page_renders(client):
    """GET /login returns HTML layout containing access panels."""
    response = await client.get("/login", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "Введите данные для авторизации" in response.text


async def test_login_form_failure(client):
    """POST /login with invalid credentials returns form with error code."""
    response = await client.post(
        "/login",
        data={"username": "wrong-user", "password": "wrong-password"},
        headers={"Accept": "text/html"},
    )
    assert response.status_code == 200
    assert "Неверное имя пользователя или пароль" in response.text


async def test_login_form_success(client):
    """POST /login with valid credentials redirects with session cookie set."""
    response = await client.post(
        "/login",
        data={"username": "tester", "password": "password"},
        headers={"Accept": "text/html"},
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "vitals_session" in response.cookies


async def test_login_rejects_open_redirect(client):
    """`next` is confined to local paths: absolute and protocol-relative targets
    fall back to '/', a genuine local path is preserved (open-redirect guard)."""
    r = await client.post(
        "/login",
        data={"username": "tester", "password": "password", "next": "https://evil.com"},
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/"

    r = await client.post(
        "/login",
        data={"username": "tester", "password": "password", "next": "//evil.com"},
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/"

    r = await client.post(
        "/login",
        data={"username": "tester", "password": "password", "next": "/glp1"},
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/glp1"


async def test_logout(auth_client):
    """POST /logout clears session cookies and redirects."""
    response = await auth_client.post("/logout")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


async def test_dashboard_renders(auth_client):
    """GET /weight returns dashboard page structure."""
    response = await auth_client.get("/weight", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "Аналитика веса и состава тела" in response.text
    assert "История взвешиваний" in response.text


async def test_log_weight_success(auth_client, db_session):
    """POST /weight/log inserts weight logs into the database."""
    response = await auth_client.post(
        "/weight/log",
        data={"weight_kg": 85.5, "date": "2026-06-10", "note": "Integration test weight"},
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/weight"

    # Confirm log saved
    result = await db_session.execute(select(WeightLog).where(WeightLog.weight_kg == 85.5))
    weight_log = result.scalar_one_or_none()
    assert weight_log is not None
    assert weight_log.note == "Integration test weight"


async def test_conflict_engine_override_flow(auth_client, db_session):
    """Test conflict blocks trigger HTTP 409, and overrides save correctly."""
    # Seed a conflict rule
    rule = ConflictRule(
        domain_a="weight",
        domain_b="weight",
        condition_a={},
        condition_b={},
        rule_type="hard_block",
        severity="block",
        message="Simulated weight log block conflict",
        active=True,
    )
    db_session.add(rule)
    await db_session.commit()

    # Log weight should be blocked
    response = await auth_client.post(
        "/weight/log",
        data={"weight_kg": 85.5, "date": "2026-06-10", "note": "Conflict block weight"},
    )
    assert response.status_code == 409
    data = response.json()
    assert "violations" in data
    assert data["violations"][0]["message"] == "Simulated weight log block conflict"

    # Override should save
    response = await auth_client.post(
        "/weight/log",
        data={
            "weight_kg": 85.5,
            "date": "2026-06-10",
            "note": "Conflict block weight overridden",
            "override": "true",
        },
    )
    assert response.status_code == 303

    # Check alert was stamped overridden
    result = await db_session.execute(select(SystemAlert))
    alerts = result.scalars().all()
    assert len(alerts) > 0
    assert alerts[0].override_at is not None


async def test_csp_headers_and_no_cdn_references(client):
    """Test that Content-Security-Policy headers are sent and no external CDNs are referenced in base template."""
    response = await client.get("/login", headers={"Accept": "text/html"})
    assert response.status_code == 200
    
    # Check CSP headers
    assert "Content-Security-Policy" in response.headers
    csp = response.headers["Content-Security-Policy"]
    assert "script-src 'self' 'unsafe-inline' 'unsafe-eval'" in csp
    assert "cdn.jsdelivr.net" not in csp
    
    # Check that external JS CDNs are not referenced in the HTML body
    html = response.text
    assert "cdn.jsdelivr.net" not in html
    assert "/static/vendor/htmx.min.js?v=" in html
    assert "/static/vendor/alpine.min.js?v=" in html


async def test_delete_weight_entry(auth_client, db_session):
    from datetime import date
    from vitals.services import weight_service
    # Seed a weight log
    w = await weight_service.log_weight(db_session, on_date=date(2026, 6, 12), weight_kg=85.0)
    await db_session.commit()

    response = await auth_client.post(f"/weight/log/{w.id}/delete")
    assert response.status_code == 303

    # Confirm log was deleted
    result = await db_session.execute(select(WeightLog).where(WeightLog.id == w.id))
    assert result.scalar_one_or_none() is None


async def test_glp1_dashboard_renders(auth_client):
    """GET /glp1 returns the protocol dashboard structure."""
    response = await auth_client.get("/glp1", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "История инъекций" in response.text
    assert "Фазы дозировки" in response.text
    assert "showForm" in response.text
    assert "Внести инфо" in response.text


async def test_glp1_log_injection(auth_client, db_session):
    """POST /glp1/injection inserts an injection row."""
    from vitals.models.glp1 import Injection

    response = await auth_client.post(
        "/glp1/injection",
        data={
            "date": "2026-06-10",
            "drug": "semaglutide",
            "dose_mg": 0.25,
            "site": "abdomen_left",
        },
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/glp1"

    result = await db_session.execute(select(Injection))
    inj = result.scalar_one_or_none()
    assert inj is not None
    assert inj.drug == "semaglutide"
    assert inj.site == "abdomen_left"


async def test_phase3_dashboards_render(auth_client):
    """The three Phase 3 dashboards render with their headings."""
    r = await auth_client.get("/supplements", headers={"Accept": "text/html"})
    assert r.status_code == 200 and "Каталог добавок" in r.text

    r = await auth_client.get("/genetics", headers={"Accept": "text/html"})
    assert r.status_code == 200 and "Генетические варианты" in r.text
    assert "Импорт VCF" in r.text

    r = await auth_client.get("/skincare", headers={"Accept": "text/html"})
    assert r.status_code == 200 and "Протокол ухода за кожей" in r.text
    assert "Схема ухода по дням недели" in r.text
    assert "Понедельник" in r.text


async def test_genetics_dashboard_post_import_view(auth_client):
    """After import, genetics dashboard initializes with admin panels hidden."""
    r = await auth_client.get("/genetics?imported=29&markers=1", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert "Персональный геном" in r.text
    assert "Импорт и настройки" in r.text
    assert "Загружено вариантов" in r.text
    assert 'x-init="showAdminPanels = false"' in r.text




async def test_skincare_retinoid_peel_block_and_override(auth_client, db_session):
    """retinoid+peel in one evening is blocked (409) then saved on override."""
    from vitals.models.conflict_rule import ConflictRule
    from vitals.models.skincare import SkincareLog

    db_session.add(
        ConflictRule(
            rule_type="hard_block",
            domain_a="skincare",
            condition_a={"retinoid": True},
            domain_b="skincare",
            condition_b={"peel": True},
            severity="block",
            message="Ретиноид и пилинг в один вечер — высокий риск раздражения.",
            active=True,
        )
    )
    await db_session.commit()

    r = await auth_client.post(
        "/skincare/log",
        data={"date": "2026-06-10", "retinoid": "true", "peel": "true"},
    )
    assert r.status_code == 409
    assert "violations" in r.json()

    r = await auth_client.post(
        "/skincare/log",
        data={"date": "2026-06-10", "retinoid": "true", "peel": "true", "override": "true"},
    )
    assert r.status_code == 303

    result = await db_session.execute(select(SkincareLog))
    log = result.scalar_one_or_none()
    assert log is not None and log.retinoid and log.peel


async def test_supplement_save_via_web(auth_client, db_session):
    from vitals.models.supplements import Supplement

    r = await auth_client.post(
        "/supplements/save",
        data={"name": "Креатин", "dose": "5 г", "evidence": "A", "active": "true"},
    )
    assert r.status_code == 303
    result = await db_session.execute(select(Supplement))
    s = result.scalar_one_or_none()
    assert s is not None and s.name == "Креатин" and s.active is True


async def test_genetics_vcf_upload(auth_client, db_session):
    """POST /genetics/import parses an uploaded VCF and upserts variants, stamping
    the conflict marker for curated rsIDs."""
    from vitals.models.genetics import GeneticVariant

    vcf = (
        "##fileformat=VCFv4.2\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
        "6\t26093141\trs1800562\tG\tA\t.\tPASS\t.\tGT\t0/1\n"  # known → imported
        "6\t100\t.\tG\tA\t.\tPASS\t.\tGT\t0/1\n"  # no rsID → skipped
        "1\t200\trs9999999\tA\tT\t.\tPASS\t.\tGT\t0/1\n"  # unknown rsID → skipped
    )
    r = await auth_client.post(
        "/genetics/import",
        files={"file": ("genome.vcf", vcf, "text/plain")},
        data={"only_interpreted": "false"},
    )
    assert r.status_code == 303
    # Only the curated rsID is imported; the unknown raw variant is dropped.
    assert "imported=1" in r.headers["location"]
    assert "markers=1" in r.headers["location"]

    result = await db_session.execute(select(GeneticVariant))
    rows = result.scalars().all()
    assert {v.rsid for v in rows} == {"rs1800562"}
    assert rows[0].marker == "hemochromatosis_carrier"


async def test_edit_weight_entry(auth_client, db_session):
    from datetime import date
    from vitals.services import weight_service
    # Seed a weight log
    w = await weight_service.log_weight(db_session, on_date=date(2026, 6, 12), weight_kg=85.0)
    await db_session.commit()

    response = await auth_client.post(
        "/weight/log",
        data={"id": w.id, "weight_kg": 87.0, "date": "2026-06-12", "note": "Edited weight"},
    )
    assert response.status_code == 303

    # Confirm log was edited
    await db_session.refresh(w)
    assert w.weight_kg == 87.0
    assert w.note == "Edited weight"


async def test_skincare_product_save_and_delete_via_web(auth_client, db_session):
    from vitals.models.skincare import SkincareProduct

    # Test Add Product
    r = await auth_client.post(
        "/skincare/product/save",
        data={
            "name": "Новое средство",
            "type": "Сыворотка",
            "active_ingredient": "Ниацинамид",
            "default_time": "morning",
            "schedule_days": ["1", "3", "5"],
            "active": "true",
        },
    )
    assert r.status_code == 303
    
    result = await db_session.execute(select(SkincareProduct))
    products = result.scalars().all()
    assert len(products) == 1  # 1 new product added in test
    new_product = products[0]
    assert new_product.active_ingredient == "Ниацинамид"
    assert new_product.schedule_days == [1, 3, 5]
    assert new_product.default_time == "morning"

    # Test Delete Product
    r = await auth_client.post(f"/skincare/product/{new_product.id}/delete")
    assert r.status_code == 303
    
    result = await db_session.execute(select(SkincareProduct).where(SkincareProduct.id == new_product.id))
    assert result.scalar_one_or_none() is None


async def test_protocol_js_global_exposure(client):
    """Test that protocol.js exposes protocolForm globally with all required fields."""
    response = await client.get("/static/protocol.js")
    assert response.status_code == 200
    assert "window.protocolForm" in response.text
    # showFormModal must be inside the returned object (not a spread)
    assert "showFormModal: false" in response.text
    # Alpine.data registration is also present
    assert "_registerProtocolForm" in response.text


async def test_html_cache_control_headers(auth_client):
    """Test that HTML responses carry Cache-Control: no-store headers to prevent caching."""
    response = await auth_client.get("/supplements", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "Cache-Control" in response.headers
    assert "no-store" in response.headers["Cache-Control"]


async def test_hevy_dashboard_renders(auth_client):
    """GET /hevy returns the workouts dashboard structure."""
    response = await auth_client.get("/hevy", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "Недавние тренировки" in response.text
    assert "Упражнения" in response.text


async def test_hevy_sync_not_configured_redirects(auth_client):
    """POST /hevy/sync with no API key configured redirects with a status flag
    rather than erroring."""
    response = await auth_client.post("/hevy/sync")
    assert response.status_code == 303
    assert response.headers["location"] == "/hevy?sync=not_configured"


async def test_hevy_dashboard_shows_synced_workout(auth_client, db_session):
    """A synced workout appears on the dashboard and its exercise in the catalog."""
    from vitals.services import hevy_service

    class _FakeClient:
        is_configured = True

        async def fetch_workouts(self, *, max_pages=50):
            return [
                {
                    "id": "w1",
                    "title": "Day A — Push",
                    "start_time": "2026-06-10T10:00:00Z",
                    "end_time": "2026-06-10T11:00:00Z",
                    "updated_at": "2026-06-10T11:00:00Z",
                    "exercises": [
                        {
                            "index": 0,
                            "title": "Bench Press (Barbell)",
                            "exercise_template_id": "BENCH",
                            "sets": [{"index": 0, "type": "normal", "weight_kg": 80.0, "reps": 10}],
                        }
                    ],
                }
            ]

    await hevy_service.sync(db_session, _FakeClient())
    await db_session.commit()

    response = await auth_client.get("/hevy", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "Bench Press (Barbell)" in response.text


async def test_garmin_dashboard_renders(auth_client):
    """GET /garmin returns the recovery/activity dashboard structure."""
    response = await auth_client.get("/garmin", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "История метрик" in response.text
    assert "showHaeModal" in response.text
    assert "Импорт JSON" in response.text


async def test_garmin_sync_not_configured_redirects(auth_client):
    """POST /garmin/sync with no credentials redirects with a status flag."""
    response = await auth_client.post("/garmin/sync")
    assert response.status_code == 303
    assert response.headers["location"] == "/garmin?sync=not_configured"


async def test_garmin_health_auto_export_upload(auth_client, db_session):
    """POST /garmin/import ingests a Health Auto Export JSON file into daily rows."""
    import json as _json
    from vitals.models.garmin import GarminDaily

    payload = {
        "data": {
            "metrics": [
                {"name": "step_count", "units": "count",
                 "data": [{"date": "2026-06-11 00:00:00 +0000", "qty": 7200}]},
            ]
        }
    }
    r = await auth_client.post(
        "/garmin/import",
        files={"file": ("export.json", _json.dumps(payload), "application/json")},
    )
    assert r.status_code == 303
    assert "synced=1" in r.headers["location"]

    row = (await db_session.execute(
        select(GarminDaily).where(GarminDaily.date == __import__("datetime").date(2026, 6, 11))
    )).scalar_one_or_none()
    assert row is not None and row.steps == 7200


async def test_labs_dashboard_renders(auth_client, monkeypatch):
    """GET /labs returns the labs dashboard structure."""
    monkeypatch.setenv("VITALS_OPENROUTER_API_KEY", "")
    response = await auth_client.get("/labs", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "Последние значения" in response.text
    assert "Каталог маркеров" in response.text
    assert "Не настроена" in response.text
    assert "showUpload" in response.text
    assert "Добавить результаты" in response.text

    monkeypatch.setenv("VITALS_OPENROUTER_API_KEY", "sk-openrouter-test-key")
    response = await auth_client.get("/labs", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "LLM подключена" in response.text


async def test_labs_manual_add_and_flag(auth_client, db_session):
    """POST /labs/result stores a result with a computed flag."""
    from vitals.models.labs import LabResult

    r = await auth_client.post(
        "/labs/result",
        data={"date": "2026-06-10", "marker": "TSH", "value": 5.5, "unit": "mIU/L",
              "ref_low": 0.4, "ref_high": 4.0},
    )
    assert r.status_code == 303

    row = (await db_session.execute(select(LabResult))).scalar_one_or_none()
    assert row is not None
    assert row.marker == "TSH" and row.flag == "high"


async def test_labs_upload_without_llm_redirects(auth_client):
    """Uploading one or more documents with no OpenRouter key configured surfaces
    a status flag rather than erroring (LLM is optional)."""
    r = await auth_client.post(
        "/labs/upload",
        files=[("files", ("panel.png", b"\x89PNG\r\n\x1a\n-bytes", "image/png"))],
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/labs?upload=not_configured"


async def test_upload_extension_allowlist_rejected(auth_client):
    """Non-allowlisted upload types are rejected (415), so an attacker-controlled
    extension can't be stored under same-origin /static/uploads."""
    # Genetics expects .vcf/.txt — an .exe is refused before any DB work.
    r = await auth_client.post(
        "/genetics/import",
        files={"file": ("evil.exe", b"MZ...", "application/octet-stream")},
        data={"only_interpreted": "false"},
    )
    assert r.status_code == 415

    # Garmin import expects .json — an .csv is refused.
    r = await auth_client.post(
        "/garmin/import",
        files={"file": ("export.csv", b"a,b,c", "text/csv")},
    )
    assert r.status_code == 415


async def test_upload_read_capped_enforces_size_limit():
    """read_capped aborts with HTTP 413 once the body exceeds the cap."""
    from fastapi import HTTPException
    from web.uploads import read_capped

    class _BigFile:
        def __init__(self, total: int):
            self.remaining = total

        async def read(self, n: int = -1) -> bytes:
            if self.remaining <= 0:
                return b""
            give = min(n if n and n > 0 else self.remaining, self.remaining, 4096)
            self.remaining -= give
            return b"x" * give

    with pytest.raises(HTTPException) as exc:
        await read_capped(_BigFile(50), max_bytes=10)
    assert exc.value.status_code == 413


async def test_reports_dashboard_renders(auth_client):
    """GET /reports returns the goals + digest dashboard structure."""
    response = await auth_client.get("/reports", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "Цели" in response.text
    assert "Еженедельный разбор" in response.text


async def test_reports_create_milestone(auth_client, db_session):
    """POST /reports/milestone creates a goal card."""
    from vitals.models.milestones import Milestone

    r = await auth_client.post(
        "/reports/milestone",
        data={"name": "Дойти до 82", "domain": "weight", "target_value": 82.0,
              "target_unit": "кг", "deadline": "2026-09-01"},
    )
    assert r.status_code == 303

    row = (await db_session.execute(select(Milestone))).scalar_one_or_none()
    assert row is not None
    assert row.name == "Дойти до 82" and row.target_value == 82.0


async def test_reports_generate_digest_without_llm_redirects(auth_client):
    """Generating a digest with no OpenRouter key surfaces a status flag."""
    r = await auth_client.post("/reports/digest")
    assert r.status_code == 303
    assert r.headers["location"] == "/reports?digest=not_configured"


async def test_mobile_navigation_rendering_unauth(client):
    """Test that mobile navigation is not rendered when unauthenticated."""
    response = await client.get("/login", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "Еще" not in response.text


async def test_mobile_navigation_rendering_auth(auth_client):
    """Test that mobile navigation is rendered when authenticated."""
    response = await auth_client.get("/weight", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "Еще" in response.text
    assert "mobileMenuOpen" in response.text


async def test_alert_deduplication_and_resolve_all(auth_client, db_session):
    """Test that duplicate alerts (e.g. differing only by ё/о or case) are deduplicated,
    resolving one resolves its duplicates, and resolve-all endpoint resolves active alerts."""
    from vitals.models.system_alert import SystemAlert
    from vitals.services import alerts_service

    # Create duplicate alerts
    alert1 = SystemAlert(
        domain="labs",
        severity="info",
        message="Средний объём эритроцитов: 97.7 фл вне нормы (high).",
        alert_key="labs.out_of_range",
        entity_ref="marker_1"
    )
    alert2 = SystemAlert(
        domain="labs",
        severity="info",
        message="Средний объем эритроцитов: 97.7 фл вне нормы (high).",
        alert_key="labs.out_of_range",
        entity_ref="marker_2"
    )
    alert3 = SystemAlert(
        domain="labs",
        severity="info",
        message="Другой маркер вне нормы.",
        alert_key="labs.out_of_range",
        entity_ref="marker_3"
    )
    alert4 = SystemAlert(
        domain="weight",
        severity="info",
        message="Вес колеблется.",
        alert_key="weight.noise",
        entity_ref=""
    )
    db_session.add_all([alert1, alert2, alert3, alert4])
    await db_session.commit()

    # 1. Test deduplication in list_active
    active_labs = await alerts_service.list_active(db_session, domain="labs")
    # alert1 and alert2 are duplicates (ё vs о, capitalization aside).
    # So we should get alert3 and either alert1 or alert2. Total: 2 alerts.
    assert len(active_labs) == 2
    # Ensure messages are the distinct ones
    messages = {a.message for a in active_labs}
    assert len(messages) == 2

    # 2. Test that resolving one resolves its duplicates too
    await auth_client.post(f"/alerts/{alert1.id}/resolve")
    # Verify both alert1 and alert2 are now resolved in database
    await db_session.refresh(alert1)
    await db_session.refresh(alert2)
    assert alert1.resolved_at is not None
    assert alert2.resolved_at is not None
    # alert3 should still be unresolved
    await db_session.refresh(alert3)
    assert alert3.resolved_at is None

    # 3. Test resolve-all endpoint
    # First, let's resolve all labs alerts
    response = await auth_client.post("/alerts/resolve-all?domain=labs")
    assert response.status_code == 303
    
    # Verify alert3 is now resolved
    await db_session.refresh(alert3)
    assert alert3.resolved_at is not None

    # alert4 (domain weight) should still be unresolved
    await db_session.refresh(alert4)
    assert alert4.resolved_at is None

    # Resolve all without domain
    response = await auth_client.post("/alerts/resolve-all")
    assert response.status_code == 303
    await db_session.refresh(alert4)
    assert alert4.resolved_at is not None


async def test_progress_photo_upload_and_delete(auth_client, db_session):
    """Test that progress photos are correctly uploaded, saved on disk, and deleted."""
    import os
    from vitals.models.weight import ProgressPhoto
    from web.templating import STATIC_DIR

    photo_data = b"fake-jpeg-image-bytes"
    file_path = None

    try:
        # 1. Upload photo via /weight/photo
        response = await auth_client.post(
            "/weight/photo",
            files={"file": ("progress.jpg", photo_data, "image/jpeg")},
            data={"date": "2026-06-15", "note": "Integration progress photo"},
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/weight"

        # Confirm it is saved in the DB
        result = await db_session.execute(select(ProgressPhoto))
        photo = result.scalar_one_or_none()
        assert photo is not None
        assert photo.note == "Integration progress photo"
        assert photo.date.isoformat() == "2026-06-15"
        assert photo.file_key.startswith("uploads/")

        # Confirm it is saved on disk
        file_path = os.path.join(STATIC_DIR, photo.file_key)
        assert os.path.exists(file_path)
        with open(file_path, "rb") as f:
            assert f.read() == photo_data

        # 2. Delete photo via /weight/photo/delete (form POST with id)
        delete_response = await auth_client.post(
            "/weight/photo/delete",
            data={"id": photo.id},
        )
        assert delete_response.status_code == 303
        assert delete_response.headers["location"] == "/weight"

        # Confirm DB entry is deleted
        result2 = await db_session.execute(select(ProgressPhoto).where(ProgressPhoto.id == photo.id))
        assert result2.scalar_one_or_none() is None

        # Confirm file is deleted from disk
        assert not os.path.exists(file_path)
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass


async def test_progress_photo_multiple_upload_success(auth_client, db_session):
    """Test that multiple progress photos are correctly uploaded, saved on disk, and DB."""
    import os
    from vitals.models.weight import ProgressPhoto
    from web.templating import STATIC_DIR

    photo_data_1 = b"fake-jpeg-image-bytes-1"
    photo_data_2 = b"fake-jpeg-image-bytes-2"
    photo_data_3 = b"fake-jpeg-image-bytes-3"
    file_paths = []

    try:
        # Upload 3 photos via /weight/photo
        response = await auth_client.post(
            "/weight/photo",
            files=[
                ("files", ("progress1.jpg", photo_data_1, "image/jpeg")),
                ("files", ("progress2.jpg", photo_data_2, "image/jpeg")),
                ("files", ("progress3.jpg", photo_data_3, "image/jpeg")),
            ],
            data={"date": "2026-06-16", "note": "Multiple progress photos note"},
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/weight"

        # Confirm all 3 are saved in the DB
        result = await db_session.execute(select(ProgressPhoto).order_by(ProgressPhoto.id))
        photos = result.scalars().all()
        assert len(photos) == 3
        for idx, photo in enumerate(photos):
            assert photo.note == "Multiple progress photos note"
            assert photo.date.isoformat() == "2026-06-16"
            assert photo.file_key.startswith("uploads/")
            
            # Confirm saved on disk
            path = os.path.join(STATIC_DIR, photo.file_key)
            file_paths.append(path)
            assert os.path.exists(path)
            
            expected_data = [photo_data_1, photo_data_2, photo_data_3][idx]
            with open(path, "rb") as f:
                assert f.read() == expected_data

    finally:
        for path in file_paths:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass


async def test_progress_photo_multiple_upload_limit_exceeded(auth_client, db_session):
    """Test that uploading more than 5 progress photos is blocked with a 400 response."""
    from vitals.models.weight import ProgressPhoto

    photo_data = b"fake-jpeg-image-bytes"

    # Upload 6 photos via /weight/photo
    response = await auth_client.post(
        "/weight/photo",
        files=[
            ("files", ("p1.jpg", photo_data, "image/jpeg")),
            ("files", ("p2.jpg", photo_data, "image/jpeg")),
            ("files", ("p3.jpg", photo_data, "image/jpeg")),
            ("files", ("p4.jpg", photo_data, "image/jpeg")),
            ("files", ("p5.jpg", photo_data, "image/jpeg")),
            ("files", ("p6.jpg", photo_data, "image/jpeg")),
        ],
        data={"date": "2026-06-17", "note": "Should fail"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Можно загрузить не более 5 фотографий одновременно."

    # Confirm nothing is saved in the DB
    result = await db_session.execute(select(ProgressPhoto))
    photos = result.scalars().all()
    assert len(photos) == 0


async def test_progress_photo_upload_empty(auth_client, db_session):
    """Test that uploading without any files is blocked with a 400 response."""
    from vitals.models.weight import ProgressPhoto

    response = await auth_client.post(
        "/weight/photo",
        data={"date": "2026-06-17", "note": "Should fail"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Файлы не выбраны."

    # Confirm nothing is saved in the DB
    result = await db_session.execute(select(ProgressPhoto))
    photos = result.scalars().all()
    assert len(photos) == 0




# ── Dashboard modularity ────────────────────────────────────────────────────────


async def test_toggle_module_hides_and_shows_nav(auth_client, db_session):
    """Journey: toggle an Optional module via the client → DB changes → the nav
    link appears/disappears on the next dashboard GET, no page reload needed."""
    html_headers = {"Accept": "text/html"}

    # Enable hevy → link present in the header nav.
    r = await auth_client.post("/settings/modules", data={"module": "hevy", "enabled": "true"})
    assert r.status_code == 200
    # Response is an OOB nav fragment that swaps the header live (no reload).
    assert 'id="primary-nav"' in r.text
    assert 'hx-swap-oob="true"' in r.text
    assert 'href="/hevy"' in r.text
    page = await auth_client.get("/weight", headers=html_headers)
    assert 'href="/hevy"' in page.text

    # Disable hevy → DB reflects it, and the nav link is gone.
    r = await auth_client.post("/settings/modules", data={"module": "hevy", "enabled": "false"})
    assert r.status_code == 200
    row = await db_session.get(AppSetting, SETTINGS_KEY)
    assert row is not None and row.value["hevy"] is False

    page = await auth_client.get("/weight", headers=html_headers)
    assert 'href="/hevy"' not in page.text
    assert "Тренировки" not in page.text

    # Re-enable → link returns.
    r = await auth_client.post("/settings/modules", data={"module": "hevy", "enabled": "true"})
    assert r.status_code == 200
    page = await auth_client.get("/weight", headers=html_headers)
    assert 'href="/hevy"' in page.text


async def test_settings_page_renders_modules_card(auth_client):
    """The /settings page renders the modules card (core locked, optional toggle)."""
    r = await auth_client.get("/settings", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert "Модули дашборда" in r.text
    assert "v-switch" in r.text                       # toggle control present
    assert 'hx-post="/settings/modules"' in r.text    # optional toggles wired to the endpoint
    assert "базовый" in r.text                         # core badge


async def test_disabled_module_route_redirects(auth_client):
    """A disabled Optional module's page redirects to the dashboard (browser GET)."""
    await auth_client.post("/settings/modules", data={"module": "glp1", "enabled": "false"})

    r = await auth_client.get("/glp1", headers={"Accept": "text/html"})
    assert r.status_code == 303
    assert r.headers["location"] == "/weight"

    # Re-enabling makes it reachable again.
    await auth_client.post("/settings/modules", data={"module": "glp1", "enabled": "true"})
    r = await auth_client.get("/glp1", headers={"Accept": "text/html"})
    assert r.status_code == 200


async def test_core_module_toggle_rejected(auth_client, db_session):
    """Core modules cannot be disabled — the endpoint returns 400."""
    r = await auth_client.post("/settings/modules", data={"module": "weight", "enabled": "false"})
    assert r.status_code == 400
    assert "error" in r.json()

    # And the (still core) module remains enabled.
    page = await auth_client.get("/weight", headers={"Accept": "text/html"})
    assert 'href="/weight"' in page.text


async def test_modules_endpoint_csrf_origin_check(auth_client):
    """Cross-origin POSTs are blocked by the origin-check middleware (403)."""
    r = await auth_client.post(
        "/settings/modules",
        data={"module": "hevy", "enabled": "false"},
        headers={"Origin": "http://evil.example"},
    )
    assert r.status_code == 403


async def test_modules_endpoint_rate_limited(auth_client):
    """The save endpoint is rate-limited via Redis (429 once the window is full)."""
    statuses = []
    for _ in range(35):
        r = await auth_client.post("/settings/modules", data={"module": "hevy", "enabled": "true"})
        statuses.append(r.status_code)

    assert statuses[0] == 200          # first request allowed
    assert 429 in statuses             # limiter eventually trips
