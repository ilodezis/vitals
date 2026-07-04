"""Body-composition scan service tests — extraction (fake vision client), the
edit-before-save flow, the weight bridge priority matrix, BIA chart points,
metric history, cascade delete, and the light alerts. Runs on SQLite (the tables
use no Postgres-only features) and on Postgres."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from vitals.enums import Source
from vitals.integrations.llm_client import LLMNotConfigured
from vitals.models.body_scan import BodyScan, BodyScanMetric
from vitals.models.raw_payload import RawPayload
from vitals.models.weight import WeightLog
from vitals.services import alerts_service, body_scan_service, raw_payload_service, weight_service

DAY = date(2026, 6, 10)
DAY2 = DAY + timedelta(days=7)


class FakeLLM:
    """Captures the image URLs it was sent and returns a canned payload."""

    def __init__(self, payload):
        self.payload = payload
        self.image_urls = []
        self.system = None

    async def extract_json(self, prompt, *, system=None, image_url=None, image_urls=None, **kw):
        self.system = system
        if image_url:
            self.image_urls.append(image_url)
        if image_urls:
            self.image_urls.extend(image_urls)
        return self.payload


# ── Extraction ────────────────────────────────────────────────────────────────
async def test_extract_from_image():
    llm = FakeLLM({"device": "InBody 770", "metrics": []})
    extracted = await body_scan_service.extract_from_file(
        b"\x89PNG\r\n\x1a\n-fake", llm=llm, content_type="image/png"
    )
    assert extracted["device"] == "InBody 770"
    assert llm.image_urls[0].startswith("data:image/png;base64,")
    assert "JSON" in llm.system  # the body-composition system prompt was used


async def test_extract_from_multipage_pdf():
    import fitz

    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    pdf_bytes = doc.write()

    llm = FakeLLM({"metrics": []})
    await body_scan_service.extract_from_file(pdf_bytes, llm=llm, content_type="application/pdf")
    assert len(llm.image_urls) == 2
    assert all(u.startswith("data:image/png;base64,") for u in llm.image_urls)


async def test_extract_propagates_not_configured():
    class RaisingLLM:
        async def extract_json(self, *a, **k):
            raise LLMNotConfigured("no key")

    with pytest.raises(LLMNotConfigured):
        await body_scan_service.extract_from_file(b"x", llm=RaisingLLM(), content_type="image/png")


# ── Normalization (pure-ish, the editable preview rows) ───────────────────────
def test_normalize_extracted_maps_and_drops_invalid():
    rows = body_scan_service.normalize_extracted({"metrics": [
        {"label": "Процент жира", "value": 18.5, "unit": "%"},
        {"label": "", "value": 5},          # no label / key → dropped
        {"label": "Белок", "value": None},  # no value → dropped
        {"label": "Неизвестная метрика X", "value": 3},  # kept as 'other'
    ]})
    keys = {r["metric_key"] for r in rows}
    assert "body_fat_pct" in keys
    assert len(rows) == 2  # bf + the captured unknown
    unknown = [r for r in rows if r["category"] == "other"][0]
    assert unknown["value"] == 3


def test_normalize_extracted_empty():
    assert body_scan_service.normalize_extracted({}) == []


# ── save_scan: rows, categories, raw stamp ────────────────────────────────────
async def test_save_scan_creates_metrics_with_categories(db_session):
    scan = await body_scan_service.save_scan(
        db_session,
        on_date=DAY,
        device="InBody 770",
        metrics=[
            {"label": "Процент жира", "value": 18.5, "unit": "%"},
            {"label": "Скелетно-мышечная масса", "value": 34.2, "unit": "кг"},
            {"label": "Right Arm", "value": 3.1, "unit": "кг", "segment": "right_arm"},
            {"label": "Вес", "value": 71.5, "unit": "кг"},
        ],
    )
    await db_session.commit()

    full = await body_scan_service.get_scan(db_session, scan.id)
    by_key = {m.metric_key: m for m in full.metrics}
    assert by_key["body_fat_pct"].category == "composition"
    assert by_key["skeletal_muscle_mass"].value == 34.2
    seg = by_key["segmental_lean"]
    assert seg.segment == "right_arm" and seg.category == "segmental"


async def test_save_scan_raw_payload_is_preserved_against_edits(db_session):
    # Vision misread body fat as 99.9; the owner corrects it to 18.5 in preview.
    extracted = {"date": DAY.isoformat(), "device": "МедАсс",
                 "metrics": [{"label": "Процент жира", "value": 99.9}]}
    raw = await raw_payload_service.upsert_raw_payload(
        db_session, domain="body_comp", source="body_scan", external_id="k1", payload=extracted
    )
    await body_scan_service.save_scan(
        db_session, on_date=DAY, raw_payload_id=raw.id,
        metrics=[{"label": "Процент жира", "value": 18.5}],
    )
    await db_session.commit()

    full = await body_scan_service.get_scan(db_session, (await _latest_scan_id(db_session)))
    assert full.metrics[0].value == 18.5  # normalized row carries the edit

    raw_row = await db_session.get(RawPayload, raw.id)
    assert raw_row.payload["metrics"][0]["value"] == 99.9  # original untouched
    assert raw_row.processed_at is not None


# ── Weight bridge priority: manual ≈ scan > garmin (Garmin overrides nothing) ──
async def test_scan_weight_supersedes_garmin(db_session):
    await weight_service.log_weight(db_session, on_date=DAY, weight_kg=70.0, source=Source.GARMIN_API.value)
    await db_session.commit()

    await body_scan_service.save_scan(db_session, on_date=DAY, metrics=[{"label": "Вес", "value": 71.5}])
    await db_session.commit()

    active = await weight_service.get_active_weight(db_session, DAY)
    assert active.source == Source.BODY_SCAN.value
    assert active.weight_kg == 71.5

    rows = (await db_session.execute(select(WeightLog).where(WeightLog.date == DAY))).scalars().all()
    assert len(rows) == 2  # both kept (data-lake)
    garmin = [r for r in rows if r.source == Source.GARMIN_API.value][0]
    assert garmin.superseded is True


async def test_garmin_never_supersedes_a_scan(db_session):
    await body_scan_service.save_scan(db_session, on_date=DAY2, metrics=[{"label": "Вес", "value": 80.0}])
    await db_session.commit()

    # Garmin arrives afterwards — must not take over.
    await weight_service.log_weight(db_session, on_date=DAY2, weight_kg=79.0, source=Source.GARMIN_API.value)
    await db_session.commit()

    active = await weight_service.get_active_weight(db_session, DAY2)
    assert active.source == Source.BODY_SCAN.value
    assert active.weight_kg == 80.0


# ── BIA chart points + metric history ─────────────────────────────────────────
async def test_bia_chart_points(db_session):
    await body_scan_service.save_scan(db_session, on_date=DAY, metrics=[
        {"label": "Процент жира", "value": 18.5},
        {"label": "Вес", "value": 80.0},
        {"label": "Безжировая масса", "value": 65.2},
    ])
    await db_session.commit()

    pts = await body_scan_service.bia_chart_points(db_session)
    assert pts["bf"] == [{"date": DAY.isoformat(), "value": 18.5}]
    assert pts["lbm"] == [{"date": DAY.isoformat(), "value": 65.2}]


async def test_metric_history_series(db_session):
    await body_scan_service.save_scan(db_session, on_date=DAY, metrics=[{"label": "Фазовый угол", "value": 6.1}])
    await body_scan_service.save_scan(db_session, on_date=DAY2, metrics=[{"label": "Фазовый угол", "value": 6.4}])
    await db_session.commit()

    hist = await body_scan_service.metric_history(db_session, "phase_angle")
    assert [h["value"] for h in hist] == [6.1, 6.4]
    assert [h["date"] for h in hist] == [DAY.isoformat(), DAY2.isoformat()]


# ── Cascade delete ────────────────────────────────────────────────────────────
async def test_delete_scan_cascades_metrics(db_session):
    scan = await body_scan_service.save_scan(db_session, on_date=DAY, metrics=[{"label": "Белок", "value": 10.2}])
    await db_session.commit()
    sid = scan.id

    assert await body_scan_service.delete_scan(db_session, sid) is True
    await db_session.commit()

    assert await db_session.get(BodyScan, sid) is None
    remaining = (await db_session.execute(select(BodyScanMetric).where(BodyScanMetric.scan_id == sid))).scalars().all()
    assert remaining == []
    assert await body_scan_service.delete_scan(db_session, sid) is False  # already gone


# ── ingest_extracted convenience (raw + save in one) ──────────────────────────
async def test_ingest_extracted(db_session):
    extracted = {"date": DAY.isoformat(), "device": "МедАсс",
                 "metrics": [{"label": "Белок", "value": 10.2, "unit": "кг"}]}
    scan = await body_scan_service.ingest_extracted(db_session, extracted, file_key="f1")
    await db_session.commit()

    full = await body_scan_service.get_scan(db_session, scan.id)
    assert full.device == "МедАсс"
    assert len(full.metrics) == 1
    raw = (await db_session.execute(select(RawPayload).where(RawPayload.external_id == "f1"))).scalars().first()
    assert raw is not None and raw.processed_at is not None


# ── Light alerts ──────────────────────────────────────────────────────────────
async def test_refresh_alerts_visceral_high_then_resolves(db_session):
    await body_scan_service.save_scan(db_session, on_date=DAY, metrics=[
        {"label": "Площадь висцерального жира", "value": 120.0, "unit": "см²", "ref_high": 100.0},
    ])
    await db_session.commit()
    await body_scan_service.refresh_alerts(db_session)
    await db_session.commit()
    active = await alerts_service.list_active(db_session, domain="body_comp")
    assert len(active) == 1

    # A later, in-range scan resolves it — this also guards the supersede logic:
    # the alert is tied to the *first* scan's id, so a naive exact-entity lookup
    # would miss it; refresh_alerts must clear it via resolve_superseded.
    await body_scan_service.save_scan(db_session, on_date=DAY2, metrics=[
        {"label": "Площадь висцерального жира", "value": 80.0, "unit": "см²", "ref_high": 100.0},
    ])
    await db_session.commit()
    await body_scan_service.refresh_alerts(db_session)
    await db_session.commit()
    active2 = await alerts_service.list_active(db_session, domain="body_comp")
    assert active2 == []


async def test_dismissed_visceral_alert_stays_hidden_until_new_scan(db_session):
    """Same forever-until-new-data contract as labs: dismissing a visceral-fat
    alert hides it forever for that scan; a new out-of-range scan raises a
    fresh one."""
    from freezegun import freeze_time

    await body_scan_service.save_scan(db_session, on_date=DAY, metrics=[
        {"label": "Площадь висцерального жира", "value": 120.0, "unit": "см²", "ref_high": 100.0},
    ])
    await db_session.commit()

    with freeze_time("2026-06-10 10:00:00"):
        await body_scan_service.refresh_alerts(db_session)
        await db_session.commit()
        active = await alerts_service.list_active(db_session, domain="body_comp")
        alert = next((a for a in active if a.alert_key == body_scan_service.VISCERAL_ALERT_KEY), None)
        assert alert is not None

        await alerts_service.resolve_alert(db_session, alert.id)
        await db_session.commit()

        await body_scan_service.refresh_alerts(db_session)
        await db_session.commit()
        active = await alerts_service.list_active(db_session, domain="body_comp")
        assert not any(a.alert_key == body_scan_service.VISCERAL_ALERT_KEY for a in active)

    # Next calendar day, same scan: still hidden — under the old daily-nag
    # design this would have reappeared.
    with freeze_time("2026-06-11 10:00:00"):
        await body_scan_service.refresh_alerts(db_session)
        await db_session.commit()
        active = await alerts_service.list_active(db_session, domain="body_comp")
        assert not any(
            a.alert_key == body_scan_service.VISCERAL_ALERT_KEY for a in active
        ), "Alert should stay hidden indefinitely for the same scan"

        # A new scan, still out of range, raises a fresh alert.
        await body_scan_service.save_scan(db_session, on_date=DAY2, metrics=[
            {"label": "Площадь висцерального жира", "value": 130.0, "unit": "см²", "ref_high": 100.0},
        ])
        await db_session.commit()
        await body_scan_service.refresh_alerts(db_session)
        await db_session.commit()
        active = await alerts_service.list_active(db_session, domain="body_comp")
        assert any(a.alert_key == body_scan_service.VISCERAL_ALERT_KEY for a in active)


async def _latest_scan_id(db_session) -> int:
    row = (await db_session.execute(select(BodyScan.id).order_by(BodyScan.id.desc()))).scalars().first()
    return row
