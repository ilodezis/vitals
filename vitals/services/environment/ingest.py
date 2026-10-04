"""Pulling snapshots from the station into ``environment_samples``.

One poll = one HTTP request, one validated snapshot, at most one new row. The row
is keyed by ``(station_id, boot_id, seq)`` and written with ``ON CONFLICT DO
NOTHING``, so asking twice for the same snapshot — which a 10 s poll against a
10 s station does all the time — changes nothing. After a station reboot the
random ``boot`` differs, so a restarted counter never collides with old rows.

``poll_once`` never raises for a station problem: a failure is recorded (Redis
status, a growing pause) and reported as ``PollOutcome.ERROR``. Only a bug — not a
dead station — propagates to the scheduler's own failure alert.
"""
from __future__ import annotations

import enum
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from redis.asyncio import Redis
from sqlalchemy import insert
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from vitals.config import load_config
from vitals.enums import Source
from vitals.integrations.esphome_client import (
    NOT_CONFIGURED,
    StationClient,
    StationError,
    StationSnapshot,
)
from vitals.models.environment import (
    CO2_RANGE,
    DOMAIN,
    HUMIDITY_RANGE,
    Q_CLOCK_UNSYNCED,
    Q_MISSING,
    Q_OUT_OF_RANGE,
    Q_STALE,
    TEMPERATURE_RANGE,
    TIME_DEVICE,
    TIME_RECEIVED,
    EnvironmentSample,
)
from vitals.services import modules_service
from vitals.services.environment import live as live_mod
from vitals.services.environment.live import station_key
from vitals.utils.timeutils import as_utc, now_utc, to_local_naive

logger = logging.getLogger(__name__)

# The station's clock before SNTP sync reads 0 (the client turns that into
# ``None``); a board without a battery clock can also come up on a 1970 date.
# Anything before this is "no real time".
MIN_VALID_EPOCH = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())
# A device timestamp this far from the moment Vitals received it cannot be right
# (the poll lag is seconds); the sample is filed under the receipt time instead.
MAX_CLOCK_SKEW = timedelta(minutes=10)

# Identical CO2, temperature and humidity for this long while the counter keeps
# running means a frozen sensor — a live SCD41 never repeats all three for half
# an hour.
FROZEN_AFTER_S = 30 * 60

# Pause between polls after consecutive failures: one interval, doubling, capped.
MAX_BACKOFF_S = 300


class PollOutcome(str, enum.Enum):
    INSERTED = "inserted"
    DUPLICATE = "duplicate"
    ERROR = "error"


def client_from_config() -> Optional[StationClient]:
    """The configured station, or ``None`` when no address is set."""
    config = load_config()
    if not config.env_station_url:
        return None
    return StationClient(
        config.env_station_url, config.env_station_user, config.env_station_password
    )


def build_row(
    snap: StationSnapshot, *, station_id: str, received_at: datetime, frozen: bool = False
) -> dict[str, Any]:
    """A validated snapshot → the column values of its ``environment_samples`` row."""
    quality = 0
    extra: dict[str, Any] = dict(snap.extra)

    # Time: the station's own clock when it has one and it agrees with ours.
    ts = received_at
    basis = TIME_RECEIVED
    if snap.t is not None and snap.t >= MIN_VALID_EPOCH:
        device_ts = datetime.fromtimestamp(snap.t, tz=timezone.utc)
        if abs(device_ts - received_at) <= MAX_CLOCK_SKEW:
            ts, basis = device_ts, TIME_DEVICE
        else:
            extra["t"] = snap.t  # kept: a clock that far off is worth seeing
    if basis == TIME_RECEIVED:
        quality |= Q_CLOCK_UNSYNCED

    # Readings: a missing sensor stays NULL (never zero); an impossible value is
    # NULLed too, with the original kept so nothing is lost.
    out_of_range: dict[str, Any] = {}

    def reading(name: str, value: Optional[float], bounds: tuple[float, float]) -> Optional[float]:
        if value is None:
            return None
        if not bounds[0] <= value <= bounds[1]:
            out_of_range[name] = value
            return None
        return value

    co2 = reading("co2", snap.co2, CO2_RANGE)
    temp = reading("temp", snap.temp, TEMPERATURE_RANGE)
    rh = reading("rh", snap.rh, HUMIDITY_RANGE)
    if out_of_range:
        quality |= Q_OUT_OF_RANGE
        extra["out_of_range"] = out_of_range
    if snap.co2 is None or snap.temp is None or snap.rh is None:
        quality |= Q_MISSING
    if frozen:
        quality |= Q_STALE

    lux_max = extra.pop("lux_max", None)
    if isinstance(lux_max, bool) or not isinstance(lux_max, (int, float)):
        lux_max = None

    return {
        "date": to_local_naive(ts).date(),
        "domain": DOMAIN,
        "source": Source.ESPHOME.value,
        "station_id": station_id,
        "boot_id": snap.boot,
        "seq": snap.seq,
        "ts": ts,
        "received_at": received_at,
        "time_basis": basis,
        "co2_ppm": co2,
        "temperature_c": temp,
        "humidity_pct": rh,
        "lux_avg": snap.lux,
        "lux_max": lux_max,
        "quality": quality,
        "extra": extra or None,
    }


async def _insert_ignoring_duplicates(session: AsyncSession, values: dict[str, Any]) -> bool:
    """``INSERT … ON CONFLICT DO NOTHING``; True when a row was written."""
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        stmt = postgresql_insert(EnvironmentSample).values(**values)
    elif dialect == "sqlite":
        stmt = sqlite_insert(EnvironmentSample).values(**values)
    else:  # pragma: no cover - the schema targets Postgres, tests use SQLite
        stmt = insert(EnvironmentSample).values(**values)
    if dialect in ("postgresql", "sqlite"):
        stmt = stmt.on_conflict_do_nothing(index_elements=["station_id", "boot_id", "seq"])
    result = await session.execute(stmt)
    return (result.rowcount or 0) > 0


# ── Redis bookkeeping (best-effort throughout) ────────────────────────────────
async def _hgetall(redis: Optional[Redis], key: str) -> dict[str, str]:
    if redis is None:
        return {}
    try:
        return await redis.hgetall(key) or {}
    except Exception:
        logger.warning("environment: could not read station state", exc_info=True)
        return {}


async def _hset(redis: Optional[Redis], key: str, mapping: dict[str, Any]) -> None:
    if redis is None:
        return
    try:
        await redis.hset(key, mapping={k: "" if v is None else str(v) for k, v in mapping.items()})
    except Exception:
        logger.warning("environment: could not write station state", exc_info=True)


async def _frozen(
    redis: Optional[Redis], station_id: str, snap: StationSnapshot, now: datetime
) -> bool:
    """Has the same CO2 + temperature + humidity been reported for 30 minutes?

    Tracked in Redis (a database lookback per poll would cost more than the flag
    is worth); without Redis the flag is simply never set."""
    if redis is None or None in (snap.co2, snap.temp, snap.rh):
        return False
    fingerprint = f"{snap.co2}|{snap.temp}|{snap.rh}"
    state = await _hgetall(redis, station_key(station_id))
    since = state.get("frozen_since")
    if state.get("frozen_fp") != fingerprint or not since:
        await _hset(
            redis,
            station_key(station_id),
            {"frozen_fp": fingerprint, "frozen_since": now.timestamp()},
        )
        return False
    try:
        return now.timestamp() - float(since) >= FROZEN_AFTER_S
    except ValueError:
        return False


async def _record_success(
    redis: Optional[Redis], station_id: str, snap: StationSnapshot, now: datetime
) -> None:
    await _hset(
        redis,
        station_key(station_id),
        {
            "last_ok_at": now.isoformat(),
            "last_error": "",
            "fail_count": 0,
            "retry_at": "",
            "boot": snap.boot,
            "seq_head": snap.seq,
        },
    )


async def _record_failure(
    redis: Optional[Redis], station_id: str, error: StationError, now: datetime, poll_seconds: int
) -> None:
    if redis is None:
        return
    state = await _hgetall(redis, station_key(station_id))
    try:
        fails = int(state.get("fail_count") or 0) + 1
    except ValueError:
        fails = 1
    pause = min(MAX_BACKOFF_S, poll_seconds * 2 ** min(fails - 1, 10))
    await _hset(
        redis,
        station_key(station_id),
        {
            "last_error": error.code,
            "last_error_at": now.isoformat(),
            "fail_count": fails,
            "retry_at": now.timestamp() + pause,
        },
    )


async def poll_once(
    session: AsyncSession,
    client: StationClient,
    *,
    redis: Optional[Redis] = None,
    now: Optional[datetime] = None,
    station_id: Optional[str] = None,
) -> PollOutcome:
    """Ask the station for a snapshot and store it. Executes the insert; the
    caller commits."""
    now = as_utc(now) if now else now_utc()
    config = load_config()
    station_id = station_id or config.env_station_id

    try:
        snap = await client.snapshot()
    except StationError as exc:
        logger.warning("environment: poll failed (%s)", exc.code)
        await _record_failure(redis, station_id, exc, now, config.env_poll_seconds)
        return PollOutcome.ERROR

    frozen = await _frozen(redis, station_id, snap, now)
    values = build_row(snap, station_id=station_id, received_at=now, frozen=frozen)
    inserted = await _insert_ignoring_duplicates(session, values)
    await _record_success(redis, station_id, snap, now)
    if not inserted:
        return PollOutcome.DUPLICATE

    await _publish_if_newer(redis, station_id, values)
    return PollOutcome.INSERTED


async def _publish_if_newer(
    redis: Optional[Redis], station_id: str, values: dict[str, Any]
) -> None:
    """Refresh the live cache — unless it already holds a newer reading (a late or
    replayed snapshot must not roll the screen back)."""
    if redis is None:
        return
    cached = await live_mod.cached_reading(redis, station_id)
    if cached is not None and cached["ts"] > values["ts"].isoformat():
        return
    extra = values["extra"] or {}
    await live_mod.publish_live(
        redis,
        station_id,
        {
            "ts": values["ts"].isoformat(),
            "received_at": values["received_at"].isoformat(),
            "boot": values["boot_id"],
            "seq": values["seq"],
            "co2_ppm": values["co2_ppm"],
            "temperature_c": values["temperature_c"],
            "humidity_pct": values["humidity_pct"],
            "lux": values["lux_avg"],
            "rssi": extra.get("rssi"),
            "fw": extra.get("fw"),
        },
    )


# ── Scheduler / API entry points ──────────────────────────────────────────────
async def _retry_at(redis: Optional[Redis], station_id: str) -> float:
    state = await _hgetall(redis, station_key(station_id))
    try:
        return float(state.get("retry_at") or 0)
    except ValueError:
        return 0.0


async def environment_poll_job(
    session_factory: async_sessionmaker[AsyncSession], redis: Optional[Redis] = None
) -> None:
    """One scheduled poll. Does nothing — not one request — without a configured
    station or with the module off, and sits out the growing pause after failures."""
    config = load_config()
    if not config.env_station_url:
        return
    async with session_factory() as session:
        enabled = await modules_service.get_enabled_modules(session, redis)
        if not enabled.get("environment"):
            return
        if await _retry_at(redis, config.env_station_id) > time.time():
            return
        client = client_from_config()
        if client is None:
            return
        await poll_once(session, client, redis=redis, station_id=config.env_station_id)
        await session.commit()


async def check_station(session: AsyncSession, redis: Optional[Redis] = None) -> dict[str, Any]:
    """Poll right now, ignoring any pause, and say how it went — the "check the
    connection" button. ``error`` is a stable code (see ``esphome_client``)."""
    client = client_from_config()
    if client is None:
        return {"ok": False, "status": "never", "error": NOT_CONFIGURED}

    station_id = load_config().env_station_id
    outcome = await poll_once(session, client, redis=redis, station_id=station_id)
    state = await live_mod.get_live(session, redis, station_id=station_id)
    status = state.station.status if state is not None else "never"
    if outcome is PollOutcome.ERROR:
        recorded = await _hgetall(redis, station_key(station_id))
        return {"ok": False, "status": status, "error": recorded.get("last_error") or "unreachable"}
    return {"ok": True, "status": status, "error": None}
