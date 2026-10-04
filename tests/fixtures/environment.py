"""Shared building blocks for the environment domain's tests.

Import from a test file as ``from fixtures.environment import ...`` — pytest puts
``tests/`` on ``sys.path``, and ``tests.fixtures`` would be exposed to the same
site-packages shadowing the conftest comments warn about.

* ``FakeStation`` — the station behind an ``httpx.MockTransport`` with a clock the
  test moves by hand; pass ``station.transport`` to ``StationClient(transport=...)``.
* ``sample_row`` / ``flat_rows`` / ``ramp_rows`` / ``night_rows`` — rows shaped like
  ``environment_samples`` (``night_rows`` is the seeded synthetic bedroom).
* ``insert_samples`` — bulk-write such rows through a session.

The station address in tests is always ``http://station.test``.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

import httpx

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "simulate_station.py"


def _load_simulator():
    """``scripts/`` is not a package, so the simulator is loaded by path."""
    spec = importlib.util.spec_from_file_location("simulate_station", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["simulate_station"] = module
    spec.loader.exec_module(module)
    return module


simulator = _load_simulator()

STATION_URL = "http://station.test"
STATION_CREDENTIALS = ("station-user", "station-pass")
STATION_ID = "bedroom"
TEST_BOOT_ID = "testboot"
_START = 1_759_600_000.0  # a fixed epoch: the fake clock starts here, never at the wall time


class FakeStation:
    """A simulated station whose clock only moves when ``advance`` is called.

    ``station.transport`` is an ``httpx.MockTransport`` answering like the device
    (envelope, 401 without the right credentials); an offline scenario raises the
    transport error a dropped connection would.
    """

    url = STATION_URL
    credentials = STATION_CREDENTIALS

    def __init__(self, scenario: str = "normal", **kw) -> None:
        kw.setdefault("seed", 1)
        self.now = _START
        self.sim = simulator.StationSim(scenario, started_at=_START, credentials=STATION_CREDENTIALS, **kw)
        self.transport = httpx.MockTransport(self._handle)

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def _handle(self, request: httpx.Request) -> httpx.Response:
        reply = self.sim.handle(
            request.method, request.url.raw_path.decode(), request.headers.get("Authorization"), self.now
        )
        if reply is None:
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.", request=request)
        return httpx.Response(reply.status, headers=reply.headers, content=reply.body, request=request)


def sample_row(
    ts: datetime,
    *,
    co2: Optional[int] = 700,
    temp: Optional[float] = 21.5,
    rh: Optional[float] = 45.0,
    seq: int = 1,
    quality: int = 0,
    station_id: str = STATION_ID,
    boot_id: str = TEST_BOOT_ID,
    tz: Optional[tzinfo] = None,
) -> dict:
    """One ``environment_samples`` row at ``ts`` (aware). ``date`` is the local date."""
    zone = tz or ZoneInfo("Europe/Chisinau")
    return {
        "station_id": station_id,
        "boot_id": boot_id,
        "seq": seq,
        "ts": ts,
        "received_at": ts + timedelta(seconds=2),
        "time_basis": "device",
        "co2_ppm": co2,
        "temperature_c": temp,
        "humidity_pct": rh,
        "lux_avg": None,
        "lux_max": None,
        "quality": quality,
        "extra": {"rssi": -60, "heap": 142000, "fw": simulator.FIRMWARE},
        "date": ts.astimezone(zone).date(),
        "domain": simulator.DOMAIN,
        "source": simulator.SOURCE,
    }


def ramp_rows(
    end: datetime,
    *,
    minutes: float,
    co2_from: int,
    co2_to: int,
    temp: float = 21.5,
    rh: float = 45.0,
    interval_s: int = 10,
    **kw,
) -> list[dict]:
    """Rows for the ``minutes`` before ``end`` (exclusive), CO2 climbing linearly;
    the last row sits one interval before ``end`` — what a poller that has just
    caught up sees."""
    count = int(minutes * 60 // interval_s)
    rows = []
    for i in range(count):
        ts = end - timedelta(seconds=(count - i) * interval_s)
        co2 = round(co2_from + (co2_to - co2_from) * i / count)
        rows.append(sample_row(ts, co2=co2, temp=temp, rh=rh, seq=i + 1, **kw))
    return rows


def flat_rows(end: datetime, *, minutes: float, co2: int = 700, **kw) -> list[dict]:
    """Like ``ramp_rows`` with every reading constant."""
    return ramp_rows(end, minutes=minutes, co2_from=co2, co2_to=co2, **kw)


def night_rows(
    on_date: date,
    kind: str = "mixed",
    *,
    interval_s: int = 60,
    seed: int = 1,
    gaps: Iterable[tuple[datetime, datetime]] = (),
    tz: Optional[tzinfo] = None,
) -> list[dict]:
    """A synthetic night: the local window ``on_date`` 00:00-12:00. ``kind`` is
    ``fresh`` / ``ok`` / ``stuffy`` / ``warm`` / ``mixed`` (see ``NIGHT_KINDS``)."""
    zone = tz or ZoneInfo("Europe/Chisinau")
    start = datetime(on_date.year, on_date.month, on_date.day, tzinfo=zone)
    end = (start.astimezone(timezone.utc) + timedelta(hours=12)).astimezone(zone)
    return list(
        simulator.generate_samples(
            start, end, seed=seed, interval_s=interval_s, night=kind, tz=zone, gaps=gaps,
            station_id=STATION_ID,
        )
    )


async def insert_samples(session, rows: list[dict], *, chunk: int = 2000) -> None:
    """Bulk-insert rows into ``environment_samples`` and commit."""
    from sqlalchemy import insert

    from vitals.models.environment import EnvironmentSample

    for i in range(0, len(rows), chunk):
        await session.execute(insert(EnvironmentSample), rows[i : i + chunk])
    await session.commit()
