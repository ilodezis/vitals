"""Environment-driven configuration for the Vitals core.

Mirrors Boxly's ``bot/config.py``: a frozen dataclass built from ``VITALS_*``
env vars, loaded once. Web-only knobs (session secret, cookie flags) live in
``web/config.py`` so the core never depends on the delivery layer.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


DEFAULT_DB_STATEMENT_TIMEOUT_MS = 10000
DEFAULT_DB_POOL_SIZE = 20
DEFAULT_DB_MAX_OVERFLOW = 10
DEFAULT_DB_POOL_TIMEOUT = 30
DEFAULT_DB_POOL_RECYCLE = 1800

DEFAULT_TIMEZONE = "Europe/Chisinau"
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_HEVY_BASE_URL = "https://api.hevyapp.com"
# Where the Garmin (garth) OAuth token store is persisted on disk, in addition to
# the Redis session cache, so a restart doesn't force a fresh login (which risks
# a captcha/MFA challenge and a temporary block).
DEFAULT_GARMIN_TOKEN_DIR = "/data/garmin_session"


def _pos_int(env_name: str, default: int) -> int:
    raw = (os.getenv(env_name) or "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else default


@dataclass(frozen=True)
class Config:
    database_url: str
    redis_url: str
    timezone: str = DEFAULT_TIMEZONE

    # Body-composition context (single user). Height feeds the Navy formula;
    # sex gates the female formula for the open-source build.
    height_cm: float = 190.0
    sex: str = "male"

    # User Profile settings (single user default based on Timur)
    user_age: int = 18
    user_program: str = "рекомпозиция тела (снижение жира, сохраняя мышцы) на протоколе GLP-1, с силовыми тренировками и отслеживанием восстановления"
    user_goals: list[str] = field(default_factory=lambda: ["снижение жира", "сохранение мышц"])

    # LLM gateway (OpenRouter, OpenAI-compatible). Empty api_key → the client is
    # constructed lazily and only fails when a call is actually attempted.
    openrouter_api_key: str = ""
    openrouter_base_url: str = DEFAULT_OPENROUTER_BASE_URL
    openrouter_http_referer: Optional[str] = None
    openrouter_x_title: Optional[str] = None
    # Per-task model slugs (OpenRouter). Digest = analytical narrative (Claude
    # Sonnet 4.6 — exact versioned slug required by OpenRouter); parser = vision
    # extraction of lab PDFs/photos (Gemini 2.5 Flash — cheap, strong document OCR).
    llm_model_digest: str = "anthropic/claude-sonnet-4.6"
    llm_model_parser: str = "google/gemini-2.5-flash"

    # ── Nutrition goals ──────────────────────────────────────────────────────────
    nutrition_protein_target_g: float = 150.0
    nutrition_calories_min: int = 1300
    nutrition_calories_max: int = 1700

    # ── Hevy (workouts) — public REST API, personal api-key ─────────────────────
    # Empty key → the client constructs lazily and only fails on an actual call,
    # so the app boots fine before credentials are configured.
    hevy_api_key: str = ""
    hevy_base_url: str = DEFAULT_HEVY_BASE_URL

    # ── Garmin Connect — web session via garminconnect/garth ────────────────────
    garmin_email: str = ""
    garmin_password: str = ""
    garmin_token_dir: str = DEFAULT_GARMIN_TOKEN_DIR

    db_statement_timeout_ms: int = DEFAULT_DB_STATEMENT_TIMEOUT_MS
    db_pool_size: int = DEFAULT_DB_POOL_SIZE
    db_max_overflow: int = DEFAULT_DB_MAX_OVERFLOW
    db_pool_timeout: int = DEFAULT_DB_POOL_TIMEOUT
    db_pool_recycle: int = DEFAULT_DB_POOL_RECYCLE


def load_config() -> Config:
    database_url = os.getenv("VITALS_DATABASE_URL")
    if not database_url:
        raise ValueError("VITALS_DATABASE_URL is not set")

    redis_url = os.getenv("VITALS_REDIS_URL", "redis://vitals_redis:6379/0")

    height_raw = (os.getenv("VITALS_HEIGHT_CM") or "").strip()
    try:
        height_cm = float(height_raw) if height_raw else 190.0
    except ValueError:
        height_cm = 190.0

    sex = (os.getenv("VITALS_SEX") or "male").strip().lower()
    if sex not in ("male", "female"):
        sex = "male"

    age_raw = (os.getenv("VITALS_USER_AGE") or "").strip()
    try:
        user_age = int(age_raw) if age_raw else 18
    except ValueError:
        user_age = 18

    user_program = (os.getenv("VITALS_USER_PROGRAM") or "рекомпозиция тела (снижение жира, сохраняя мышцы) на протоколе GLP-1, с силовыми тренировками и отслеживанием восстановления").strip()

    goals_raw = (os.getenv("VITALS_USER_GOALS") or "").strip()
    if goals_raw:
        user_goals = [g.strip() for g in goals_raw.split(",") if g.strip()]
    else:
        user_goals = ["снижение жира", "сохранение мышц"]

    protein_raw = (os.getenv("VITALS_NUTRITION_PROTEIN_TARGET_G") or "").strip()
    try:
        nutrition_protein_target_g = float(protein_raw) if protein_raw else 150.0
    except ValueError:
        nutrition_protein_target_g = 150.0

    cal_min_raw = (os.getenv("VITALS_NUTRITION_CALORIES_MIN") or "").strip()
    try:
        nutrition_calories_min = int(cal_min_raw) if cal_min_raw else 1300
    except ValueError:
        nutrition_calories_min = 1300

    cal_max_raw = (os.getenv("VITALS_NUTRITION_CALORIES_MAX") or "").strip()
    try:
        nutrition_calories_max = int(cal_max_raw) if cal_max_raw else 1700
    except ValueError:
        nutrition_calories_max = 1700

    return Config(
        database_url=database_url,
        redis_url=redis_url,
        timezone=os.getenv("VITALS_TIMEZONE", DEFAULT_TIMEZONE) or DEFAULT_TIMEZONE,
        height_cm=height_cm,
        sex=sex,
        user_age=user_age,
        user_program=user_program,
        user_goals=user_goals,
        nutrition_protein_target_g=nutrition_protein_target_g,
        nutrition_calories_min=nutrition_calories_min,
        nutrition_calories_max=nutrition_calories_max,
        openrouter_api_key=os.getenv("VITALS_OPENROUTER_API_KEY", ""),
        openrouter_base_url=(
            os.getenv("VITALS_OPENROUTER_BASE_URL") or DEFAULT_OPENROUTER_BASE_URL
        ),
        openrouter_http_referer=os.getenv("VITALS_OPENROUTER_HTTP_REFERER") or None,
        openrouter_x_title=os.getenv("VITALS_OPENROUTER_X_TITLE") or None,
        llm_model_digest=os.getenv(
            "VITALS_LLM_MODEL_DIGEST", "anthropic/claude-sonnet-4.6"
        ),
        llm_model_parser=os.getenv(
            "VITALS_LLM_MODEL_PARSER", "google/gemini-2.5-flash"
        ),
        hevy_api_key=os.getenv("VITALS_HEVY_API_KEY", ""),
        hevy_base_url=(os.getenv("VITALS_HEVY_BASE_URL") or DEFAULT_HEVY_BASE_URL),
        garmin_email=os.getenv("VITALS_GARMIN_EMAIL", ""),
        garmin_password=os.getenv("VITALS_GARMIN_PASSWORD", ""),
        garmin_token_dir=(
            os.getenv("VITALS_GARMIN_TOKEN_DIR") or DEFAULT_GARMIN_TOKEN_DIR
        ),
        db_statement_timeout_ms=_pos_int(
            "VITALS_DB_STATEMENT_TIMEOUT_MS", DEFAULT_DB_STATEMENT_TIMEOUT_MS
        ),
        db_pool_size=_pos_int("VITALS_DB_POOL_SIZE", DEFAULT_DB_POOL_SIZE),
        db_max_overflow=_pos_int("VITALS_DB_MAX_OVERFLOW", DEFAULT_DB_MAX_OVERFLOW),
        db_pool_timeout=_pos_int("VITALS_DB_POOL_TIMEOUT", DEFAULT_DB_POOL_TIMEOUT),
        db_pool_recycle=_pos_int("VITALS_DB_POOL_RECYCLE", DEFAULT_DB_POOL_RECYCLE),
    )
