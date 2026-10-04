#!/usr/bin/env python3
"""Stand-in for the bedroom environment station, so the domain can be built and
tested without the hardware.

Two things live here:

* ``StationSim`` / ``make_server`` — a small HTTP server that answers
  ``GET /text_sensor/env_snapshot`` exactly like the station's ESPHome web server
  does (the v1 snapshot contract, behind basic auth), with scenarios that walk the
  readings through the situations the alert rules and screens care about.
* ``generate_samples`` — a seeded generator of synthetic days and nights, as rows
  shaped like ``environment_samples``, for developing a screen without waiting a
  week for data (``scripts/seed_demo.py`` writes them to the dev database).

Standard library only, so it also runs where the project's virtualenv is not set up.

    python scripts/simulate_station.py --scenario co2_rising --speed 10

Credentials are never baked in: they come from ``--user``/``--password`` or from the
same ``VITALS_ENV_STATION_USER`` / ``VITALS_ENV_STATION_PASSWORD`` variables Vitals
reads, so pointing Vitals at the simulator needs only ``VITALS_ENV_STATION_URL``.

Scenarios (``--scenario``):

    normal      comfortable room, readings drift slowly
    co2_rising  CO2 climbs from ~700 to 1600 ppm, holds, then falls after "airing"
    humid       humidity above 70 %
    dry         humidity below 30 %
    hot         temperature around 28 C
    offline     stops answering after ``--after`` seconds (Wi-Fi drop: same boot, the
                station keeps counting); ``--offline-for`` brings it back
    reboot      power-cycles after ``--after`` seconds: new ``boot``, ``seq`` from 1
                (``--reboot-every`` repeats it)
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import math
import os
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone, tzinfo
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Iterable, Iterator, NamedTuple, Optional
from zoneinfo import ZoneInfo

SNAPSHOT_PATH = "/text_sensor/env_snapshot"
SENSOR_ID = "text_sensor-env_snapshot"
CONTRACT_VERSION = 1
FIRMWARE = "env-sim-1.0"

# Values the rows carry — kept equal to ``Domain.ENVIRONMENT`` / ``Source.ESPHOME``
# (a test pins that), so this script needs no import from the application.
DOMAIN = "environment"
SOURCE = "esphome"

SCENARIOS = ("normal", "co2_rising", "humid", "dry", "hot", "offline", "reboot")

# CO2 ramp of ``co2_rising``, in scenario seconds. Long enough above 1400 ppm
# (≈11 min) for a "every snapshot of the last five minutes" rule to fire.
_RISE_START_PPM = 700
_PEAK_PPM = 1600
_RISE_S = 1200
_HOLD_S = 360
_FALL_TAU_S = 240


class Reply(NamedTuple):
    status: int
    headers: dict
    body: bytes


def basic_auth_header(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {token}"


def _wave(s: float, period_s: float, phase: float = 0.0) -> float:
    return math.sin(2 * math.pi * s / period_s + phase)


@dataclass
class StationSim:
    """The device, as a pure function of time.

    Nothing here reads the wall clock: every method takes ``now`` (epoch seconds), so
    a test can drive a day of snapshots without sleeping, and the HTTP server passes
    ``time.time()``. Readings are deterministic for a given ``seed`` and ``started_at``.

    ``interval`` is the real snapshot cadence in seconds; ``speed`` compresses only
    the scenario's own clock (a 20-minute CO2 ramp at ``speed=10`` takes two minutes),
    never the cadence.
    """

    scenario: str = "normal"
    interval: float = 10.0
    seed: int = 0
    speed: float = 1.0
    started_at: float = field(default_factory=time.time)
    after: float = 30.0
    offline_for: float = 0.0
    reboot_every: float = 0.0
    unsynced: bool = False
    cold_start: bool = False
    credentials: Optional[tuple[str, str]] = None

    def __post_init__(self) -> None:
        if self.scenario not in SCENARIOS:
            raise ValueError(f"unknown scenario {self.scenario!r}; choose from {', '.join(SCENARIOS)}")
        if self.interval <= 0:
            raise ValueError("interval must be positive")

    # ── time ────────────────────────────────────────────────────────────────

    def _elapsed(self, now: float) -> float:
        return max(0.0, now - self.started_at)

    def _boot(self, elapsed: float) -> tuple[int, float]:
        """Which boot the station is in at ``elapsed`` and when that boot began."""
        if self.scenario != "reboot" or elapsed < self.after:
            return 0, 0.0
        if self.reboot_every > 0:
            n = int((elapsed - self.after) // self.reboot_every)
            return 1 + n, self.after + n * self.reboot_every
        return 1, self.after

    def is_offline(self, now: float) -> bool:
        if self.scenario != "offline":
            return False
        elapsed = self._elapsed(now)
        if elapsed < self.after:
            return False
        return self.offline_for <= 0 or elapsed < self.after + self.offline_for

    # ── the snapshot ────────────────────────────────────────────────────────

    def snapshot(self, now: float) -> dict:
        """The v1 snapshot current at ``now``. Repeats until the next interval, as the
        real text sensor does — which is what makes ``(boot, seq)`` an identity."""
        elapsed = self._elapsed(now)
        boot_index, boot_start = self._boot(elapsed)
        tick = int((elapsed - boot_start + 1e-6) // self.interval)
        made_at = boot_start + tick * self.interval  # when this snapshot was generated

        rng = random.Random(f"{self.seed}:{int(round(made_at * 1000))}")
        if self.cold_start and tick == 0:
            co2 = temp = rh = None
        else:
            co2, temp, rh = self._readings(made_at * self.speed, rng)

        return {
            "v": CONTRACT_VERSION,
            "boot": hashlib.sha1(
                f"{self.seed}:{int(self.started_at)}:{boot_index}".encode()
            ).hexdigest()[:8],
            "seq": tick + 1,
            "t": 0 if self.unsynced else int(self.started_at + made_at),
            "up": int(tick * self.interval),
            "co2": co2,
            "temp": temp,
            "rh": rh,
            "lux": None,
            "rssi": -60 + rng.randint(-4, 4),
            "heap": 142336 - rng.randint(0, 800),
            "fw": FIRMWARE,
        }

    def _readings(self, s: float, rng: random.Random) -> tuple[int, float, float]:
        co2 = 620 + 70 * _wave(s, 5400)
        temp = 21.5 + 0.6 * _wave(s, 7200, 1.0)
        rh = 43 + 3 * _wave(s, 9000, 2.0)

        if self.scenario == "co2_rising":
            if s < _RISE_S:
                co2 = _RISE_START_PPM + (_PEAK_PPM - _RISE_START_PPM) * s / _RISE_S
            elif s < _RISE_S + _HOLD_S:
                co2 = _PEAK_PPM
            else:  # the window is open: back down onto the normal curve
                co2 += (_PEAK_PPM - co2) * math.exp(-(s - _RISE_S - _HOLD_S) / _FALL_TAU_S)
        elif self.scenario == "humid":
            rh = 74 + 1.5 * _wave(s, 3600)
            temp = 22.0 + 0.3 * _wave(s, 7200)
        elif self.scenario == "dry":
            rh = 25 + 1.5 * _wave(s, 3600)
            temp = 22.5 + 0.3 * _wave(s, 7200)
        elif self.scenario == "hot":
            temp = 28.5 + 0.4 * _wave(s, 3600)
            rh = 38 + 2 * _wave(s, 9000)

        co2 += rng.gauss(0, 6)
        temp += rng.gauss(0, 0.05)
        rh += rng.gauss(0, 0.3)
        return int(round(co2)), round(temp, 1), round(min(max(rh, 0.0), 100.0), 1)

    # ── the HTTP surface ────────────────────────────────────────────────────

    def handle(self, method: str, path: str, authorization: Optional[str], now: float) -> Optional[Reply]:
        """What the device would answer, or ``None`` when it does not answer at all
        (offline). Shared by the socket server and by tests that mock the transport."""
        if self.is_offline(now):
            return None
        if self.credentials is not None and not self._authorized(authorization):
            return _json_reply(401, {"detail": "unauthorized"}, {"WWW-Authenticate": 'Basic realm="station"'})
        if method != "GET":
            return _json_reply(405, {"detail": "method not allowed"})
        if path.split("?", 1)[0] != SNAPSHOT_PATH:
            return _json_reply(404, {"detail": "not found"})

        value = json.dumps(self.snapshot(now), separators=(",", ":"))
        return _json_reply(200, {"id": SENSOR_ID, "value": value, "state": value})

    def _authorized(self, header: Optional[str]) -> bool:
        if not header or not header.startswith("Basic "):
            return False
        user, password = self.credentials
        expected = f"{user}:{password}".encode()
        try:
            given = base64.b64decode(header[6:], validate=True)
        except ValueError:
            return False
        return hmac.compare_digest(given, expected)


def _json_reply(status: int, payload: dict, headers: Optional[dict] = None) -> Reply:
    return Reply(status, {"Content-Type": "application/json", **(headers or {})},
                 json.dumps(payload, separators=(",", ":")).encode())


def make_server(
    station: StationSim,
    host: str = "127.0.0.1",
    port: int = 0,
    *,
    clock: Callable[[], float] = time.time,
    verbose: bool = False,
) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _serve(self) -> None:
            reply = station.handle(self.command, self.path, self.headers.get("Authorization"), clock())
            if reply is None:  # a station with no Wi-Fi sends nothing back
                self.close_connection = True
                return
            self.send_response(reply.status)
            for name, value in reply.headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(reply.body)))
            self.end_headers()
            self.wfile.write(reply.body)
            if self.command != "GET":  # an unread request body would desync a kept-alive socket
                self.close_connection = True

        do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _serve

        def log_message(self, fmt, *args) -> None:
            if verbose:
                sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


# ── synthetic history ────────────────────────────────────────────────────────

# kind of night -> (air changes per hour while asleep, extra °C the room carries)
NIGHT_KINDS: dict[str, tuple[float, float]] = {
    "fresh": (2.0, 0.0),    # window ajar
    "ok": (1.0, 0.0),       # door open
    "stuffy": (0.35, 0.0),  # everything shut
    "warm": (0.5, 3.0),     # shut and warm
}
_NIGHT_WEIGHTS = (("fresh", 0.25), ("ok", 0.35), ("stuffy", 0.30), ("warm", 0.10))

_OUTDOOR_CO2 = 420.0
_CO2_PPM_PER_H_PER_PERSON = 450.0  # one sleeper in a ~40 m³ room with no air exchange
_AWAKE_ACH = 0.6
_WINDOW_OPEN_ACH = 8.0
_WARMUP_H = 12


def _default_tz() -> tzinfo:
    return ZoneInfo(os.getenv("VITALS_TIMEZONE") or "Europe/Chisinau")


class _Routine:
    """When the bedroom is slept in and aired, per local date, from the seed alone —
    so the same date looks the same whichever range it is generated inside."""

    def __init__(self, seed: int, night: str) -> None:
        self.seed, self.night = seed, night
        self._cache: dict[tuple[str, date], object] = {}

    def _memo(self, label: str, d: date, make: Callable[[random.Random], object]):
        key = (label, d)
        if key not in self._cache:
            self._cache[key] = make(random.Random(f"{self.seed}:{label}:{d.isoformat()}"))
        return self._cache[key]

    def bed(self, d: date) -> float:
        """Hour of day ``d`` they go to bed; up to 24.5, i.e. half past midnight."""
        return self._memo("bed", d, lambda r: r.uniform(23.0, 24.5))

    def wake(self, d: date) -> float:
        """Hour of day ``d + 1`` they get up, for the night that starts on ``d``."""
        return self._memo("wake", d, lambda r: r.uniform(6.5, 8.0))

    def kind(self, d: date) -> str:
        if self.night != "mixed":
            return self.night
        def pick(r: random.Random) -> str:
            roll, acc = r.random(), 0.0
            for name, weight in _NIGHT_WEIGHTS:
                acc += weight
                if roll < acc:
                    return name
            return _NIGHT_WEIGHTS[-1][0]
        return self._memo("kind", d, pick)

    def airings(self, d: date) -> list[tuple[float, float]]:
        """(start hour, length in hours) of every time the window is opened on ``d``."""
        def make(r: random.Random) -> list[tuple[float, float]]:
            out = []
            if r.random() < 0.9:
                out.append((self.wake(d - timedelta(days=1)), r.uniform(10, 20) / 60))
            if r.random() < 0.6:
                out.append((13 + r.uniform(0, 4), 10 / 60))
            if r.random() < 0.5:
                out.append((22 + r.uniform(0, 0.8), 10 / 60))
            return out
        return self._memo("air", d, make)

    def conditions(self, local: datetime) -> tuple[float, float, float, float]:
        """(sleeping share, occupancy, air changes per hour, extra warmth) at ``local``."""
        h = local.hour + local.minute / 60 + local.second / 3600
        d = local.date()
        prev = d - timedelta(days=1)

        kind = None
        if h >= self.bed(d):
            kind = self.kind(d)
        elif h < self.wake(prev) and h + 24 >= self.bed(prev):
            kind = self.kind(prev)

        if kind is not None:
            ach, warm = NIGHT_KINDS[kind]
            return 1.0, 1.0, ach, warm
        if any(start <= h < start + length for start, length in self.airings(d)):
            ach = _WINDOW_OPEN_ACH
        else:
            ach = _AWAKE_ACH
        wake_prev = self.wake(prev)
        if 21.0 <= h < self.bed(d):
            occupancy = 0.8
        elif wake_prev <= h < wake_prev + 1.0:
            occupancy = 0.6
        else:
            occupancy = 0.03
        return 0.0, occupancy, ach, 0.0


class _Room:
    """Three first-order lags: CO2 from breathing against air exchange, temperature
    toward the day's curve (cooled by an open window), humidity toward a target that
    follows temperature and the sleeper."""

    def __init__(self) -> None:
        self.co2, self.temp, self.rh = 500.0, 21.0, 45.0

    def advance(self, local: datetime, dt_h: float, routine: _Routine) -> None:
        sleeping, occupancy, ach, warm = routine.conditions(local)
        h = local.hour + local.minute / 60

        self.co2 += dt_h * (_CO2_PPM_PER_H_PER_PERSON * occupancy - ach * (self.co2 - _OUTDOOR_CO2))

        outdoor = 12 + 5 * math.sin(2 * math.pi * (h - 9) / 24)
        target = 21.0 + math.sin(2 * math.pi * (h - 10) / 24) + 0.9 * sleeping + warm * sleeping
        cooling = 0.15 * max(ach - 1.0, 0.0) * (self.temp - outdoor)
        self.temp += dt_h * ((target - self.temp) / 1.5 - cooling)

        rh_target = 44 - 1.8 * (self.temp - 21.5) + 6 * sleeping + 2 * occupancy
        self.rh += dt_h * (rh_target - self.rh) / 0.75


def generate_samples(
    start: datetime,
    end: datetime,
    *,
    seed: int = 0,
    interval_s: int = 10,
    station_id: str = "bedroom",
    night: str = "mixed",
    tz: Optional[tzinfo] = None,
    gaps: Iterable[tuple[datetime, datetime]] = (),
    boot_id: Optional[str] = None,
) -> Iterator[dict]:
    """Rows shaped like ``environment_samples`` for ``[start, end)``, one per
    ``interval_s``, from a bedroom that is slept in and aired on a seeded routine.

    ``night`` is one of ``NIGHT_KINDS`` or ``"mixed"`` (a seeded draw per night).
    ``gaps`` are ``(start, end)`` ranges the station was unreachable for: rows are
    dropped but ``seq`` keeps counting, which is what a Wi-Fi drop looks like to the
    poller. The room is warmed up for 12 h before ``start``, so a range that begins
    at midnight does not begin in a cold-start state.
    """
    if night != "mixed" and night not in NIGHT_KINDS:
        raise ValueError(f"unknown night kind {night!r}; choose from mixed, {', '.join(NIGHT_KINDS)}")
    if interval_s <= 0:
        raise ValueError("interval_s must be positive")
    return _generate(start, end, seed, interval_s, station_id, night, tz or _default_tz(),
                     tuple(gaps), boot_id or hashlib.sha1(f"{seed}:history".encode()).hexdigest()[:8])


def _generate(start, end, seed, interval_s, station_id, night, tz, gaps, boot_id) -> Iterator[dict]:
    routine = _Routine(seed, night)
    room = _Room()
    noise = random.Random(f"{seed}:noise")
    start_utc = start.astimezone(timezone.utc)
    end_utc = end.astimezone(timezone.utc)
    gaps_utc = [(a.astimezone(timezone.utc), b.astimezone(timezone.utc)) for a, b in gaps]

    warm = start_utc - timedelta(hours=_WARMUP_H)
    for k in range(_WARMUP_H * 60):
        room.advance((warm + timedelta(minutes=k)).astimezone(tz), 1 / 60, routine)

    substeps = max(1, math.ceil(interval_s / 60))
    dt_h = interval_s / substeps / 3600
    seq, ts = 0, start_utc
    while ts < end_utc:
        seq += 1
        local = ts.astimezone(tz)
        for _ in range(substeps):
            room.advance(local, dt_h, routine)
        co2 = room.co2 + noise.gauss(0, 6)
        temp = room.temp + noise.gauss(0, 0.05)
        rh = room.rh + noise.gauss(0, 0.3)
        rssi = -60 + noise.randint(-4, 4)
        heap = 142336 - noise.randint(0, 800)
        if not any(a <= ts < b for a, b in gaps_utc):
            yield {
                "station_id": station_id,
                "boot_id": boot_id,
                "seq": seq,
                "ts": ts,
                "received_at": ts + timedelta(seconds=2),
                "time_basis": "device",
                "co2_ppm": int(round(co2)),
                "temperature_c": round(temp, 1),
                "humidity_pct": round(min(max(rh, 0.0), 100.0), 1),
                "lux_avg": None,
                "lux_max": None,
                "quality": 0,
                "extra": {"rssi": rssi, "heap": heap, "up": (seq - 1) * interval_s, "fw": FIRMWARE},
                "date": local.date(),
                "domain": DOMAIN,
                "source": SOURCE,
            }
        ts = start_utc + timedelta(seconds=seq * interval_s)


# ── command line ─────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Simulate the environment station's snapshot endpoint.")
    p.add_argument("--scenario", choices=SCENARIOS, default="normal")
    p.add_argument("--host", default="127.0.0.1",
                   help="bind address; use 0.0.0.0 to be reachable from a container")
    p.add_argument("--port", type=int, default=8085)
    p.add_argument("--interval", type=float, default=10.0, help="seconds between snapshots")
    p.add_argument("--seed", type=int, default=0, help="makes the readings reproducible")
    p.add_argument("--speed", type=float, default=1.0,
                   help="run the scenario's own clock this many times faster (not the snapshot cadence)")
    p.add_argument("--after", type=float, default=30.0,
                   help="seconds before 'offline' stops answering / 'reboot' power-cycles")
    p.add_argument("--offline-for", type=float, default=0.0,
                   help="'offline' comes back after this many seconds (0 = never)")
    p.add_argument("--reboot-every", type=float, default=0.0,
                   help="'reboot' repeats at this period (0 = once)")
    p.add_argument("--unsynced", action="store_true", help="report t=0, as before the first SNTP sync")
    p.add_argument("--cold-start", action="store_true",
                   help="the first snapshot after each boot carries null readings")
    p.add_argument("--user", default=None, help="basic-auth user (default: $VITALS_ENV_STATION_USER)")
    p.add_argument("--password", default=None,
                   help="basic-auth password (default: $VITALS_ENV_STATION_PASSWORD; the variable "
                        "keeps it out of the process list)")
    p.add_argument("--no-auth", action="store_true", help="answer without asking for credentials")
    p.add_argument("--verbose", action="store_true", help="log every request")
    return p


def resolve_credentials(args: argparse.Namespace) -> Optional[tuple[str, str]]:
    if args.no_auth:
        return None
    user = args.user or os.getenv("VITALS_ENV_STATION_USER")
    password = args.password or os.getenv("VITALS_ENV_STATION_PASSWORD")
    return (user, password) if user and password else None


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    credentials = resolve_credentials(args)
    if credentials is None and not args.no_auth:
        print(
            "error: no credentials. Set VITALS_ENV_STATION_USER and VITALS_ENV_STATION_PASSWORD "
            "(the variables Vitals reads), pass --user/--password, or pass --no-auth.",
            file=sys.stderr,
        )
        return 2

    station = StationSim(
        args.scenario, interval=args.interval, seed=args.seed, speed=args.speed,
        after=args.after, offline_for=args.offline_for, reboot_every=args.reboot_every,
        unsynced=args.unsynced, cold_start=args.cold_start, credentials=credentials,
    )
    server = make_server(station, args.host, args.port, verbose=args.verbose)
    host, port = server.server_address[:2]
    print(
        f"simulating '{args.scenario}' at http://{host}:{port}{SNAPSHOT_PATH} "
        f"(snapshot every {args.interval:g}s, {'no auth' if credentials is None else 'basic auth'})"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
