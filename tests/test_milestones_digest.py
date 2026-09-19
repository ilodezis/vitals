"""Milestones + weekly-digest tests — goal CRUD/progress and the cross-domain
context assembly + LLM narrative generation (with a fake LLM, no network)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from vitals.enums import Domain
from vitals.models.milestones import WeeklyDigest
from vitals.services import (
    digest_service,
    garmin_service,
    hevy_service,
    milestones_service,
    weight_service,
)

DAY = date(2026, 6, 10)

pytestmark = pytest.mark.usefixtures("all_modules_on")


# ── Milestones ────────────────────────────────────────────────────────────────
async def test_create_and_progress_weight_goal(db_session):
    await weight_service.log_weight(db_session, on_date=DAY, weight_kg=90.0)
    m = await milestones_service.create_milestone(
        db_session, name="Дойти до 82", domain="weight", target_value=82.0,
        target_unit="кг", deadline=DAY + timedelta(days=60),
    )
    await db_session.commit()

    cards = await milestones_service.dashboard_cards(db_session)
    assert len(cards) == 1
    card = cards[0]
    assert card["current"] == 90.0
    assert card["remaining"] == 8.0  # 90 - 82
    assert card["days_left"] is not None

    assert await milestones_service.set_status(db_session, m.id, "achieved")
    await db_session.commit()
    assert (await milestones_service.list_milestones(db_session, status="achieved"))[0].id == m.id

    assert await milestones_service.delete_milestone(db_session, m.id)
    await db_session.commit()
    assert len(await milestones_service.list_milestones(db_session)) == 0


async def test_weight_goal_closes_itself_once_crossed(db_session):
    """A goal the scale has already passed must not sit as "active" with a
    positive "remaining": crossing the target marks it achieved."""
    await weight_service.log_weight(db_session, on_date=DAY, weight_kg=105.3)
    await milestones_service.create_milestone(
        db_session, name="Дойти до 105", domain="weight", target_value=105.0,
        target_unit="кг", deadline=DAY - timedelta(days=41),
    )
    await db_session.commit()
    assert (await milestones_service.dashboard_cards(db_session))[0]["status"] == "active"

    await weight_service.log_weight(db_session, on_date=DAY + timedelta(days=1), weight_kg=104.1)
    await db_session.commit()
    card = (await milestones_service.dashboard_cards(db_session))[0]
    assert card["remaining"] == pytest.approx(-0.9)
    assert card["status"] == "achieved"
    assert await milestones_service.list_milestones(db_session, status="achieved")


async def test_progress_guards_against_unit_domain_mismatch(db_session):
    """A goal filed under domain="weight" but with a "%" target_unit (e.g.
    copy-pasted from a body-fat goal) must not compute current/remaining — on the
    old code this compared a percentage target against a kilogram reading and
    printed a nonsense "remaining"."""
    await weight_service.log_weight(db_session, on_date=DAY, weight_kg=86.1)
    m = await milestones_service.create_milestone(
        db_session, name="Body fat under 15%", domain="weight", target_value=15.0,
        target_unit="%",
    )
    await db_session.commit()

    card = (await milestones_service.dashboard_cards(db_session))[0]
    assert card["current"] is None
    assert card["remaining"] is None

    # A matching unit still computes normally (kg goal, kg unit).
    await milestones_service.update_milestone(db_session, m.id, target_unit="кг")
    await db_session.commit()
    card = (await milestones_service.dashboard_cards(db_session))[0]
    assert card["current"] == 86.1
    assert card["remaining"] == pytest.approx(71.1, abs=0.01)

    # No unit at all stays permissive (older goals predate this field).
    await milestones_service.update_milestone(db_session, m.id, target_unit=None)
    await db_session.commit()
    card = (await milestones_service.dashboard_cards(db_session))[0]
    assert card["current"] == 86.1


async def test_create_and_progress_body_fat_goal(db_session, monkeypatch):
    # 1. Log Navy body fat (approx 14.52% for height=190, neck=38, waist=85, weight=88)
    await weight_service.log_weight(db_session, on_date=DAY, weight_kg=88.0)
    await weight_service.upsert_body_measurement(
        db_session, on_date=DAY, neck_cm=38, waist_cm=85
    )
    
    m = await milestones_service.create_milestone(
        db_session, name="Снизить жир до 12%", domain="body_comp", target_value=12.0,
        target_unit="%", deadline=DAY + timedelta(days=60),
    )
    await db_session.commit()

    cards = await milestones_service.dashboard_cards(db_session)
    assert len(cards) == 1
    card = cards[0]
    # Verify Navy body fat is retrieved and progress is computed
    assert card["current"] is not None
    assert card["current"] == pytest.approx(14.52, abs=0.1)
    assert card["remaining"] == pytest.approx(14.52 - 12.0, abs=0.1)

    # 2. Enable body_comp module and save a scan with 15.5% fat on DAY + 1 day
    from vitals.services.modules_service import set_module_enabled
    await set_module_enabled(db_session, key="body_comp", enabled=True)
    
    from vitals.services import body_scan_service
    await body_scan_service.save_scan(
        db_session,
        on_date=DAY + timedelta(days=1),
        device="InBody 770",
        metrics=[
            {"label": "Процент жира", "value": 15.5, "unit": "%"},
        ],
    )
    await db_session.commit()

    # Get cards - BIA is available, so "latest" (default) picks it over Navy
    cards = await milestones_service.dashboard_cards(db_session)
    card = cards[0]
    assert card["current"] == 15.5
    assert card["remaining"] == pytest.approx(15.5 - 12.0, abs=0.1)

    # 3. Test body_fat_source preference - force "navy"
    monkeypatch.setenv("VITALS_BODY_FAT_SOURCE", "navy")
    cards = await milestones_service.dashboard_cards(db_session)
    card = cards[0]
    assert card["current"] == pytest.approx(14.52, abs=0.1)

    # 4. Force "bia"
    monkeypatch.setenv("VITALS_BODY_FAT_SOURCE", "bia")
    cards = await milestones_service.dashboard_cards(db_session)
    card = cards[0]
    assert card["current"] == 15.5

    # 5. Back to default ("latest"): even a Navy measurement logged *after* the
    # BIA scan must not steal the spot back — BIA outranks Navy whenever it's
    # available, this isn't a "most recent date wins" contest.
    monkeypatch.delenv("VITALS_BODY_FAT_SOURCE", raising=False)
    await weight_service.upsert_body_measurement(
        db_session, on_date=DAY + timedelta(days=2), neck_cm=39, waist_cm=90
    )
    await db_session.commit()
    cards = await milestones_service.dashboard_cards(db_session)
    card = cards[0]
    assert card["current"] == 15.5


# ── Digest context ────────────────────────────────────────────────────────────
async def test_assemble_context_is_robust_when_empty(db_session, monkeypatch):
    """Context assembles even with no data in any domain."""
    # The profile block comes from env (load_dotenv picks up a real .env), so pin it —
    # otherwise this passes on a bare checkout and fails inside the deploy image, where
    # the production .env carries the owner's actual age/height.
    monkeypatch.setenv("VITALS_USER_AGE", "18")
    monkeypatch.setenv("VITALS_SEX", "male")
    monkeypatch.setenv("VITALS_HEIGHT_CM", "190")
    ctx = await digest_service.assemble_context(db_session, on_date=DAY)
    assert ctx["date"] == "2026-06-10"
    assert ctx["report_meta"]["report_date"] == "2026-06-10"
    assert ctx["report_meta"]["period_days"] == 7
    assert ctx["user_profile"]["age"] == 18
    assert ctx["user_profile"]["sex"] == "male"
    assert ctx["user_profile"]["height_cm"] == 190.0
    assert ctx["weight"]["latest_kg"] is None
    assert ctx["garmin"] is None
    assert ctx["hevy"]["total_workouts"] == 0
    assert ctx["labs"]["out_of_range"] == []
    assert ctx["milestones"] == []
    assert ctx["body_comp"] is None
    # Domains added so the digest reasons across them; null/empty when no data.
    assert ctx["supplements"] is None
    assert ctx["skincare"] is None
    assert ctx["genetics"] is None
    assert ctx["alerts"] is None


async def test_signals_reach_the_digest_context(db_session):
    """The capture domain exists to explain the other domains' numbers. If it
    never lands in the context, everything written to the bot is write-only."""
    from vitals.services import signals_service

    await signals_service.create_signals(
        db_session,
        items=[{"kind": "exposure", "key": "caffeine_late", "at_time": "22:00",
                "note": "кофе в 22"}],
        on_date=DAY - timedelta(days=1),
    )
    rows = await signals_service.create_signals(
        db_session,
        items=[{"kind": "symptom", "key": "headache", "value_num": 4}],
        on_date=DAY,
    )
    await db_session.commit()

    ctx = await digest_service.assemble_context(db_session, on_date=DAY)

    assert [s["key"] for s in ctx["signals"]] == ["caffeine_late", "headache"]
    assert ctx["signals"][0]["at_time"] == "22:00", "the hour is what makes it correlatable"
    assert ctx["signals"][0]["note"] == "кофе в 22"

    # A row he tapped "не то" on is not evidence and must not reach the model.
    await signals_service.mark_misparse(db_session, rows[0].batch_id)
    await db_session.commit()

    ctx = await digest_service.assemble_context(db_session, on_date=DAY)
    assert [s["key"] for s in ctx["signals"]] == ["caffeine_late"]


async def test_assemble_context_pulls_each_domain(db_session):
    from vitals.services import labs_service

    await weight_service.log_weight(db_session, on_date=DAY, weight_kg=88.0)
    await garmin_service.ingest_daily(
        db_session, DAY, {"summary": {"restingHeartRate": 52},
                          "sleep": {"dailySleepDTO": {"sleepScores": {"overall": {"value": 80}}}}}
    )
    await labs_service.add_result(
        db_session, on_date=DAY - timedelta(days=10), marker="TSH", value=5.5, ref_low=0.4, ref_high=4.0
    )
    await db_session.commit()

    ctx = await digest_service.assemble_context(db_session, on_date=DAY)
    assert ctx["weight"]["latest_kg"] == 88.0
    assert ctx["garmin"]["resting_hr"] == 52
    assert ctx["garmin"]["sleep_score"] == 80
    assert ctx["garmin"]["total_days_logged"] == 1
    assert ctx["labs"]["out_of_range"][0]["marker"] == "TSH"
    assert ctx["labs"]["out_of_range"][0]["date"] == (DAY - timedelta(days=10)).isoformat()


async def test_assemble_context_includes_supplements_skincare_genetics_alerts(db_session):
    """The weekly digest must see supplements, skincare, genetics and active
    alerts — previously these enabled domains were absent, so cross-domain
    reasoning (e.g. 'started a supplement → sleep shifted', 'introduced a retinoid
    → skin reacted') had no data to work with."""
    from vitals.services import (
        alerts_service,
        genetics_service,
        skincare_service,
        supplements_service,
    )

    await supplements_service.add_supplement(
        db_session, name="Creatine", dose="5 g", timing="morning", evidence="A"
    )
    await skincare_service.add_observation(
        db_session, on_date=DAY, inflammation=3, pih=1, zone="cheeks", note="reacted"
    )
    await genetics_service.add_variant(
        db_session, gene="HFE", rsid="rs1800562", genotype="GG", marker="hemochromatosis_carrier"
    )
    alert = await alerts_service.raise_alert(
        db_session, domain="labs", severity="warn", message="Ferritin high",
        alert_key="ferritin_high", entity_ref="labs:ferritin",
    )
    alert.created_at = datetime.combine(DAY, datetime.min.time())
    await db_session.commit()

    ctx = await digest_service.assemble_context(db_session, on_date=DAY)

    assert ctx["supplements"] is not None
    assert ctx["supplements"][0]["name"] == "Creatine"
    assert ctx["skincare"] is not None
    assert ctx["skincare"]["recent_observations"][0]["inflammation"] == 3
    assert ctx["skincare"]["active_products"] == 0
    assert ctx["genetics"] is not None
    assert ctx["genetics"][0]["marker"] == "hemochromatosis_carrier"
    assert ctx["alerts"] is not None
    assert ctx["alerts"][0]["message"] == "Ferritin high"


async def test_assemble_context_includes_body_comp(db_session):
    """The weekly digest must see the latest BIA/InBody scan (headline metrics
    + derived LBM) — previously body composition was absent from the analysis."""
    from vitals.models.body_scan import BodyScan, BodyScanMetric

    scan = BodyScan(
        date=DAY - timedelta(days=2), domain="body_comp", source="body_scan", device="InBody 770"
    )
    db_session.add(scan)
    await db_session.flush()
    db_session.add_all(
        [
            BodyScanMetric(
                scan_id=scan.id, metric_key="body_fat_pct", label="PBF",
                value=18.0, unit="%", category="composition",
            ),
            BodyScanMetric(
                scan_id=scan.id, metric_key="skeletal_muscle_mass", label="SMM",
                value=41.5, unit="кг", category="composition",
            ),
            BodyScanMetric(
                scan_id=scan.id, metric_key="phase_angle", label="Phase Angle",
                value=6.2, unit="", category="score",
            ),
        ]
    )
    await db_session.commit()

    ctx = await digest_service.assemble_context(db_session, on_date=DAY)
    bc = ctx["body_comp"]
    assert bc is not None
    assert bc["date"] == (DAY - timedelta(days=2)).isoformat()
    assert bc["device"] == "InBody 770"
    assert bc["metrics"]["body_fat_pct"]["value"] == 18.0
    assert bc["metrics"]["skeletal_muscle_mass"]["value"] == 41.5
    assert bc["metrics"]["phase_angle"]["value"] == 6.2
    # LBM is derived from weight+bf% when no explicit lean metric is present; here
    # there's no weight metric on the scan, so it's simply absent (not invented).
    assert "lean_body_mass" not in bc["metrics"]


async def test_assemble_context_with_custom_period_days(db_session):
    from vitals.models.hevy import HevyWorkout
    from vitals.enums import Source

    workout1 = HevyWorkout(
        external_id="w_old",
        domain="hevy",
        date=DAY - timedelta(days=5),
        source=Source.HEVY_API.value,
        title="Push Day",
    )
    workout2 = HevyWorkout(
        external_id="w_new",
        domain="hevy",
        date=DAY - timedelta(days=2),
        source=Source.HEVY_API.value,
        title="Pull Day",
    )
    db_session.add_all([workout1, workout2])
    await db_session.commit()

    # With period_days=7, both workouts should be counted
    ctx_7 = await digest_service.assemble_context(db_session, on_date=DAY, period_days=7)
    assert ctx_7["hevy"]["total_workouts"] == 2

    # With period_days=4, only the one from 2 days ago should be counted
    ctx_4 = await digest_service.assemble_context(db_session, on_date=DAY, period_days=4)
    assert ctx_4["hevy"]["total_workouts"] == 1


async def test_assemble_context_includes_hrt_and_timeline(db_session):
    """Hormones and the timeline must reach the digest. Without them the
    strongest intervention in the lake (a compound change) and the ready-made
    explanation for a dip (illness, travel) were invisible to the narrative."""
    from vitals.services import hrt_cycle_service, hrt_service, timeline_service

    await hrt_cycle_service.add_cycle(
        db_session, kind="course", name="TRT", start_date=DAY - timedelta(days=30)
    )
    await hrt_service.log_dose(
        db_session, compound_key="testosterone_enanthate", on_date=DAY - timedelta(days=2),
        dose=125.0, unit="mg", site="glute_left",
    )
    await hrt_service.log_side_effect(
        db_session, on_date=DAY - timedelta(days=1), effect_type="acne", severity=2
    )
    await timeline_service.create_annotation(
        db_session, title="Грипп", on_date=DAY - timedelta(days=3),
        end_date=DAY - timedelta(days=1), kind="illness",
    )
    # Outside the 7-day window — must not leak in.
    await timeline_service.create_annotation(
        db_session, title="Старая поездка", on_date=DAY - timedelta(days=60), kind="travel"
    )
    await db_session.commit()

    ctx = await digest_service.assemble_context(db_session, on_date=DAY, period_days=7)

    assert ctx["hrt"] is not None
    assert ctx["hrt"]["doses"][0]["compound_key"] == "testosterone_enanthate"
    assert ctx["hrt"]["doses"][0]["dose"] == 125.0
    assert ctx["hrt"]["side_effects"][0]["effect_type"] == "acne"
    assert ctx["hrt"]["cycle"]["name"] == "TRT"
    assert ctx["hrt"]["cycle"]["kind"] == "course"
    assert [a["title"] for a in ctx["timeline"]] == ["Грипп"]

    # The model ignores keys the system prompt never names.
    llm = FakeLLM()
    await digest_service.generate_digest(db_session, llm, on_date=DAY)
    system_prompt = llm.prompts[0][0]
    assert "hrt:" in system_prompt
    assert "timeline:" in system_prompt


# ── Every domain reaches the digest ───────────────────────────────────────────
#
# Same contract as DOMAIN_EXPORT_KEYS in test_data_portability: assemble_context
# is a long hand-written function whose real failure mode is a new domain being
# added and nobody remembering to give it a block — the AI report then silently
# loses a whole module (which is exactly how hrt and timeline went missing).

DIGEST_DOMAIN_PATHS: dict[Domain, tuple[str, ...]] = {
    Domain.WEIGHT: ("weight", "weight.measurements", "coverage.weight"),
    Domain.BODY_COMPOSITION: (
        "body_comp",
        "body_comp.scans",
        "body_comp.deltas_from_previous_scan",
        "coverage.body_comp",
    ),
    Domain.GLP1: (
        "glp1.active_phase",
        "glp1.phases",
        "glp1.injections",
        "glp1.side_effects",
        "coverage.glp1",
    ),
    Domain.HRT: (
        "hrt.cycle.items",
        "hrt.planned_administrations",
        "hrt.doses",
        "hrt.side_effects",
        "coverage.hrt",
    ),
    Domain.LABS: (
        "labs.results_in_period",
        "labs.trends",
        "labs.retest",
        "coverage.labs",
    ),
    Domain.WORKOUTS: ("hevy.sessions", "training", "coverage.hevy"),
    Domain.GARMIN: ("garmin.activities", "training", "coverage.garmin"),
    Domain.NUTRITION: ("nutrition", "period_stats", "coverage.nutrition"),
    Domain.SUPPLEMENTS: ("supplements", "coverage.supplements"),
    Domain.GENETICS: ("genetics", "coverage.genetics"),
    Domain.SKINCARE: (
        "skincare.logs",
        "skincare.products",
        "skincare.recent_observations",
        "coverage.skincare",
    ),
    Domain.MILESTONES: ("milestones", "coverage.milestones"),
    Domain.TIMELINE: ("timeline", "coverage.timeline"),
    Domain.SIGNALS: (
        "signals",
        "day_context",
        "coverage.signals",
        "coverage.day_context",
    ),
    # Infra rows reach the digest as the active-alert list, not as their own block.
    Domain.SYSTEM: ("alerts",),
}


def test_every_domain_is_mapped_to_digest_keys():
    """A new domain needs an explicit subtable-level context contract."""
    assert set(DIGEST_DOMAIN_PATHS) == set(Domain)
    assert all(DIGEST_DOMAIN_PATHS.values())
    assert set(digest_service._DOMAIN_MODULE) == {domain.value for domain in Domain}


async def test_assemble_context_has_a_key_for_every_domain(db_session):
    """Every mapped key is actually assembled — on an empty database too, so a
    domain can't be "present" only when it happens to have rows."""
    ctx = await digest_service.assemble_context(db_session, on_date=DAY)
    for paths in DIGEST_DOMAIN_PATHS.values():
        for path in paths:
            key = path.split(".", 1)[0]
            assert key in ctx, f"digest context is missing root for {path!r}"


# ── Digest generation ─────────────────────────────────────────────────────────
class FakeLLM:
    digest_model = "fake/model"

    def __init__(self):
        self.prompts = []

    async def complete_text(self, prompt, *, system=None, max_tokens=None, **kw):
        self.prompts.append((system, prompt))
        return "Неделя прошла стабильно: вес снижается, восстановление в норме."


async def test_generate_digest_persists_narrative_and_context(db_session):
    await weight_service.log_weight(db_session, on_date=DAY, weight_kg=88.0)
    await db_session.commit()

    llm = FakeLLM()
    row = await digest_service.generate_digest(db_session, llm, on_date=DAY)
    await db_session.commit()

    assert "стабильно" in row.content
    assert row.model == "fake/model"
    assert row.context_json["weight"]["latest_kg"] == 88.0
    # The system prompt frames it as an analytical peer or partner.
    assert "peer" in llm.prompts[0][0] or "напарник" in llm.prompts[0][0]

    latest = await digest_service.latest_digest(db_session)
    assert latest.id == row.id
    stored = (await db_session.execute(select(WeeklyDigest))).scalars().all()
    assert len(stored) == 1


class FakeBlankLLM:
    """Always returns a blank completion — mirrors the observed prod failure
    (200 OK, no exception, just an empty message)."""

    digest_model = "fake/model"

    def __init__(self):
        self.calls = 0

    async def complete_text(self, prompt, *, system=None, max_tokens=None, **kw):
        self.calls += 1
        return ""


class FakeFlakyLLM:
    """Blank on the first call, real content on the second — the one-retry-clears-it
    case."""

    digest_model = "fake/model"

    def __init__(self):
        self.calls = 0

    async def complete_text(self, prompt, *, system=None, max_tokens=None, **kw):
        self.calls += 1
        if self.calls == 1:
            return ""
        return "Восстановилось со второй попытки."


async def test_generate_digest_raises_and_persists_nothing_when_llm_stays_blank(db_session):
    from vitals.integrations.llm_client import LLMEmptyResponse
    import pytest

    llm = FakeBlankLLM()
    with pytest.raises(LLMEmptyResponse):
        await digest_service.generate_digest(db_session, llm, on_date=DAY)

    assert llm.calls == 2  # one retry, then give up
    stored = (await db_session.execute(select(WeeklyDigest))).scalars().all()
    assert len(stored) == 0


async def test_generate_digest_asks_for_enough_output_tokens(db_session):
    """Regression: prod ran with max_tokens=6000 and the narrative came back cut
    mid-sentence — a reasoning model spends part of the same budget on thinking."""

    class RecordingLLM(FakeLLM):
        def __init__(self):
            super().__init__()
            self.budgets = []

        async def complete_text(self, prompt, *, system=None, max_tokens=None, **kw):
            self.budgets.append(max_tokens)
            return await super().complete_text(prompt, system=system, **kw)

    llm = RecordingLLM()
    await digest_service.generate_digest(db_session, llm, on_date=DAY)
    assert llm.budgets and all(b >= 12000 for b in llm.budgets)


async def test_complete_text_warns_when_the_answer_is_cut_by_the_token_limit(caplog):
    """The SDK reports truncation only via finish_reason — without the log line a
    half-written digest is indistinguishable from a finished one."""
    import logging
    from types import SimpleNamespace

    from vitals.integrations.llm_client import LLMClient

    class FakeCompletions:
        async def create(self, **kw):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="Питание и восстановление рабо"),
                        finish_reason="length",
                    )
                ]
            )

    client = LLMClient()
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))

    with caplog.at_level(logging.WARNING, logger="vitals.integrations.llm_client"):
        text = await client.complete_text("prompt", max_tokens=10)

    assert text == "Питание и восстановление рабо"
    assert any("truncated by max_tokens" in r.getMessage() for r in caplog.records)


async def test_generate_digest_retries_once_and_recovers_from_a_blank_response(db_session):
    llm = FakeFlakyLLM()
    row = await digest_service.generate_digest(db_session, llm, on_date=DAY)
    await db_session.commit()

    assert llm.calls == 2
    assert row.content == "Восстановилось со второй попытки."


async def test_assemble_context_includes_intersecting_noise_markers(db_session):
    # Add noise markers: some overlapping, some not.
    # DAY is 2026-06-10. Current is [06-04, 06-10], previous [05-28, 06-03].
    
    # 1. Overlapping noise marker (ends during the period)
    await weight_service.add_noise_marker(
        db_session,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 5),
        reason="sodium spike"
    )
    # 2. Ongoing noise marker starting during the period
    await weight_service.add_noise_marker(
        db_session,
        start_date=date(2026, 6, 8),
        end_date=None,
        reason="creatine load"
    )
    # 3. Non-overlapping noise marker in the future
    await weight_service.add_noise_marker(
        db_session,
        start_date=date(2026, 6, 12),
        end_date=date(2026, 6, 15),
        reason="future noise"
    )
    # 4. Marker in the comparison window
    await weight_service.add_noise_marker(
        db_session,
        start_date=date(2026, 5, 20),
        end_date=date(2026, 6, 2),
        reason="past noise"
    )
    await db_session.commit()

    ctx = await digest_service.assemble_context(db_session, on_date=DAY, period_days=7)
    markers = ctx["weight"]["noise_markers"]
    
    # Both sides of the comparison must carry their overlapping noise context.
    reasons = [m["reason"] for m in markers]
    assert "sodium spike" in reasons
    assert "creatine load" in reasons
    assert "past noise" in reasons
    assert "future noise" not in reasons
    assert len(reasons) == 3

    # Check structure of the returned markers
    sodium_marker = next(m for m in markers if m["reason"] == "sodium spike")
    assert sodium_marker["start"] == "2026-06-01"
    assert sodium_marker["end"] == "2026-06-05"
    assert sodium_marker["periods"] == ["current", "previous"]

    creatine_marker = next(m for m in markers if m["reason"] == "creatine load")
    assert creatine_marker["start"] == "2026-06-08"
    assert creatine_marker["end"] is None
    assert creatine_marker["periods"] == ["current"]

    past_marker = next(m for m in markers if m["reason"] == "past noise")
    assert past_marker["periods"] == ["previous"]

    # Check that system prompt mentions noise_markers
    llm = FakeLLM()
    await digest_service.generate_digest(db_session, llm, on_date=DAY, period_days=7)
    system_prompt = llm.prompts[0][0]
    assert "noise_markers" in system_prompt
    assert "период" in system_prompt or "period" in system_prompt


async def test_assemble_context_trend_excludes_noise(db_session):
    """The weight trend handed to the LLM must be computed on noise-excluded
    points — otherwise the digest reasons about a spike it's told to discount."""
    import pytest

    base = date(2026, 6, 1)
    for i in range(11):
        await weight_service.log_weight(
            db_session, on_date=base + timedelta(days=i), weight_kg=100.0 - i
        )
    # Water-weight spike on 06-06, marked as noise.
    await weight_service.log_weight(
        db_session, on_date=base + timedelta(days=5), weight_kg=120.0
    )
    await weight_service.add_noise_marker(
        db_session,
        start_date=base + timedelta(days=5),
        end_date=base + timedelta(days=5),
        reason="sodium",
    )
    await db_session.commit()

    ctx = await digest_service.assemble_context(
        db_session, on_date=base + timedelta(days=10), period_days=7
    )
    # Clean −1kg/day line → ≈ −7kg/week, undistorted by the +20kg spike.
    assert ctx["weight"]["trend_kg_per_week"] == pytest.approx(-7.0, abs=0.1)
