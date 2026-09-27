"""Dashboard modularity — which optional domains are visible.

Single source of truth for the **module registry** (Core vs Optional) and a
fail-safe service to read/write the enabled set.

Storage: one ``app_settings`` row, ``key='enabled_modules'``, ``value`` a JSON
object ``{"hevy": true, ...}``. Redis (``settings:enabled_modules``) is a
read-through cache; the DB is the source of truth.

Manifest — **Zero Silent Errors**: every fallback path is *logged*, never
swallowed. ``get_enabled_modules`` NEVER raises: on a broken/empty/corrupt config
it returns the safe default (Core → True, Optional → False) so the UI degrades to
"core only" instead of 500-ing.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.models.app_settings import AppSetting

logger = logging.getLogger(__name__)

SETTINGS_KEY = "enabled_modules"          # app_settings.key
REDIS_KEY = "settings:enabled_modules"    # cache key
REDIS_TTL = 300                           # seconds


class ModuleToggleError(ValueError):
    """Raised when a caller tries to toggle a non-existent or Core (locked)
    module. The router maps this to HTTP 400."""


@dataclass(frozen=True)
class ModuleSpec:
    key: str
    category: str       # "core" | "optional"
    route: str          # URL prefix / nav href
    rubric: str = ""    # one of NAV_RUBRICS; "" = not in nav
    eyebrow: str = ""   # overrides the rubric's masthead eyebrow for one section
    # No label here on purpose: every surface renders ``t("nav." + key)``, so a
    # label field would be a second, silently-stale copy of the i18n string.


# Rubric order = the order the sidebar rail renders its groups, and the number
# in the masthead eyebrow ("SECTION 02 · Markers"). Label key: ``masthead.rubric.<id>``.
NAV_RUBRICS: tuple[str, ...] = ("health", "markers", "lifestyle", "journal")

# Ordered registry — the ONE source of truth for navigation. ``key`` == route
# name == nav anchor == i18n suffix. Order within a rubric = render order, so
# entries are grouped by rubric rather than by core/optional (the settings card
# filters on ``category`` and doesn't care).
MODULE_REGISTRY: dict[str, ModuleSpec] = {
    m.key: m
    for m in (
        # ── Health ───────────────────────────────────────────────────────────
        ModuleSpec("weight", "core", "/weight", "health"),
        ModuleSpec("garmin", "core", "/garmin", "health"),
        ModuleSpec("hevy", "optional", "/hevy", "health"),
        ModuleSpec("nutrition", "optional", "/nutrition", "health"),
        # ── Markers ──────────────────────────────────────────────────────────
        # The bottom bar has no Markers slot (see BOTTOM_SLOT_CANDIDATES) — on a
        # phone these four live on the "More" screen.
        ModuleSpec("glp1", "optional", "/glp1", "markers"),
        ModuleSpec("hrt", "optional", "/hrt", "markers"),
        ModuleSpec("labs", "core", "/labs", "markers"),
        ModuleSpec("genetics", "optional", "/genetics", "markers"),
        # ── Lifestyle ────────────────────────────────────────────────────────
        ModuleSpec("supplements", "optional", "/supplements", "lifestyle"),
        ModuleSpec("skincare", "optional", "/skincare", "lifestyle"),
        ModuleSpec("interactions", "optional", "/interactions", "lifestyle"),
        # Signals — the free-text capture domain *and* the master switch for the
        # whole proactive layer: off means the Telegram bot says nothing at all
        # (enforced in proactive/delivery.py). Optional, so it defaults to off.
        ModuleSpec("signals", "optional", "/signals", "lifestyle"),
        # Body composition (InBody / МедАсс) — a tab inside /weight, not its own
        # nav item; the toggle just shows/hides that tab and its routes. No
        # rubric: it never appears in navigation.
        ModuleSpec("body_comp", "optional", "/weight"),
        # ── Journal ──────────────────────────────────────────────────────────
        # Views over every other domain rather than a domain of their own. No
        # bottom-bar slot (absent from BOTTOM_SLOT_CANDIDATES), so on a phone
        # they live on the "More" screen.
        ModuleSpec("timeline", "optional", "/timeline", "journal"),
        ModuleSpec("reports", "core", "/reports", "journal", eyebrow="digest"),
        ModuleSpec("charts", "core", "/charts", "journal"),
    )
}


def nav_modules(
    enabled: Optional[dict[str, bool]] = None,
    *,
    rubric: Optional[str] = None,
) -> list[ModuleSpec]:
    """Navigation entries visible for ``enabled``, in registry order.

    Core modules are always visible; Optional ones only when their key is on.
    ``rubric`` narrows the result to one rail group. Registered as a Jinja global
    so the rail, the tab bar and the mobile nav all read this one list.
    """
    em = enabled or {}
    return [
        s
        for s in MODULE_REGISTRY.values()
        if s.rubric
        and (s.category == "core" or em.get(s.key))
        and (rubric is None or s.rubric == rubric)
    ]


# ── Phone bottom bar ─────────────────────────────────────────────────────────
# Five columns, always — the old bar sized its grid from the number of enabled
# modules, so icons drifted and labels clipped whenever a toggle moved. "Today"
# and "More" are fixed ends; the three middle slots are drawn from the candidate
# list below, first three with visible content win. A slot is either a whole
# rubric (tapping it opens the rubric's first section, the masthead chips switch
# within it) or one module that earns its own column.
#
# Markers is last on purpose: it is the least-often-opened rubric, so with
# everything on it falls through to the "More" screen — which is exactly the
# section list frame 3d shows. Journal is not a candidate at all: it always
# lives on "More".
BOTTOM_SLOT_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("health", "rubric"),
    ("nutrition", "module"),
    ("lifestyle", "rubric"),
    ("markers", "rubric"),
)
BOTTOM_SLOT_COUNT = 3


@dataclass(frozen=True)
class NavSlot:
    """One middle column of the phone bottom bar."""

    key: str                    # slot id — also the icon/label lookup key
    label_key: str              # i18n key for the caption
    icon: str                   # ``mh_icon`` key (the slot's first section)
    route: str                  # tap target
    routes: tuple[str, ...]     # path prefixes that light this slot up


def bottom_slots(enabled: Optional[dict[str, bool]] = None) -> list[NavSlot]:
    """The three middle slots of the phone bottom bar, always exactly three
    (unless the registry itself has nothing left to show)."""
    em = enabled or {}
    # A module with its own column also sits inside a rubric (nutrition is in
    # Health), so its route must not light up both slots — the narrower one wins.
    own_column = {
        MODULE_REGISTRY[k].route for k, kind in BOTTOM_SLOT_CANDIDATES if kind == "module"
    }
    out: list[NavSlot] = []
    for key, kind in BOTTOM_SLOT_CANDIDATES:
        if len(out) == BOTTOM_SLOT_COUNT:
            break
        if kind == "rubric":
            members = nav_modules(em, rubric=key)
            if not members:
                continue
            routes = tuple(m.route for m in members if m.route not in own_column)
            out.append(
                NavSlot(
                    key=key,
                    label_key=f"nav.tab.{key}",
                    icon=members[0].key,
                    route=members[0].route,
                    routes=routes or tuple(m.route for m in members),
                )
            )
        else:
            spec = MODULE_REGISTRY[key]
            if spec.category != "core" and not em.get(key):
                continue
            out.append(
                NavSlot(
                    key=key,
                    label_key=f"nav.{key}",
                    icon=key,
                    route=spec.route,
                    routes=(spec.route,),
                )
            )
    return out


def more_rubrics(enabled: Optional[dict[str, bool]] = None) -> list[str]:
    """Rubrics that did NOT get a bottom-bar slot — the section list on /more.

    Derived, not a second hand-kept list: whatever the bar cannot fit is exactly
    what the "More" screen has to carry, so a module can never fall out of both.
    """
    taken = {s.key for s in bottom_slots(enabled)}
    return [
        r for r in NAV_RUBRICS if r not in taken and nav_modules(enabled, rubric=r)
    ]


def more_routes(enabled: Optional[dict[str, bool]] = None) -> tuple[str, ...]:
    """Path prefixes that light up the bottom bar's "More" cell.

    Not just ``/more``: every section reachable only through that screen is
    "inside" it as far as the bar is concerned, so standing on Labs must not
    leave all five cells dark. The account rows (/share, /settings) count too.
    """
    return ("/more", "/share", "/settings") + tuple(
        s.route for r in more_rubrics(enabled) for s in nav_modules(enabled, rubric=r)
    )


CORE_KEYS: frozenset[str] = frozenset(
    k for k, s in MODULE_REGISTRY.items() if s.category == "core"
)
OPTIONAL_KEYS: frozenset[str] = frozenset(
    k for k, s in MODULE_REGISTRY.items() if s.category == "optional"
)

# Safe fallback set: Core on, Optional off. Used ONLY when config is missing or
# unreadable — not what the migration seeds (it seeds optional ON).
DEFAULT_STATE: dict[str, bool] = {
    **{k: True for k in CORE_KEYS},
    **{k: False for k in OPTIONAL_KEYS},
}


def _sanitize(raw: Any) -> dict[str, bool]:
    """Project arbitrary stored data onto the registry.

    Core keys are forced True; Optional keys take ``bool(raw[key])`` when present
    else their default (False); unknown keys are dropped. Resilient to schema
    drift and to a non-dict ``raw`` (returns clean defaults).
    """
    state = dict(DEFAULT_STATE)
    if isinstance(raw, dict):
        for key in OPTIONAL_KEYS:
            if key in raw:
                state[key] = bool(raw[key])
    for key in CORE_KEYS:
        state[key] = True
    return state


async def get_enabled_modules(
    session: AsyncSession, redis: Optional[Redis] = None
) -> dict[str, bool]:
    """Resolve the enabled-module map. Never raises — falls back to safe defaults.

    Order: Redis cache → DB (``app_settings``) → ``DEFAULT_STATE``.
    """
    # 1) Redis read-through cache.
    if redis is not None:
        try:
            cached = await redis.get(REDIS_KEY)
            if cached:
                return _sanitize(json.loads(cached))
        except Exception:
            logger.warning(
                "modules: Redis read failed; falling through to DB", exc_info=True
            )

    # 2) Database (source of truth).
    try:
        row = await session.get(AppSetting, SETTINGS_KEY)
        if row is not None:
            if isinstance(row.value, dict):
                state = _sanitize(row.value)
                await prime_cache(redis, state)
                return state
            logger.warning(
                "modules: app_settings[%s] is not an object (%s); using defaults",
                SETTINGS_KEY,
                type(row.value).__name__,
            )
            return dict(DEFAULT_STATE)
        # Empty config is normal on a fresh DB — debug, not a warning.
        logger.debug("modules: no app_settings row; using defaults")
    except Exception:
        logger.warning(
            "modules: DB read failed; using safe defaults", exc_info=True
        )

    # 3) Safe fallback.
    return dict(DEFAULT_STATE)


async def set_module_enabled(
    session: AsyncSession, *, key: str, enabled: bool
) -> dict[str, bool]:
    """Toggle an Optional module. Flushes (caller commits). Returns the new state.

    Raises ``ModuleToggleError`` for unknown keys or Core (locked) modules.
    """
    if key not in MODULE_REGISTRY:
        raise ModuleToggleError(f"unknown module '{key}'")
    if key in CORE_KEYS:
        raise ModuleToggleError(f"module '{key}' is core and cannot be disabled")

    # Lock the settings row FOR UPDATE so concurrent toggles serialize on it.
    # This is a read-modify-write (read the JSON map, flip one key, write it back);
    # without the row lock two near-simultaneous toggles both read the old map and
    # the second write silently drops the first one's change (lost update). On
    # SQLite (fast test path) with_for_update is a no-op, but there is no real
    # concurrency there; the guarantee that matters is on Postgres in prod.
    row = (
        await session.execute(
            select(AppSetting)
            .where(AppSetting.key == SETTINGS_KEY)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        state = dict(DEFAULT_STATE)
        state[key] = bool(enabled)
        session.add(AppSetting(key=SETTINGS_KEY, value=state))
    else:
        current = row.value if isinstance(row.value, dict) else {}
        # Reassign a NEW dict so SQLAlchemy detects the change (column is plain
        # JSON/JSONB, not a MutableDict).
        row.value = {**_sanitize(current), key: bool(enabled)}

    await session.flush()
    new_state = await session.get(AppSetting, SETTINGS_KEY)
    return _sanitize(new_state.value if new_state else None)


async def prime_cache(redis: Optional[Redis], state: dict[str, bool]) -> None:
    """Write-through the resolved state into Redis. Best-effort (logged on fail)."""
    if redis is None:
        return
    try:
        await redis.set(REDIS_KEY, json.dumps(_sanitize(state)), ex=REDIS_TTL)
    except Exception:
        logger.warning("modules: Redis prime failed", exc_info=True)
