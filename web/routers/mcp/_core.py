"""Shared plumbing of the MCP server: the ``FastMCP`` instance, the tool
registration helper with its annotations, row serialization, argument parsing,
module gating and action routing for the consolidated tools.

Every domain module imports from here; nothing here imports a domain module.
"""
from __future__ import annotations

import functools
import inspect
import logging
import sys
from datetime import date as date_type, datetime
from typing import Optional

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from vitals.services.conflict_engine import ConflictBlocked
from vitals.utils.timeutils import format_iso

logger = logging.getLogger("web.routers.mcp")

INSTRUCTIONS = """\
Vitals is one person's health data lake: weight and body composition, GLP-1 and \
HRT protocols, supplements, skincare, Garmin recovery and activity, Hevy workouts, \
labs, genetics, nutrition, the bedroom air station, signals about how days felt. \
It is decision support for its owner, not a clinician: be concrete, non-alarmist, \
and never present a reading as a diagnosis.

Orientation: get_today for the current state, export_data(mode="overview") for \
what data exists, get_full_snapshot for a multi-domain review of a period, \
get_trend instead of pulling raw rows when the question is a direction or a rate.

Conventions:
- Dates are YYYY-MM-DD, times HH:MM, in the owner's timezone (get_settings).
- Reads are capped (usually 100 rows, newest first); narrow by date range.
- A recoverable problem returns {"error": "..."}; fix the call, don't retry blindly.
- A write blocked by a hard conflict rule returns {"blocked": true, "violations": \
[...]}. Explain the violations; retry with override=true only when the owner \
explicitly says to save anyway.
- save_* tools create a record when no id is passed and edit one when it is; an \
edit changes only the fields you pass. Ids come from the matching get_* tool.
- delete_record, manage_alerts(action="resolve_all") and create_report(kind="shared") \
are two-step: the first call previews, repeat with confirm=true after the owner agrees.
- Optional domains the owner switched off are hidden from the tool list and \
refuse writes; get_settings(section="modules") shows them, \
update_settings(section="modules") switches them (only when asked).
"""

mcp = FastMCP("Vitals", instructions=INSTRUCTIONS)

# Set by ``get_mcp_app``: the FastAPI app the server is mounted on, for the tools
# that act on it (re-timing the scheduler after a settings change).
_HOST_APP = None


def _pkg():
    """The ``web.routers.mcp`` package, looked up at call time.

    Tests patch ``web.routers.mcp.get_session_factory`` (and a few other names) on
    the package; the domain modules read them through here so a patch reaches
    every module instead of only the one it was applied to."""
    return sys.modules[__name__.rpartition(".")[0]]


def get_session_factory():
    return _pkg().get_session_factory()


def get_redis_client():
    return _pkg().get_redis_client()


# ── Registration ─────────────────────────────────────────────────────────────

# tool name → the optional module it belongs to. Used only to hide a switched-off
# module's tools from ``tools/list``: their schemas are re-sent with every message
# of every conversation, so a domain the owner does not track is pure weight. Reads
# stay callable if invoked directly — hiding is a budget decision, the write gate
# (``gated``) is the permission one. Tools that span several modules (delete,
# settings, photos) are not listed here; they gate per action instead.
TOOL_MODULES: dict[str, str] = {}

READ = "read"
WRITE = "write"


def tool(
    kind: str,
    *,
    module: Optional[str] = None,
    destructive: bool = False,
    idempotent: Optional[bool] = None,
    open_world: bool = False,
):
    """Register ``fn`` as an MCP tool with accurate behaviour hints.

    ``kind`` is ``READ`` (no side effects; idempotent by definition) or ``WRITE``.
    ``destructive`` marks tools that can delete or irreversibly revoke data;
    ``open_world`` marks tools that reach outside Vitals (Garmin, Hevy, the LLM,
    a public report link). ``module`` puts the tool in ``TOOL_MODULES``.
    """
    read_only = kind == READ

    def decorator(fn):
        if module is not None:
            TOOL_MODULES[fn.__name__] = module
        mcp.tool(
            annotations=ToolAnnotations(
                readOnlyHint=read_only,
                destructiveHint=False if read_only else destructive,
                idempotentHint=True if read_only else bool(idempotent),
                openWorldHint=open_world,
            )
        )(fn)
        return fn

    return decorator


async def route(handler, label: str, args: dict, *, rename: Optional[dict] = None):
    """Call ``handler`` with the consolidated tool's arguments that it takes.

    A consolidated tool carries the union of its actions' parameters, every one
    defaulting to ``None``. Only the non-``None`` ones are passed on; one the
    chosen action does not take is an error naming it (silently dropping it would
    save something other than what the model meant), and so is a missing required
    one. ``rename`` maps a tool parameter onto the handler's own name for it
    (``record_id`` → ``meal_id``)."""
    rename = rename or {}
    given = {rename.get(k, k): v for k, v in args.items() if v is not None}
    params = inspect.signature(handler).parameters
    unused = sorted(
        next((k for k, v in rename.items() if v == name), name)
        for name in given
        if name not in params
    )
    if unused:
        return {"error": f"{label} does not take: {', '.join(unused)}"}
    missing = sorted(
        next((k for k, v in rename.items() if v == name), name)
        for name, p in params.items()
        if p.default is inspect.Parameter.empty and name not in given
    )
    if missing:
        return {"error": f"{label} needs: {', '.join(missing)}"}
    return await handler(**given)


def choice_error(param: str, value, options) -> dict:
    return {"error": f"unknown {param} {value!r} — use one of: {', '.join(options)}"}


async def dispatch(
    tool_name: str,
    param: str,
    choice: str,
    table: dict,
    args: dict,
    record_id=None,
):
    """Route a consolidated save/act tool to the handler for ``choice``.

    ``table`` maps ``(choice, editing)`` to ``(handler, id_param)``: ``editing`` is
    whether a ``record_id`` was passed, ``id_param`` the handler's name for that
    id (``None`` when it takes none). One choice can thus create without an id
    and edit with one."""
    choices = list(dict.fromkeys(c for c, _ in table))
    if choice not in choices:
        return choice_error(param, choice, choices)
    label = f"{tool_name}({param}={choice!r})"
    entry = table.get((choice, record_id is not None))
    if entry is None:
        if record_id is None:
            return {"error": f"{label} needs record_id"}
        return {"error": f"{label} does not take record_id"}
    handler, id_param = entry
    if id_param is not None:
        args = {**args, id_param: record_id}
    return await route(handler, label, args)


# Columns every row carries and no tool ever accepts back: bookkeeping the model
# cannot act on. Dropped from serialized rows along with every ``None`` value —
# at a hundred rows per read the key names alone outweigh the data. ``id`` and
# ``date`` stay (edits and deletes address rows by id); ``source`` stays (weight
# priority and provenance are answers in their own right).
_ROW_NOISE = frozenset({"domain", "created_at", "updated_at", "raw_payload_id"})


def serialize_row(row) -> dict:
    """Helper to convert any SQLAlchemy model instance into a JSON-serializable dict.

    Omits bookkeeping columns (``_ROW_NOISE``) and unset fields: an absent key and
    a ``null`` one read the same to the model, and the null costs tokens per row.
    """
    if row is None:
        return {}
    d = {}
    for column in row.__table__.columns:
        if column.name in _ROW_NOISE:
            continue
        val = getattr(row, column.name)
        if val is None:
            continue
        if isinstance(val, datetime):
            d[column.name] = format_iso(val)
        elif hasattr(val, "isoformat"):
            d[column.name] = val.isoformat()
        else:
            d[column.name] = val
    if hasattr(row, "__tablename__"):
        if row.__tablename__ == "meal_logs":
            if hasattr(row, "created_at") and row.created_at:
                d["logged_at"] = format_iso(row.created_at, is_utc=True)
            if "eaten_at" not in d:
                d["eaten_at"] = None
        elif row.__tablename__ == "body_measurements":
            if "body_fat_pct" in d:
                d["body_fat_pct_navy"] = d["body_fat_pct"]
                d["method"] = "navy"
        elif row.__tablename__ == "body_scan_metrics":
            if d.get("metric_key") == "body_fat_pct":
                d["body_fat_pct_bia"] = d.get("value")
                d["method"] = "bia"
        elif row.__tablename__ == "glp1_injections":
            if "site" not in d:
                d["site"] = None
        elif row.__tablename__ == "garmin_activities":
            if "training_effect_aerobic" in d and d["training_effect_aerobic"] is not None:
                d["training_effect_aerobic"] = round(d["training_effect_aerobic"], 1)
            if "training_effect_anaerobic" in d and d["training_effect_anaerobic"] is not None:
                d["training_effect_anaerobic"] = round(d["training_effect_anaerobic"], 1)
            if "hr_zone_seconds" in d and isinstance(d["hr_zone_seconds"], list):
                zones = []
                for z in d["hr_zone_seconds"]:
                    if isinstance(z, dict):
                        z_copy = dict(z)
                        if "secs" in z_copy and isinstance(z_copy["secs"], (int, float)):
                            z_copy["secs"] = round(z_copy["secs"], 1)
                        if z_copy.get("low_hr") is None:
                            z_copy.pop("low_hr", None)
                        zones.append(z_copy)
                    else:
                        zones.append(z)
                d["hr_zone_seconds"] = zones
    return d


async def serialize_written(session, row) -> dict:
    """Serialize a row that was just written. After an UPDATE flush, server-side
    ``onupdate``/``server_default`` columns (e.g. ``updated_at``) are *expired*;
    reading them in the sync ``serialize_row`` would trigger a lazy SELECT outside
    the async greenlet and fail with ``greenlet_spawn has not been called``. An
    explicit ``await session.refresh`` reloads them inside the async context first.
    """
    if row is None:
        return {}
    await session.refresh(row)
    return serialize_row(row)


def _conflict_payload(exc: ConflictBlocked) -> dict:
    """Structured result for a write blocked by a hard conflict rule.

    The HTML UI gets a 409 + violations and renders "Save anyway (Override)".
    A tool call has no HTTP status the model can act on, so we return the same
    violation list as a plain dict instead of letting the exception escape as an
    opaque 500 — the model can inspect the block and retry the call with
    ``override=True`` (the MCP equivalent of the override button)."""
    return {
        "blocked": True,
        "message": str(exc),
        "violations": [v.to_dict() for v in exc.violations],
        "hint": "Retry the same call with override=True to save anyway.",
    }


class ToolValueError(ToolError, ValueError):
    """A ToolError that also inherits from ValueError for backward compatibility."""
    pass


def _parse_date(value: Optional[str], default=None, *, field: str):
    """Parse a ``YYYY-MM-DD`` tool argument, falling back to ``default`` when omitted.

    A model writes dates the way a person says them ("вчера", "01.07.2026"), and
    the stdlib answers with "Invalid isoformat string: ..." — which names neither
    the argument nor the shape expected, so the model can't fix its own call.
    """
    if value is None:
        return default
    try:
        return date_type.fromisoformat(value)
    except (ValueError, TypeError):
        raise ToolValueError(f"{field} must be a YYYY-MM-DD date, got {value!r}") from None


def _parse_time(value: Optional[str], *, field: str):
    """Same as ``_parse_date`` for an ``HH:MM`` argument."""
    from datetime import time as time_type

    if value is None:
        return None
    try:
        return time_type.fromisoformat(value)
    except (ValueError, TypeError):
        raise ToolValueError(f"{field} must be an HH:MM time, got {value!r}") from None


async def _merged(session, model, record_id: int, **fields) -> Optional[dict]:
    """Fill a partial tool edit in from the stored row: a field left ``None`` keeps
    its current value. Keys are column names on ``model``; ``None`` if the row is gone.

    The update services replace every field they are handed, because the web forms
    post the whole form and clearing an input there has to clear the column. A tool
    call carries only what the conversation mentioned, so the same call would blank
    everything the model didn't repeat — a rename would cost the meal its calories.
    """
    row = await session.get(model, record_id)
    if row is None:
        return None
    return {k: (getattr(row, k) if v is None else v) for k, v in fields.items()}


async def _module_enabled(session, key: str) -> bool:
    """True when an optional module is on (write tools honour the toggle)."""
    from vitals.services import modules_service

    state = await modules_service.get_enabled_modules(session)
    return bool(state.get(key))


def gated(module_key: str):
    """Refuse a call when its optional module is switched off.

    Turning a module off in settings is the owner saying "I don't track this" —
    the web routes honour it (``require_module``), and so does every write handler
    of an optional domain, whichever consolidated tool routes to it.
    ``tests/test_mcp_module_gate.py`` holds the full list, so a new handler has to
    be classified rather than quietly ungated."""
    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            session_factory = get_session_factory()
            async with session_factory() as session:
                if not await _module_enabled(session, module_key):
                    return {"error": f"module '{module_key}' is disabled"}
            return await fn(*args, **kwargs)

        wrapper.module_key = module_key
        return wrapper

    return decorator
