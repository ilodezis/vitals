"""Labs service tests — pure flag logic, manual entry + catalog, history,
out-of-range / retest alerts, defer-retest, and the LLM extraction → ingest path
(with a fake vision client, no network)."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from vitals.i18n import t
from vitals.models.labs import LabMarker, LabResult
from vitals.models.raw_payload import RawPayload
from vitals.services import alerts_service, labs_service

# asyncio_mode=auto runs the async tests; compute_flag tests stay synchronous.

DAY = date(2026, 6, 10)


# ── Pure flag logic ───────────────────────────────────────────────────────────
def test_compute_flag_classifies():
    assert labs_service.compute_flag(100, 30, 400) == "normal"
    # Wide range [30,400] (width 370): mildly out → low/high.
    assert labs_service.compute_flag(25, 30, 400) == "low"
    assert labs_service.compute_flag(450, 30, 400) == "high"
    # >half the range width beyond a bound → critical (400 + 185 = 585).
    assert labs_service.compute_flag(700, 30, 400) == "critical_high"
    # Narrow range [80,120] (width 40): 50 < 80-20 → critical_low; 70 → low.
    assert labs_service.compute_flag(50, 80, 120) == "critical_low"
    assert labs_service.compute_flag(70, 80, 120) == "low"
    # one-sided range (LDL < 3.0) → relative margin off the bound.
    assert labs_service.compute_flag(2.0, None, 3.0) == "normal"
    assert labs_service.compute_flag(3.5, None, 3.0) == "high"
    assert labs_service.compute_flag(4.5, None, 3.0) == "critical_high"
    # no range → unknown
    assert labs_service.compute_flag(5.0, None, None) is None


# ── Manual entry + catalog ────────────────────────────────────────────────────
async def test_add_result_creates_marker_and_flag(db_session):
    r = await labs_service.add_result(
        db_session, on_date=DAY, marker="TSH", value=5.5, unit="mIU/L",
        ref_low=0.4, ref_high=4.0,
    )
    await db_session.commit()
    assert r.flag == "high"

    markers = await labs_service.list_markers(db_session)
    assert len(markers) == 1
    assert markers[0].name == "TSH"
    assert markers[0].ref_high == 4.0


async def test_add_result_falls_back_to_catalog_range(db_session):
    # First result establishes the catalog range.
    await labs_service.add_result(
        db_session, on_date=DAY, marker="Ferritin", value=95, unit="ng/mL",
        ref_low=30, ref_high=400,
    )
    await db_session.commit()
    # Second result omits the range → catalog default is used to flag it.
    r = await labs_service.add_result(
        db_session, on_date=DAY + timedelta(days=30), marker="Ferritin", value=20
    )
    await db_session.commit()
    assert r.ref_low == 30 and r.ref_high == 400
    assert r.flag == "low"  # below 30 but within half the wide range width


async def test_marker_history_and_latest(db_session):
    await labs_service.add_result(db_session, on_date=DAY, marker="TSH", value=2.0, ref_low=0.4, ref_high=4.0)
    await labs_service.add_result(db_session, on_date=DAY + timedelta(days=90), marker="TSH", value=3.0, ref_low=0.4, ref_high=4.0)
    await db_session.commit()

    hist = await labs_service.marker_history(db_session, "TSH")
    assert [p["value"] for p in hist] == [2.0, 3.0]

    latest = await labs_service.latest_per_marker(db_session)
    assert len(latest) == 1
    assert latest[0].value == 3.0


# ── Alerts ────────────────────────────────────────────────────────────────────
async def test_refresh_alerts_raises_and_resolves(db_session):
    await labs_service.add_result(db_session, on_date=DAY, marker="TSH", value=5.5, ref_low=0.4, ref_high=4.0)
    await db_session.commit()
    await labs_service.refresh_alerts(db_session, on_date=DAY)
    await db_session.commit()

    active = await alerts_service.list_active(db_session, domain="labs")
    assert any(a.alert_key == labs_service.OUT_OF_RANGE_KEY and a.entity_ref.startswith("TSH:") for a in active)

    # A later in-range value clears it.
    await labs_service.add_result(db_session, on_date=DAY + timedelta(days=90), marker="TSH", value=2.0, ref_low=0.4, ref_high=4.0)
    await db_session.commit()
    await labs_service.refresh_alerts(db_session, on_date=DAY + timedelta(days=90))
    await db_session.commit()
    active = await alerts_service.list_active(db_session, domain="labs")
    assert not any(a.alert_key == labs_service.OUT_OF_RANGE_KEY for a in active)


async def test_out_of_range_alert_message_uses_localized_flag(db_session):
    """Regression: the raw ``critical_high`` enum must not leak into the alert
    copy — the localized flag label is shown instead (U19)."""
    # 700 in a [30, 400] range → critical_high (see compute_flag tests above).
    await labs_service.add_result(db_session, on_date=DAY, marker="Ferritin", value=700, ref_low=30, ref_high=400)
    await db_session.commit()
    await labs_service.refresh_alerts(db_session, on_date=DAY)
    await db_session.commit()

    active = await alerts_service.list_active(db_session, domain="labs")
    alert = next(a for a in active if a.alert_key == labs_service.OUT_OF_RANGE_KEY)
    assert "critical_high" not in alert.message
    assert t("enum.flag.critical_high") in alert.message


async def test_overdue_retest_alert_and_defer(db_session):
    await labs_service.add_result(db_session, on_date=DAY, marker="Ferritin", value=100, ref_low=30, ref_high=400)
    marker = await labs_service.get_marker(db_session, "Ferritin")
    marker.retest_interval_days = 90
    await db_session.commit()

    later = DAY + timedelta(days=120)  # overdue
    await labs_service.refresh_alerts(db_session, on_date=later)
    await db_session.commit()
    active = await alerts_service.list_active(db_session, domain="labs")
    assert any(a.alert_key == labs_service.RETEST_DUE_KEY for a in active)

    # Defer pushes it out and resolves the alert.
    await labs_service.defer_retest(db_session, "Ferritin", until=later + timedelta(days=30))
    await db_session.commit()
    await labs_service.refresh_alerts(db_session, on_date=later)
    await db_session.commit()
    active = await alerts_service.list_active(db_session, domain="labs")
    assert not any(a.alert_key == labs_service.RETEST_DUE_KEY for a in active)


async def test_dismissed_out_of_range_alert_stays_hidden_until_new_result(db_session):
    """Dismissing an out-of-range alert hides it forever for that result — not
    just for the rest of the day, unlike the noise/plateau alerts. Only a new
    out-of-range result for the same marker raises a fresh alert."""
    from freezegun import freeze_time

    await labs_service.add_result(
        db_session, on_date=DAY, marker="TSH", value=9.0, ref_low=0.4, ref_high=4.0
    )
    await db_session.commit()

    with freeze_time("2026-06-10 10:00:00"):
        await labs_service.refresh_alerts(db_session, on_date=DAY)
        await db_session.commit()
        active = await alerts_service.list_active(db_session, domain="labs")
        alert = next(
            (a for a in active if a.alert_key == labs_service.OUT_OF_RANGE_KEY and a.entity_ref.startswith("TSH:")),
            None,
        )
        assert alert is not None

        # User dismisses the alert.
        await alerts_service.resolve_alert(db_session, alert.id)
        await db_session.commit()

        # Second load (same day): stays hidden.
        await labs_service.refresh_alerts(db_session, on_date=DAY)
        await db_session.commit()
        active = await alerts_service.list_active(db_session, domain="labs")
        assert not any(
            a.alert_key == labs_service.OUT_OF_RANGE_KEY and a.entity_ref.startswith("TSH:")
            for a in active
        ), "Alert should stay hidden after dismiss on the same day"

    # Next calendar day, same underlying result: still hidden — this is the
    # behavior change from the old daily-nag design.
    with freeze_time("2026-06-11 10:00:00"):
        await labs_service.refresh_alerts(db_session, on_date=DAY + timedelta(days=1))
        await db_session.commit()
        active = await alerts_service.list_active(db_session, domain="labs")
        assert not any(
            a.alert_key == labs_service.OUT_OF_RANGE_KEY and a.entity_ref.startswith("TSH:")
            for a in active
        ), "Alert should stay hidden indefinitely for the same result — only new data revives it"

        # A genuinely new out-of-range result for the same marker (a new upload)
        # raises a fresh alert.
        await labs_service.add_result(
            db_session, on_date=DAY + timedelta(days=1), marker="TSH", value=9.5, ref_low=0.4, ref_high=4.0
        )
        await db_session.commit()
        await labs_service.refresh_alerts(db_session, on_date=DAY + timedelta(days=1))
        await db_session.commit()
        active = await alerts_service.list_active(db_session, domain="labs")
        new_alerts = [
            a for a in active
            if a.alert_key == labs_service.OUT_OF_RANGE_KEY and a.entity_ref.startswith("TSH:")
        ]
        assert len(new_alerts) == 1, "A new upload should raise exactly one fresh alert"
        assert new_alerts[0].entity_ref != alert.entity_ref


async def test_new_out_of_range_result_supersedes_previous_alert(db_session):
    """A new out-of-range result for the same marker resolves the (still-active,
    never dismissed) alert tied to the previous result, instead of leaving it
    active alongside a fresh duplicate."""
    await labs_service.add_result(db_session, on_date=DAY, marker="TSH", value=9.0, ref_low=0.4, ref_high=4.0)
    await db_session.commit()
    await labs_service.refresh_alerts(db_session, on_date=DAY)
    await db_session.commit()
    active = await alerts_service.list_active(db_session, domain="labs")
    tsh_alerts = [a for a in active if a.alert_key == labs_service.OUT_OF_RANGE_KEY and a.entity_ref.startswith("TSH:")]
    assert len(tsh_alerts) == 1
    old_entity = tsh_alerts[0].entity_ref

    await labs_service.add_result(
        db_session, on_date=DAY + timedelta(days=1), marker="TSH", value=9.8, ref_low=0.4, ref_high=4.0
    )
    await db_session.commit()
    await labs_service.refresh_alerts(db_session, on_date=DAY + timedelta(days=1))
    await db_session.commit()

    active = await alerts_service.list_active(db_session, domain="labs")
    tsh_alerts = [a for a in active if a.alert_key == labs_service.OUT_OF_RANGE_KEY and a.entity_ref.startswith("TSH:")]
    assert len(tsh_alerts) == 1, "The stale alert for the old result must be superseded, not left active"
    assert tsh_alerts[0].entity_ref != old_entity


async def test_dismissed_retest_due_alert_stays_hidden_until_new_result(db_session):
    """Same forever-until-new-data contract as out-of-range alerts applies to
    the overdue-retest reminder."""
    await labs_service.add_result(db_session, on_date=DAY, marker="Ferritin", value=100, ref_low=30, ref_high=400)
    marker = await labs_service.get_marker(db_session, "Ferritin")
    marker.retest_interval_days = 90
    await db_session.commit()

    later = DAY + timedelta(days=120)  # overdue
    await labs_service.refresh_alerts(db_session, on_date=later)
    await db_session.commit()
    active = await alerts_service.list_active(db_session, domain="labs")
    alert = next((a for a in active if a.alert_key == labs_service.RETEST_DUE_KEY), None)
    assert alert is not None

    await alerts_service.resolve_alert(db_session, alert.id)
    await db_session.commit()

    # Much later, still no new test taken: stays hidden — under the old
    # daily-nag design this would have reappeared the very next day.
    much_later = DAY + timedelta(days=200)
    await labs_service.refresh_alerts(db_session, on_date=much_later)
    await db_session.commit()
    active = await alerts_service.list_active(db_session, domain="labs")
    assert not any(a.alert_key == labs_service.RETEST_DUE_KEY for a in active)

    # The user finally retests — once the new result in turn becomes overdue,
    # a fresh reminder is raised.
    retest_date = DAY + timedelta(days=210)
    await labs_service.add_result(db_session, on_date=retest_date, marker="Ferritin", value=90, ref_low=30, ref_high=400)
    await db_session.commit()
    final_check = retest_date + timedelta(days=100)
    await labs_service.refresh_alerts(db_session, on_date=final_check)
    await db_session.commit()
    active = await alerts_service.list_active(db_session, domain="labs")
    assert any(a.alert_key == labs_service.RETEST_DUE_KEY for a in active)


# ── LLM extraction → ingest ───────────────────────────────────────────────────
class FakeLLM:
    def __init__(self, payload):
        self.payload = payload
        self.image_urls = []

    async def extract_json(self, prompt, *, system=None, image_url=None, image_urls=None, **kw):
        if image_url:
            self.image_urls.append(image_url)
        if image_urls:
            self.image_urls.extend(image_urls)
        return self.payload


async def test_extract_and_ingest(db_session):
    payload = {
        "date": "2026-06-10",
        "lab_name": "Synevo",
        "results": [
            {"marker": "Ferritin", "value": 95, "unit": "ng/mL", "ref_low": 30, "ref_high": 400},
            {"marker": "TSH", "value": 5.5, "unit": "mIU/L", "ref_low": 0.4, "ref_high": 4.0},
        ],
    }
    llm = FakeLLM(payload)
    extracted = await labs_service.extract_from_file(
        b"\x89PNG\r\n\x1a\n-fake-image-bytes", llm=llm, content_type="image/png"
    )
    assert extracted == payload
    assert llm.image_urls[0].startswith("data:image/png;base64,")

    summary = await labs_service.ingest_extracted(db_session, extracted, file_key="doc1")
    await db_session.commit()
    assert summary["created"] == 2 and summary["skipped"] == 0
    assert {r.marker for r in summary["results"]} == {"Ferritin", "TSH"}

    tsh = await labs_service.list_results(db_session, marker="TSH")
    assert tsh[0].flag == "high"
    assert tsh[0].source == "lab_parser"

    raw = (await db_session.execute(select(RawPayload).where(RawPayload.external_id == "doc1"))).scalars().first()
    assert raw is not None and raw.processed_at is not None

    # Re-ingesting the same document dedupes.
    summary2 = await labs_service.ingest_extracted(db_session, extracted, file_key="doc1")
    await db_session.commit()
    assert summary2["created"] == 0 and summary2["skipped"] == 2 and summary2["results"] == []
    n = (await db_session.execute(select(LabResult))).scalars().all()
    assert len(n) == 2


async def test_extract_and_ingest_multipage_pdf(db_session):
    import fitz
    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    pdf_bytes = doc.write()

    payload = {
        "date": "2026-06-10",
        "lab_name": "Synevo",
        "results": [
            {"marker": "Ferritin", "value": 95, "unit": "ng/mL", "ref_low": 30, "ref_high": 400},
            {"marker": "TSH", "value": 5.5, "unit": "mIU/L", "ref_low": 0.4, "ref_high": 4.0},
        ],
    }
    llm = FakeLLM(payload)
    extracted = await labs_service.extract_from_file(
        pdf_bytes, llm=llm, content_type="application/pdf"
    )
    assert extracted == payload
    # Should have rendered and sent 2 pages
    assert len(llm.image_urls) == 2
    assert all(url.startswith("data:image/png;base64,") for url in llm.image_urls)


def test_normalize_marker():
    # Test aliases
    assert labs_service.normalize_marker("определение иммунореактивного инсулина") == "Инсулин"
    assert labs_service.normalize_marker("тиреотропный гормон (ттг)") == "ТТГ"
    assert labs_service.normalize_marker("определение холестерина общего") == "Холестерин общий"
    # Test fallback capitalization
    assert labs_service.normalize_marker("ferritin") == "Ferritin"
    assert labs_service.normalize_marker("кальций") == "Кальций"


async def test_add_result_normalizes_marker_name(db_session):
    # Add a result with a synonym name
    r1 = await labs_service.add_result(
        db_session, on_date=DAY, marker="определение иммунореактивного инсулина", value=38.0
    )
    # Add a result with standard name
    r2 = await labs_service.add_result(
        db_session, on_date=DAY + timedelta(days=1), marker="Инсулин", value=9.0
    )
    await db_session.commit()

    # The marker names should be normalized and merged
    assert r1.marker == "Инсулин"
    assert r2.marker == "Инсулин"

    markers = await labs_service.list_markers(db_session)
    assert len(markers) == 1
    assert markers[0].name == "Инсулин"

    hist = await labs_service.marker_history(db_session, "Инсулин")
    assert [p["value"] for p in hist] == [38.0, 9.0]

