"""Doctor reports — build a frozen document and publish it behind a password.

Vitals had two exports and neither is readable by a person: ``export_full`` is a
machine dump of every table, ``export_llm`` a flat JSON for a chat window. This
is the third kind — one appointment's worth of data, chosen by domain and period,
events listed line by line and metrics reduced to aggregates, handed over as a
link plus a password.

Three properties do the work:

  * **Frozen.** The snapshot is built once and never refreshed. There is no
    "update" button: data moved, make a new report. A number a doctor read in the
    appointment still reads the same next week.
  * **Filtered twice.** A domain reaches the document only if it was ticked *and*
    its module is on. A module the owner switched off behaves as absent here
    exactly as it does everywhere else.
  * **Two independent clocks.** How much history the report covers
    (``period_start``/``period_end``) and how long the link stays alive
    (``expires_at``) have nothing to do with each other — a 180-day report can
    live for a week.

Most of the assembly is ``digest_service.assemble_context``, which already reads
every domain for a window. Three things are gathered directly on top of it,
because a doctor needs the full list where the digest only needs the headline:
every lab result in the period (not only the abnormal ones), every GLP-1/HRT dose
line by line, and the current supplement stack.
"""
from __future__ import annotations

import logging
import secrets
from datetime import date as date_type, datetime, timedelta
from typing import Any, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import Domain
from vitals.models.share import SharedReport
from vitals.utils.passwords import hash_password
from vitals.utils.timeutils import now_local, today_local

logger = logging.getLogger(__name__)

SNAPSHOT_VERSION = 1

# Which module switch gates each selectable domain. A domain missing from this
# map cannot be published at all — the map, not the form, is the gate.
DOMAIN_MODULE: dict[str, str] = {
    Domain.WEIGHT.value: "weight",
    Domain.BODY_COMPOSITION.value: "body_comp",
    Domain.LABS.value: "labs",
    Domain.GLP1.value: "glp1",
    Domain.HRT.value: "hrt",
    Domain.SUPPLEMENTS.value: "supplements",
    Domain.GARMIN.value: "garmin",
    Domain.WORKOUTS.value: "hevy",
    Domain.NUTRITION.value: "nutrition",
    Domain.SKINCARE.value: "skincare",
    Domain.GENETICS.value: "genetics",
    Domain.SIGNALS.value: "signals",
}

# Render order of the document's sections, so a snapshot's key order never
# decides what a doctor reads first.
DOMAIN_ORDER: tuple[str, ...] = tuple(DOMAIN_MODULE)

_ALL = list(DOMAIN_MODULE)

# Built-in presets — constants, not a table. Six cover the appointments that
# actually happen; the form also pre-fills from the last report, which is a
# personal preset without a schema to maintain.
PRESETS: dict[str, dict[str, Any]] = {
    "full": {"domains": _ALL, "labs_flagged_only": False},
    "labs_meds": {
        "domains": [
            Domain.LABS.value,
            Domain.GLP1.value,
            Domain.HRT.value,
            Domain.SUPPLEMENTS.value,
        ],
        "labs_flagged_only": False,
    },
    "endocrinologist": {
        "domains": [
            Domain.LABS.value,
            Domain.GLP1.value,
            Domain.HRT.value,
            Domain.WEIGHT.value,
            Domain.BODY_COMPOSITION.value,
            Domain.SUPPLEMENTS.value,
            Domain.NUTRITION.value,
        ],
        "labs_flagged_only": False,
    },
    "gp": {
        "domains": [
            Domain.LABS.value,
            Domain.GLP1.value,
            Domain.HRT.value,
            Domain.SUPPLEMENTS.value,
            Domain.WEIGHT.value,
            Domain.SIGNALS.value,
        ],
        # A first-contact doctor wants what is wrong, not the whole panel.
        "labs_flagged_only": True,
    },
    "dermatologist": {
        "domains": [
            Domain.SKINCARE.value,
            Domain.LABS.value,
            Domain.HRT.value,
            Domain.GLP1.value,
            Domain.SUPPLEMENTS.value,
            Domain.SIGNALS.value,
        ],
        "labs_flagged_only": False,
    },
    "sports": {
        "domains": [
            Domain.GARMIN.value,
            Domain.WORKOUTS.value,
            Domain.WEIGHT.value,
            Domain.BODY_COMPOSITION.value,
            Domain.LABS.value,
            Domain.NUTRITION.value,
        ],
        "labs_flagged_only": False,
    },
}

PERIOD_CHOICES: tuple[int, ...] = (30, 90, 180)
EXPIRY_CHOICES: tuple[int, ...] = (7, 30, 90)
DEFAULT_EXPIRY_DAYS = 30

# Password shown once, then only its hash exists. Six words of base32-ish
# alphabet read aloud over a desk without "was that an l or a 1".
_PASSWORD_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"
_PASSWORD_LENGTH = 12


def generate_password() -> str:
    return "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(_PASSWORD_LENGTH))


def resolve_domains(
    domains: Sequence[str], enabled: Optional[dict[str, bool]] = None
) -> list[str]:
    """Requested domains ∩ known domains ∩ switched-on modules, in render order.

    The single choke point for "a disabled module never leaves the building":
    both the form and the snapshot builder go through it, so they cannot disagree.
    """
    from vitals.services.modules_service import CORE_KEYS

    wanted = set(domains or ())
    em = enabled or {}
    return [
        d
        for d in DOMAIN_ORDER
        if d in wanted and em.get(DOMAIN_MODULE[d], DOMAIN_MODULE[d] in CORE_KEYS)
    ]


def available_domains(enabled: Optional[dict[str, bool]] = None) -> list[str]:
    """Every domain the owner could tick right now, in render order."""
    return resolve_domains(DOMAIN_ORDER, enabled)


# ── Snapshot ──────────────────────────────────────────────────────────────────


async def build_snapshot(
    session: AsyncSession,
    *,
    domains: Sequence[str],
    period_start: date_type,
    period_end: date_type,
    labs_flagged_only: bool = False,
    enabled: Optional[dict[str, bool]] = None,
) -> dict[str, Any]:
    """Assemble the document's data for one window. No DB writes.

    A report covers days that are **over**. Today is still being lived — it has
    no sleep in it yet and possibly no meals — so a window asked for "through
    today" is read through yesterday and the row stores that, rather than a
    header claiming a day the numbers don't cover.
    """
    from vitals.config import load_config
    from vitals.i18n import current_lang
    from vitals.services import digest_service

    chosen = resolve_domains(domains, enabled)
    start, end = clamp_window(period_start, period_end)
    span_days = max((end - start).days + 1, 1)
    ctx = await digest_service.assemble_context(
        session,
        on_date=end,
        period_days=span_days,
        mode=digest_service.REPORT_MODE_CLOSED,
        enabled_modules=enabled,
        max_period_days=max(PERIOD_CHOICES),
    )
    stats = ctx.get("period_stats") or {}
    cfg = load_config()

    blocks: dict[str, Any] = {}
    for domain in chosen:
        builder = _BUILDERS[domain]
        block = await builder(session, ctx, stats, start, end, labs_flagged_only)
        # An empty domain draws no section at all — a "no data" placeholder is a
        # line a doctor reads and gets nothing from.
        if block:
            blocks[domain] = block

    return {
        "version": SNAPSHOT_VERSION,
        "lang": current_lang.get(),
        "generated_at": now_local().isoformat(timespec="minutes"),
        "period": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "days": (end - start).days + 1,
        },
        "profile": {
            "age": cfg.user_age,
            "sex": cfg.sex,
            "height_cm": cfg.height_cm,
        },
        # What the document actually holds, not what was ticked. An empty domain
        # draws no section, so a contents line naming one sends a doctor looking
        # for labs that never arrived — and a missing section reads as "nothing
        # to report" when it means "nothing in this window".
        "domains": [d for d in chosen if d in blocks],
        "labs_flagged_only": bool(labs_flagged_only),
        "blocks": blocks,
    }


async def _weight_block(session, ctx, stats, start, end, flagged_only) -> dict:
    """Where the scale started and where it ended, plus the series for the chart.

    Points come from ``chart_series`` rather than the raw table so the average
    drawn here is the same noise-excluded one the owner sees on /weight.
    """
    from vitals.services import weight_service

    series = await weight_service.chart_series(session)
    in_window = [
        p for p in series["raw"] if start.isoformat() <= p["date"] <= end.isoformat()
    ]
    ma_window = [
        p for p in series["trend_ma"] if start.isoformat() <= p["date"] <= end.isoformat()
    ]
    if not in_window:
        return {}
    first, last = in_window[0], in_window[-1]
    return {
        "first": {"date": first["date"], "kg": first["weight_kg"]},
        "last": {"date": last["date"], "kg": last["weight_kg"]},
        "delta_kg": round(last["weight_kg"] - first["weight_kg"], 1),
        "readings": len(in_window),
        "points": [[p["date"], p["weight_kg"]] for p in in_window],
        "ma": [[p["date"], p["weight_kg"]] for p in ma_window],
    }


async def _body_comp_block(session, ctx, stats, start, end, flagged_only) -> dict:
    from vitals.i18n import current_lang
    from vitals.services import body_scan_service
    from vitals.services.analytics.body_metrics import METRIC_REGISTRY, display_name

    lang = current_lang.get()
    scans = await body_scan_service.list_scans(session, start=start, end=end)
    rows = []
    for scan in scans:
        metrics = []
        for m in scan.metrics:
            spec = METRIC_REGISTRY.get(m.metric_key)
            if spec is None or not spec.headline:
                continue
            metrics.append(
                {
                    "label": display_name(m.metric_key, lang) or m.metric_key,
                    "value": m.value,
                    # The registry's unit wins over the one read off the sheet:
                    # an InBody printout is in English, and "41,7 kg" sitting
                    # next to "33,7 %" is the document speaking two languages.
                    # Falls back for metrics the registry leaves unitless.
                    "unit": spec.unit or m.unit,
                }
            )
        if metrics:
            rows.append(
                {"date": scan.date.isoformat(), "device": scan.device, "metrics": metrics}
            )
    return {"scans": rows} if rows else {}


async def _labs_block(session, ctx, stats, start, end, flagged_only) -> dict:
    """Every marker measured in the window, with its reference range and the two
    readings before it — a value without its range and its direction is a number
    a doctor has to go and look up."""
    from vitals.services import labs_service

    # Anchored at the window's end, not at "the newest results in the table": read
    # the other way round, a report about last spring is filled by every draw taken
    # since, and the markers it is actually about fall off the bottom of the cap.
    # ponytail: the cap now limits how far *back* history reaches, which is all the
    # two previous readings need.
    rows = await labs_service.list_results(session, end=end, limit=2000)  # newest first
    by_marker: dict[str, list] = {}
    for r in rows:
        by_marker.setdefault(r.marker, []).append(r)

    markers = []
    for marker, history in by_marker.items():
        current = next((r for r in history if r.date >= start), None)
        if current is None:
            continue
        if flagged_only and not labs_service.is_out_of_range(current.flag):
            continue
        earlier = [r for r in history if r.date < current.date][:2]
        markers.append(
            {
                "marker": marker,
                "value": current.value,
                "unit": current.unit,
                "flag": current.flag,
                "date": current.date.isoformat(),
                "ref_low": current.ref_low,
                "ref_high": current.ref_high,
                # Oldest first, so the line reads left to right in time.
                "history": [
                    {"date": r.date.isoformat(), "value": r.value}
                    for r in reversed(earlier)
                ],
            }
        )
    markers.sort(key=lambda m: (not labs_service.is_out_of_range(m["flag"]), m["marker"]))
    return {"markers": markers} if markers else {}


async def _glp1_block(session, ctx, stats, start, end, flagged_only) -> dict:
    from vitals.services import glp1_service

    phase = ctx.get("glp1") or {}
    injections = [
        i for i in await glp1_service.list_injections(session) if start <= i.date <= end
    ]
    effects = [
        e for e in await glp1_service.list_side_effects(session) if start <= e.date <= end
    ]
    current = (
        {"drug": phase.get("drug"), "dose_mg": phase.get("dose_mg")}
        if phase.get("drug")
        else None
    )
    if not current and not injections and not effects:
        return {}
    return {
        "current": current,
        "doses": [
            {"date": i.date.isoformat(), "drug": i.drug, "dose_mg": i.dose_mg}
            for i in sorted(injections, key=lambda x: x.date)
        ],
        "side_effects": [
            {
                "date": e.date.isoformat(),
                "effect_type": e.effect_type,
                "severity": e.severity,
            }
            for e in sorted(effects, key=lambda x: x.date)
        ],
    }


async def _hrt_block(session, ctx, stats, start, end, flagged_only) -> dict:
    from vitals.i18n import current_lang
    from vitals.services import hrt_service

    hrt = ctx.get("hrt") or {}
    doses = await hrt_service.list_doses(session, start=start, end=end)
    effects = [
        e for e in await hrt_service.list_side_effects(session) if start <= e.date <= end
    ]
    cycle = hrt.get("cycle")
    if not cycle and not doses and not effects:
        return {}

    # A doctor gets the molecule's name, not the catalog slug ("test_enanthate").
    lang = current_lang.get()
    compounds = await hrt_service.list_compounds(session, active_only=False)
    names = {
        c.key: ((c.name_ru or c.name) if lang == "ru" else (c.name or c.name_ru))
        for c in compounds
    }
    return {
        "cycle": (
            {
                "name": cycle.get("name"),
                "start_date": cycle.get("start_date"),
                "end_date": cycle.get("end_date"),
                "compounds": [
                    names.get(k, k) for k in cycle.get("compounds") or ()
                ],
            }
            if cycle
            else None
        ),
        "doses": [
            {
                "date": d.date.isoformat(),
                "compound": names.get(d.compound_key, d.compound_key),
                "dose": d.dose,
                "unit": d.unit,
            }
            for d in sorted(doses, key=lambda x: x.date)
        ],
        "side_effects": [
            {
                "date": e.date.isoformat(),
                "effect_type": e.effect_type,
                "severity": e.severity,
            }
            for e in sorted(effects, key=lambda x: x.date)
        ],
    }


async def _supplements_block(session, ctx, stats, start, end, flagged_only) -> dict:
    from vitals.services import supplements_service

    items = await supplements_service.list_supplements(session, active_only=True)
    return {
        "items": [
            {"name": s.name, "dose": s.dose, "timing": s.timing} for s in items
        ]
    } if items else {}


async def _garmin_block(session, ctx, stats, start, end, flagged_only) -> dict:
    """Averages over the window and over the one before it. Two lines, not a
    table of nights — a doctor is looking for the level, not the diary."""
    current = stats.get("current") or {}
    if not current.get("garmin_days"):
        return {}
    previous = stats.get("previous") or {}
    keys = ("sleep_hours", "sleep_score", "resting_hr", "hrv_avg", "steps")
    return {
        "days": current.get("garmin_days"),
        "current": {k: current.get(k) for k in keys},
        "previous": {k: previous.get(k) for k in keys},
    }


async def _workouts_block(session, ctx, stats, start, end, flagged_only) -> dict:
    hevy = ctx.get("hevy") or {}
    current = stats.get("current") or {}
    if not current.get("workouts"):
        return {}
    return {
        "sessions": current.get("workouts"),
        "mean_gap_days": hevy.get("mean_gap_days"),
        "volume_per_session_kg": current.get("volume_per_session_kg"),
    }


async def _nutrition_block(session, ctx, stats, start, end, flagged_only) -> dict:
    current = stats.get("current") or {}
    if not current.get("nutrition_days_logged"):
        return {}
    return {
        "days_logged": current.get("nutrition_days_logged"),
        "calories_per_day": current.get("calories_per_day"),
        "protein_per_day_g": current.get("protein_per_day_g"),
    }


async def _skincare_block(session, ctx, stats, start, end, flagged_only) -> dict:
    skin = ctx.get("skincare") or {}
    if not skin:
        return {}
    observations = [
        {
            "date": o["date"],
            "inflammation": o["inflammation"],
            "pih": o["pih"],
            "zone": o["zone"],
        }
        for o in skin.get("recent_observations") or ()
        if start.isoformat() <= o["date"] <= end.isoformat()
    ]
    if not observations and not skin.get("active_products"):
        return {}
    return {"active_products": skin.get("active_products"), "observations": observations}


async def _genetics_block(session, ctx, stats, start, end, flagged_only) -> dict:
    from vitals.services import genetics_service

    variants = await genetics_service.list_variants(session)
    rows = [
        {
            "gene": v.gene,
            "rsid": v.rsid,
            "genotype": v.genotype,
            "interpretation": v.interpretation,
        }
        for v in variants
        if v.interpretation
    ]
    return {"variants": rows} if rows else {}


async def _signals_block(session, ctx, stats, start, end, flagged_only) -> dict:
    """What the patient said about how he felt — symptoms, in his own words.

    ``state`` rows are a daily mood/energy score he keeps for himself; on a
    clinical document they are noise between the symptoms that matter.

    Two filters that only a real document makes obvious. A row with no note
    carries nothing but its normalized key — "low_heart_rate" is this app's
    vocabulary, not a complaint, and a doctor reading it learns nothing. And
    ``value_num`` is a 1-5 severity for a symptom but a raw measurement for
    anything the parser tagged loosely, which is how "40 of 5" ends up on a
    clinical document; outside that range it is not a severity and is dropped.
    """
    from vitals.enums import SignalKind
    from vitals.services import signals_service

    rows = await signals_service.list_signals(
        session, kind=SignalKind.SYMPTOM.value, start=start, end=end, limit=1000
    )
    items = [
        {
            "date": s.date.isoformat(),
            "what": (s.note or "").strip(),
            "severity": (
                int(s.value_num)
                if s.value_num is not None and 1 <= s.value_num <= 5
                else None
            ),
        }
        for s in rows
        if (s.note or "").strip()
    ]
    items.sort(key=lambda x: x["date"])
    return {"symptoms": items} if items else {}


_BUILDERS = {
    Domain.WEIGHT.value: _weight_block,
    Domain.BODY_COMPOSITION.value: _body_comp_block,
    Domain.LABS.value: _labs_block,
    Domain.GLP1.value: _glp1_block,
    Domain.HRT.value: _hrt_block,
    Domain.SUPPLEMENTS.value: _supplements_block,
    Domain.GARMIN.value: _garmin_block,
    Domain.WORKOUTS.value: _workouts_block,
    Domain.NUTRITION.value: _nutrition_block,
    Domain.SKINCARE.value: _skincare_block,
    Domain.GENETICS.value: _genetics_block,
    Domain.SIGNALS.value: _signals_block,
}


# ── Lifecycle ─────────────────────────────────────────────────────────────────


async def create_report(
    session: AsyncSession,
    *,
    title: str,
    domains: Sequence[str],
    period_start: date_type,
    period_end: date_type,
    expires_days: int = DEFAULT_EXPIRY_DAYS,
    note: Optional[str] = None,
    labs_flagged_only: bool = False,
    preset: Optional[str] = None,
    enabled: Optional[dict[str, bool]] = None,
) -> tuple[SharedReport, str]:
    """Freeze a document and publish it. Flushes; the caller commits.

    Returns the row **and the plaintext password**, which exists only in this
    return value — after this call there is nothing but the bcrypt hash.
    """
    snapshot = await build_snapshot(
        session,
        domains=domains,
        period_start=period_start,
        period_end=period_end,
        labs_flagged_only=labs_flagged_only,
        enabled=enabled,
    )
    password = generate_password()
    row = SharedReport(
        token=secrets.token_urlsafe(32),
        password_hash=hash_password(password),
        title=title.strip()[:120],
        preset=preset,
        domains=snapshot["domains"],
        period_start=date_type.fromisoformat(snapshot["period"]["start"]),
        period_end=date_type.fromisoformat(snapshot["period"]["end"]),
        labs_flagged_only=bool(labs_flagged_only),
        note=(note or "").strip() or None,
        snapshot=snapshot,
        expires_at=now_local() + timedelta(days=max(int(expires_days), 1)),
    )
    session.add(row)
    await session.flush()
    return row, password


async def list_reports(session: AsyncSession) -> Sequence[SharedReport]:
    result = await session.execute(
        select(SharedReport).order_by(SharedReport.created_at.desc(), SharedReport.id.desc())
    )
    return result.scalars().all()


async def get_report(session: AsyncSession, report_id: int) -> Optional[SharedReport]:
    return await session.get(SharedReport, report_id)


async def resolve_public(session: AsyncSession, token: str) -> Optional[SharedReport]:
    """The row behind a public token, or ``None``.

    One ``None`` for all four ways a link can fail — unknown, revoked, expired,
    purged — because the visitor must not be able to tell them apart, and a page
    that says "this was revoked" tells them.
    """
    if not token:
        return None
    row = (
        await session.execute(select(SharedReport).where(SharedReport.token == token))
    ).scalars().first()
    if row is None or row.revoked_at is not None or row.snapshot is None:
        return None
    if row.expires_at <= now_local():
        return None
    return row


async def register_open(session: AsyncSession, row: SharedReport) -> None:
    """Count one successful open. Flushes; the caller commits."""
    row.opened_count = (row.opened_count or 0) + 1
    row.last_opened_at = now_local()
    await session.flush()


async def revoke(session: AsyncSession, report_id: int) -> bool:
    """Kill the link now. The snapshot goes with it — a revoked report is one the
    owner decided should stop existing, not one to keep a copy of."""
    row = await session.get(SharedReport, report_id)
    if row is None or row.revoked_at is not None:
        return False
    row.revoked_at = now_local()
    row.snapshot = None
    await session.flush()
    return True


async def delete_report(session: AsyncSession, report_id: int) -> bool:
    row = await session.get(SharedReport, report_id)
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


async def purge_expired(session: AsyncSession, *, now: Optional[datetime] = None) -> int:
    """Empty the snapshot of every dead link; keep the metadata.

    An expired report is unreachable already — this is about not keeping a full
    copy of the medical record for every appointment ever attended. The row stays
    so /share can still say what was shared and when.
    """
    moment = now or now_local()
    rows = (
        await session.execute(
            select(SharedReport)
            .where(SharedReport.expires_at <= moment)
            .where(SharedReport.snapshot.is_not(None))
        )
    ).scalars().all()
    for row in rows:
        row.snapshot = None
    await session.flush()
    return len(rows)


async def purge_job(session_factory, redis=None) -> None:
    """Daily sweep — see :func:`purge_expired`."""
    async with session_factory() as session:
        purged = await purge_expired(session)
        await session.commit()
    if purged:
        logger.info("shared reports: cleared %s expired snapshot(s)", purged)


def window_for(days: int) -> tuple[date_type, date_type]:
    """``days`` **complete** days, ending yesterday.

    Counting back from today would hand the document a day with no sleep in it
    and, before dinner, no food either — and then average over it.
    """
    end = today_local() - timedelta(days=1)
    return end - timedelta(days=max(days, 1) - 1), end


def clamp_window(start: date_type, end: date_type) -> tuple[date_type, date_type]:
    """A window the reader picked, trimmed to days that are actually over."""
    yesterday = today_local() - timedelta(days=1)
    end = min(end, yesterday)
    return min(start, end), end


def default_period(days: int = 90) -> tuple[date_type, date_type]:
    """What the custom-range inputs open on."""
    return window_for(days)


async def earliest_data_date(session: AsyncSession) -> Optional[date_type]:
    """The oldest dated row in any domain a report can carry — what "all time"
    means. Nine cheap ``MIN()`` reads on one form submit, so a report that says
    it covers everything starts where the record actually starts rather than at
    some round number of years ago."""
    from sqlalchemy import func

    from vitals.models.body_scan import BodyScan
    from vitals.models.garmin import GarminDaily
    from vitals.models.glp1 import Injection
    from vitals.models.hevy import HevyWorkout
    from vitals.models.hrt import HrtDose
    from vitals.models.labs import LabResult
    from vitals.models.nutrition import MealLog
    from vitals.models.signals import Signal
    from vitals.models.weight import WeightLog

    columns = (
        WeightLog.date, LabResult.date, GarminDaily.date, HevyWorkout.date,
        MealLog.date, HrtDose.date, Injection.date, BodyScan.date, Signal.date,
    )
    found = []
    for column in columns:
        value = (await session.execute(select(func.min(column)))).scalar()
        if value is not None:
            found.append(value)
    return min(found) if found else None


# ── Full view collection for API / UI ─────────────────────────────────────────
async def collect(
    session: AsyncSession, enabled_modules: Optional[dict[str, bool]] = None
) -> dict[str, Any]:
    """Collect everything needed by the Share dashboard in one round-trip."""
    enabled = enabled_modules or {}
    reports = await list_reports(session)
    default_start, default_end = default_period()
    moment = now_local()

    report_items = []
    for r in reports:
        if r.revoked_at is not None:
            state = "revoked"
        elif r.expires_at <= moment:
            state = "expired"
        else:
            state = "live"

        report_items.append({
            "id": r.id,
            "token": r.token,
            "title": r.title,
            "preset": r.preset,
            "domains": list(r.domains) if r.domains else [],
            "period_start": r.period_start.isoformat(),
            "period_end": r.period_end.isoformat(),
            "expires_at": r.expires_at.isoformat(),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "revoked_at": r.revoked_at.isoformat() if r.revoked_at else None,
            "opened_count": r.opened_count or 0,
            "last_opened_at": r.last_opened_at.isoformat() if r.last_opened_at else None,
            "state": state,
            "url": f"/r/{r.token}",
        })

    presets_dict = {
        key: {
            "domains": resolve_domains(spec["domains"], enabled),
            "labs_flagged_only": spec["labs_flagged_only"],
        }
        for key, spec in PRESETS.items()
    }

    return {
        "reports": report_items,
        "available_domains": available_domains(enabled),
        "presets": presets_dict,
        "period_choices": list(PERIOD_CHOICES),
        "expiry_choices": list(EXPIRY_CHOICES),
        "default_expiry": DEFAULT_EXPIRY_DAYS,
        "default_start": default_start.isoformat(),
        "default_end": default_end.isoformat(),
        "today": today_local().isoformat(),
    }

