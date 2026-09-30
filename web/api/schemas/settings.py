"""Pydantic schemas for the settings endpoints under ``/api/v1/settings``.

CRITICAL SECURITY RULE:
Secrets (API keys, passwords, MCP client secret, 2FA secret) MUST NEVER
be returned in GET responses or mutation returns. Return only booleans
(e.g. ``openrouter_api_key_set``) or masked indicators.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class ProfileSettings(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    height_cm: str = "190"
    sex: str = "male"
    user_age: str = "18"
    timezone: str = "Europe/Chisinau"
    user_program: str = ""
    user_goals: str = ""


class ProfileUpdate(BaseModel):
    height_cm: Optional[str] = None
    sex: Optional[str] = None
    user_age: Optional[str] = None
    timezone: Optional[str] = None
    user_program: Optional[str] = None
    user_goals: Optional[str] = None


class NutritionGoalsSettings(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    nutrition_protein_target_g: str = "150"
    nutrition_calories_min: str = "1300"
    nutrition_calories_max: str = "1700"


class NutritionGoalsUpdate(BaseModel):
    nutrition_protein_target_g: Optional[str] = None
    nutrition_calories_min: Optional[str] = None
    nutrition_calories_max: Optional[str] = None


class LanguageSettings(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    language: str = "ru"


class LanguageUpdate(BaseModel):
    language: str


class ModuleInfo(BaseModel):
    """One switchable dashboard section, on or off — the list a switched-off one stays in."""

    key: str
    rubric: str
    core: bool


class ModulesSettings(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    enabled_modules: dict[str, bool] = Field(default_factory=dict)
    registry: list[ModuleInfo] = Field(default_factory=list)


class ModuleToggleUpdate(BaseModel):
    module: str
    enabled: bool


class AiSettings(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    openrouter_api_key_set: bool = False
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_model_digest: str = "anthropic/claude-sonnet-4.6"
    llm_model_parser: str = "google/gemini-2.5-flash"
    llm_model_brief: str = ""


class AiUpdate(BaseModel):
    openrouter_api_key: Optional[str] = None
    openrouter_base_url: Optional[str] = None
    llm_model_digest: Optional[str] = None
    llm_model_parser: Optional[str] = None
    llm_model_brief: Optional[str] = None


class HevySettings(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    hevy_api_key_set: bool = False


class HevyUpdate(BaseModel):
    hevy_api_key: Optional[str] = None


class GarminSettings(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    garmin_email: str = ""
    garmin_password_set: bool = False
    garmin_credentials_configured: bool = False
    garmin_weight_export_enabled: bool = False
    garmin_weight_status: Optional[dict[str, Any]] = None
    breaker: Optional[dict[str, Any]] = None


class GarminUpdate(BaseModel):
    garmin_email: Optional[str] = None
    garmin_password: Optional[str] = None


class GarminWeightToggleUpdate(BaseModel):
    enabled: bool


class McpSettings(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    mcp_client_id: str = "vitals-claude-connector"
    mcp_client_secret_set: bool = False


class McpUpdate(BaseModel):
    mcp_client_id: Optional[str] = None
    mcp_client_secret: Optional[str] = None


class SecuritySettings(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    twofa_enabled: bool = False
    twofa_pending: bool = False


class PasswordChangeUpdate(BaseModel):
    old_password: str
    new_password: str
    new_password_confirm: str


class TwoFaStartResponse(BaseModel):
    secret: str
    otpauth_uri: str
    qr_svg: str


class TwoFaCodeUpdate(BaseModel):
    code: str


class ProactiveSettings(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    brief_time: str
    evening_time: str
    quiet_start: str
    quiet_end: str
    daily_budget: int
    garmin_sync_hours: int
    garmin_weight_export_minutes: int
    garmin_weight_max_age_days: int
    pulse_seconds: int
    pulse_start_hour: int
    pulse_end_hour: int
    nudges: dict[str, bool] = Field(default_factory=dict)
    week_template: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ProactiveUpdate(BaseModel):
    brief_time: Optional[str] = None
    evening_time: Optional[str] = None
    quiet_start: Optional[str] = None
    quiet_end: Optional[str] = None
    daily_budget: Optional[int] = None
    garmin_sync_hours: Optional[int] = None
    garmin_weight_export_minutes: Optional[int] = None
    garmin_weight_max_age_days: Optional[int] = None
    pulse_seconds: Optional[int] = None
    pulse_start_hour: Optional[int] = None
    pulse_end_hour: Optional[int] = None
    nudges: Optional[list[str]] = None
    week_template: Optional[dict[str, dict[str, Any]]] = None


class SettingsView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    username: str
    profile: ProfileSettings
    nutrition_goals: NutritionGoalsSettings
    language: LanguageSettings
    modules: ModulesSettings
    ai: AiSettings
    hevy: HevySettings
    garmin: GarminSettings
    mcp: McpSettings
    security: SecuritySettings
    proactive: ProactiveSettings


class SaveResponse(BaseModel):
    saved: bool = True
    adjusted: Optional[bool] = None
    message: Optional[str] = None


class ImportResult(BaseModel):
    summary: str
    restored: bool = True


class StatusResponse(BaseModel):
    status: str
