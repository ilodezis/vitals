"""Milestones + weekly-digest tests — goal CRUD/progress and the cross-domain
context assembly + LLM narrative generation (with a fake LLM, no network)."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from vitals.models.milestones import WeeklyDigest
from vitals.services import (
    digest_service,
    garmin_service,
    hevy_service,
    milestones_service,
    weight_service,
)

DAY = date(2026, 6, 10)


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


# ── Digest context ────────────────────────────────────────────────────────────
async def test_assemble_context_is_robust_when_empty(db_session):
    """Context assembles even with no data in any domain."""
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


async def test_assemble_context_includes_body_comp(db_session):
    """B3: the weekly digest must see the latest BIA/InBody scan (headline metrics
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


async def test_generate_digest_retries_once_and_recovers_from_a_blank_response(db_session):
    llm = FakeFlakyLLM()
    row = await digest_service.generate_digest(db_session, llm, on_date=DAY)
    await db_session.commit()

    assert llm.calls == 2
    assert row.content == "Восстановилось со второй попытки."


async def test_assemble_context_includes_intersecting_noise_markers(db_session):
    # Add noise markers: some overlapping, some not.
    # DAY is 2026-06-10. 7-day period is [2026-06-04, 2026-06-10]
    
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
    # 4. Non-overlapping noise marker in the past
    await weight_service.add_noise_marker(
        db_session,
        start_date=date(2026, 5, 20),
        end_date=date(2026, 6, 2),
        reason="past noise"
    )
    await db_session.commit()

    ctx = await digest_service.assemble_context(db_session, on_date=DAY, period_days=7)
    markers = ctx["weight"]["noise_markers"]
    
    # Only overlapping/ongoing markers must be present
    reasons = [m["reason"] for m in markers]
    assert "sodium spike" in reasons
    assert "creatine load" in reasons
    assert "future noise" not in reasons
    assert "past noise" not in reasons
    assert len(reasons) == 2

    # Check structure of the returned markers
    sodium_marker = next(m for m in markers if m["reason"] == "sodium spike")
    assert sodium_marker["start"] == "2026-06-01"
    assert sodium_marker["end"] == "2026-06-05"

    creatine_marker = next(m for m in markers if m["reason"] == "creatine load")
    assert creatine_marker["start"] == "2026-06-08"
    assert creatine_marker["end"] is None

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

