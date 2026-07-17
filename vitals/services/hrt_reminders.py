"""HRT reminders — hormone-panel bloodwork seeding + the two scheduled nags.

Two protocol-aware reminders, complementary to Labs' own generic per-marker
overdue-retest alert:

  * **Bloodwork due** (``hrt.labs_due``) — while a cycle is active, if no
    hormone-panel result exists within a kind-dependent window (blasts need
    tighter monitoring than a TRT cruise), raise a passive ``warn``.
  * **Injection due** (``hrt.injection_due``) — for each active cycle item, if the
    most recent shot the fixed-grid schedule expected by today hasn't been logged,
    raise a per-compound ``info`` nag. Fixed grid: being late doesn't shift it.

Both are idempotent, respect same-day dismissal, and resolve themselves once the
condition clears — safe on every dashboard load and scheduler tick.

:func:`seed_hormone_panel` registers the panel markers in the Labs catalog (with
a retest interval + ``hrt_panel`` category) so they also power Labs' own overdue
alert and show up as a coherent group. Called once at startup, idempotent.
"""
from __future__ import annotations

import logging
from datetime import date as date_type
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import Domain, Severity
from vitals.i18n import current_lang, t
from vitals.models.hrt import HrtDose
from vitals.models.labs import LabMarker, LabResult
from vitals.services import alerts_service, hrt_cycle_service, hrt_service, labs_service
from vitals.utils.timeutils import today_local

logger = logging.getLogger(__name__)

LABS_DUE_KEY = "hrt.labs_due"
INJECTION_DUE_KEY = "hrt.injection_due"

# Hormone / safety panel: canonical marker name -> retest interval (days). Names
# are in the normalized form Labs stores (labs_service.normalize_marker), so a
# user-logged result lands on the same row.
HORMONE_PANEL: dict[str, int] = {
    "Тестостерон общий": 90,
    "Тестостерон свободный": 90,
    "Эстрадиол": 90,
    "ЛГ": 90,
    "ФСГ": 90,
    "Пролактин": 90,
    "ГСПГ": 90,
    "Гематокрит": 90,
    "Гемоглобин": 90,
    "АЛТ": 90,
    "АСТ": 90,
    "ПСА": 180,
}
_PANEL_CATEGORY = "hrt_panel"

# How stale the panel may get before nagging, by cycle kind. Blasts push harder,
# so they warrant tighter monitoring than a steady TRT cruise.
PANEL_WINDOW_BY_KIND: dict[str, int] = {
    "blast": 56,
    "trt_baseline": 90,
    "cruise": 90,
    "pct": 30,
    "bridge": 60,
}
_DEFAULT_PANEL_WINDOW = 90


async def seed_hormone_panel(session: AsyncSession) -> dict[str, int]:
    """Register the panel markers in the Labs catalog. Idempotent — creates a
    missing marker, and backfills ``category``/``retest_interval_days`` on an
    existing one only when unset (never clobbers a user's edit)."""
    created = 0
    updated = 0
    for name, interval in HORMONE_PANEL.items():
        row = await labs_service.get_marker(session, name)
        if row is None:
            session.add(
                LabMarker(
                    domain=labs_service.DOMAIN,
                    name=labs_service.normalize_marker(name),
                    category=_PANEL_CATEGORY,
                    retest_interval_days=interval,
                )
            )
            created += 1
        else:
            touched = False
            if row.category is None:
                row.category = _PANEL_CATEGORY
                touched = True
            if row.retest_interval_days is None:
                row.retest_interval_days = interval
                touched = True
            if touched:
                updated += 1
    await session.flush()
    logger.info("hrt_reminders.seed_hormone_panel: %d created, %d updated", created, updated)
    return {"created": created, "updated": updated}


async def _latest_panel_result_date(session: AsyncSession) -> Optional[date_type]:
    names = [labs_service.normalize_marker(n) for n in HORMONE_PANEL]
    result = await session.execute(
        select(LabResult.date)
        .where(LabResult.marker.in_(names))
        .order_by(LabResult.date.desc())
        .limit(1)
    )
    return result.scalars().first()


async def refresh_labs_due(
    session: AsyncSession, *, on_date: Optional[date_type] = None
) -> None:
    """Raise/clear the bloodwork-due warn for the active cycle. No cycle → clear."""
    today = on_date or today_local()
    cycle = await hrt_cycle_service.active_cycle(session, on_date=today)
    if cycle is None:
        await alerts_service.resolve_by_key(session, alert_key=LABS_DUE_KEY)
        return

    window = PANEL_WINDOW_BY_KIND.get(cycle.kind, _DEFAULT_PANEL_WINDOW)
    latest = await _latest_panel_result_date(session)
    overdue = latest is None or (today - latest).days > window
    if overdue:
        if await alerts_service._was_dismissed_today(session, LABS_DUE_KEY, ""):
            return
        await alerts_service.raise_alert(
            session,
            domain=Domain.HRT.value,
            severity=Severity.WARN.value,
            message=t("alert.hrt_labs_due", days=window),
            alert_key=LABS_DUE_KEY,
        )
    else:
        await alerts_service.resolve_by_key(session, alert_key=LABS_DUE_KEY)


async def _compound_display_name(session: AsyncSession, key: str) -> str:
    """Localized catalog name for a compound key (falls back to the key for a
    free-text/custom compound not in the catalog)."""
    compound = await hrt_service.get_compound(session, key)
    if compound is None:
        return key
    if current_lang.get() == "ru":
        return compound.name_ru or compound.name or key
    return compound.name or compound.name_ru or key


async def _last_actual_dose_date(
    session: AsyncSession, compound_key: str
) -> Optional[date_type]:
    result = await session.execute(
        select(HrtDose.date)
        .where(HrtDose.compound_key == compound_key)
        .order_by(HrtDose.date.desc())
        .limit(1)
    )
    return result.scalars().first()


async def refresh_injection_due(
    session: AsyncSession, *, on_date: Optional[date_type] = None
) -> None:
    """Per active-cycle-item: nag if the last shot the fixed grid expected by
    today hasn't been logged. Resolves per compound once caught up, and clears any
    stale alert whose compound is no longer planned (cycle ended/deleted or the
    item removed) so a nag never outlives the plan that raised it."""
    today = on_date or today_local()
    cycle = await hrt_cycle_service.active_cycle(session, on_date=today)
    planned_keys: set[str] = set()

    if cycle is not None:
        for item in cycle.items:
            entity = item.compound_key
            planned_keys.add(entity)
            planned = hrt_cycle_service.expand_item_schedule(
                item, cycle.start_date, cycle.start_date, today
            )
            if not planned:
                await alerts_service.resolve_by_key(
                    session, alert_key=INJECTION_DUE_KEY, entity_ref=entity
                )
                continue
            last_planned = planned[-1][0]
            last_actual = await _last_actual_dose_date(session, entity)
            overdue = last_actual is None or last_actual < last_planned
            if overdue:
                if await alerts_service._was_dismissed_today(
                    session, INJECTION_DUE_KEY, entity
                ):
                    continue
                await alerts_service.raise_alert(
                    session,
                    domain=Domain.HRT.value,
                    severity=Severity.INFO.value,
                    message=t(
                        "alert.hrt_injection_due",
                        compound=await _compound_display_name(session, entity),
                        date=last_planned.isoformat(),
                    ),
                    alert_key=INJECTION_DUE_KEY,
                    entity_ref=entity,
                )
            else:
                await alerts_service.resolve_by_key(
                    session, alert_key=INJECTION_DUE_KEY, entity_ref=entity
                )

    # Clear stale nags for compounds no longer in the active plan.
    for alert in await alerts_service.list_active(session, domain=Domain.HRT.value):
        if alert.alert_key == INJECTION_DUE_KEY and alert.entity_ref not in planned_keys:
            await alerts_service.resolve_by_key(
                session, alert_key=INJECTION_DUE_KEY, entity_ref=alert.entity_ref
            )


async def refresh_all(
    session: AsyncSession, *, on_date: Optional[date_type] = None
) -> None:
    """Run both reminders — called from the dashboard load and the scheduled job."""
    await refresh_labs_due(session, on_date=on_date)
    await refresh_injection_due(session, on_date=on_date)


async def reminders_job(session_factory, redis=None) -> None:
    """Daily HRT reminders (registered in vitals/scheduler/jobs.py)."""
    async with session_factory() as session:
        from vitals.i18n import current_lang
        from vitals.services.language_service import get_language

        lang = await get_language(session, redis)
        current_lang.set(lang)

        await refresh_all(session)
        await session.commit()
