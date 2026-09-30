"""Settings API router under ``/api/v1/settings``.

All reads and writes for configuration, credentials, integrations, modules,
proactive schedules, and data portability.

CRITICAL SECURITY RULE:
Secrets (API keys, passwords, client secrets) MUST NEVER be returned in GET
responses or mutation returns.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from typing import Any, Optional

from fastapi import Depends, File, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.i18n import t
from vitals.integrations.garmin_client import login_breaker_state
from vitals.services import (
    data_portability_service,
    garmin_weight_service,
    language_service,
    modules_service,
    twofa_service,
)
from vitals.services.modules_service import ModuleToggleError
from vitals.services.proactive import day_plan, prefs
from vitals.utils.passwords import hash_password
from vitals.utils.timeutils import today_local
from web.api.errors import ApiRouter
from web.api.schemas.settings import (
    AiSettings,
    AiUpdate,
    GarminSettings,
    GarminUpdate,
    GarminWeightToggleUpdate,
    HevySettings,
    HevyUpdate,
    ImportResult,
    LanguageSettings,
    LanguageUpdate,
    McpSettings,
    McpUpdate,
    ModuleInfo,
    ModulesSettings,
    ModuleToggleUpdate,
    NutritionGoalsSettings,
    NutritionGoalsUpdate,
    PasswordChangeUpdate,
    ProfileSettings,
    ProfileUpdate,
    ProactiveSettings,
    ProactiveUpdate,
    SaveResponse,
    SecuritySettings,
    SettingsView,
    StatusResponse,
    TwoFaCodeUpdate,
    TwoFaStartResponse,
)
from web.auth import authenticate, create_session, set_session_cookie
from web.config import get_web_config
from web.deps import get_redis, get_session, require_auth
from web.ratelimit import rate_limit
from web.services.env_writer import read_key, write_keys
from web.uploads import JSON_EXTS, VCF_MAX_BYTES, read_capped, validate_extension

logger = logging.getLogger(__name__)

router = ApiRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(require_auth)])


_SENTINEL = "••••••••"  # what we show in place of a real secret


def _is_sentinel(value: str) -> bool:
    return value.strip() == _SENTINEL


def _garmin_credentials() -> tuple[str, str]:
    """Return the persisted Garmin credentials without ever logging them."""
    return (
        read_key("VITALS_GARMIN_EMAIL").strip(),
        read_key("VITALS_GARMIN_PASSWORD").strip(),
    )


def _activate_garmin_credentials(email: str, password: str) -> None:
    """Make persisted credentials visible to clients created in this process."""
    os.environ["VITALS_GARMIN_EMAIL"] = email
    os.environ["VITALS_GARMIN_PASSWORD"] = password


def apply_schedule(app, settings: dict) -> None:
    """Re-register the jobs and push them onto the running scheduler.

    Best-effort on purpose: the settings *are* saved by the time this runs, so a
    scheduler that isn't up (tests, a worker that never started one) must not turn
    a successful save into a 500 — the new schedule is picked up at next boot
    either way.
    """
    from vitals.scheduler.jobs import register_all_jobs
    from vitals.scheduler.scheduler import apply_registry
    from web.deps import get_redis_client, get_session_factory

    scheduler = getattr(app.state, "scheduler", None)
    if scheduler is None:
        return
    try:
        register_all_jobs(settings)
        apply_registry(scheduler, get_session_factory(), get_redis_client())
    except Exception:
        logger.exception("could not apply the new schedule; it takes effect on restart")



@router.get("", response_model=SettingsView)
async def read_settings(
    request: Request,
    username: str = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> SettingsView:
    """Read the complete settings view model without leaking any secrets."""
    twofa = await twofa_service.get_state(db)
    proactive = await prefs.get_prefs(db)
    week_template = await day_plan.get_week_template(db)
    breaker = await login_breaker_state(redis)
    garmin_status = await garmin_weight_service.get_status(db)
    garmin_email, garmin_pwd = _garmin_credentials()

    enabled_modules = getattr(request.state, "enabled_modules", None)
    if not enabled_modules:
        enabled_modules = await modules_service.get_enabled_modules(db, redis)

    profile = ProfileSettings(
        height_cm=read_key("VITALS_HEIGHT_CM") or "190",
        sex=read_key("VITALS_SEX") or "male",
        user_age=read_key("VITALS_USER_AGE") or "18",
        timezone=read_key("VITALS_TIMEZONE") or "Europe/Chisinau",
        user_program=read_key("VITALS_USER_PROGRAM") or "",
        user_goals=read_key("VITALS_USER_GOALS") or "",
    )

    nutrition_goals = NutritionGoalsSettings(
        nutrition_protein_target_g=read_key("VITALS_NUTRITION_PROTEIN_TARGET_G") or "150",
        nutrition_calories_min=read_key("VITALS_NUTRITION_CALORIES_MIN") or "1300",
        nutrition_calories_max=read_key("VITALS_NUTRITION_CALORIES_MAX") or "1700",
    )

    lang_code = getattr(request.state, "lang", None) or await language_service.get_language(db, redis)
    language = LanguageSettings(language=lang_code)

    modules = ModulesSettings(
        enabled_modules=enabled_modules,
        registry=[
            # Body composition is a tab of the weight section, so it is listed with Health.
            ModuleInfo(key=spec.key, rubric=spec.rubric or "health", core=spec.category == "core")
            for spec in modules_service.MODULE_REGISTRY.values()
        ],
    )

    ai = AiSettings(
        openrouter_api_key_set=bool(read_key("VITALS_OPENROUTER_API_KEY")),
        openrouter_base_url=read_key("VITALS_OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1",
        llm_model_digest=read_key("VITALS_LLM_MODEL_DIGEST") or "anthropic/claude-sonnet-4.6",
        llm_model_parser=read_key("VITALS_LLM_MODEL_PARSER") or "google/gemini-2.5-flash",
        llm_model_brief=read_key("VITALS_LLM_MODEL_BRIEF") or "",
    )

    hevy = HevySettings(
        hevy_api_key_set=bool(read_key("VITALS_HEVY_API_KEY")),
    )

    garmin = GarminSettings(
        garmin_email=garmin_email,
        garmin_password_set=bool(garmin_pwd),
        garmin_credentials_configured=bool(garmin_email and garmin_pwd),
        garmin_weight_export_enabled=bool(garmin_status.get("enabled", False)),
        garmin_weight_status=garmin_status,
        breaker=breaker,
    )

    mcp = McpSettings(
        mcp_client_id=read_key("VITALS_MCP_CLIENT_ID") or "vitals-claude-connector",
        mcp_client_secret_set=bool(read_key("VITALS_MCP_CLIENT_SECRET")),
    )

    security = SecuritySettings(
        twofa_enabled=twofa.enabled,
        twofa_pending=twofa.pending,
    )

    proactive_settings = ProactiveSettings(
        brief_time=proactive.get("brief_time", prefs.DEFAULTS["brief_time"]),
        evening_time=proactive.get("evening_time", prefs.DEFAULTS["evening_time"]),
        quiet_start=proactive.get("quiet_start", prefs.DEFAULTS["quiet_start"]),
        quiet_end=proactive.get("quiet_end", prefs.DEFAULTS["quiet_end"]),
        daily_budget=proactive.get("daily_budget", prefs.DEFAULTS["daily_budget"]),
        garmin_sync_hours=proactive.get("garmin_sync_hours", prefs.DEFAULTS["garmin_sync_hours"]),
        garmin_weight_export_minutes=proactive.get(
            "garmin_weight_export_minutes", prefs.DEFAULTS["garmin_weight_export_minutes"]
        ),
        garmin_weight_max_age_days=proactive.get(
            "garmin_weight_max_age_days", prefs.DEFAULTS["garmin_weight_max_age_days"]
        ),
        pulse_seconds=proactive.get("pulse_seconds", prefs.DEFAULTS["pulse_seconds"]),
        pulse_start_hour=proactive.get("pulse_start_hour", prefs.DEFAULTS["pulse_start_hour"]),
        pulse_end_hour=proactive.get("pulse_end_hour", prefs.DEFAULTS["pulse_end_hour"]),
        nudges=proactive.get("nudges", {}),
        week_template=week_template,
    )

    return SettingsView(
        username=username,
        profile=profile,
        nutrition_goals=nutrition_goals,
        language=language,
        modules=modules,
        ai=ai,
        hevy=hevy,
        garmin=garmin,
        mcp=mcp,
        security=security,
        proactive=proactive_settings,
    )


@router.post("/profile", response_model=SaveResponse)
async def update_profile(body: ProfileUpdate) -> SaveResponse:
    updates: dict[str, str] = {}
    if body.height_cm is not None and body.height_cm.strip():
        updates["VITALS_HEIGHT_CM"] = body.height_cm.strip()
    if body.sex is not None and body.sex in ("male", "female"):
        updates["VITALS_SEX"] = body.sex
    if body.user_age is not None and body.user_age.strip().isdigit():
        updates["VITALS_USER_AGE"] = body.user_age.strip()
    if body.timezone is not None and body.timezone.strip():
        updates["VITALS_TIMEZONE"] = body.timezone.strip()
    if body.user_program is not None:
        updates["VITALS_USER_PROGRAM"] = " ".join(body.user_program.split())
    if body.user_goals is not None:
        updates["VITALS_USER_GOALS"] = body.user_goals.strip()

    if updates:
        write_keys(updates)
    return SaveResponse(saved=True)


@router.post("/nutrition", response_model=SaveResponse)
async def update_nutrition_goals(body: NutritionGoalsUpdate) -> SaveResponse:
    updates: dict[str, str] = {}
    if body.nutrition_protein_target_g is not None and body.nutrition_protein_target_g.strip():
        updates["VITALS_NUTRITION_PROTEIN_TARGET_G"] = body.nutrition_protein_target_g.strip()
    if body.nutrition_calories_min is not None and body.nutrition_calories_min.strip():
        updates["VITALS_NUTRITION_CALORIES_MIN"] = body.nutrition_calories_min.strip()
    if body.nutrition_calories_max is not None and body.nutrition_calories_max.strip():
        updates["VITALS_NUTRITION_CALORIES_MAX"] = body.nutrition_calories_max.strip()

    if updates:
        write_keys(updates)
    return SaveResponse(saved=True)


@router.post("/language", response_model=SaveResponse)
async def update_language(
    body: LanguageUpdate,
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> SaveResponse:
    await language_service.set_language(db, body.language, redis)
    await db.commit()
    return SaveResponse(saved=True)


@router.post("/modules", response_model=SaveResponse)
async def toggle_module(
    body: ModuleToggleUpdate,
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    _rl: None = Depends(rate_limit("settings_modules", limit=30, window=60)),
) -> SaveResponse:
    try:
        state = await modules_service.set_module_enabled(db, key=body.module, enabled=body.enabled)
    except ModuleToggleError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    await db.commit()
    await modules_service.prime_cache(redis, state)
    return SaveResponse(saved=True)


@router.post("/ai", response_model=SaveResponse)
async def update_ai(body: AiUpdate) -> SaveResponse:
    updates: dict[str, str] = {}
    if body.openrouter_api_key is not None:
        key = body.openrouter_api_key.strip()
        if key and not _is_sentinel(key):
            updates["VITALS_OPENROUTER_API_KEY"] = key
    if body.openrouter_base_url is not None:
        updates["VITALS_OPENROUTER_BASE_URL"] = body.openrouter_base_url.strip()
    if body.llm_model_digest is not None:
        updates["VITALS_LLM_MODEL_DIGEST"] = body.llm_model_digest.strip()
    if body.llm_model_parser is not None:
        updates["VITALS_LLM_MODEL_PARSER"] = body.llm_model_parser.strip()
    if body.llm_model_brief is not None:
        updates["VITALS_LLM_MODEL_BRIEF"] = body.llm_model_brief.strip()

    if updates:
        write_keys(updates)
    return SaveResponse(saved=True)


@router.post("/hevy", response_model=SaveResponse)
async def update_hevy(body: HevyUpdate) -> SaveResponse:
    updates: dict[str, str] = {}
    if body.hevy_api_key is not None:
        key = body.hevy_api_key.strip()
        if key and not _is_sentinel(key):
            updates["VITALS_HEVY_API_KEY"] = key

    if updates:
        write_keys(updates)
    return SaveResponse(saved=True)


@router.post("/garmin", response_model=SaveResponse)
async def update_garmin(body: GarminUpdate) -> SaveResponse:
    stored_email, stored_password = _garmin_credentials()
    submitted_email = (body.garmin_email or "").strip()
    submitted_password = (body.garmin_password or "").strip()
    effective_email = submitted_email or stored_email
    effective_password = (
        submitted_password
        if submitted_password and not _is_sentinel(submitted_password)
        else stored_password
    )

    updates: dict[str, str] = {}
    if submitted_email:
        updates["VITALS_GARMIN_EMAIL"] = submitted_email
    if submitted_password and not _is_sentinel(submitted_password):
        updates["VITALS_GARMIN_PASSWORD"] = submitted_password

    if updates:
        write_keys(updates)
    _activate_garmin_credentials(effective_email, effective_password)
    return SaveResponse(saved=True)


@router.post("/garmin/weight-toggle", response_model=SaveResponse)
async def toggle_garmin_weight(
    body: GarminWeightToggleUpdate,
    db: AsyncSession = Depends(get_session),
    _rl: None = Depends(rate_limit("garmin_weight_toggle", limit=20, window=60)),
) -> SaveResponse:
    email, password = _garmin_credentials()
    if body.enabled and not (email and password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="credentials_required",
        )

    if body.enabled:
        _activate_garmin_credentials(email, password)
    await garmin_weight_service.set_enabled(db, body.enabled)
    await db.commit()
    return SaveResponse(saved=True)


@router.post("/garmin/weight/send-now", response_model=StatusResponse)
async def send_garmin_weight(
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    _rl: None = Depends(rate_limit("garmin_weight_send_now", limit=6, window=3600)),
) -> StatusResponse:
    try:
        result = await garmin_weight_service.send_now(db, redis=redis)
        await db.commit()
        action = str(result.get("status") or "done")
    except Exception:
        await db.rollback()
        logger.exception("Could not run Garmin weight reconciliation")
        action = "error"
    return StatusResponse(status=action)


@router.post("/mcp", response_model=SaveResponse)
async def update_mcp(body: McpUpdate) -> SaveResponse:
    updates: dict[str, str] = {}
    if body.mcp_client_id is not None and body.mcp_client_id.strip():
        updates["VITALS_MCP_CLIENT_ID"] = body.mcp_client_id.strip()
    if body.mcp_client_secret is not None:
        sec = body.mcp_client_secret.strip()
        if sec and not _is_sentinel(sec):
            updates["VITALS_MCP_CLIENT_SECRET"] = sec

    if updates:
        write_keys(updates)
        for k, v in updates.items():
            os.environ[k] = v
    return SaveResponse(saved=True)


@router.post("/password", response_model=SaveResponse)
async def update_password(
    body: PasswordChangeUpdate,
    response: Response,
) -> SaveResponse:
    cfg = get_web_config()
    if not authenticate(cfg.auth_username, body.old_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="wrong_password",
        )
    if not body.new_password or len(body.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="password_too_short",
        )
    if body.new_password != body.new_password_confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="password_mismatch",
        )

    hashed = hash_password(body.new_password)
    write_keys({"VITALS_AUTH_PASSWORD_HASH": hashed})
    os.environ["VITALS_AUTH_PASSWORD_HASH"] = hashed

    # Re-issue cookie so session stays active
    token = create_session(cfg.auth_username)
    set_session_cookie(response, token)
    return SaveResponse(saved=True)


@router.post("/2fa/start", response_model=TwoFaStartResponse)
async def start_twofa(
    username: str = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> TwoFaStartResponse:
    """Start 2FA enrolment: mints an unconfirmed secret and returns the setup payload."""
    state = await twofa_service.get_state(db)
    if state.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="twofa_already_enabled",
        )
    secret = await twofa_service.start_enrolment(db)
    await db.commit()

    uri = twofa_service.provisioning_uri(secret, account=username)
    try:
        qr = twofa_service.qr_svg(uri)
    except Exception:
        qr = ""
    return TwoFaStartResponse(
        secret=twofa_service.format_secret(secret),
        otpauth_uri=uri,
        qr_svg=qr,
    )


@router.post("/2fa/enable", response_model=SaveResponse)
async def enable_twofa(
    body: TwoFaCodeUpdate,
    db: AsyncSession = Depends(get_session),
    _rl: None = Depends(rate_limit("twofa_setup", limit=10, window=300)),
) -> SaveResponse:
    success = await twofa_service.confirm_enrolment(db, body.code)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="twofa_bad_code",
        )
    await db.commit()
    return SaveResponse(saved=True)


@router.post("/2fa/disable", response_model=SaveResponse)
async def disable_twofa(
    body: TwoFaCodeUpdate,
    db: AsyncSession = Depends(get_session),
    _rl: None = Depends(rate_limit("twofa_setup", limit=10, window=300)),
) -> SaveResponse:
    success = await twofa_service.disable(db, body.code)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="twofa_bad_code",
        )
    await db.commit()
    return SaveResponse(saved=True)


@router.post("/proactive", response_model=SaveResponse)
async def update_proactive(
    request: Request,
    body: ProactiveUpdate,
    db: AsyncSession = Depends(get_session),
) -> SaveResponse:
    current = await prefs.get_prefs(db)
    raw_prefs = dict(current)

    if body.brief_time is not None:
        raw_prefs["brief_time"] = body.brief_time
    if body.evening_time is not None:
        raw_prefs["evening_time"] = body.evening_time
    if body.quiet_start is not None:
        raw_prefs["quiet_start"] = body.quiet_start
    if body.quiet_end is not None:
        raw_prefs["quiet_end"] = body.quiet_end
    if body.daily_budget is not None:
        raw_prefs["daily_budget"] = body.daily_budget
    if body.garmin_sync_hours is not None:
        raw_prefs["garmin_sync_hours"] = body.garmin_sync_hours
    if body.garmin_weight_export_minutes is not None:
        raw_prefs["garmin_weight_export_minutes"] = body.garmin_weight_export_minutes
    if body.garmin_weight_max_age_days is not None:
        raw_prefs["garmin_weight_max_age_days"] = body.garmin_weight_max_age_days
    if body.pulse_seconds is not None:
        raw_prefs["pulse_seconds"] = body.pulse_seconds
    if body.pulse_start_hour is not None:
        raw_prefs["pulse_start_hour"] = body.pulse_start_hour
    if body.pulse_end_hour is not None:
        raw_prefs["pulse_end_hour"] = body.pulse_end_hour
    if body.nudges is not None:
        raw_prefs["nudges"] = {c: c in body.nudges for c in prefs.NUDGE_CATEGORIES}

    settings = await prefs.set_prefs(db, raw_prefs)

    if body.week_template is not None:
        await day_plan.set_week_template(db, body.week_template)

    await db.commit()
    apply_schedule(request.app, settings)

    adjusted = raw_prefs != settings
    return SaveResponse(saved=True, adjusted=adjusted)


@router.get("/export")
async def export_backup(
    db: AsyncSession = Depends(get_session),
    _rl: None = Depends(rate_limit("data_export", limit=2, window=60)),
) -> Response:
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
    db: AsyncSession = Depends(get_session),
    _rl: None = Depends(rate_limit("data_export", limit=2, window=60)),
) -> Response:
    snapshot = await data_portability_service.export_llm(db)
    body = json.dumps(snapshot, ensure_ascii=False, indent=2, default=str)
    filename = f"vitals_llm_{today_local().strftime('%Y%m%d')}.json"
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import", response_model=ImportResult)
async def import_backup(
    db: AsyncSession = Depends(get_session),
    backup_file: UploadFile = File(...),
    _rl: None = Depends(rate_limit("data_import", limit=2, window=60)),
) -> ImportResult:
    validate_extension(backup_file.filename, JSON_EXTS)
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
    return ImportResult(summary=stats.summary(), restored=True)


@router.post("/restart", response_model=StatusResponse)
async def restart_container(username: str = Depends(require_auth)) -> StatusResponse:
    logger.info("User %s requested container restart via API. Terminating in 500ms...", username)

    async def shutdown():
        await asyncio.sleep(0.5)
        os.kill(os.getpid(), signal.SIGTERM)

    asyncio.create_task(shutdown())
    return StatusResponse(status="restarting")
