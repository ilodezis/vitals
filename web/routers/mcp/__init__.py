"""Model Context Protocol (MCP) server integration for Vitals.

Exposes the app to Claude: everything the owner can do on a screen of the app,
Claude can do from a conversation, through the same services and the same
conflict checks. Deliberately absent: credentials, password/2FA, backup import
and the container restart — a conversation must not be able to lock the owner
out or overwrite the lake.

The surface is kept small on purpose: every tool schema is re-sent with every
message of every conversation, so related actions share one tool with an
``entry`` / ``view`` / ``action`` / ``section`` argument instead of a tool each.
Reads and writes stay separate tools so their behaviour hints
(``ToolAnnotations``) are exact.

Layout: ``_core`` holds the ``FastMCP`` instance and shared plumbing; one module
per domain holds that domain's handlers and the tools registered over them;
``settings`` holds the cross-domain settings tools; ``resources`` the resources
and the prompt; ``server`` the visibility middleware, bearer auth and
``get_mcp_app``.

Response conventions (a stable contract the model can rely on):
  * Success — the tool's normal payload (a dict, or a list of dicts).
  * A recoverable problem (bad id, unknown key, missing dependency) — a dict
    ``{"error": "<human message>"}`` (list-returning reads wrap it: ``[{"error": ...}]``).
  * A hard conflict block on a write — ``{"blocked": true, "violations": [...],
    "message": ..., "hint": ...}``; retry the same call with ``override=True``.
  * A delete — ``{"deleted": <bool>, "domain": <str>, "record_id": <id>}``.
  * A write to a switched-off optional domain — ``{"error": "module '<key>' is
    disabled"}``.

Every handler (the former one-tool-per-action functions) stays importable from
this package under its old name, so services and tests can call it directly.
"""
from __future__ import annotations

from web.routers.mcp import (  # noqa: F401  (import order = registration order)
    _core,
    profile,
    weight,
    glp1,
    activity,
    nutrition,
    hrt,
    supplements,
    skincare,
    body_comp,
    labs,
    photos,
    records,
    alerts,
    signals,
    environment,
    sharing,
    overview,
    settings,
    resources,
    server,
)

_MODULES = (
    _core, profile, weight, glp1, activity, nutrition, hrt, supplements, skincare,
    body_comp, labs, photos, records, alerts, signals, environment, sharing, overview,
    settings, resources, server,
)

# Re-export every handler, helper and constant under the package, as the single
# ``mcp.py`` module exposed them. Objects defined in a module win over names it
# merely imported.
_PATCH_POINTS = {"get_session_factory", "get_redis_client"}
for _module in _MODULES:
    for _name, _obj in vars(_module).items():
        if _name.startswith("__") or _name in _PATCH_POINTS:
            continue
        if getattr(_obj, "__module__", None) == _module.__name__ or _name not in globals():
            globals()[_name] = _obj
del _module, _name, _obj

# The real dependency getters, last: tests patch these on the package, and the
# domain modules resolve them through ``_core`` at call time.
from web.deps import get_redis_client, get_session_factory  # noqa: E402,F401
