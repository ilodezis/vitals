"""Integration tests for the Vitals FastAPI web panel and router endpoints."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select

from vitals.models.app_settings import AppSetting
from vitals.models.conflict_rule import ConflictRule
from vitals.models.labs import LabResult
from vitals.models.raw_payload import RawPayload
from vitals.models.system_alert import SystemAlert
from vitals.models.weight import WeightLog
from vitals.services.modules_service import SETTINGS_KEY
from vitals.utils.timeutils import today_local

# No module-level ``pytest.mark.asyncio``: pytest.ini runs asyncio_mode=auto, and
# the mark on this file's *sync* template tests only produced warnings.


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
    assert res_data["scheduler"] == "ok"
    # Job ids name the modules this install runs — a stranger gets the verdict,
    # not the diagnosis.
    assert "stale_jobs" not in res_data
    assert "scheduler_heartbeat_age_seconds" not in res_data


async def test_unauthorized_redirects(client):
    """GET requests to authed pages redirect to login, while JSON endpoints return 401."""
    # Navigation GET request should redirect to /login
    response = await client.get("/weight", headers={"Accept": "text/html"})
    assert response.status_code == 302
    parsed = urlsplit(response.headers["location"])
    assert parsed.path == "/login"
    assert parse_qs(parsed.query)["next"][0] == "/weight"

    # API POST request should return 401 Unauthorized
    response = await client.post("/weight/log", data={"weight_kg": 80.0, "date": "2026-06-22"})
    assert response.status_code == 401


async def test_login_page_renders(client):
    """GET /login renders the sign-in form: heading, both fields, submit."""
    response = await client.get("/login", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "С возвращением" in response.text
    assert 'id="lg-username"' in response.text
    assert 'id="lg-password"' in response.text
    # Nothing about the data itself before auth — no subtitle, no stats.
    assert "Личный кабинет здоровья" not in response.text


async def test_login_form_failure(client):
    """POST /login with invalid credentials returns form with error code."""
    response = await client.post(
        "/login",
        data={"username": "wrong-user", "password": "wrong-password"},
        headers={"Accept": "text/html"},
    )
    assert response.status_code == 200
    assert "Неверное имя пользователя или пароль" in response.text
    # The message stands on its own — the old "Ошибка: " prefix is gone.
    assert "Ошибка: " not in response.text
    assert "lg-field is-error" in response.text


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


async def test_navigation_is_a_real_page_load(auth_client):
    """The "graphs/tables/inputs randomly don't load until reload" bug came from
    hx-boost swapping <body> on every tap, and htmx's view-transition wrapper
    around that swap had to be switched off because an interrupted one left the
    page half-rendered. Navigation is now the browser's own: no boost anywhere
    in the frame, and the page transition is the CSS cross-document one, which
    has no script step to interrupt."""
    html = (await auth_client.get("/weight", headers={"Accept": "text/html"})).text
    assert 'hx-boost="true"' not in html
    assert "globalViewTransitions = true" not in html
    css = (Path(__file__).resolve().parent.parent / "web" / "static" / "vitals.css").read_text(encoding="utf-8")
    assert "@view-transition" in css and "navigation: auto" in css
    # In-page htmx swaps (a save re-rendering <main>) keep their watchdog.
    assert "Alpine.initTree" in html
    assert "_x_dataStack" in html  # guard against Alpine double-init


async def test_plain_post_forms_still_ask_before_deleting(auth_client):
    """Without hx-boost a delete form is a plain browser post, which htmx's
    htmx:confirm hook never sees — the capture-phase submit listener has to ask
    instead, or every trash icon deletes on the first tap."""
    html = (await auth_client.get("/weight", headers={"Accept": "text/html"})).text
    assert 'data-confirm="' in html  # the page does carry a confirmed delete form
    assert "form.hasAttribute('data-confirm')" in html
    assert "form.requestSubmit(submitter" in html
    assert "htmx:confirm" in html  # hx-post elements keep the htmx route


async def test_a_post_that_lands_back_on_its_page_keeps_the_scroll(auth_client):
    html = (await auth_client.get("/weight", headers={"Accept": "text/html"})).text
    assert "sessionStorage.setItem('vitals_scroll'" in html
    assert "held.path === location.pathname" in html


def test_body_script_const_is_iife_scoped():
    """Regression lock for a second, sharper cause of the same "randomly dead
    until reload" bug: the <script> in base.html's <body> (toast/confirm/loader/
    slowRoutes helpers) re-runs on every hx-boost swap. A bare top-level `const
    slowRoutes` there collided with itself on the second boosted navigation —
    inline <script> declarations share one global lexical scope across separate
    executions, so redeclaring a `const` throws a SyntaxError from inside htmx's
    own script-execution step, aborting the rest of that swap's script processing
    (including any page-specific <script> further down, e.g. nutrition.js). The
    const must stay wrapped in an IIFE so each re-execution gets a fresh scope."""
    base_html = (
        Path(__file__).resolve().parent.parent / "web" / "templates" / "base.html"
    ).read_text(encoding="utf-8")
    iife_start = base_html.index("(function () {\n        // Transient toast")
    const_pos = base_html.index("const slowRoutes = {", iife_start)
    iife_end = base_html.index("})();\n    </script>", iife_start)
    assert iife_start < const_pos < iife_end


def test_page_dashboards_register_as_plain_globals():
    """Regression lock: weightOSDashboard/glp1Dashboard/nutritionDashboard must be
    plain `window.X = function ...` assignments, not Alpine.data() factories wired
    up via a `document.addEventListener('alpine:init', ...)` listener. alpine:init
    fires exactly once, at Alpine's initial boot; these scripts live in <body> and
    re-run on every hx-boost swap, so a listener registered on a later boosted
    navigation is dead on arrival — the component factory never registers, and
    Alpine throws "X is not defined" the first time that page is reached via SPA
    navigation instead of a hard reload (hit in production for nutritionDashboard,
    2026-07-10)."""
    static_dir = Path(__file__).resolve().parent.parent / "web" / "static"
    checks = {
        "app.js": "weightOSDashboard",
        "glp1.js": "glp1Dashboard",
        "nutrition.js": "nutritionDashboard",
        "labs_upload.js": "labsUpload",
    }
    for filename, name in checks.items():
        src = (static_dir / filename).read_text(encoding="utf-8")
        assert f"window.{name} = function" in src
        assert f"Alpine.data('{name}'" not in src


def test_page_controller_scripts_load_once_from_head():
    """Regression lock for the race the plain-globals fix above didn't cover:
    window.X = function stopped the *permanent* "never registers after the first
    boost" failure, but each controller was still loaded via <script src> inside
    its own page's swapped <body> content — a brand-new DOM node (and thus a fresh
    async fetch) on every hx-boost navigation. Alpine's MutationObserver reacts to
    that DOM insertion within a microtask, almost always before the network fetch
    resolves, so x-data="nutritionDashboard()" evaluates while the function is
    still undefined. Alpine then silently falls back to x-data="{}" instead of
    throwing, so the swap watchdog's `!_x_dataStack` "did the observer miss this
    root" check never fires for it either (hit in production for
    nutritionDashboard, 2026-07-10, despite the plain-globals fix already being
    live). Fix: load these once from <head> with defer, exactly like Alpine
    itself, so they're always ready before Alpine ever touches a swapped page."""
    templates_dir = Path(__file__).resolve().parent.parent / "web" / "templates"
    base_html = (templates_dir / "base.html").read_text(encoding="utf-8")

    scripts = [
        "app.js", "glp1.js", "nutrition.js", "protocol.js", "charts.js",
        "garmin.js", "garmin_sleep.js", "labs_upload.js",
    ]
    alpine_pos = base_html.index('id="alpine-script"')
    for filename in scripts:
        tag = f"<script defer src=\"{{{{ static_version('/static/{filename}') }}}}\">"
        pos = base_html.index(tag)
        assert pos < alpine_pos, f"{filename} must load (and be deferred) before Alpine boots"

    # None of the pages that use these controllers may still load them a second
    # time from within the swapped <body> content — that would reintroduce the
    # exact per-navigation re-fetch race this test guards against.
    page_templates = [
        "nutrition/index.html",
        "glp1/index.html",
        "weight/index.html",
        "skincare/index.html",
        "supplements/index.html",
        "charts/index.html",
        "garmin/index.html",
        "garmin/sleep.html",
        "garmin/sleep_list.html",
        "garmin/activities.html",
    ]
    for rel_path in page_templates:
        html = (templates_dir / rel_path).read_text(encoding="utf-8")
        for filename in scripts:
            assert f"'/static/{filename}'" not in html, f"{rel_path} must not also load {filename}"


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


async def test_log_weight_without_javascript(auth_client, db_session):
    """The form's own submission, before Alpine takes it over, still saves.

    The hidden ``override`` input is bound by ``x-model``, so without Alpine it
    goes out empty; that must read as "no override", not fail validation."""
    response = await auth_client.post(
        "/weight/log",
        data={"weight_kg": 84.2, "date": "2026-06-11", "override": ""},
    )
    assert response.status_code == 303

    result = await db_session.execute(select(WeightLog).where(WeightLog.weight_kg == 84.2))
    assert result.scalar_one_or_none() is not None


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
    assert "Новая запись" in response.text


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
    assert r.status_code == 200 and "Добавки" in r.text

    r = await auth_client.get("/genetics", headers={"Accept": "text/html"})
    assert r.status_code == 200 and "Генетика" in r.text
    assert "Импорт VCF" in r.text

    r = await auth_client.get("/skincare", headers={"Accept": "text/html"})
    assert r.status_code == 200 and "Кожа" in r.text
    assert "Схема ухода по дням недели" in r.text
    assert "Понедельник" in r.text


async def test_genetics_dashboard_post_import_view(auth_client):
    """After import, genetics dashboard initializes with admin panels hidden."""
    r = await auth_client.get("/genetics?imported=29&markers=1", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert "Генетика" in r.text
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


async def test_genetics_save_dedupes_by_rsid(auth_client, db_session):
    """Saving the same rsID twice from the manual form updates in place — never
    a duplicate row or a 500 from the uq_genetic_variant_rsid constraint."""
    from vitals.models.genetics import GeneticVariant

    r1 = await auth_client.post(
        "/genetics/save", data={"gene": "HFE", "rsid": "rs1800562", "genotype": "G/G"}
    )
    assert r1.status_code == 303
    r2 = await auth_client.post(
        "/genetics/save", data={"gene": "HFE", "rsid": "rs1800562", "genotype": "A/G"}
    )
    assert r2.status_code == 303

    rows = (await db_session.execute(select(GeneticVariant))).scalars().all()
    assert len(rows) == 1
    assert rows[0].genotype == "A/G"


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


async def test_edit_measurement_blank_field_clears_it(auth_client, db_session):
    """The edit form posts every field it renders, so an emptied input has to
    delete the value. FastAPI turns a blank number input into None, which the
    service's partial merge used to read as "not passed" and silently restore."""
    from datetime import date
    from vitals.services import weight_service

    m = await weight_service.upsert_body_measurement(
        db_session,
        on_date=date(2026, 6, 13),
        neck_cm=39.0,
        waist_cm=86.0,
        note="morning",
    )
    await db_session.commit()

    response = await auth_client.post(
        "/weight/measurement",
        data={
            "id": m.id,
            "date": "2026-06-13",
            "neck_cm": "",
            "waist_cm": "85.0",
            "note": "",
        },
    )
    assert response.status_code == 303

    await db_session.refresh(m)
    assert m.waist_cm == 85.0
    assert m.neck_cm is None
    assert m.note is None
    assert m.body_fat_pct is None


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


async def test_garmin_sleep_night_page_renders(auth_client, db_session):
    """GET /garmin/sleep/<date> renders the night's hypnogram + curve data."""
    from datetime import date, datetime

    from vitals.models.garmin import GarminDaily, GarminIntraday

    db_session.add_all([
        GarminDaily(
            date=date(2026, 6, 10), domain="garmin", source="garmin_api",
            sleep_seconds=27000, sleep_score=78, avg_sleep_hr=54, spo2_lowest=91,
            sleep_start=datetime(2026, 6, 9, 23, 0), sleep_end=datetime(2026, 6, 10, 6, 30),
            sleep_stages=[
                {"start": "2026-06-09T23:00:00", "end": "2026-06-10T01:00:00", "stage": "deep"},
            ],
        ),
        GarminIntraday(
            date=date(2026, 6, 10), domain="garmin", source="garmin_api",
            series_type="sleep_hr", ts=datetime(2026, 6, 9, 23, 10), value=58.0,
        ),
    ])
    await db_session.commit()

    response = await auth_client.get("/garmin/sleep/2026-06-10", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "Фазы сна" in response.text
    assert "garminHypnogram" in response.text
    # The chart data is handed to the renderer, not fetched by it.
    assert "vitalsGarminSleep" in response.text
    assert "sleep_hr" in response.text


async def test_garmin_sleep_night_page_unknown_date_is_404(auth_client):
    response = await auth_client.get("/garmin/sleep/2019-01-01", headers={"Accept": "text/html"})
    assert response.status_code == 404


async def test_garmin_sleep_list_renders(auth_client, db_session):
    """GET /garmin/sleep lists nights (days with sleep data), newest first, each
    row linking to its own detail page."""
    from datetime import date

    from vitals.models.garmin import GarminDaily

    db_session.add_all([
        GarminDaily(date=date(2026, 6, 9), domain="garmin", source="garmin_api", sleep_seconds=25200, sleep_score=70),
        GarminDaily(date=date(2026, 6, 10), domain="garmin", source="garmin_api", sleep_seconds=27000, sleep_score=78),
    ])
    await db_session.commit()

    response = await auth_client.get("/garmin/sleep", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "/garmin/sleep/2026-06-10" in response.text
    assert "/garmin/sleep/2026-06-09" in response.text


async def test_garmin_sleep_list_hero_card_and_rows(auth_client, db_session):
    """The latest night gets a hero card (date, duration, score, phase bar);
    every night below it is a full-row link with its own mini phase bar and a
    correctly signed Body Battery delta (never the old force-prefixed "+-12")."""
    from datetime import date

    from vitals.models.garmin import GarminDaily

    db_session.add_all([
        GarminDaily(
            date=date(2026, 6, 9), domain="garmin", source="garmin_api",
            sleep_seconds=25200, sleep_score=70, awake_count=3,
            body_battery_change=-12,
        ),
        GarminDaily(
            date=date(2026, 6, 10), domain="garmin", source="garmin_api",
            sleep_seconds=27000, sleep_score=78, awake_count=1,
            body_battery_change=18,
            deep_sleep_seconds=5400, light_sleep_seconds=14400,
            rem_sleep_seconds=5400, awake_seconds=1800,
        ),
    ])
    await db_session.commit()

    response = await auth_client.get("/garmin/sleep", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "Прошлая ночь" in response.text
    assert "v-phase-seg violet" in response.text
    assert "v-phase-seg cool" in response.text
    assert "v-phase-seg good" in response.text
    assert "v-phase-seg muted" in response.text
    assert "Фазы" in response.text
    assert "+18" in response.text
    assert "-12" in response.text
    assert "+-12" not in response.text


async def test_garmin_sleep_night_page_body_battery_sign(auth_client, db_session):
    """Regression: a negative overnight Body Battery change renders as "-12",
    never "+-12" (the sign used to be force-prefixed regardless). The
    awakenings/restless caption moved off the BB tile's footer onto its own
    line but must still render somewhere on the page."""
    from datetime import date

    from vitals.models.garmin import GarminDaily

    db_session.add(GarminDaily(
        date=date(2026, 6, 10), domain="garmin", source="garmin_api",
        sleep_seconds=27000, body_battery_change=-12,
        awake_count=2, restless_moments=15,
    ))
    await db_session.commit()

    response = await auth_client.get("/garmin/sleep/2026-06-10", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "+-12" not in response.text
    assert "-12" in response.text
    assert "Пробуждения: 2" in response.text
    assert "ворочания: 15" in response.text


async def test_garmin_sleep_night_page_masthead_and_nav(auth_client, db_session):
    """Masthead mode gets the shared editorial header (title = the night's own
    date, metrics = score/HR/SpO2/BB) instead of the classic card, and the
    prev/next night arrows link to the correct adjacent dates in both shells."""
    from datetime import date

    from vitals.models.garmin import GarminDaily

    db_session.add_all([
        GarminDaily(date=date(2026, 6, 9), domain="garmin", source="garmin_api", sleep_seconds=25200, sleep_score=70),
        GarminDaily(
            date=date(2026, 6, 10), domain="garmin", source="garmin_api",
            sleep_seconds=27000, sleep_score=78, avg_sleep_hr=54, spo2_lowest=91, body_battery_change=18,
        ),
        GarminDaily(date=date(2026, 6, 11), domain="garmin", source="garmin_api", sleep_seconds=26000, sleep_score=80),
    ])
    await db_session.commit()

    r = await auth_client.get("/garmin/sleep/2026-06-10", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert 'class="mh-head"' in r.text
    assert "10-06-2026" in r.text
    assert 'href="/garmin/sleep/2026-06-09"' in r.text
    assert 'href="/garmin/sleep/2026-06-11"' in r.text

    # Oldest night: no earlier neighbor, prev arrow renders disabled (no link).
    r = await auth_client.get("/garmin/sleep/2026-06-09", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert 'href="/garmin/sleep/2026-06-08"' not in r.text
    assert "is-disabled" in r.text


async def test_garmin_activities_list_renders(auth_client, db_session):
    """GET /garmin/activities renders the full activity list (moved off the
    overview page onto its own full-width tab)."""
    from datetime import date, datetime

    from vitals.models.garmin import GarminActivity

    db_session.add(GarminActivity(
        date=date(2026, 6, 10), domain="garmin", source="garmin_api",
        external_id="act-1", activity_type="running", name="Вечерняя пробежка",
        start_time=datetime(2026, 6, 10, 18, 0), duration_seconds=1800,
    ))
    await db_session.commit()

    response = await auth_client.get("/garmin/activities", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "Вечерняя пробежка" in response.text


async def test_garmin_tabs_mark_the_right_tab_active(auth_client):
    """The overview/sleep/activities sub-tab bar renders on all three top-level
    Garmin routes with exactly the current one marked is-active."""
    for route in ("/garmin", "/garmin/sleep", "/garmin/activities"):
        r = await auth_client.get(route, headers={"Accept": "text/html"})
        assert f'href="{route}" class="mh-tab is-active"' in r.text


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


async def test_garmin_dashboard_day_strip_renders_in_masthead(auth_client, db_session):
    """The day-strip (steps/stress/sleep score/intensity minutes/active calories)
    used to live only in a classic-only grid, so masthead lost 5 of 9 daily
    metrics. It's now a shared card — regression-check it actually shows up
    once the session is switched to masthead.

    Readiness and training status were dropped from the strip: they only exist on
    watches with trainingReadinessCapable / trainingStatusCapable, so on a
    vívoactive-class device they rendered "—" forever."""
    from datetime import date

    from vitals.models.garmin import GarminDaily

    db_session.add(GarminDaily(
        date=date(2026, 6, 15), domain="garmin", source="garmin_api",
        steps=12345, avg_stress=33, sleep_score=86, active_calories=612,
        intensity_minutes_moderate=36, intensity_minutes_vigorous=22,
    ))
    await db_session.commit()

    response = await auth_client.get("/garmin", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "12 345" in response.text
    assert "Оценка сна" in response.text and "86" in response.text
    # Garmin weights a vigorous minute double: 36 + 2×22 = 80.
    assert "80" in response.text
    assert "умер. 36 · интенс. 22" in response.text
    assert "Тренировочный статус" not in response.text


async def test_garmin_dashboard_no_longer_lists_activities(auth_client, db_session):
    """Activities moved to their own tab — the overview page must not
    render them a second time."""
    from datetime import date, datetime

    from vitals.models.garmin import GarminActivity

    db_session.add(GarminActivity(
        date=date(2026, 6, 10), domain="garmin", source="garmin_api",
        external_id="act-overview-check", activity_type="running",
        name="Контрольная пробежка", start_time=datetime(2026, 6, 10, 18, 0),
        duration_seconds=1800,
    ))
    await db_session.commit()

    response = await auth_client.get("/garmin", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "Контрольная пробежка" not in response.text


async def test_garmin_history_table_drops_sleep_column(auth_client, db_session):
    """The metrics-history table used to duplicate sleep duration (with its own
    link into the night page); sleep now lives only on its own tab. Regression:
    a history-only row's sleep duration must not render anywhere on /garmin."""
    from datetime import date

    from vitals.models.garmin import GarminDaily

    db_session.add_all([
        GarminDaily(
            date=date(2026, 6, 9), domain="garmin", source="garmin_api",
            sleep_seconds=9000, resting_hr=47,
        ),
        # The newest *reported* day, so it is the one the masthead reads — a row
        # with nothing on it at all is a placeholder and latest_daily skips it,
        # which would put the older row's sleep back in the header.
        GarminDaily(
            date=date(2026, 6, 16), domain="garmin", source="garmin_api",
            sleep_seconds=None, resting_hr=50,
        ),
    ])
    await db_session.commit()

    response = await auth_client.get("/garmin", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "2h 30m" not in response.text


async def test_garmin_activities_card_shows_distance_calories_hr(auth_client, db_session):
    """The activity card's collapsed view must surface distance/calories/HR —
    fields that were captured in the DB but had no home in the UI before."""
    from datetime import date, datetime

    from vitals.models.garmin import GarminActivity

    db_session.add(GarminActivity(
        date=date(2026, 6, 10), domain="garmin", source="garmin_api",
        external_id="act-detail-check", activity_type="running", name="Темповый бег",
        start_time=datetime(2026, 6, 10, 18, 0), duration_seconds=1800,
        distance_m=5230.0, calories=412, avg_hr=142, max_hr=168,
    ))
    await db_session.commit()

    response = await auth_client.get("/garmin/activities", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "10-06-2026 18:00" in response.text
    assert "5.23" in response.text
    assert "412" in response.text
    assert "142" in response.text
    assert "168" in response.text


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


async def test_delete_controls_render_for_labs_skincare_and_hrt(auth_client, db_session):
    """Four delete routes existed with no button anywhere — a mis-parsed lab
    result, a diary entry, an observation and a whole cycle could only be removed
    through the API. Also covers the diary/observation lists themselves, which the
    skincare page never rendered."""
    from vitals.services import (
        hrt_cycle_service,
        labs_service,
        skincare_service,
    )
    from vitals.utils.timeutils import today_local

    day = today_local()
    result = await labs_service.add_result(
        db_session, on_date=day, marker="TSH", value=5.5, ref_low=0.4, ref_high=4.0
    )
    log = await skincare_service.upsert_log(db_session, on_date=day, retinoid=True)
    obs = await skincare_service.add_observation(
        db_session, on_date=day, inflammation=3, zone="cheeks"
    )
    cycle = await hrt_cycle_service.add_cycle(db_session, kind="course", start_date=day)
    await db_session.commit()

    page = (await auth_client.get("/labs", headers={"Accept": "text/html"})).text
    assert f'action="/labs/result/{result.id}/delete"' in page

    page = (await auth_client.get("/skincare", headers={"Accept": "text/html"})).text
    assert f'action="/skincare/log/{log.id}/delete"' in page
    assert f'action="/skincare/observation/{obs.id}/delete"' in page
    assert "Ретиноид" in page  # the diary row shows what was actually applied
    assert "Воспаление 3/5" in page

    page = (await auth_client.get("/hrt", headers={"Accept": "text/html"})).text
    assert f'action="/hrt/cycle/{cycle.id}/delete"' in page


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


async def test_labs_manual_add_with_a_cyrillic_marker_over_fetch(auth_client, db_session):
    """The form now posts through the shared conflict-aware controller, which sends
    ``hx-request`` — and that turns the redirect into an ``HX-Redirect`` *header*.
    Headers are latin-1, so a raw "Ферритин" in the URL is a 500, not a bad link."""
    from vitals.models.labs import LabResult

    r = await auth_client.post(
        "/labs/result",
        data={"date": "2026-06-10", "marker": "Ферритин", "value": 120,
              "ref_low": 30, "ref_high": 400},
        headers={"hx-request": "true"},
    )
    assert r.status_code == 303
    assert "%D0%A4" in r.headers["HX-Redirect"]

    row = (await db_session.execute(select(LabResult))).scalar_one()
    assert row.marker == "Ферритин"


async def test_labs_unit_html_is_escaped_in_render(auth_client):
    """A unit value containing HTML must render escaped, never as live markup —
    labs.unit can come from a mis-parsed photo import, so it isn't trusted input."""
    r = await auth_client.post(
        "/labs/result",
        data={"date": "2026-06-10", "marker": "WBC", "value": 5.5,
              "unit": "<img src=x onerror=alert(1)>", "ref_low": 4.0, "ref_high": 10.0},
    )
    assert r.status_code == 303

    response = await auth_client.get("/labs", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "<img src=x onerror=alert(1)>" not in response.text
    assert "&lt;img src=x onerror=alert(1)&gt;" in response.text


async def test_labs_unit_superscript_still_renders(auth_client):
    """Regression guard: the 10^9 -> <sup>9</sup> substitution must survive the
    escaping fix (applied to the already-escaped string, not via | safe)."""
    r = await auth_client.post(
        "/labs/result",
        data={"date": "2026-06-10", "marker": "Neutrophils", "value": 4.2,
              "unit": "10^9/L", "ref_low": 1.8, "ref_high": 7.5},
    )
    assert r.status_code == 303

    response = await auth_client.get("/labs", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "10<sup>9</sup>/L" in response.text


async def test_labs_upload_without_llm_returns_json(auth_client):
    """Uploading with no OpenRouter key configured surfaces a JSON flag rather
    than erroring (LLM is optional). A later change turned /labs/upload from a redirecting
    form endpoint into a single-file JSON preview endpoint (upload -> preview ->
    confirm), so this no longer redirects — the client shows the flag and moves
    on to the next queued file."""
    r = await auth_client.post(
        "/labs/upload",
        files={"file": ("panel.png", b"\x89PNG\r\n\x1a\n-bytes", "image/png")},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert data["reason"] == "not_configured"
    assert data["message"]


async def test_labs_upload_extraction_failure_returns_error_json(auth_client, monkeypatch):
    """A file that fails vision extraction surfaces ok:false/reason:error in the
    JSON response (the original failure-signalling intent, now at single-file
    granularity — multi-file batching moved into a client-side queue)."""
    from vitals.services import labs_service

    async def fake_extract(contents, *, llm, content_type, filename=None):
        raise ValueError("could not parse")

    monkeypatch.setattr(labs_service, "extract_from_file", fake_extract)

    r = await auth_client.post(
        "/labs/upload",
        files={"file": ("bad.png", b"\x89PNG\r\n\x1a\n-bytes", "image/png")},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert data["reason"] == "error"


async def test_failed_extraction_leaves_no_orphan_file(auth_client, monkeypatch):
    """The document used to be written to disk before extraction ran, so every
    failed parse left a file nothing in the DB referenced — unreachable from the
    UI and accumulating silently. Nothing is written unless the parse succeeds."""
    import os

    from vitals.services import labs_service
    from web.templating import STATIC_DIR

    uploads = os.path.join(STATIC_DIR, "uploads", "labs")
    before = set(os.listdir(uploads)) if os.path.isdir(uploads) else set()

    async def fake_extract(contents, *, llm, content_type, filename=None):
        raise ValueError("could not parse")

    monkeypatch.setattr(labs_service, "extract_from_file", fake_extract)

    r = await auth_client.post(
        "/labs/upload",
        files={"file": ("bad.png", b"\x89PNG\r\n\x1a\n-bytes", "image/png")},
    )
    assert r.json()["ok"] is False

    after = set(os.listdir(uploads)) if os.path.isdir(uploads) else set()
    assert after == before


async def test_labs_upload_returns_preview_without_persisting_results(auth_client, db_session, monkeypatch):
    """Regression: /labs/upload must extract and return an editable preview
    without writing any LabResult — the whole point of the preview step is that
    a misread value never reaches the DB until the owner confirms it."""
    from vitals.services import labs_service

    payload = {
        "date": "2026-06-10",
        "lab_name": "Synevo",
        "results": [{"marker": "Ferritin", "value": 95, "unit": "ng/mL", "ref_low": 30, "ref_high": 400}],
    }

    async def fake_extract(contents, *, llm, content_type, filename=None):
        return payload

    monkeypatch.setattr(labs_service, "extract_from_file", fake_extract)

    r = await auth_client.post(
        "/labs/upload",
        files={"file": ("panel.png", b"\x89PNG\r\n\x1a\n-bytes", "image/png")},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["lab"]["date"] == "2026-06-10"
    assert data["lab"]["lab_name"] == "Synevo"
    assert data["lab"]["markers"] == [
        {"marker": "Ferritin", "value": 95.0, "unit": "ng/mL", "ref_low": 30.0, "ref_high": 400.0}
    ]

    results = (await db_session.execute(select(LabResult))).scalars().all()
    assert results == []

    raw = await db_session.get(RawPayload, data["lab"]["raw_payload_id"])
    assert raw is not None and raw.processed_at is None


async def test_labs_confirm_persists_edited_markers(auth_client, db_session, monkeypatch):
    """Regression: /labs/confirm must save the owner's edits, not the raw OCR
    values — proves the edit-before-save step actually takes effect."""
    from vitals.services import labs_service

    payload = {
        "date": "2026-06-10",
        "lab_name": "Synevo",
        "results": [{"marker": "Ferritin", "value": 95, "unit": "ng/mL", "ref_low": 30, "ref_high": 400}],
    }

    async def fake_extract(contents, *, llm, content_type, filename=None):
        return payload

    monkeypatch.setattr(labs_service, "extract_from_file", fake_extract)

    upload_r = await auth_client.post(
        "/labs/upload",
        files={"file": ("panel.png", b"\x89PNG\r\n\x1a\n-bytes", "image/png")},
    )
    lab = upload_r.json()["lab"]

    # Owner corrects a misread value (95 -> 105) before saving.
    confirm_r = await auth_client.post(
        "/labs/confirm",
        json={
            "date": lab["date"],
            "lab_name": lab["lab_name"],
            "file_key": lab["file_key"],
            "raw_payload_id": lab["raw_payload_id"],
            "markers": [{**lab["markers"][0], "value": 105}],
        },
    )
    assert confirm_r.status_code == 200
    assert confirm_r.json() == {"ok": True, "created": 1}

    results = (await db_session.execute(select(LabResult))).scalars().all()
    assert len(results) == 1
    assert results[0].marker == "Ferritin"
    assert results[0].value == 105.0

    raw = await db_session.get(RawPayload, lab["raw_payload_id"])
    assert raw is not None and raw.processed_at is not None


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


async def test_reports_moves_reached_goals_to_a_green_archive(auth_client, db_session):
    """A crossed goal leaves the active grid for the archive, tinted as a win,
    and a missed deadline on a live goal says overdue instead of negative days."""
    from datetime import timedelta

    from vitals.services import milestones_service, weight_service
    from vitals.utils.timeutils import today_local

    today = today_local()
    await weight_service.log_weight(db_session, on_date=today, weight_kg=104.1)
    await milestones_service.create_milestone(
        db_session, name="Дойти до 105", domain="weight", target_value=105.0,
        target_unit="кг", deadline=today - timedelta(days=41),
    )
    await milestones_service.create_milestone(
        db_session, name="Дойти до 100", domain="weight", target_value=100.0,
        target_unit="кг", deadline=today - timedelta(days=3),
    )
    await db_session.commit()

    html = (await auth_client.get("/reports", headers={"Accept": "text/html"})).text
    active, archive = html.split("Архив целей", 1)
    assert "Дойти до 100" in active and "Дойти до 105" not in active
    assert "осталось 4,1" in active
    assert "просрочено на 3 дн." in active
    assert "Дойти до 105" in archive and "is-won" in archive
    assert "позже дедлайна" in archive
    assert "-41" not in html and "-3 дн." not in html


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


async def test_reports_create_body_comp_milestone(auth_client, db_session):
    """POST /reports/milestone creates a body composition goal card."""
    from vitals.models.milestones import Milestone

    r = await auth_client.post(
        "/reports/milestone",
        data={"name": "Снизить процент жира до 15%", "domain": "body_comp", "target_value": 15.0,
              "target_unit": "%", "deadline": "2026-09-01"},
    )
    assert r.status_code == 303

    rows = (await db_session.execute(select(Milestone))).scalars().all()
    row = next((x for x in rows if x.domain == "body_comp"), None)
    assert row is not None
    assert row.name == "Снизить процент жира до 15%"
    assert row.target_value == 15.0


async def test_reports_generate_digest_without_llm_redirects(auth_client):
    """Generating a digest with no OpenRouter key surfaces a status flag."""
    r = await auth_client.post("/reports/digest")
    assert r.status_code == 303
    assert r.headers["location"] == "/reports?digest=not_configured"


async def test_mobile_navigation_rendering_unauth(client):
    """Test that mobile navigation is not rendered when unauthenticated."""
    response = await client.get("/login", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "Ещё" not in response.text


async def test_mobile_navigation_rendering_auth(auth_client):
    """Test that mobile navigation is rendered when authenticated.

    Five fixed columns: Today, three slots, More — and no drawer any more, so the
    "More" cell is a link to the /more page, not a button that opens an overlay.
    """
    response = await auth_client.get("/weight", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "Ещё" in response.text
    assert 'href="/more"' in response.text
    assert "mobileMenuOpen" not in response.text


async def test_alerts_with_same_text_are_distinct_and_resolve_all(auth_client, db_session):
    """Regression: alerts are identified by (alert_key, entity_ref), NOT by
    message text. Two alerts for different entities that happen to share wording
    are both kept, and resolving one must not silently resolve the other. The
    old fuzzy message-text dedup collapsed them (and could even resolve an
    unrelated alert in another domain that read the same). resolve-all still
    clears everything."""
    from vitals.models.system_alert import SystemAlert
    from vitals.services import alerts_service

    # alert1 and alert2 are DIFFERENT alerts (different entity_ref = different lab
    # markers/rows); their message text differs only by ё/о + case. They must
    # NOT be treated as duplicates.
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

    # 1. list_active returns every distinct (key, entity) — all three labs alerts,
    #    including the two that share normalized text.
    active_labs = await alerts_service.list_active(db_session, domain="labs")
    assert len(active_labs) == 3
    assert {a.entity_ref for a in active_labs} == {"marker_1", "marker_2", "marker_3"}

    # 2. Resolving one alert resolves ONLY that alert — the text-twin stays active.
    await auth_client.post(f"/alerts/{alert1.id}/resolve")
    await db_session.refresh(alert1)
    await db_session.refresh(alert2)
    await db_session.refresh(alert3)
    assert alert1.resolved_at is not None
    assert alert2.resolved_at is None, "text-twin in the same domain must stay active"
    assert alert3.resolved_at is None

    # 3. resolve-all by domain clears the rest of labs but leaves other domains.
    response = await auth_client.post("/alerts/resolve-all?domain=labs")
    assert response.status_code == 303
    await db_session.refresh(alert2)
    await db_session.refresh(alert3)
    assert alert2.resolved_at is not None
    assert alert3.resolved_at is not None
    await db_session.refresh(alert4)
    assert alert4.resolved_at is None

    # 4. resolve-all without a domain clears everything.
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
    assert 'id="primary-nav-masthead"' in r.text
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


# ── Security perimeter ────────────────────────────────────────────────────────
async def test_safe_next_rejects_offsite_targets():
    """safe_next confines the post-login redirect to a same-site path, including
    the backslash trick browsers normalise into a protocol-relative off-site URL."""
    from web.auth import safe_next

    assert safe_next("/weight") == "/weight"
    assert safe_next("/glp1?tab=1") == "/glp1?tab=1"
    # Open-redirect vectors all fall back to "/".
    assert safe_next("//evil.com") == "/"
    assert safe_next("/\\evil.com") == "/"          # \ is normalised to / by browsers
    assert safe_next("https://evil.com") == "/"
    assert safe_next("http://evil.com") == "/"
    assert safe_next(None) == "/"
    assert safe_next("") == "/"


async def test_login_rate_limited_by_ip(client):
    """Repeated login attempts from one IP are throttled (429) so password guessing
    on the single pre-auth endpoint is bounded, not unlimited."""
    last = None
    for _ in range(11):  # limit=10 per window; the 11th trips the limiter
        last = await client.post(
            "/login", data={"username": "tester", "password": "wrong"}
        )
    assert last.status_code == 429


# ── Rail: collapsible rubrics ───────────────────────────────────────────────────

_RAIL_ITEM = __import__("re").compile(r'class="mh-rail-btn[^"]*"')


@pytest.mark.parametrize("route", ["/weight", "/reports", "/labs", "/today"])
async def test_rail_lists_every_section_at_once(auth_client, route):
    """The rail is flat: every enabled section is a row on screen, whatever page
    you are on. It briefly collapsed to one rubric at a time to save vertical
    space; that cost the thing a rail is for, and the owner asked for the whole
    list back."""
    from vitals.services.modules_service import nav_modules

    r = await auth_client.get(route, headers={"Accept": "text/html"})
    assert r.status_code == 200
    rail = r.text.split('id="primary-nav-masthead"')[1].split("</aside>")[0]
    for spec in nav_modules({k: True for k in ("hevy", "nutrition", "timeline", "glp1",
                                               "hrt", "genetics", "supplements",
                                               "skincare", "interactions", "signals")}):
        assert f'href="{spec.route}"' in rail, f"{route}: {spec.key} missing from the rail"
    # No group is hidden behind a toggle any more.
    assert "mh-rail-group-head" not in rail
    assert "display:none" not in rail
    # …and "Today" still sits pinned above the rubrics.
    assert 'class="mh-rail-pinned"' in r.text


async def test_domain_pages_carry_the_rubric_tab_row(auth_client):
    """The sibling sections of the page you are on, in the content column."""
    r = await auth_client.get("/weight", headers={"Accept": "text/html"})
    tabs = r.text.split('class="mh-tabs"')[1].split("</nav>")[0]
    assert 'href="/garmin"' in tabs and 'href="/reports"' in tabs
    assert 'class="mh-tab is-active"' in tabs


# ── /weight split: trend vs measures ────────────────────────────────────────────


async def test_weight_section_splits_into_trend_and_measures(auth_client):
    """/weight was six domains in one page. It is now the trend (chart, history,
    one weight field); /weight/measures is the desk (circumferences, noise,
    photos). Both carry the same masthead figures and the same sub-tabs."""
    html = {"Accept": "text/html"}
    await auth_client.post(
        "/weight/log", data={"date": today_local().isoformat(), "weight_kg": "86.1"}
    )
    trend = await auth_client.get("/weight", headers=html)
    measures = await auth_client.get("/weight/measures", headers=html)
    assert trend.status_code == 200 and measures.status_code == 200

    for r in (trend, measures):
        assert 'href="/weight/measures"' in r.text     # the sub-tab pair
        assert "mh-metric" in r.text                   # same key figures
        assert 'id="conflict-modal"' in r.text or "showConfirm" in r.text

    # The trend page asks for one number and nothing else.
    assert 'id="weightChart"' in trend.text
    assert 'id="form-log"' in trend.text
    assert 'action="/weight/measurement"' not in trend.text
    assert 'action="/weight/photo"' not in trend.text

    # The desk holds everything that is not the trend.
    assert 'action="/weight/measurement"' in measures.text
    assert 'action="/weight/noise"' in measures.text
    assert 'action="/weight/photo"' in measures.text
    assert 'id="weightChart"' not in measures.text


async def test_measures_page_gates_body_scans_on_the_module(auth_client, db_session):
    """The body_comp toggle keeps gating its blocks inside the desk, not the
    whole page — with it off the page must still render the rest."""
    html = {"Accept": "text/html"}
    await auth_client.post("/settings/modules", data={"module": "body_comp", "enabled": "false"})
    off = await auth_client.get("/weight/measures", headers=html)
    assert off.status_code == 200
    assert 'action="/weight/body-scan/upload"' not in off.text
    assert "bsPreviewOpen" not in off.text
    assert 'action="/weight/measurement"' in off.text          # the rest survives

    await auth_client.post("/settings/modules", data={"module": "body_comp", "enabled": "true"})
    on = await auth_client.get("/weight/measures", headers=html)
    assert on.status_code == 200
    assert "bsPreviewOpen" in on.text


async def test_a_save_returns_to_the_page_it_was_posted_from(auth_client):
    """Every weight POST used to redirect to /weight. A measurement saved on the
    desk must come back to the desk, not bounce onto the trend page."""
    r = await auth_client.post(
        "/weight/measurement",
        data={"date": today_local().isoformat(), "neck_cm": "38", "waist_cm": "85"},
        headers={"referer": "http://test/weight/measures"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/weight/measures"

    # A weigh-in from the trend page still lands on the trend page…
    r = await auth_client.post(
        "/weight/log",
        data={"date": today_local().isoformat(), "weight_kg": "86.1"},
        headers={"referer": "http://test/weight"},
        follow_redirects=False,
    )
    assert r.headers["location"] == "/weight"

    # …and an off-site or missing Referer falls back to /weight rather than
    # turning the save into an open redirect.
    r = await auth_client.post(
        "/weight/log",
        data={"date": today_local().isoformat(), "weight_kg": "86.2"},
        headers={"referer": "https://evil.example/weight/measures"},
        follow_redirects=False,
    )
    assert r.headers["location"] == "/weight"


# ── /today: the landing screen ──────────────────────────────────────────────────


async def test_root_lands_on_today(auth_client):
    """The app opened on a weight-entry form. It now opens on the day."""
    r = await auth_client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/today"


async def test_today_page_renders_its_own_hero_and_quick_log(auth_client):
    """One sentence, five figures, a one-field weight form and the chips that hand
    the rest of the day to the page that owns the long form. No masthead header
    and no rubric tab row: this page is not a section of a rubric."""
    html = {"Accept": "text/html"}
    await auth_client.post(
        "/weight/log", data={"date": today_local().isoformat(), "weight_kg": "86.1"}
    )

    r = await auth_client.get("/today", headers=html)
    assert r.status_code == 200
    assert 'class="v-today-title"' in r.text
    assert r.text.count('class="v-today-figure"') == 5   # weight, sleep, HRV, BB, eaten
    assert 'class="mh-head"' not in r.text
    assert 'action="/weight/log"' in r.text
    # The form posts to a conflict-aware route, so the override modal has to ship
    # with it (tests/test_router_page_contracts.py guards the same pairing).
    assert "showConfirm" in r.text
    for href in ('href="/nutrition"', 'href="/glp1"', 'href="/weight/measures"', 'href="/timeline?new=1"'):
        assert href in r.text, href


async def test_today_survives_every_optional_module_being_off(auth_client, db_session):
    """An instance running "weight + Garmin only" gets a shorter screen, not five
    empty cards — and no chip pointing at a section that isn't there."""
    from vitals.services.modules_service import OPTIONAL_KEYS

    for key in sorted(OPTIONAL_KEYS):
        r = await auth_client.post("/settings/modules", data={"module": key, "enabled": "false"})
        assert r.status_code == 200

    r = await auth_client.get("/today", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert 'class="v-today-title"' in r.text
    assert 'href="/nutrition"' not in r.text
    assert 'href="/timeline?new=1"' not in r.text
    # Weight is core, so its measurement chip is always reachable.
    assert 'href="/weight/measures"' in r.text


async def test_today_is_pinned_in_the_rail_without_a_rubric_number(auth_client):
    """It is the entry point, not a domain: pinned above the rubrics, never inside
    one, and it must not appear in the module registry's numbering."""
    from vitals.services.modules_service import MODULE_REGISTRY

    assert "today" not in MODULE_REGISTRY
    r = await auth_client.get("/today", headers={"Accept": "text/html"})
    assert 'class="mh-rail-pinned"' in r.text
    pinned = r.text.split('class="mh-rail-pinned"')[1].split("</div>")[0]
    assert 'href="/today"' in pinned and "is-active" in pinned


async def test_weight_saved_from_today_comes_back_to_today(auth_client):
    """The quick-log posts to /weight/log; landing back on /weight would bounce the
    owner out of the screen he was working on."""
    r = await auth_client.post(
        "/weight/log",
        data={"date": today_local().isoformat(), "weight_kg": "85.4"},
        headers={"referer": "http://test/today"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/today"
