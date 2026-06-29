"""Tests for the i18n translation system, plurals, digest prompts, and localized routing."""
from __future__ import annotations

import pytest
from sqlalchemy import select
from vitals.i18n import t, plural, current_lang
from vitals.services.digest_service import build_prompt
from vitals.models.app_settings import AppSetting
from vitals.services.language_service import SETTINGS_KEY as LANG_SETTINGS_KEY


def test_translation_basic():
    # Test translations in EN
    current_lang.set("en")
    assert t("nav.weight") == "Weight"
    assert t("settings.sex_male") == "Male"

    # Test translations in RU
    current_lang.set("ru")
    assert t("nav.weight") == "Вес"
    assert t("settings.sex_male") == "Мужской"


def test_translation_fallback():
    # If key doesn't exist in current language but exists in default (EN), it should fall back to EN
    current_lang.set("ru")
    # For testing fallback, let's look up a key that is defined in both, or test behavior when a key is absent
    assert t("non_existent_key_xyz") == "non_existent_key_xyz"


def test_plurals():
    # English plurals: 2 forms (1 vs other)
    current_lang.set("en")
    assert plural(1, "session", "sessions") == "session"
    assert plural(2, "session", "sessions") == "sessions"
    assert plural(0, "session", "sessions") == "sessions"
    assert plural(5, "session", "sessions") == "sessions"

    # Russian plurals: 3 forms (1 vs 2-4 vs many)
    current_lang.set("ru")
    assert plural(1, "сессия", "сессии", "сессий") == "сессия"
    assert plural(21, "сессия", "сессии", "сессий") == "сессия"
    assert plural(2, "сессия", "сессии", "сессий") == "сессии"
    assert plural(4, "сессия", "сессии", "сессий") == "сессии"
    assert plural(0, "сессия", "сессии", "сессий") == "сессий"
    assert plural(5, "сессия", "сессии", "сессий") == "сессий"
    assert plural(11, "сессия", "сессии", "сессий") == "сессий"


def test_digest_build_prompt():
    context = {"test": "data"}
    
    # RU prompt
    prompt_ru = build_prompt(context, lang="ru")
    assert "Структурный срез данных за период" in prompt_ru
    assert "Напиши аналитический разбор" in prompt_ru

    # EN prompt
    prompt_en = build_prompt(context, lang="en")
    assert "Structured data snapshot for the period" in prompt_en
    assert "Write an analytical digest" in prompt_en


@pytest.mark.asyncio
async def test_oauth_page_renders_localized(auth_client, db_session, redis):
    # Set language to RU
    response = await auth_client.post("/settings/language", data={"language": "ru"})
    assert response.status_code == 303
    
    # Query authorization view
    r = await auth_client.get("/oauth/authorize?response_type=code&client_id=test-id&redirect_uri=http://localhost&state=123", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert "Разрешение доступа" in r.text
    assert "Истории изменения веса" in r.text

    # Set language to EN
    response = await auth_client.post("/settings/language", data={"language": "en"})
    assert response.status_code == 303
    
    # Query authorization view again
    r = await auth_client.get("/oauth/authorize?response_type=code&client_id=test-id&redirect_uri=http://localhost&state=123", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert "Access Authorization" in r.text
    assert "Weight history and body composition" in r.text


def test_i18n_key_parity():
    from vitals.i18n import STRINGS
    
    en_keys = set(STRINGS["en"].keys())
    ru_keys = set(STRINGS["ru"].keys())
    
    missing_in_ru = en_keys - ru_keys
    missing_in_en = ru_keys - en_keys
    
    assert not missing_in_ru, f"Translation keys missing in RU: {missing_in_ru}"
    assert not missing_in_en, f"Translation keys missing in EN: {missing_in_en}"
