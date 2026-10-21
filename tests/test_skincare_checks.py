"""The skincare routine as a plan for the day, and what was ticked off of it.

What has to hold:

  * the plan is exactly the catalog's schedule for that weekday and slot —
    "both" in both, inactive products nowhere;
  * a tick is what feeds the conflict engine now, so a tick has to set the
    product's flag on the day's log, and an untick has to clear it — but only
    when no other tick of the day still carries the same flag;
  * the history never shows the days before tracking existed as "missed".
"""
from __future__ import annotations

import importlib
from datetime import date, timedelta

import pytest

from vitals.models.conflict_rule import ConflictRule
from vitals.models.skincare import SkincareCheck
from vitals.services import skincare_service
from vitals.services.conflict_engine import ConflictBlocked

WED = date(2026, 10, 21)  # weekday 3 in the catalog's numbering
THU = WED + timedelta(days=1)

migration = importlib.import_module("migrations.versions.0038_skincare_checks_and_photos")


async def _product(db_session, name, *, time="evening", days=(3,), flag=None, active=True):
    row = await skincare_service.add_product(
        db_session,
        name=name,
        type="test",
        default_time=time,
        schedule_days=list(days),
        active=active,
        active_flag=flag,
    )
    await db_session.commit()
    return row


async def _retinoid_peel_rule(db_session):
    db_session.add(
        ConflictRule(
            rule_type="hard_block",
            domain_a="skincare",
            condition_a={"retinoid": True},
            domain_b="skincare",
            condition_b={"peel": True},
            severity="block",
            message="Ретиноид и пилинг в один вечер.",
            active=True,
        )
    )
    await db_session.commit()


def _names(items):
    return [i["name"] for i in items]


# ── The plan ──────────────────────────────────────────────────────────────────
async def test_plan_is_the_schedule_for_that_weekday_and_slot(db_session):
    await _product(db_session, "SPF", time="morning", days=(3,))
    await _product(db_session, "Крем", time="both", days=(3, 4))
    await _product(db_session, "Ретиноид", time="evening", days=(4,))
    await _product(db_session, "Старое", time="evening", days=(3,), active=False)

    plan = await skincare_service.plan_for(db_session, WED)

    assert _names(plan["morning"]) == ["SPF", "Крем"] or _names(plan["morning"]) == ["Крем", "SPF"]
    assert _names(plan["evening"]) == ["Крем"]
    assert not any(i["done"] for slot in plan.values() for i in slot)


async def test_sunday_is_zero_in_the_catalog(db_session):
    """The catalog numbers days like JS ``getDay``; Python's Sunday is 6."""
    await _product(db_session, "Воскресное", days=(0,))
    sunday = date(2026, 10, 25)
    assert _names((await skincare_service.plan_for(db_session, sunday))["evening"]) == [
        "Воскресное"
    ]


# ── Ticks feed the conflict engine's checklist ───────────────────────────────
async def test_a_tick_sets_the_flag_and_an_untick_clears_it(db_session):
    p = await _product(db_session, "Дифферин", flag="retinoid")

    await skincare_service.set_check(
        db_session, on_date=WED, product_id=p.id, slot="evening", done=True
    )
    await db_session.commit()
    log = await skincare_service.get_log(db_session, WED)
    assert log is not None and log.retinoid is True
    plan = await skincare_service.plan_for(db_session, WED)
    assert plan["evening"][0]["done"] is True

    await skincare_service.set_check(
        db_session, on_date=WED, product_id=p.id, slot="evening", done=False
    )
    await db_session.commit()
    # Nothing left on the day and no note: the empty log goes too.
    assert await skincare_service.get_log(db_session, WED) is None


async def test_ticking_twice_is_one_tick(db_session):
    p = await _product(db_session, "Крем", flag="moisturizer")
    for _ in range(2):
        await skincare_service.set_check(
            db_session, on_date=WED, product_id=p.id, slot="evening", done=True
        )
    await db_session.commit()
    rows = (await skincare_service.checks_between(db_session, WED, WED))
    assert len(rows) == 1


async def test_an_untick_keeps_a_flag_another_tick_still_sets(db_session):
    """Cream in the morning and in the evening: unticking one is not "no cream"."""
    p = await _product(db_session, "Крем", time="both", flag="moisturizer")
    for slot in ("morning", "evening"):
        await skincare_service.set_check(
            db_session, on_date=WED, product_id=p.id, slot=slot, done=True
        )
    await skincare_service.set_check(
        db_session, on_date=WED, product_id=p.id, slot="morning", done=False
    )
    await db_session.commit()
    assert (await skincare_service.get_log(db_session, WED)).moisturizer is True


async def test_an_untick_does_not_touch_a_flag_set_by_hand(db_session):
    """A log written through the old form (or MCP) keeps what no tick set."""
    await skincare_service.upsert_log(db_session, on_date=WED, peel=True, note="салон")
    p = await _product(db_session, "Крем", flag="moisturizer")
    await skincare_service.set_check(
        db_session, on_date=WED, product_id=p.id, slot="evening", done=True
    )
    await skincare_service.set_check(
        db_session, on_date=WED, product_id=p.id, slot="evening", done=False
    )
    await db_session.commit()
    log = await skincare_service.get_log(db_session, WED)
    assert log.peel is True and log.moisturizer is False and log.note == "салон"


async def test_a_conflicting_tick_is_blocked_unless_overridden(db_session):
    await _retinoid_peel_rule(db_session)
    ret_id = (await _product(db_session, "Дифферин", flag="retinoid")).id
    peel_id = (await _product(db_session, "Пилинг", flag="peel")).id
    await skincare_service.set_check(
        db_session, on_date=WED, product_id=ret_id, slot="evening", done=True
    )
    await db_session.commit()

    with pytest.raises(ConflictBlocked):
        await skincare_service.set_check(
            db_session, on_date=WED, product_id=peel_id, slot="evening", done=True
        )
    await db_session.rollback()

    violations = await skincare_service.set_check(
        db_session, on_date=WED, product_id=peel_id, slot="evening", done=True, override=True
    )
    await db_session.commit()
    assert violations and violations[0].is_blocking
    log = await skincare_service.get_log(db_session, WED)
    assert log.retinoid is True and log.peel is True


async def test_a_product_without_a_flag_is_tracked_and_never_conflicts(db_session):
    p = await _product(db_session, "Пенка")
    await skincare_service.set_check(
        db_session, on_date=WED, product_id=p.id, slot="evening", done=True
    )
    await db_session.commit()
    assert await skincare_service.get_log(db_session, WED) is None
    assert (await skincare_service.plan_for(db_session, WED))["evening"][0]["done"] is True


async def test_complete_slot_ticks_only_what_is_open(db_session):
    a = await _product(db_session, "A")
    await _product(db_session, "B")
    await _product(db_session, "Утреннее", time="morning")
    await skincare_service.set_check(
        db_session, on_date=WED, product_id=a.id, slot="evening", done=True
    )
    await skincare_service.complete_slot(db_session, on_date=WED, slot="evening")
    await db_session.commit()

    plan = await skincare_service.plan_for(db_session, WED)
    assert all(i["done"] for i in plan["evening"])
    assert not any(i["done"] for i in plan["morning"])


async def test_a_deleted_product_keeps_its_history(db_session):
    p = await _product(db_session, "Снятый с продажи")
    await skincare_service.set_check(
        db_session, on_date=WED, product_id=p.id, slot="evening", done=True
    )
    await db_session.commit()
    await skincare_service.delete_product(db_session, p.id)
    await db_session.commit()

    item = (await skincare_service.plan_for(db_session, WED))["evening"][0]
    assert item["name"] == "Снятый с продажи"
    assert item["done"] is True and item["planned"] is False


async def test_unknown_slot_and_product_are_refused(db_session):
    with pytest.raises(ValueError):
        await skincare_service.set_check(
            db_session, on_date=WED, product_id=1, slot="noon", done=True
        )
    with pytest.raises(LookupError):
        await skincare_service.set_check(
            db_session, on_date=WED, product_id=999, slot="evening", done=True
        )


# ── History ──────────────────────────────────────────────────────────────────
async def test_history_starts_at_the_first_tick(db_session):
    """Before tracking existed nothing was "missed" — there was no button."""
    p = await _product(db_session, "Крем", days=(0, 1, 2, 3, 4, 5, 6))
    await skincare_service.set_check(
        db_session, on_date=WED, product_id=p.id, slot="evening", done=True
    )
    await db_session.commit()

    days = await skincare_service.history(db_session, end=WED + timedelta(days=3))
    assert [d["date"] for d in days] == [
        (WED + timedelta(days=2)).isoformat(),
        (WED + timedelta(days=1)).isoformat(),
        WED.isoformat(),
    ]
    assert days[0]["evening"][0]["done"] is False  # missed
    assert days[-1]["evening"][0]["done"] is True


async def test_no_ticks_no_history(db_session):
    await _product(db_session, "Крем", days=(0, 1, 2, 3, 4, 5, 6))
    assert await skincare_service.history(db_session, end=THU) == []


# ── The backfill of the product → flag mapping ───────────────────────────────
@pytest.mark.parametrize(
    "texts, flag",
    [
        (("Ретиноид", "Дифферин (Ретиноид)", "Адапален 0.1%"), "retinoid"),
        (("Азелаин", "Азелик", None), "azelaic"),
        (("Кислотный пилинг", None, "AHA/BHA кислоты"), "peel"),
        (("Ниацинамид + SPF", "Сыворотка + SPF", None), "niacinamide_spf"),
        (("Увлажнение", "Увлажняющий крем", "Базовый крем"), "moisturizer"),
        (("Очищение", "Пенка", None), None),
    ],
)
def test_migration_guesses_the_flag_from_the_seeded_catalog(texts, flag):
    assert migration.guess_flag(*texts) == flag


def test_check_model_is_registered():
    assert SkincareCheck.__tablename__ == "skincare_checks"
