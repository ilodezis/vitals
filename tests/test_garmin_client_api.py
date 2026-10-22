"""Every ``garminconnect`` method ``GarminClient`` calls must exist on the real
library. The client resolves most of them by name and treats a failure as
"Garmin did not answer", so a misspelled or removed method never raises — it
just leaves a metric empty forever (HR-zone boundaries were lost that way).
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

garminconnect = pytest.importorskip("garminconnect")

from garminconnect import Garmin  # noqa: E402

from vitals.config import Config  # noqa: E402
from vitals.integrations.garmin_client import GarminClient  # noqa: E402


class _RealSurface:
    """Answers only for attributes the real ``Garmin`` class has and records
    every name the client asks for that it doesn't."""

    def __init__(self):
        self.missing: list[str] = []

    def __getattr__(self, name):
        if not callable(getattr(Garmin, name, None)):
            self.missing.append(name)
            raise AttributeError(name)
        return lambda *args, **kwargs: {}


async def test_client_only_calls_methods_the_library_has():
    surface = _RealSurface()
    client = GarminClient(Config(database_url="", redis_url=""))
    client._garmin = surface
    day = date(2026, 10, 1)

    await client.fetch_daily(day)
    await client.fetch_summary(day)
    await client.fetch_activities(day, day)
    await client.fetch_activity_details(12345)
    await client.fetch_daily_weigh_ins(day)
    await client.add_weigh_in(80.0, datetime(2026, 10, 1, 8, 0))
    await client.delete_weigh_in("1", day)

    assert surface.missing == []
