"""Settings panel: read and persist VITALS_* configuration via the web UI.

GET  /settings          — render the settings page (prefilled from .env)
POST /settings/profile  — save profile block (height, sex, age, timezone, program, goals)
POST /settings/ai       — save AI / OpenRouter block (api key, model slugs)
POST /settings/hevy     — save Hevy API key
POST /settings/garmin   — save Garmin credentials (email + password)
POST /settings/password — change the login password (requires old password)

All writes go to the .env file via ``web.services.env_writer``.  The app
shows a banner asking the user to restart the container so the new values
are picked up by ``load_config()`` / ``get_web_config()``.

Sensitive inputs (API keys, passwords) are always shown masked in the form.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.i18n import t
from vitals.services import data_portability_service, language_service, modules_service
from vitals.services.modules_service import MODULE_REGISTRY, ModuleToggleError
from vitals.utils.timeutils import today_local
from web.deps import get_redis, get_session, require_auth
from web.ratelimit import rate_limit
from web.services.env_writer import read_key, write_keys
from web.templating import templates
from web.uploads import JSON_EXTS, VCF_MAX_BYTES, read_capped, validate_extension

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])

# Keys that are shown partially-masked in the UI (never echoed as plaintext).
_SECRET_KEYS = {
    "VITALS_OPENROUTER_API_KEY",
    "VITALS_HEVY_API_KEY",
    "VITALS_GARMIN_PASSWORD",
    "VITALS_AUTH_PASSWORD_HASH",
    "VITALS_MCP_CLIENT_SECRET",
}

_SENTINEL = "••••••••"  # what we show in place of a real secret


def _masked(key: str) -> str:
    """Return a masked placeholder when the key has a value, else empty."""
    return _SENTINEL if read_key(key) else ""


def _is_sentinel(value: str) -> bool:
    return value.strip() == _SENTINEL


# ── Helpers ───────────────────────────────────────────────────────────────────


def _redirect(suffix: str = "") -> RedirectResponse:
    url = f"/settings{suffix}"
    return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)


def _page(request: Request, username: str, *, saved: Optional[str] = None, error: Optional[str] = None) -> HTMLResponse:
    """Build the template context and render settings.html."""
    ctx = {
        "username": username,
        "saved": saved,
        "error": error,
        # Profile
        "height_cm": read_key("VITALS_HEIGHT_CM") or "190",
        "sex": read_key("VITALS_SEX") or "male",
        "user_age": read_key("VITALS_USER_AGE") or "18",
        "timezone": read_key("VITALS_TIMEZONE") or "Europe/Chisinau",
        "user_program": read_key("VITALS_USER_PROGRAM"),
        "user_goals": read_key("VITALS_USER_GOALS"),
        # AI
        "openrouter_api_key_set": bool(read_key("VITALS_OPENROUTER_API_KEY")),
        "openrouter_base_url": read_key("VITALS_OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1",
        "llm_model_digest": read_key("VITALS_LLM_MODEL_DIGEST") or "anthropic/claude-sonnet-4.6",
        "llm_model_parser": read_key("VITALS_LLM_MODEL_PARSER") or "google/gemini-2.5-flash",
        # Hevy
        "hevy_api_key_set": bool(read_key("VITALS_HEVY_API_KEY")),
        # Garmin
        "garmin_email": read_key("VITALS_GARMIN_EMAIL"),
        "garmin_password_set": bool(read_key("VITALS_GARMIN_PASSWORD")),
        # MCP
        "mcp_client_id": read_key("VITALS_MCP_CLIENT_ID") or "vitals-claude-connector",
        "mcp_client_secret_set": bool(read_key("VITALS_MCP_CLIENT_SECRET")),
        # Dashboard modules — registry + current state (set on request.state by
        # the global load_enabled_modules dependency).
        # Nutrition goals
        "nutrition_protein_target_g": read_key("VITALS_NUTRITION_PROTEIN_TARGET_G") or "150",
        "nutrition_calories_min": read_key("VITALS_NUTRITION_CALORIES_MIN") or "1300",
        "nutrition_calories_max": read_key("VITALS_NUTRITION_CALORIES_MAX") or "1700",
        # Dashboard modules
        "module_registry": MODULE_REGISTRY,
        "enabled_modules": getattr(request.state, "enabled_modules", {}) or {},
    }
    return templates.TemplateResponse(request, "settings/settings.html", ctx)


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    username: str = Depends(require_auth),
    saved: Optional[str] = None,
    error: Optional[str] = None,
):
    return _page(request, username, saved=saved, error=error)


@router.post("/profile")
async def save_profile(
    request: Request,
    username: str = Depends(require_auth),
    height_cm: str = Form("190"),
    sex: str = Form("male"),
    user_age: str = Form("18"),
    timezone: str = Form("Europe/Chisinau"),
    user_program: str = Form(""),
    user_goals: str = Form(""),
    nutrition_protein_target_g: str = Form(""),
    nutrition_calories_min: str = Form(""),
    nutrition_calories_max: str = Form(""),
):
    updates: dict[str, str] = {}
    if height_cm.strip():
        updates["VITALS_HEIGHT_CM"] = height_cm.strip()
    if sex in ("male", "female"):
        updates["VITALS_SEX"] = sex
    if user_age.strip().isdigit():
        updates["VITALS_USER_AGE"] = user_age.strip()
    if timezone.strip():
        updates["VITALS_TIMEZONE"] = timezone.strip()
    if user_program.strip():
        # Collapse newlines: this textarea is free text, but env_writer rejects
        # \n/\r in values (an unescaped newline would break out of its KEY=value
        # line in the .env file).
        updates["VITALS_USER_PROGRAM"] = " ".join(user_program.split())
    if user_goals.strip():
        updates["VITALS_USER_GOALS"] = user_goals.strip()
    if nutrition_protein_target_g.strip():
        updates["VITALS_NUTRITION_PROTEIN_TARGET_G"] = nutrition_protein_target_g.strip()
    if nutrition_calories_min.strip():
        updates["VITALS_NUTRITION_CALORIES_MIN"] = nutrition_calories_min.strip()
    if nutrition_calories_max.strip():
        updates["VITALS_NUTRITION_CALORIES_MAX"] = nutrition_calories_max.strip()

    if updates:
        write_keys(updates)
    return _redirect("?saved=profile")


@router.post("/ai")
async def save_ai(
    request: Request,
    username: str = Depends(require_auth),
    openrouter_api_key: str = Form(""),
    openrouter_base_url: str = Form(""),
    llm_model_digest: str = Form(""),
    llm_model_parser: str = Form(""),
):
    updates: dict[str, str] = {}
    # Only overwrite the API key if user typed a real value (not the sentinel).
    if openrouter_api_key.strip() and not _is_sentinel(openrouter_api_key):
        updates["VITALS_OPENROUTER_API_KEY"] = openrouter_api_key.strip()
    if openrouter_base_url.strip():
        updates["VITALS_OPENROUTER_BASE_URL"] = openrouter_base_url.strip()
    if llm_model_digest.strip():
        updates["VITALS_LLM_MODEL_DIGEST"] = llm_model_digest.strip()
    if llm_model_parser.strip():
        updates["VITALS_LLM_MODEL_PARSER"] = llm_model_parser.strip()

    if updates:
        write_keys(updates)
    return _redirect("?saved=ai")


@router.post("/hevy")
async def save_hevy(
    request: Request,
    username: str = Depends(require_auth),
    hevy_api_key: str = Form(""),
):
    updates: dict[str, str] = {}
    if hevy_api_key.strip() and not _is_sentinel(hevy_api_key):
        updates["VITALS_HEVY_API_KEY"] = hevy_api_key.strip()

    if updates:
        write_keys(updates)
    return _redirect("?saved=hevy")


@router.post("/garmin")
async def save_garmin(
    request: Request,
    username: str = Depends(require_auth),
    garmin_email: str = Form(""),
    garmin_password: str = Form(""),
):
    updates: dict[str, str] = {}
    if garmin_email.strip():
        updates["VITALS_GARMIN_EMAIL"] = garmin_email.strip()
    if garmin_password.strip() and not _is_sentinel(garmin_password):
        updates["VITALS_GARMIN_PASSWORD"] = garmin_password.strip()

    if updates:
        write_keys(updates)
    return _redirect("?saved=garmin")


@router.post("/mcp")
async def save_mcp(
    request: Request,
    username: str = Depends(require_auth),
    mcp_client_id: str = Form("vitals-claude-connector"),
    mcp_client_secret: str = Form(""),
):
    updates: dict[str, str] = {}
    if mcp_client_id.strip():
        updates["VITALS_MCP_CLIENT_ID"] = mcp_client_id.strip()
    if mcp_client_secret.strip() and not _is_sentinel(mcp_client_secret):
        updates["VITALS_MCP_CLIENT_SECRET"] = mcp_client_secret.strip()

    if updates:
        write_keys(updates)
        # Apply to current process environment to support immediate refresh
        import os
        for k, v in updates.items():
            os.environ[k] = v
    return _redirect("?saved=mcp")



@router.post("/modules")
async def toggle_module(
    request: Request,
    module: str = Form(...),
    enabled: bool = Form(...),
    username: str = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    _rl: None = Depends(rate_limit("settings_modules", limit=30, window=60)),
):
    """Enable/disable an Optional dashboard module, on the fly.

    Persists to ``app_settings`` (source of truth), write-through to Redis, then
    returns an OOB fragment that re-renders the header nav so it updates live —
    no page reload.
    """
    try:
        state = await modules_service.set_module_enabled(db, key=module, enabled=enabled)
    except ModuleToggleError as e:
        # Core/unknown module — reject loudly (Zero Silent Errors).
        return JSONResponse({"error": str(e)}, status_code=status.HTTP_400_BAD_REQUEST)

    await db.commit()
    await modules_service.prime_cache(redis, state)
    # Reflect the new state for the OOB nav render in *this* response.
    request.state.enabled_modules = state
    return templates.TemplateResponse(
        request,
        "partials/modules_oob.html",
        {"username": username, "enabled_modules": state},
    )


@router.post("/language")
async def save_language(
    request: Request,
    language: str = Form(...),
    username: str = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
):
    lang = await language_service.set_language(db, language, redis)
    await db.commit()
    return RedirectResponse(
        url="/settings?saved=language",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/password")
async def change_password(
    request: Request,
    username: str = Depends(require_auth),
    old_password: str = Form(""),
    new_password: str = Form(""),
    new_password_confirm: str = Form(""),
):
    from web.auth import authenticate, clear_session_cookie, create_session, set_session_cookie
    from web.config import get_web_config
    from web.security import hash_password

    cfg = get_web_config()

    if not authenticate(cfg.auth_username, old_password):
        return _page(request, username, error="wrong_password")

    if not new_password or len(new_password) < 8:
        return _page(request, username, error="password_too_short")

    if new_password != new_password_confirm:
        return _page(request, username, error="password_mismatch")

    hashed = hash_password(new_password)
    write_keys({"VITALS_AUTH_PASSWORD_HASH": hashed})
    # Apply live: get_web_config() reads the env at call time, so updating the
    # process env makes the new password work immediately and invalidates the old
    # one without waiting for a container restart (unlike the other settings,
    # which are cached/loaded at startup — that's fine for them, not for a secret).
    import os

    os.environ["VITALS_AUTH_PASSWORD_HASH"] = hashed

    # Re-issue session so the user isn't kicked out by the cookie change.
    token = create_session(cfg.auth_username)
    response = _redirect("?saved=password")
    set_session_cookie(response, token)
    return response


# ── Data portability (backup / restore / LLM export) ──────────────────────────


@router.get("/export")
async def export_backup(
    username: str = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
    _rl: None = Depends(rate_limit("data_export", limit=2, window=60)),
):
    """Download a full machine-readable backup of every table (one JSON file)."""
    snapshot = await data_portability_service.export_full(db)
    body = json.dumps(snapshot, ensure_ascii=False, indent=2, default=str)
    filename = f"vitals_backup_{today_local().strftime('%Y%m%d')}.json"
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export-llm")
async def export_llm(
    username: str = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
    _rl: None = Depends(rate_limit("data_export", limit=2, window=60)),
):
    """Download a curated, flat, secret-free digest for pasting into an LLM chat."""
    snapshot = await data_portability_service.export_llm(db)
    body = json.dumps(snapshot, ensure_ascii=False, indent=2, default=str)
    filename = f"vitals_llm_{today_local().strftime('%Y%m%d')}.json"
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import")
async def import_backup(
    request: Request,
    username: str = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
    backup_file: UploadFile = File(...),
    _rl: None = Depends(rate_limit("data_import", limit=2, window=60)),
):
    """Restore (replace) the whole DB from an uploaded full-backup JSON file.

    Atomic: the import runs in this request's transaction, so a malformed file
    rolls everything back. Validation failures return a clean 400 (no silent
    errors); success returns an OOB fragment with the per-domain stats.
    """
    validate_extension(backup_file.filename, JSON_EXTS)
    # Backups can be large (the raw_payloads data-lake), so allow the bigger cap.
    raw = await read_capped(backup_file, max_bytes=VCF_MAX_BYTES)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=t("import.error.bad_json", msg=exc.msg, line=exc.lineno),
        )

    try:
        stats = await data_portability_service.import_full(db, payload)
    except data_portability_service.PortabilityError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    await db.commit()
    return templates.TemplateResponse(
        request,
        "settings/import_result.html",
        {"summary": stats.summary()},
    )


@router.post("/restart")
async def restart_container(
    request: Request,
    username: str = Depends(require_auth),
):
    import os
    import signal
    import asyncio
    from fastapi.responses import JSONResponse

    logger.info("User %s requested container restart. Terminating process in 500ms...", username)

    async def shutdown():
        await asyncio.sleep(0.5)
        os.kill(os.getpid(), signal.SIGTERM)

    asyncio.create_task(shutdown())
    return JSONResponse(content={"status": "restarting"})

