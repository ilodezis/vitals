"""Alerts for the bedroom air: a badge in the app and, for what is worth it, a
Telegram message.

Seven rules (stuffy, warn-level CO2, hot, cool, dry, humid, station silent), checked
every 30 seconds against the stored samples. Each one is a *condition that has held
for a while*, not a reading: a window has to be covered by snapshots, every one of
them past the threshold, before anything fires — a single spike or a station that
reported twice proves nothing.

An **episode** is one continuous stretch of the condition. It starts when a rule
fires and ends only once the value is clearly back (hysteresis: ten per cent past
the threshold, half a degree for temperature), so a CO2 hovering around 1400 does not
flap a message on and off. Its identity is the moment it began, taken from the
data itself — which makes everything below survive a restart, a dismissed badge and
a Redis wipe without any state of its own:

* the badge is a ``system_alerts`` row whose ``entity_ref`` is the episode;
* the Telegram message is journaled with ``dedupe_key = env:<rule>:<episode>``, so an
  episode speaks at most once, and a per-rule cooldown stops a flapping room from
  speaking again and again;
* when the episode ends the badge is resolved and — only if the episode actually
  sent a message — one short "back to normal" follows.

Telegram goes through ``delivery.send`` as ``CATEGORY_ENVIRONMENT``: it ignores the
daily budget and respects quiet hours. A message held back by quiet hours is simply
not sent *yet*: nothing is journaled, so the next tick tries again, and a room that
is still stuffy at 10:00 gets its message at 10:00. The "back to normal" note is the
opposite — it is only worth sending close to the moment it became true, so it is
dropped, not delayed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from vitals.config import load_config
from vitals.enums import Domain, Severity
from vitals.i18n import current_lang, t
from vitals.models.environment import EnvironmentSample
from vitals.models.proactive import Notification
from vitals.services import alerts_service, modules_service
from vitals.services.language_service import get_language
from vitals.services.environment import settings as env_settings
from vitals.services.environment import stats
from vitals.services.environment.live import station_key
from vitals.services.environment.rollup import SampleRow, load_rows
from vitals.services.proactive import channels, delivery, prefs
from vitals.utils.timeutils import as_utc, now_utc, to_local_naive

logger = logging.getLogger(__name__)

DOMAIN = Domain.ENVIRONMENT.value

# A newest snapshot older than this means the station is not reporting right now,
# whatever the older ones said.
DATA_FRESH_S = 90.0
# Share of a rule's window that has to be covered by snapshots before it can fire.
MIN_COVERAGE = 0.8
# How long the value must stay clearly back before an episode counts as over.
RELEASE_WINDOW_MIN = 3
# "Back to normal" is only sent within this long of becoming true.
OK_MESSAGE_WINDOW_MIN = 10
# The longest window any rule looks at, and how far back an episode's start is
# searched for when it has to be recovered from the data.
TRIGGER_LOOKBACK = timedelta(minutes=60)
EPISODE_LOOKBACK = timedelta(hours=6)
# Snapshots further apart than this are not the same continuous stretch.
EPISODE_MAX_GAP_S = 120.0

SILENT_AFTER_MIN = 15
# The station's silence only counts while Vitals has been asking: a poll (or a
# failed one) recorded this recently. Long enough to span the poll back-off.
POLL_EVIDENCE_S = 6 * 60.0

KEY_STATION_SILENT = "env_station_silent"


# ── The rules ─────────────────────────────────────────────────────────────────
def _temp(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def _limit(value: float) -> str:
    return f"{value:g}"


@dataclass(frozen=True)
class Rule:
    key: str
    metric: str  # SampleRow attribute: co2 | temp | rh
    above: bool  # fires when the value is above the trigger (else below it)
    strict: bool  # ``>`` / ``<`` instead of ``>=`` / ``<=``
    window_min: int
    severity: str
    i18n_key: str  # the badge text
    trigger: Callable[[env_settings.EnvSettings], float]
    release: Callable[[env_settings.EnvSettings], float]
    # Telegram: ``None`` = badge only. Both take the current value.
    cooldown_h: Optional[float] = None
    text: Optional[Callable[[float], str]] = None
    ok_text: Optional[Callable[[float], str]] = None

    def breached(self, value: float, cfg: env_settings.EnvSettings) -> bool:
        limit = self.trigger(cfg)
        if self.above:
            return value > limit if self.strict else value >= limit
        return value < limit if self.strict else value <= limit

    def released(self, value: float, cfg: env_settings.EnvSettings) -> bool:
        """Clearly back, not merely under the line again."""
        limit = self.release(cfg)
        return value < limit if self.above else value > limit


RULES: tuple[Rule, ...] = (
    Rule(
        key="env_co2_bad", metric="co2", above=True, strict=False, window_min=5,
        severity=Severity.WARN.value, i18n_key="alert.env_co2_bad",
        trigger=lambda c: c.co2_bad, release=lambda c: c.co2_bad * 0.9,
        cooldown_h=2,
        text=lambda v: f"Душно: CO₂ {round(v)} ppm. Открой окно минут на 10.",
        ok_text=lambda v: f"Воздух в норме: {round(v)} ppm",
    ),
    Rule(
        key="env_co2_warn", metric="co2", above=True, strict=False, window_min=15,
        severity=Severity.INFO.value, i18n_key="alert.env_co2_warn",
        trigger=lambda c: c.co2_warn, release=lambda c: c.co2_warn * 0.9,
    ),
    Rule(
        key="env_temp_high", metric="temp", above=True, strict=False, window_min=15,
        severity=Severity.WARN.value, i18n_key="alert.env_temp_high",
        trigger=lambda c: c.temp_day_max + 1, release=lambda c: c.temp_day_max + 0.5,
        cooldown_h=3,
        text=lambda v: f"В комнате {_temp(v)} °C, жарковато.",
        ok_text=lambda v: f"Температура в норме: {_temp(v)} °C",
    ),
    Rule(
        key="env_temp_low", metric="temp", above=False, strict=False, window_min=15,
        severity=Severity.INFO.value, i18n_key="alert.env_temp_low",
        trigger=lambda c: c.temp_day_min - 1, release=lambda c: c.temp_day_min - 0.5,
        cooldown_h=3,
        text=lambda v: f"В комнате {_temp(v)} °C, прохладно.",
        ok_text=lambda v: f"Температура в норме: {_temp(v)} °C",
    ),
    Rule(
        key="env_rh_low", metric="rh", above=False, strict=True, window_min=60,
        severity=Severity.INFO.value, i18n_key="alert.env_rh_low",
        trigger=lambda c: c.rh_alert_low, release=lambda c: c.rh_alert_low * 1.1,
        cooldown_h=6,
        text=lambda v: f"Сухой воздух: {round(v)}%.",
        ok_text=lambda v: f"Влажность в норме: {round(v)}%",
    ),
    Rule(
        key="env_rh_high", metric="rh", above=True, strict=True, window_min=60,
        severity=Severity.INFO.value, i18n_key="alert.env_rh_high",
        trigger=lambda c: c.rh_alert_high, release=lambda c: c.rh_alert_high * 0.9,
        cooldown_h=6,
        text=lambda v: f"Влажно: {round(v)}%.",
        ok_text=lambda v: f"Влажность в норме: {round(v)}%",
    ),
)


# ── Reading the data ──────────────────────────────────────────────────────────
Series = list[tuple[datetime, float]]


def _series(rows: list[SampleRow], metric: str) -> Series:
    return [(r.ts, getattr(r, metric)) for r in rows if getattr(r, metric) is not None]


def _sustained(
    values: Series, window_min: int, now: datetime, ok: Callable[[float], bool]
) -> bool:
    """Has ``ok`` held for every snapshot of the last ``window_min`` minutes, with
    those snapshots actually covering the window and the newest one recent?"""
    start = now - timedelta(minutes=window_min)
    window = [(ts, v) for ts, v in values if ts >= start]
    if not window:
        return False
    if (now - window[-1][0]).total_seconds() > DATA_FRESH_S:
        return False
    if not all(ok(v) for _, v in window):
        return False
    covered = stats.covered_seconds([ts for ts, _ in window], start, now)
    return covered >= MIN_COVERAGE * window_min * 60


def _release_streak_start(
    values: Series, released: Callable[[float], bool], now: datetime
) -> Optional[datetime]:
    """When the current unbroken run of "clearly back" snapshots began, if the
    newest snapshots are one."""
    start: Optional[datetime] = None
    for ts, v in reversed(values):
        if not released(v):
            break
        start = ts
    return start


def _stamp(ts: datetime) -> str:
    """An episode's identity: the minute it began, UTC. No colons — it is part of
    a dedupe key that is split on them."""
    return as_utc(ts).strftime("%Y%m%dT%H%MZ")


async def _episode_start(
    session: AsyncSession, station_id: str, rule: Rule, cfg: env_settings.EnvSettings,
    now: datetime,
) -> str:
    """When the current stretch of this condition began, from the data: walk back
    from the newest snapshot while the value has not clearly recovered and the
    snapshots are continuous."""
    rows = await load_rows(session, station_id, now - EPISODE_LOOKBACK, now + timedelta(seconds=1))
    began: Optional[datetime] = None
    newer: Optional[datetime] = None
    for ts, v in reversed(_series(rows, rule.metric)):
        if newer is not None and (newer - ts).total_seconds() > EPISODE_MAX_GAP_S:
            break
        if rule.released(v, cfg):
            break
        began, newer = ts, ts
    return _stamp(began or now)


# ── Telegram ──────────────────────────────────────────────────────────────────
def _breach_key(rule_key: str, episode: str) -> str:
    return f"env:{rule_key}:{episode}"


async def _last_breach_sent(session: AsyncSession, rule_key: str) -> Optional[Notification]:
    result = await session.execute(
        select(Notification)
        .where(
            Notification.dedupe_key.like(f"env:{rule_key}:%"),
            Notification.dedupe_key.not_like("%:ok"),
        )
        .order_by(Notification.id.desc())
        .limit(1)
    )
    return result.scalars().first()


async def _send_breach(
    session: AsyncSession, notifier: Any, rule: Rule, episode: str, value: float,
    local_now: datetime,
) -> Optional[Notification]:
    last = await _last_breach_sent(session, rule.key)
    if last is not None and local_now - last.sent_at < timedelta(hours=rule.cooldown_h or 0):
        return None
    return await delivery.send(
        session,
        notifier,
        text=rule.text(value),
        category=delivery.CATEGORY_ENVIRONMENT,
        dedupe_key=_breach_key(rule.key, episode),
        now=local_now,
    )


async def _send_ok(
    session: AsyncSession, notifier: Any, rule: Rule, episode: Optional[str], value: float,
    local_now: datetime,
) -> Optional[Notification]:
    """One "back to normal" — only for an episode that actually spoke, and only
    once. ``episode`` is the one that just ended; when its badge was dismissed and
    it is no longer known, the latest message of the rule has to be recent enough
    to be about it."""
    last = await _last_breach_sent(session, rule.key)
    if last is None:
        return None
    if episode is not None:
        if last.dedupe_key != _breach_key(rule.key, episode):
            return None
    elif local_now - last.sent_at > timedelta(hours=6):
        return None
    return await delivery.send(
        session,
        notifier,
        text=rule.ok_text(value),
        category=delivery.CATEGORY_ENVIRONMENT,
        dedupe_key=f"{last.dedupe_key}:ok",
        now=local_now,
    )


# ── One rule, one tick ────────────────────────────────────────────────────────
async def _run_rule(
    session: AsyncSession,
    notifier: Any,
    rule: Rule,
    *,
    rows: list[SampleRow],
    cfg: env_settings.EnvSettings,
    active: dict[str, Any],
    telegram: bool,
    station_id: str,
    now: datetime,
    local_now: datetime,
) -> list[Notification]:
    values = _series(rows, rule.metric)
    alert = active.get(rule.key)
    sent: list[Notification] = []

    if _sustained(values, rule.window_min, now, lambda v: rule.breached(v, cfg)):
        episode = alert.entity_ref if alert is not None else await _episode_start(
            session, station_id, rule, cfg, now
        )
        await alerts_service.raise_alert(
            session,
            domain=DOMAIN,
            severity=rule.severity,
            message=t(rule.i18n_key, limit=_limit(rule.trigger(cfg))),
            alert_key=rule.key,
            entity_ref=episode,
        )
        if telegram and rule.text is not None:
            row = await _send_breach(session, notifier, rule, episode, values[-1][1], local_now)
            if row is not None:
                sent.append(row)
        return sent

    def back(v: float) -> bool:
        return rule.released(v, cfg)

    if not _sustained(values, RELEASE_WINDOW_MIN, now, back):
        return sent  # still inside the hysteresis band, or no fresh data: no change

    if alert is not None:
        await alerts_service.resolve_by_key(
            session, alert_key=rule.key, entity_ref=alert.entity_ref
        )
    if telegram and rule.ok_text is not None:
        began = _release_streak_start(values, back, now)
        if began is not None and now - began <= timedelta(minutes=OK_MESSAGE_WINDOW_MIN):
            row = await _send_ok(
                session, notifier, rule, alert.entity_ref if alert is not None else None,
                values[-1][1], local_now,
            )
            if row is not None:
                sent.append(row)
    return sent


# ── The station falling silent ────────────────────────────────────────────────
async def _poll_evidence(redis: Optional[Redis], station_id: str, now: datetime) -> bool:
    """Has Vitals been asking the station recently? Without that, a quiet table
    may just mean Vitals itself was down — not that the station is."""
    if redis is None:
        return True
    try:
        state = await redis.hgetall(station_key(station_id))
    except Exception:
        logger.warning("environment alerts: could not read station state", exc_info=True)
        return True
    stamps = []
    for field in ("last_ok_at", "last_error_at"):
        raw = state.get(field)
        if raw:
            try:
                stamps.append(as_utc(datetime.fromisoformat(raw)))
            except ValueError:
                continue
    return bool(stamps) and (now - max(stamps)).total_seconds() <= POLL_EVIDENCE_S


async def _run_silent(
    session: AsyncSession,
    notifier: Any,
    *,
    active: dict[str, Any],
    telegram: bool,
    station_id: str,
    redis: Optional[Redis],
    now: datetime,
    local_now: datetime,
) -> list[Notification]:
    last_ts = (
        await session.execute(
            select(EnvironmentSample.ts)
            .where(EnvironmentSample.station_id == station_id)
            .order_by(EnvironmentSample.ts.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if last_ts is None:  # never reported: that is "not set up yet", not "went quiet"
        return []
    last_ts = as_utc(last_ts)
    quiet_for = now - last_ts
    alert = active.get(KEY_STATION_SILENT)

    silent = quiet_for >= timedelta(minutes=SILENT_AFTER_MIN) and await _poll_evidence(
        redis, station_id, now
    )
    if not silent:
        if alert is not None and quiet_for < timedelta(minutes=SILENT_AFTER_MIN):
            await alerts_service.resolve_by_key(
                session, alert_key=KEY_STATION_SILENT, entity_ref=alert.entity_ref
            )
        return []

    episode = _stamp(last_ts)  # the silence began with the last snapshot
    await alerts_service.raise_alert(
        session,
        domain=DOMAIN,
        severity=Severity.WARN.value,
        message=t("alert.env_station_silent", minutes=SILENT_AFTER_MIN),
        alert_key=KEY_STATION_SILENT,
        entity_ref=episode,
    )
    if not telegram:
        return []
    minutes = int(quiet_for.total_seconds() // 60)
    row = await delivery.send(
        session,
        notifier,
        text=f"Станция молчит {minutes} мин: проверь питание и Wi-Fi.",
        category=delivery.CATEGORY_ENVIRONMENT,
        dedupe_key=_breach_key(KEY_STATION_SILENT, episode),
        now=local_now,
    )
    return [row] if row is not None else []


# ── Entry points ──────────────────────────────────────────────────────────────
async def evaluate(
    session: AsyncSession,
    notifier: Any,
    *,
    now: Optional[datetime] = None,
    redis: Optional[Redis] = None,
    station_id: Optional[str] = None,
) -> list[Notification]:
    """Walk the rules once. Returns the journal rows of what went out. Flushes;
    the caller commits.

    ``now`` is an instant (naive is read as UTC). With ``alerts_enabled`` off
    nothing is raised or sent, and any badge already showing is cleared.
    """
    now = as_utc(now) if now else now_utc()
    local_now = to_local_naive(now)
    station_id = station_id or load_config().env_station_id
    cfg = await env_settings.get_settings(session)

    active = {a.alert_key: a for a in await alerts_service.list_active(session, domain=DOMAIN)}
    if not cfg.alerts_enabled:
        for alert in active.values():
            await alerts_service.resolve_by_key(
                session, alert_key=alert.alert_key, entity_ref=alert.entity_ref
            )
        return []

    proactive = await prefs.get_prefs(session)
    telegram = (
        cfg.alert_telegram
        and notifier is not None
        and bool(proactive["nudges"].get(prefs.CATEGORY_ENVIRONMENT, True))
    )

    rows = await load_rows(
        session, station_id, now - TRIGGER_LOOKBACK, now + timedelta(seconds=1)
    )
    sent: list[Notification] = []
    for rule in RULES:
        try:
            sent += await _run_rule(
                session, notifier, rule, rows=rows, cfg=cfg, active=active, telegram=telegram,
                station_id=station_id, now=now, local_now=local_now,
            )
        except Exception:  # noqa: BLE001 - one broken rule must not silence the others
            logger.warning("environment rule %s failed; skipped", rule.key, exc_info=True)
    try:
        sent += await _run_silent(
            session, notifier, active=active, telegram=telegram, station_id=station_id,
            redis=redis, now=now, local_now=local_now,
        )
    except Exception:  # noqa: BLE001
        logger.warning("environment silent-station rule failed; skipped", exc_info=True)
    return sent


async def environment_alerts_job(
    session_factory: async_sessionmaker[AsyncSession], redis: Optional[Redis] = None
) -> None:
    """Every 30 seconds. Does nothing without a configured station; with the module
    off it only makes sure no stale badge is left showing. A missing Telegram
    channel still raises the badges — only the messages need it."""
    config = load_config()
    if not config.env_station_url:
        return
    async with session_factory() as session:
        enabled = await modules_service.get_enabled_modules(session, redis)
        if not enabled.get("environment"):
            await alerts_service.resolve_all(session, domain=DOMAIN)
            await session.commit()
            return
        # The badge texts are translated at raise time, so a job needs the
        # owner's language the way a request does.
        current_lang.set(await get_language(session, redis))
        await evaluate(session, channels.build_notifier(), redis=redis, station_id=config.env_station_id)
        await session.commit()
