"""The landing screen's assembly (``GET /today``).

Every one of these is really the same question asked from a different angle: can
the first screen the owner sees be assembled from whatever happens to be in the
lake — nothing at all, one domain, all of them — without waiting on the model and
without rendering a card for a module that is switched off.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from vitals.enums import DigestKind, Domain, Severity, Source
from vitals.models.milestones import DOMAIN as INSIGHTS_DOMAIN, WeeklyDigest
from vitals.services import milestones_service, nutrition_service, today_service, weight_service
from vitals.utils.timeutils import today_local

ALL_OFF: dict[str, bool] = {}
ALL_ON = {"nutrition": True, "timeline": True, "signals": True, "glp1": True, "hevy": True}


async def test_build_survives_an_empty_database(db_session):
    """Nothing logged, no integrations, no digest — still a coherent screen."""
    ctx = await today_service.build(db_session, enabled_modules=ALL_ON)

    assert ctx["date"] == today_local()
    assert ctx["narrative"]  # never blank: the fallback sentence stands in
    assert ctx["narrative_source"] == "computed"
    assert ctx["feed"] == []
    assert ctx["changes"] == []
    assert ctx["goal"] is None
    # The figures row is the page's skeleton — it renders with em dashes rather
    # than collapsing, so the screen doesn't change shape once data arrives.
    assert [f["key"] for f in ctx["figures"]][:4] == [
        "weight",
        "sleep_score",
        "hrv_avg",
        "body_battery_high",
    ]
    # Nothing measured reads as an em dash, not a zero. "Съедено 0" is the one
    # honest zero here — no meal logged today is a real number of calories.
    assert all(f["value"] == "—" for f in ctx["figures"][:4])


# What ``generate_brief`` actually stores: the whole message that went to
# Telegram — the deterministic header, the day line, then the model's block.
BRIEF_CONTEXT = {
    "garmin": {"sleep_score": 75, "hrv_avg": 42, "resting_hr": 63, "body_battery_high": 86},
    "weight": {"latest_kg": 106.8, "trend_kg_per_week": -1.06},
    "day": {"answers": {"where": "дома", "gym": "нет"}, "source": Source.TEMPLATE.value},
}
BRIEF_PROSE = "HRV и пульс покоя держатся на твоём базовом уровне — крути день как обычно."


def _stored_brief(prose: str = BRIEF_PROSE, *, model: str | None = "test-model"):
    """A brief row shaped the way the morning job writes one."""
    from vitals.services.proactive import compose, day_plan

    blocks = compose.header_blocks(BRIEF_CONTEXT)
    day = day_plan.day_block(BRIEF_CONTEXT["day"])
    if day is not None:
        blocks.append(day)
    if prose:
        blocks.append(compose.Block(compose.KIND_NARRATIVE, prose, 90))
    return WeeklyDigest(
        date=today_local(),
        domain=INSIGHTS_DOMAIN,
        source=Source.MANUAL.value,
        kind=DigestKind.DAILY_BRIEF.value,
        content=compose.render(blocks),
        context_json=BRIEF_CONTEXT,
        model=model,
    )


async def test_hero_takes_only_the_prose_out_of_todays_brief(db_session):
    """The stored brief is the whole Telegram message, header numbers included —
    printed whole it made the hero repeat every key figure back in 38px."""
    db_session.add(_stored_brief())
    await db_session.commit()

    ctx = await today_service.build(db_session, enabled_modules=ALL_OFF)

    assert ctx["narrative"] == BRIEF_PROSE
    assert ctx["narrative_source"] == "digest"
    assert "Body Battery" not in ctx["narrative"]
    assert "HRV 42" not in ctx["narrative"]
    # The brief is the one feed row allowed to carry the accent.
    assert [row["dot"] for row in ctx["feed"]] == ["amber"]


async def test_a_header_only_brief_falls_back_to_the_computed_sentence(db_session):
    """The model stayed silent that morning, so the row is numbers only — promoting
    a number line into the headline is worse than composing one."""
    db_session.add(_stored_brief(prose="", model=None))
    await db_session.commit()

    ctx = await today_service.build(db_session, enabled_modules=ALL_OFF)

    assert ctx["narrative_source"] == "computed"
    assert ctx["feed"] == []


async def test_yesterdays_brief_does_not_stand_in_for_today(db_session):
    """A narrative is about a day. Yesterday's read as today's is worse than none."""
    db_session.add(
        WeeklyDigest(
            date=today_local() - timedelta(days=1),
            domain=INSIGHTS_DOMAIN,
            source=Source.MANUAL.value,
            kind=DigestKind.DAILY_BRIEF.value,
            content="Вчерашний текст.",
        )
    )
    await db_session.commit()

    ctx = await today_service.build(db_session, enabled_modules=ALL_OFF)

    assert ctx["narrative_source"] == "computed"
    assert "Вчерашний текст." != ctx["narrative"]


async def test_weight_drives_the_figure_and_the_fallback_sentence(db_session):
    for offset, kg in ((14, 95.0), (7, 93.5), (0, 92.0)):
        await weight_service.log_weight(
            db_session, on_date=today_local() - timedelta(days=offset), weight_kg=kg
        )
    await db_session.commit()

    ctx = await today_service.build(db_session, enabled_modules=ALL_OFF)

    weight_figure = ctx["figures"][0]
    assert weight_figure["key"] == "weight"
    assert weight_figure["value"] == "92"
    assert "92" in ctx["narrative"]
    # A week-over-week weight row needs both ends of the window; with three
    # weigh-ins spanning a fortnight there is one.
    assert [c["key"] for c in ctx["changes"]] == ["weight"]
    assert ctx["changes"][0]["href"] == "/weight"


async def test_a_disabled_module_contributes_nothing(db_session):
    """Nutrition off: no calories figure, no meal in the feed — not an empty card."""
    await nutrition_service.log_meal(
        db_session, on_date=today_local(), name="Курица с рисом", calories=520
    )
    await db_session.commit()

    off = await today_service.build(db_session, enabled_modules=ALL_OFF)
    assert "calories" not in [f["key"] for f in off["figures"]]
    assert off["feed"] == []

    on = await today_service.build(db_session, enabled_modules={"nutrition": True})
    assert "calories" in [f["key"] for f in on["figures"]]
    assert [row["text"] for row in on["feed"]] == ["Курица с рисом"]


async def test_calories_change_compares_logged_days(db_session):
    """Intake week over week is per *logged* day: a week with three days filled in
    must not read as a crash in intake that never happened."""
    for offset, cal in ((10, 1800.0), (9, 2000.0), (2, 1500.0)):
        await nutrition_service.log_meal(
            db_session,
            on_date=today_local() - timedelta(days=offset),
            name="Обед",
            calories=cal,
        )
    await db_session.commit()

    ctx = await today_service.build(db_session, enabled_modules={"nutrition": True})

    row = next(c for c in ctx["changes"] if c["key"] == "calories")
    assert row["href"] == "/nutrition"
    assert row["sentence"].startswith("1900 → 1500")   # (1800+2000)/2 → 1500/1
    assert row["delta"] == "−400"


async def test_goal_reads_as_distance_covered(db_session):
    """The bar needs a starting point, and milestones_service has no notion of one
    — the first logged weight is what "11.2 of 17.5 covered" is measured from."""
    for offset, kg in ((30, 100.0), (0, 94.0)):
        await weight_service.log_weight(
            db_session, on_date=today_local() - timedelta(days=offset), weight_kg=kg
        )
    await milestones_service.create_milestone(
        db_session, name="Дойти до 85", domain=Domain.WEIGHT.value,
        target_value=85.0, target_unit="кг",
    )
    await db_session.commit()

    goal = (await today_service.build(db_session, enabled_modules=ALL_OFF))["goal"]

    assert goal["done"] == "6"     # 100 → 94
    assert goal["total"] == "15"   # 100 → 85
    assert goal["pct"] == 40


async def test_goal_skips_a_goal_already_reached(db_session):
    """Once the nearer goal is crossed and closes itself, the bar moves on to the
    next one instead of sitting at 100% on a finished goal."""
    for offset, kg in ((30, 110.0), (0, 104.0)):
        await weight_service.log_weight(
            db_session, on_date=today_local() - timedelta(days=offset), weight_kg=kg
        )
    await milestones_service.create_milestone(
        db_session, name="Дойти до 105", domain=Domain.WEIGHT.value,
        target_value=105.0, target_unit="кг", deadline=today_local() - timedelta(days=1),
    )
    await milestones_service.create_milestone(
        db_session, name="Дойти до 90", domain=Domain.WEIGHT.value,
        target_value=90.0, target_unit="кг",
    )
    await db_session.commit()

    goal = (await today_service.build(db_session, enabled_modules=ALL_OFF))["goal"]

    assert goal["name"] == "Дойти до 90"


async def test_recovery_advice_arrives_as_an_observation(db_session):
    """An interpretation of the numbers is not a failure: it joins the attention
    card on the quietest rung, never as a warning."""
    from vitals.models.garmin import GarminDaily

    db_session.add(
        GarminDaily(
            date=today_local(),
            domain=Domain.GARMIN.value,
            source=Source.GARMIN_API.value,
            sleep_score=41,
            hrv_avg=28,
            body_battery_high=44,
        )
    )
    await db_session.commit()

    ctx = await today_service.build(db_session, enabled_modules=ALL_OFF)

    notes = [a for a in ctx["attention"] if a["severity"] == Severity.NOTE.value]
    assert notes, ctx["attention"]
    assert all(a["severity"] != Severity.WARN.value for a in notes)


async def test_feed_stays_a_glance_on_a_busy_day(db_session):
    """Every seeded goal and supplement carries today's date on a first run — the
    card is the day at a glance, so it is capped rather than left unbounded."""
    for i in range(20):
        await nutrition_service.log_meal(
            db_session, on_date=today_local(), name=f"Приём {i}", calories=100
        )
    await db_session.commit()

    ctx = await today_service.build(db_session, enabled_modules={"nutrition": True})

    assert len(ctx["feed"]) == today_service._FEED_LIMIT


# ── collect(): the same day as raw values, for the React screen ──────────────
#
# ``build()`` phrases everything for the server-rendered page. The API sends the
# screen numbers and dates and lets it phrase them, so ``collect()`` is the one
# assembly and ``build()`` a formatter over it.


def _garmin(days_ago: int, **fields):
    from vitals.models.garmin import GarminDaily

    return GarminDaily(
        date=today_local() - timedelta(days=days_ago),
        domain=Domain.GARMIN.value,
        source=Source.GARMIN_API.value,
        **fields,
    )


async def _daily_weights(db_session, start_kg: float, end_kg: float, days: int = 15):
    for offset in range(days):
        kg = end_kg + (start_kg - end_kg) * offset / (days - 1)
        await weight_service.log_weight(
            db_session, on_date=today_local() - timedelta(days=offset), weight_kg=round(kg, 2)
        )


async def test_collect_hands_over_numbers_not_phrases(db_session):
    for offset, kg in ((14, 95.0), (7, 93.5), (0, 92.0)):
        await weight_service.log_weight(
            db_session, on_date=today_local() - timedelta(days=offset), weight_kg=kg
        )
    db_session.add(
        _garmin(0, sleep_score=82, sleep_seconds=27240, hrv_avg=46.0,
                body_battery_high=94, body_battery_change=58)
    )
    await db_session.commit()

    data = await today_service.collect(db_session, enabled_modules=ALL_OFF)

    figures = {f["key"]: f for f in data["figures"]}
    assert figures["weight"]["value"] == 92.0
    assert isinstance(figures["weight"]["trend"], float)
    assert figures["sleep_score"]["value"] == 82
    assert figures["sleep_score"]["sleep_seconds"] == 27240
    assert figures["body_battery_high"]["gained"] == 58
    # A date is a date and the weight it belongs to is a number: the screen
    # formats both, in the reader's language.
    assert data["latest_weight"] == {"kg": 92.0, "date": today_local()}
    assert data["date"] == today_local()
    assert data["sync"] == [{"source": "Garmin", "date": today_local()}]


async def test_collect_gives_recovery_its_personal_range(db_session):
    """His own fortnight, before today, is the yardstick: mean ± one standard
    deviation is the corridor a night is read against."""
    for n in range(1, 15):
        db_session.add(_garmin(n, hrv_avg=48.0 if n % 2 else 56.0))
    db_session.add(_garmin(0, hrv_avg=46.0))
    await db_session.commit()

    data = await today_service.collect(db_session, enabled_modules=ALL_OFF)

    hrv = next(f for f in data["figures"] if f["key"] == "hrv_avg")
    assert hrv["baseline"] == 52.0
    assert hrv["corridor"] == {"lo": 48.0, "hi": 56.0}
    change = next(c for c in data["changes"] if c["key"] == "hrv_avg")
    assert (change["lo"], change["hi"]) == (48.0, 56.0)
    assert change["before"] == pytest.approx(51.43, abs=0.01)
    assert change["after"] == pytest.approx(51.14, abs=0.01)
    assert change["domain_key"] == "garmin"


async def test_a_range_needs_enough_history_to_mean_anything(db_session):
    for n in range(1, 3):
        db_session.add(_garmin(n, hrv_avg=50.0))
    db_session.add(_garmin(0, hrv_avg=46.0))
    await db_session.commit()

    data = await today_service.collect(db_session, enabled_modules=ALL_OFF)

    hrv = next(f for f in data["figures"] if f["key"] == "hrv_avg")
    assert hrv["baseline"] is None
    assert hrv["corridor"] is None


async def test_the_weight_row_has_no_corridor(db_session):
    """A norm for a weight would be a verdict on the number; the goal has its own card."""
    await _daily_weights(db_session, 96.0, 92.0, days=15)
    await db_session.commit()

    data = await today_service.collect(db_session, enabled_modules=ALL_OFF)

    change = next(c for c in data["changes"] if c["key"] == "weight")
    assert change["lo"] is None and change["hi"] is None
    assert change["domain_key"] == "weight"
    assert change["tone"] == "good"


async def test_calories_carry_the_daily_goal_as_their_corridor(db_session):
    await nutrition_service.log_meal(
        db_session, on_date=today_local(), name="Обед", calories=520, protein_g=30
    )
    await db_session.commit()

    data = await today_service.collect(db_session, enabled_modules={"nutrition": True})

    calories = next(f for f in data["figures"] if f["key"] == "calories")
    assert calories["value"] == 520
    assert calories["corridor"]["lo"] < calories["corridor"]["hi"]


async def test_meals_arrive_as_calories_not_as_text(db_session):
    await nutrition_service.log_meal(
        db_session, on_date=today_local(), name="Курица с рисом", calories=520
    )
    await db_session.commit()

    data = await today_service.collect(db_session, enabled_modules={"nutrition": True})

    assert data["feed"] == [
        {"time": data["feed"][0]["time"], "kind": "meal", "dot": "good",
         "text": "Курица с рисом", "detail": "", "value": 520.0}
    ]


async def test_todays_weigh_in_joins_the_feed_only_when_asked(db_session):
    """The React screen adds a weigh-in to the day the moment it is saved, so a
    refetch has to keep it there; the server-rendered feed never listed one."""
    await weight_service.log_weight(db_session, on_date=today_local(), weight_kg=86.1)
    await db_session.commit()

    plain = await today_service.collect(db_session, enabled_modules=ALL_OFF)
    asked = await today_service.collect(db_session, enabled_modules=ALL_OFF, weigh_ins=True)

    assert plain["feed"] == []
    assert len(asked["feed"]) == 1
    row = asked["feed"][0]
    assert (row["kind"], row["dot"], row["value"]) == ("weight", "good", 86.1)
    # ``created_at`` has no reliable zone; a row without a time says so honestly.
    assert row["time"] == ""


async def test_the_goal_forecasts_where_the_trend_lands(db_session):
    await _daily_weights(db_session, 100.0, 93.0)
    await milestones_service.create_milestone(
        db_session, name="Дойти до 85", domain=Domain.WEIGHT.value,
        target_value=85.0, target_unit="кг", deadline=today_local() + timedelta(days=60),
    )
    await db_session.commit()

    goal = (await today_service.collect(db_session, enabled_modules=ALL_OFF))["goal"]

    assert goal["start_kg"] == 100.0
    assert goal["current_kg"] == 93.0
    assert goal["target_kg"] == 85.0
    assert goal["deadline"] == today_local() + timedelta(days=60)
    forecast = goal["forecast"]
    assert today_local() < forecast["date"] < goal["deadline"]
    # Positive: ahead of the deadline.
    assert forecast["days_ahead"] == (goal["deadline"] - forecast["date"]).days
    assert forecast["days_ahead"] > 0


async def test_a_trend_that_moves_away_forecasts_nothing(db_session):
    await _daily_weights(db_session, 90.0, 94.0)
    await milestones_service.create_milestone(
        db_session, name="Дойти до 85", domain=Domain.WEIGHT.value,
        target_value=85.0, target_unit="кг",
    )
    await db_session.commit()

    goal = (await today_service.collect(db_session, enabled_modules=ALL_OFF))["goal"]

    assert goal["forecast"] is None


async def test_a_goal_without_a_deadline_still_forecasts_a_date(db_session):
    await _daily_weights(db_session, 100.0, 93.0)
    await milestones_service.create_milestone(
        db_session, name="Дойти до 85", domain=Domain.WEIGHT.value,
        target_value=85.0, target_unit="кг",
    )
    await db_session.commit()

    goal = (await today_service.collect(db_session, enabled_modules=ALL_OFF))["goal"]

    assert goal["deadline"] is None
    assert goal["forecast"]["date"] > today_local()
    assert goal["forecast"]["days_ahead"] is None


async def test_a_crawl_toward_the_goal_is_not_a_forecast(db_session):
    """At a gram a week the "date" is past any horizon a person plans by."""
    await _daily_weights(db_session, 93.01, 93.0)
    await milestones_service.create_milestone(
        db_session, name="Дойти до 85", domain=Domain.WEIGHT.value,
        target_value=85.0, target_unit="кг",
    )
    await db_session.commit()

    goal = (await today_service.collect(db_session, enabled_modules=ALL_OFF))["goal"]

    assert goal["forecast"] is None


async def test_attention_names_the_domain_it_is_about(db_session):
    from vitals.services import alerts_service

    await alerts_service.raise_alert(
        db_session, domain=Domain.LABS.value, severity=Severity.WARN.value,
        message="Витамин D ниже референса", alert_key="labs.out_of_range", entity_ref="lab:1",
    )
    await db_session.commit()

    data = await today_service.collect(db_session, enabled_modules=ALL_OFF)

    assert {"severity": "warn", "message": "Витамин D ниже референса", "domain": "labs"} in data["attention"]


async def test_attention_sorts_by_severity_and_preserves_freshness(db_session):
    from vitals.services import alerts_service

    # Clean existing alerts to test deterministic order
    await alerts_service.resolve_all(db_session)
    await db_session.commit()

    # Raise alerts: older then newer for each severity
    await alerts_service.raise_alert(
        db_session, domain=Domain.LABS.value, severity=Severity.WARN.value,
        message="warn_old", alert_key="k_warn_1", entity_ref="e1",
    )
    await db_session.commit()

    await alerts_service.raise_alert(
        db_session, domain=Domain.WEIGHT.value, severity=Severity.INFO.value,
        message="info_old", alert_key="k_info_1", entity_ref="e2",
    )
    await db_session.commit()

    await alerts_service.raise_alert(
        db_session, domain=Domain.SUPPLEMENTS.value, severity=Severity.BLOCK.value,
        message="block_old", alert_key="k_block_1", entity_ref="e3",
    )
    await db_session.commit()

    await alerts_service.raise_alert(
        db_session, domain=Domain.LABS.value, severity=Severity.WARN.value,
        message="warn_new", alert_key="k_warn_2", entity_ref="e4",
    )
    await db_session.commit()

    await alerts_service.raise_alert(
        db_session, domain=Domain.SUPPLEMENTS.value, severity=Severity.BLOCK.value,
        message="block_new", alert_key="k_block_2", entity_ref="e5",
    )
    await db_session.commit()

    await alerts_service.raise_alert(
        db_session, domain=Domain.WEIGHT.value, severity=Severity.INFO.value,
        message="info_new", alert_key="k_info_2", entity_ref="e6",
    )
    await db_session.commit()

    data = await today_service.collect(db_session, enabled_modules=ALL_OFF)
    messages = [a["message"] for a in data["attention"] if a["message"].startswith(("block_", "warn_", "info_"))]

    assert messages == ["block_new", "block_old", "warn_new", "warn_old", "info_new", "info_old"]

