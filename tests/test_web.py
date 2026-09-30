"""Integration tests for the Vitals FastAPI web panel: health, login/logout, the
security perimeter, and the rules that sit behind the JSON API (``/api/v1``)."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from vitals.models.app_settings import AppSetting
from vitals.models.conflict_rule import ConflictRule
from vitals.models.labs import LabResult
from vitals.models.raw_payload import RawPayload
from vitals.models.system_alert import SystemAlert
from vitals.services.modules_service import SETTINGS_KEY
from vitals.utils.timeutils import today_local

# No module-level ``pytest.mark.asyncio``: pytest.ini runs asyncio_mode=auto.

API = "/api/v1"
_PNG = b"\x89PNG\r\n\x1a\n-bytes"


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


async def test_html_cache_control_headers(auth_client):
    """Test that HTML responses carry Cache-Control: no-store headers to prevent caching."""
    response = await auth_client.get("/supplements", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "Cache-Control" in response.headers
    assert "no-store" in response.headers["Cache-Control"]


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


async def test_mobile_navigation_rendering_unauth(client):
    """Test that mobile navigation is not rendered when unauthenticated."""
    response = await client.get("/login", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "Ещё" not in response.text


async def test_modules_endpoint_csrf_origin_check(auth_client):
    """Cross-origin POSTs are blocked by the origin-check middleware (403)."""
    r = await auth_client.post(
        f"{API}/settings/modules",
        json={"module": "hevy", "enabled": False},
        headers={"Origin": "http://evil.example"},
    )
    assert r.status_code == 403


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


async def test_root_lands_on_today(auth_client):
    """The app opened on a weight-entry form. It now opens on the day."""
    r = await auth_client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/today"


# ── Rules that used to be pinned through the server-rendered forms ─────────────
# The forms are gone; the same rules now sit behind /api/v1 and are pinned there.


# Skincare


async def test_skincare_retinoid_peel_block_and_override(auth_client, db_session):
    """retinoid+peel in one evening is blocked (409) then saved on override."""
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

    body = {"date": "2026-06-10", "retinoid": True, "peel": True}
    r = await auth_client.post(f"{API}/skincare/logs", json=body)
    assert r.status_code == 409
    assert r.json()["error"] == "conflict"
    assert r.json()["violations"]
    assert (await db_session.execute(select(SkincareLog))).scalar_one_or_none() is None

    r = await auth_client.post(f"{API}/skincare/logs", json={**body, "override": True})
    assert r.status_code == 200

    log = (await db_session.execute(select(SkincareLog))).scalar_one_or_none()
    assert log is not None and log.retinoid and log.peel


# Genetics


async def test_genetics_save_dedupes_by_rsid(auth_client, db_session):
    """Saving the same rsID twice from the manual form updates in place — never
    a duplicate row or a 500 from the uq_genetic_variant_rsid constraint."""
    from vitals.models.genetics import GeneticVariant

    first = await auth_client.post(
        f"{API}/genetics/variants", json={"gene": "HFE", "rsid": "rs1800562", "genotype": "G/G"}
    )
    second = await auth_client.post(
        f"{API}/genetics/variants", json={"gene": "HFE", "rsid": "rs1800562", "genotype": "A/G"}
    )
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    rows = (await db_session.execute(select(GeneticVariant))).scalars().all()
    assert len(rows) == 1
    assert rows[0].genotype == "A/G"


async def test_genetics_vcf_upload_keeps_only_curated_rsids(auth_client, db_session):
    """A VCF upload imports only the curated rsIDs (stamping their conflict marker);
    a row with no rsID and an unknown rsID are dropped."""
    from vitals.models.genetics import GeneticVariant

    vcf = (
        "##fileformat=VCFv4.2\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
        "6\t26093141\trs1800562\tG\tA\t.\tPASS\t.\tGT\t0/1\n"  # known → imported
        "6\t100\t.\tG\tA\t.\tPASS\t.\tGT\t0/1\n"  # no rsID → skipped
        "1\t200\trs9999999\tA\tT\t.\tPASS\t.\tGT\t0/1\n"  # unknown rsID → skipped
    )
    r = await auth_client.post(
        f"{API}/genetics/upload", files={"file": ("genome.vcf", vcf, "text/plain")}
    )
    assert r.status_code == 200
    assert r.json()["imported"] == 1
    assert r.json()["markers"] == 1

    rows = (await db_session.execute(select(GeneticVariant))).scalars().all()
    assert {v.rsid for v in rows} == {"rs1800562"}
    assert rows[0].marker == "hemochromatosis_carrier"


# Hevy


async def test_hevy_synced_workout_reaches_the_screen(auth_client, db_session):
    """A workout pulled by the real sync shows up on the screen, its exercise in the catalog."""
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

    r = await auth_client.get(f"{API}/workouts")
    assert r.status_code == 200
    data = r.json()
    assert [w["title"] for w in data["workouts"]] == ["Day A — Push"]
    assert [e["title"] for e in data["workouts"][0]["exercises"]] == ["Bench Press (Barbell)"]
    assert [c["title"] for c in data["catalog"]] == ["Bench Press (Barbell)"]


# Garmin


async def test_garmin_sleep_night_links_its_neighbours(auth_client, db_session):
    """The night screen carries the nearest nights either side; at the oldest there is no earlier one."""
    from datetime import date

    from vitals.models.garmin import GarminDaily

    db_session.add_all([
        GarminDaily(date=date(2026, 6, 9), domain="garmin", source="garmin_api", sleep_seconds=25200, sleep_score=70),
        GarminDaily(date=date(2026, 6, 10), domain="garmin", source="garmin_api", sleep_seconds=27000, sleep_score=78),
        GarminDaily(date=date(2026, 6, 11), domain="garmin", source="garmin_api", sleep_seconds=26000, sleep_score=80),
    ])
    await db_session.commit()

    mid = (await auth_client.get(f"{API}/recovery/sleep/2026-06-10")).json()
    assert (mid["prev_date"], mid["next_date"]) == ("2026-06-09", "2026-06-11")

    oldest = (await auth_client.get(f"{API}/recovery/sleep/2026-06-09")).json()
    assert oldest["prev_date"] is None
    assert oldest["next_date"] == "2026-06-10"


# Labs


async def test_labs_manual_add_and_flag(auth_client, db_session):
    """POST /labs/results stores a result with a computed flag."""
    r = await auth_client.post(
        f"{API}/labs/results",
        json={"date": "2026-06-10", "marker": "TSH", "value": 5.5, "unit": "mIU/L",
              "refLow": 0.4, "refHigh": 4.0},
    )
    assert r.status_code == 201

    row = (await db_session.execute(select(LabResult))).scalar_one_or_none()
    assert row is not None
    assert row.marker == "TSH" and row.flag == "high"


class _FakeLLM:
    """Stands in for the vision client so the upload route gets past its key check."""


async def test_labs_upload_without_llm_says_not_configured(auth_client):
    """Uploading with no OpenRouter key configured answers with a flag rather than
    erroring (the LLM is optional): the client shows it and moves on to the next file."""
    r = await auth_client.post(
        f"{API}/labs/upload",
        files={"file": ("panel.png", _PNG, "image/png")},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert data["reason"] == "not_configured"
    assert data["message"]


async def test_labs_upload_extraction_failure_is_an_error_flag(auth_client, monkeypatch):
    """A file that fails vision extraction surfaces ok:false/reason:error."""
    from vitals.services import labs_service

    async def fake_extract(contents, *, llm, content_type, filename=None):
        raise ValueError("could not parse")

    monkeypatch.setattr("web.api.labs.LLMClient", _FakeLLM)
    monkeypatch.setattr(labs_service, "extract_from_file", fake_extract)

    r = await auth_client.post(
        f"{API}/labs/upload",
        files={"file": ("bad.png", _PNG, "image/png")},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert data["reason"] == "error"


async def test_failed_extraction_leaves_no_orphan_file(auth_client, monkeypatch):
    """Nothing is written to disk unless the parse succeeds — a failed parse must not
    leave a file nothing in the DB references."""
    import os

    from vitals.services import labs_service
    from web.templating import STATIC_DIR

    uploads = os.path.join(STATIC_DIR, "uploads", "labs")
    before = set(os.listdir(uploads)) if os.path.isdir(uploads) else set()

    async def fake_extract(contents, *, llm, content_type, filename=None):
        raise ValueError("could not parse")

    monkeypatch.setattr("web.api.labs.LLMClient", _FakeLLM)
    monkeypatch.setattr(labs_service, "extract_from_file", fake_extract)

    r = await auth_client.post(
        f"{API}/labs/upload",
        files={"file": ("bad.png", _PNG, "image/png")},
    )
    assert r.json()["ok"] is False

    after = set(os.listdir(uploads)) if os.path.isdir(uploads) else set()
    assert after == before


def _extracted_ferritin():
    return {
        "date": "2026-06-10",
        "lab_name": "Synevo",
        "results": [{"marker": "Ferritin", "value": 95, "unit": "ng/mL", "ref_low": 30, "ref_high": 400}],
    }


async def test_labs_upload_returns_preview_without_persisting_results(auth_client, db_session, monkeypatch):
    """Upload must extract and return an editable preview without writing any
    LabResult — a misread value never reaches the DB until the owner confirms it."""
    from vitals.services import labs_service

    async def fake_extract(contents, *, llm, content_type, filename=None):
        return _extracted_ferritin()

    monkeypatch.setattr("web.api.labs.LLMClient", _FakeLLM)
    monkeypatch.setattr(labs_service, "extract_from_file", fake_extract)

    r = await auth_client.post(
        f"{API}/labs/upload",
        files={"file": ("panel.png", _PNG, "image/png")},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["lab"]["date"] == "2026-06-10"
    assert data["lab"]["labName"] == "Synevo"
    assert data["lab"]["markers"] == [
        {"marker": "Ferritin", "value": 95.0, "unit": "ng/mL", "refLow": 30.0, "refHigh": 400.0}
    ]

    results = (await db_session.execute(select(LabResult))).scalars().all()
    assert results == []

    raw = await db_session.get(RawPayload, data["lab"]["rawPayloadId"])
    assert raw is not None and raw.processed_at is None


async def test_labs_confirm_persists_edited_markers(auth_client, db_session, monkeypatch):
    """Confirm must save the owner's edits, not the raw OCR values — proves the
    edit-before-save step actually takes effect."""
    from vitals.services import labs_service

    async def fake_extract(contents, *, llm, content_type, filename=None):
        return _extracted_ferritin()

    monkeypatch.setattr("web.api.labs.LLMClient", _FakeLLM)
    monkeypatch.setattr(labs_service, "extract_from_file", fake_extract)

    upload_r = await auth_client.post(
        f"{API}/labs/upload",
        files={"file": ("panel.png", _PNG, "image/png")},
    )
    lab = upload_r.json()["lab"]

    # Owner corrects a misread value (95 -> 105) before saving.
    confirm_r = await auth_client.post(
        f"{API}/labs/confirm",
        json={
            "date": lab["date"],
            "labName": lab["labName"],
            "fileKey": lab["fileKey"],
            "rawPayloadId": lab["rawPayloadId"],
            "markers": [{**lab["markers"][0], "value": 105}],
        },
    )
    assert confirm_r.status_code == 200
    assert confirm_r.json() == {"ok": True, "created": 1}

    results = (await db_session.execute(select(LabResult))).scalars().all()
    assert len(results) == 1
    assert results[0].marker == "Ferritin"
    assert results[0].value == 105.0

    raw = await db_session.get(RawPayload, lab["rawPayloadId"])
    assert raw is not None and raw.processed_at is not None


async def test_upload_extension_allowlist_rejected(auth_client):
    """Non-allowlisted upload types are rejected (415), so an attacker-controlled
    extension can't be stored under same-origin /static/uploads."""
    # Genetics expects .vcf/.txt — an .exe is refused before any DB work.
    r = await auth_client.post(
        f"{API}/genetics/upload",
        files={"file": ("evil.exe", b"MZ...", "application/octet-stream")},
    )
    assert r.status_code == 415

    # Garmin import expects .json — a .csv is refused.
    r = await auth_client.post(
        f"{API}/recovery/import",
        files={"file": ("export.csv", b"a,b,c", "text/csv")},
    )
    assert r.status_code == 415

    # A lab document is a PDF or an image.
    r = await auth_client.post(
        f"{API}/labs/upload",
        files={"file": ("evil.exe", b"MZ...", "application/octet-stream")},
    )
    assert r.status_code == 415

    # Progress photos are images.
    r = await auth_client.post(
        f"{API}/weight/photos",
        files={"files": ("evil.exe", b"MZ...", "application/octet-stream")},
        data={"date": "2026-06-15"},
    )
    assert r.status_code == 415


# Reports


async def test_reports_moves_reached_goals_to_the_archive(auth_client, db_session):
    """A crossed goal leaves the active list for the archive, and a missed deadline
    on a live goal is reported as a negative day count the screen words as overdue."""
    from datetime import timedelta

    from vitals.services import milestones_service, weight_service

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

    data = (await auth_client.get(f"{API}/reports")).json()

    assert [g["name"] for g in data["activeGoals"]] == ["Дойти до 100"]
    live = data["activeGoals"][0]
    assert live["remaining"] == pytest.approx(4.1)
    assert live["daysLeft"] == -3

    assert [g["name"] for g in data["closedGoals"]] == ["Дойти до 105"]
    assert data["closedGoals"][0]["status"] == "achieved"
    # Reached after the deadline it had.
    assert data["closedGoals"][0]["deadlineMarginDays"] < 0


async def test_reports_create_body_comp_milestone(auth_client, db_session):
    """A body composition goal card is created and listed under its own domain."""
    from vitals.models.milestones import Milestone

    r = await auth_client.post(
        f"{API}/reports/milestones",
        json={"name": "Снизить процент жира до 15%", "domain": "body_comp", "targetValue": 15.0,
              "targetUnit": "%", "deadline": "2026-09-01"},
    )
    assert r.status_code == 201

    rows = (await db_session.execute(select(Milestone))).scalars().all()
    row = next((x for x in rows if x.domain == "body_comp"), None)
    assert row is not None
    assert row.name == "Снизить процент жира до 15%"
    assert row.target_value == 15.0

    goals = (await auth_client.get(f"{API}/reports")).json()["activeGoals"]
    assert [(g["id"], g["domain"]) for g in goals] == [(row.id, "body_comp")]


# Alerts


async def test_alerts_with_same_text_are_distinct_and_resolve_all(auth_client, db_session):
    """Alerts are identified by (alert_key, entity_ref), NOT by message text. Two
    alerts for different entities that happen to share wording are both kept, and
    resolving one must not silently resolve the other. resolve-all still clears
    everything."""
    from vitals.services import alerts_service

    # alert1 and alert2 are DIFFERENT alerts (different entity_ref = different lab
    # markers/rows); their message text differs only by ё/о + case. They must
    # NOT be treated as duplicates.
    alert1 = SystemAlert(
        domain="labs",
        severity="info",
        message="Средний объём эритроцитов: 97.7 фл вне нормы (high).",
        alert_key="labs.out_of_range",
        entity_ref="marker_1",
    )
    alert2 = SystemAlert(
        domain="labs",
        severity="info",
        message="Средний объем эритроцитов: 97.7 фл вне нормы (high).",
        alert_key="labs.out_of_range",
        entity_ref="marker_2",
    )
    alert3 = SystemAlert(
        domain="labs",
        severity="info",
        message="Другой маркер вне нормы.",
        alert_key="labs.out_of_range",
        entity_ref="marker_3",
    )
    alert4 = SystemAlert(
        domain="weight",
        severity="info",
        message="Вес колеблется.",
        alert_key="weight.noise",
        entity_ref="",
    )
    db_session.add_all([alert1, alert2, alert3, alert4])
    await db_session.commit()

    # 1. Every distinct (key, entity) is listed — all three labs alerts, including
    #    the two that share normalized text.
    active_labs = await alerts_service.list_active(db_session, domain="labs")
    assert len(active_labs) == 3
    assert {a.entity_ref for a in active_labs} == {"marker_1", "marker_2", "marker_3"}
    listed = (await auth_client.get(f"{API}/alerts?domain=labs")).json()
    assert listed["count"] == 3

    # 2. Resolving one alert resolves ONLY that alert — the text-twin stays active.
    r = await auth_client.post(f"{API}/alerts/{alert1.id}/resolve")
    assert r.status_code == 200
    await db_session.refresh(alert1)
    await db_session.refresh(alert2)
    await db_session.refresh(alert3)
    assert alert1.resolved_at is not None
    assert alert2.resolved_at is None, "text-twin in the same domain must stay active"
    assert alert3.resolved_at is None

    # 3. resolve-all by domain clears the rest of labs but leaves other domains.
    response = await auth_client.post(f"{API}/alerts/resolve-all?domain=labs")
    assert response.status_code == 200
    await db_session.refresh(alert2)
    await db_session.refresh(alert3)
    assert alert2.resolved_at is not None
    assert alert3.resolved_at is not None
    await db_session.refresh(alert4)
    assert alert4.resolved_at is None

    # 4. resolve-all without a domain clears everything.
    response = await auth_client.post(f"{API}/alerts/resolve-all")
    assert response.status_code == 200
    await db_session.refresh(alert4)
    assert alert4.resolved_at is not None


# Progress photos


async def test_progress_photo_upload_and_delete(auth_client, db_session):
    """Progress photos are saved on disk and in the DB, and deleted from both."""
    import os
    from vitals.models.weight import ProgressPhoto
    from web.templating import STATIC_DIR

    photo_data = b"fake-jpeg-image-bytes"
    file_path = None

    try:
        response = await auth_client.post(
            f"{API}/weight/photos",
            files={"file": ("progress.jpg", photo_data, "image/jpeg")},
            data={"date": "2026-06-15", "note": "Integration progress photo"},
        )
        assert response.status_code == 201

        result = await db_session.execute(select(ProgressPhoto))
        photo = result.scalar_one_or_none()
        assert photo is not None
        assert photo.note == "Integration progress photo"
        assert photo.date.isoformat() == "2026-06-15"
        assert photo.file_key.startswith("uploads/")
        assert response.json()[0]["id"] == photo.id

        file_path = os.path.join(STATIC_DIR, photo.file_key)
        assert os.path.exists(file_path)
        with open(file_path, "rb") as f:
            assert f.read() == photo_data

        delete_response = await auth_client.delete(f"{API}/weight/photos/{photo.id}")
        assert delete_response.status_code == 204

        result2 = await db_session.execute(select(ProgressPhoto).where(ProgressPhoto.id == photo.id))
        assert result2.scalar_one_or_none() is None
        assert not os.path.exists(file_path)
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass


async def test_progress_photo_multiple_upload_success(auth_client, db_session):
    """Several progress photos in one request are all saved on disk and in the DB."""
    import os
    from vitals.models.weight import ProgressPhoto
    from web.templating import STATIC_DIR

    blobs = [b"fake-jpeg-image-bytes-1", b"fake-jpeg-image-bytes-2", b"fake-jpeg-image-bytes-3"]
    file_paths = []

    try:
        response = await auth_client.post(
            f"{API}/weight/photos",
            files=[("files", (f"progress{i}.jpg", blob, "image/jpeg")) for i, blob in enumerate(blobs, 1)],
            data={"date": "2026-06-16", "note": "Multiple progress photos note"},
        )
        assert response.status_code == 201
        assert len(response.json()) == 3

        result = await db_session.execute(select(ProgressPhoto).order_by(ProgressPhoto.id))
        photos = result.scalars().all()
        assert len(photos) == 3
        for photo, expected in zip(photos, blobs):
            assert photo.note == "Multiple progress photos note"
            assert photo.date.isoformat() == "2026-06-16"
            assert photo.file_key.startswith("uploads/")

            path = os.path.join(STATIC_DIR, photo.file_key)
            file_paths.append(path)
            assert os.path.exists(path)
            with open(path, "rb") as f:
                assert f.read() == expected
    finally:
        for path in file_paths:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass


async def test_progress_photo_multiple_upload_limit_exceeded(auth_client, db_session):
    """Uploading more than 5 progress photos at once is refused and nothing is saved."""
    from vitals.models.weight import ProgressPhoto

    response = await auth_client.post(
        f"{API}/weight/photos",
        files=[("files", (f"p{i}.jpg", b"fake-jpeg-image-bytes", "image/jpeg")) for i in range(1, 7)],
        data={"date": "2026-06-17", "note": "Should fail"},
    )
    assert response.status_code == 400

    assert (await db_session.execute(select(ProgressPhoto))).scalars().all() == []


async def test_progress_photo_upload_empty(auth_client, db_session):
    """Uploading without any files is refused and nothing is saved."""
    from vitals.models.weight import ProgressPhoto

    response = await auth_client.post(
        f"{API}/weight/photos",
        data={"date": "2026-06-17", "note": "Should fail"},
    )
    assert response.status_code == 400

    assert (await db_session.execute(select(ProgressPhoto))).scalars().all() == []


# Dashboard modularity


async def test_toggle_module_gates_its_screen(auth_client, db_session):
    """Journey: toggle an Optional module → DB changes → its screen answers 404
    module_disabled, and comes back when it is switched on again."""
    r = await auth_client.post(f"{API}/settings/modules", json={"module": "hevy", "enabled": True})
    assert r.status_code == 200
    assert (await auth_client.get(f"{API}/workouts")).status_code == 200

    r = await auth_client.post(f"{API}/settings/modules", json={"module": "hevy", "enabled": False})
    assert r.status_code == 200
    row = await db_session.get(AppSetting, SETTINGS_KEY)
    assert row is not None and row.value["hevy"] is False
    gone = await auth_client.get(f"{API}/workouts")
    assert gone.status_code == 404
    assert gone.json() == {"error": "module_disabled"}

    r = await auth_client.post(f"{API}/settings/modules", json={"module": "hevy", "enabled": True})
    assert r.status_code == 200
    assert (await auth_client.get(f"{API}/workouts")).status_code == 200


async def test_disabled_module_screen_is_gone_until_switched_back_on(auth_client):
    """A disabled Optional module's screen is a 404; re-enabling makes it reachable again."""
    await auth_client.post(f"{API}/settings/modules", json={"module": "glp1", "enabled": False})

    r = await auth_client.get(f"{API}/glp1")
    assert r.status_code == 404
    assert r.json() == {"error": "module_disabled"}

    await auth_client.post(f"{API}/settings/modules", json={"module": "glp1", "enabled": True})
    r = await auth_client.get(f"{API}/glp1")
    assert r.status_code == 200


async def test_core_module_toggle_rejected(auth_client):
    """Core modules cannot be disabled — the endpoint returns 400 and the screen stays."""
    r = await auth_client.post(f"{API}/settings/modules", json={"module": "weight", "enabled": False})
    assert r.status_code == 400

    assert (await auth_client.get(f"{API}/weight")).status_code == 200
    modules = (await auth_client.get(f"{API}/settings")).json()["modules"]
    assert modules["enabled_modules"]["weight"] is True


async def test_modules_endpoint_rate_limited(auth_client):
    """The save endpoint is rate-limited via Redis (429 once the window is full)."""
    statuses = []
    for _ in range(35):
        r = await auth_client.post(f"{API}/settings/modules", json={"module": "hevy", "enabled": True})
        statuses.append(r.status_code)

    assert statuses[0] == 200          # first request allowed
    assert 429 in statuses             # limiter eventually trips


# Today


async def test_today_survives_every_optional_module_being_off(auth_client):
    """An instance running "weight + Garmin only" gets a shorter screen, not an error."""
    from vitals.services.modules_service import OPTIONAL_KEYS

    for key in sorted(OPTIONAL_KEYS):
        r = await auth_client.post(f"{API}/settings/modules", json={"module": key, "enabled": False})
        assert r.status_code == 200

    r = await auth_client.get(f"{API}/today")
    assert r.status_code == 200
    body = r.json()
    assert body["narrative"]
    # Weight is core, so its figure is always there.
    assert "weight" in [f["key"] for f in body["figures"]]
