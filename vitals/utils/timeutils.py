"""Local-time helpers — the ONLY sanctioned source of "now"/"today".

Ported in spirit from Boxly's ``bot/utils/timeutils``: business logic must read
the wall clock through these helpers, never ``datetime.now()``/``utcnow()``
directly, so a container running in UTC can't skew "today" / date windows.

The timezone comes from ``VITALS_TIMEZONE`` (default Europe/Chisinau) and is
resolved lazily and cached. We return **naive** values (tzinfo stripped) on
purpose so they stay directly comparable with the naive ``Date``/``DateTime``
columns used across the schema. The container also pins ``TZ`` as defence in
depth.

``set_timezone()`` exists for tests (``freezegun`` covers the clock; this covers
the zone) — production reads the env once.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = "Europe/Chisinau"

_tz_name: str | None = None
_tz: ZoneInfo | None = None


def _zone() -> ZoneInfo:
    global _tz_name, _tz
    configured = os.getenv("VITALS_TIMEZONE", DEFAULT_TIMEZONE) or DEFAULT_TIMEZONE
    if _tz is None or configured != _tz_name:
        _tz_name = configured
        _tz = ZoneInfo(configured)
    return _tz


def set_timezone(name: str) -> None:
    """Override the active zone (tests). Clears the cache so the next call to
    :func:`now_local` reflects it."""
    global _tz_name, _tz
    os.environ["VITALS_TIMEZONE"] = name
    _tz_name = None
    _tz = None


def now_local() -> datetime:
    """Current local wall-clock time as a naive datetime."""
    return datetime.now(_zone()).replace(tzinfo=None)


def today_local() -> date:
    """Current local calendar date."""
    return now_local().date()


def to_local_naive(dt: Optional[datetime]) -> Optional[datetime]:
    """Convert a datetime to a **naive local** datetime (matching the schema's
    naive columns). A tz-aware value is converted into the configured zone; a
    naive value is assumed to already be UTC (how Garmin/Hevy timestamps arrive).
    ``None`` passes through."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_zone()).replace(tzinfo=None)
