"""Process-wide overlay for settings that change at runtime without a restart.

Some ``VITALS_*`` values (the owner's profile, nutrition goals) are edited from
the Settings screen or the MCP tools and stored in the database
(``vitals.services.profile_store``). The process reads its environment once at
start, so those saves would otherwise only reach the computations after a
container restart. This module holds the saved values in memory and every
reader goes through :func:`env`: overlay first, then the process environment,
then the caller's default.

Stdlib only and no ``vitals`` imports: ``vitals.config`` and
``vitals.utils.timeutils`` import it, so it must sit below both. An in-process
cache is correct because the app runs a single uvicorn worker; the database row
stays the source of truth and :func:`replace` reloads it at startup.
"""
from __future__ import annotations

import os
import threading
from typing import Mapping, Optional

_LOCK = threading.Lock()
_overlay: dict[str, str] = {}


def get(key: str) -> Optional[str]:
    """The overlay value for ``key``, or ``None`` when nothing was saved."""
    return _overlay.get(key)


def env(key: str, default: Optional[str] = None) -> Optional[str]:
    """Overlay value, else ``os.getenv(key)``, else ``default``."""
    value = _overlay.get(key)
    if value is not None:
        return value
    return os.getenv(key, default)


def snapshot() -> dict[str, str]:
    """A copy of the whole overlay."""
    with _LOCK:
        return dict(_overlay)


def replace(values: Mapping[str, str]) -> None:
    """Swap the whole overlay for ``values`` (startup load, tests)."""
    global _overlay
    fresh = {str(k): str(v) for k, v in values.items()}
    with _LOCK:
        _overlay = fresh


def update(values: Mapping[str, str]) -> None:
    """Merge ``values`` into the overlay (a save)."""
    with _LOCK:
        _overlay.update({str(k): str(v) for k, v in values.items()})


def discard(key: str) -> None:
    """Drop one key so the environment applies again."""
    with _LOCK:
        _overlay.pop(key, None)


def clear() -> None:
    """Empty the overlay (test isolation)."""
    with _LOCK:
        _overlay.clear()
