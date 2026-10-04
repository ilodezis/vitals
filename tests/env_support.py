"""Shared helpers for the environment tests: a fake station behind
``httpx.MockTransport`` and a way to lay down samples without a poller.

The station address in tests is always ``http://station.test``.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Optional

import httpx

from vitals.integrations.esphome_client import SNAPSHOT_PATH, StationClient
from vitals.models.environment import DOMAIN, EnvironmentSample
from vitals.utils.timeutils import to_local_naive

UTC = timezone.utc
STATION_URL = "http://station.test"


def snapshot(
    *,
    boot: str = "9f3a1c2e",
    seq: int = 1,
    t: Optional[int] = None,
    co2: Any = 812,
    temp: Any = 21.4,
    rh: Any = 41.2,
    **extra: Any,
) -> dict[str, Any]:
    """A contract-v1 snapshot (pass ``t=0`` for a station without a clock)."""
    body: dict[str, Any] = {
        "v": 1,
        "boot": boot,
        "seq": seq,
        "t": 0 if t is None else t,
        "up": 547020,
        "co2": co2,
        "temp": temp,
        "rh": rh,
        "lux": None,
        "rssi": -61,
        "heap": 142336,
        "fw": "env-1.1.0",
    }
    body.update(extra)
    return body


def esphome_body(snap: Any) -> bytes:
    """What the station's web server returns for the snapshot text sensor."""
    value = snap if isinstance(snap, str) else json.dumps(snap)
    return json.dumps({"id": "text_sensor-env_snapshot", "value": value, "state": value}).encode()


class FakeStation:
    """A scripted station. ``current`` is the snapshot served; set ``status`` or
    ``raises`` to make it misbehave. Every request lands in ``requests``."""

    def __init__(self, current: Any = None) -> None:
        self.current: Any = snapshot() if current is None else current
        self.status = 200
        self.raises: Optional[Exception] = None
        self.body: Optional[bytes] = None
        self.headers: dict[str, str] = {}
        self.requests: list[httpx.Request] = []

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.raises is not None:
            raise self.raises
        body = self.body if self.body is not None else esphome_body(self.current)
        return httpx.Response(self.status, content=body, headers=self.headers)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def client(self, *, user: str = "u", password: str = "p") -> StationClient:
        return StationClient(STATION_URL, user, password, transport=self.transport)


def sample(
    ts: datetime,
    seq: int,
    *,
    boot: str = "b1",
    station: str = "bedroom",
    co2: Optional[int] = 800,
    temp: Optional[float] = 21.0,
    rh: Optional[float] = 45.0,
    **kw: Any,
) -> EnvironmentSample:
    return EnvironmentSample(
        date=to_local_naive(ts).date(),
        domain=DOMAIN,
        source="esphome",
        station_id=station,
        boot_id=boot,
        seq=seq,
        ts=ts,
        received_at=ts,
        time_basis="device",
        co2_ppm=co2,
        temperature_c=temp,
        humidity_pct=rh,
        quality=0,
        **kw,
    )


async def add_samples(
    session,
    start: datetime,
    *,
    count: int,
    step_s: int = 10,
    co2: Callable[[int], Optional[int]] | int = 800,
    temp: Callable[[int], Optional[float]] | float = 21.0,
    rh: Callable[[int], Optional[float]] | float = 45.0,
    boot: str = "b1",
    first_seq: int = 1,
    station: str = "bedroom",
) -> list[EnvironmentSample]:
    """``count`` samples ``step_s`` apart from ``start``; each value is a constant
    or a function of the sample's index."""

    def pick(v, i):
        return v(i) if callable(v) else v

    rows = [
        sample(
            start + timedelta(seconds=i * step_s),
            first_seq + i,
            boot=boot,
            station=station,
            co2=pick(co2, i),
            temp=pick(temp, i),
            rh=pick(rh, i),
        )
        for i in range(count)
    ]
    session.add_all(rows)
    await session.flush()
    return rows


def at(iso: str) -> datetime:
    """``"2026-10-05T12:00:00"`` → an aware UTC datetime."""
    return datetime.fromisoformat(iso).replace(tzinfo=UTC)


__all__: Iterable[str] = [
    "SNAPSHOT_PATH",
    "STATION_URL",
    "FakeStation",
    "UTC",
    "add_samples",
    "at",
    "esphome_body",
    "sample",
    "snapshot",
]
