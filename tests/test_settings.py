"""Tests for the settings router and env_writer utility."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio



def test_env_writer_read_missing_file(tmp_path, monkeypatch):
    """read_key returns empty string when .env file does not exist."""
    monkeypatch.setenv("VITALS_ENV_FILE", str(tmp_path / "nonexistent.env"))
    from web.services.env_writer import read_key
    assert read_key("SOME_KEY") == ""


def test_env_writer_read_existing_key(tmp_path, monkeypatch):
    """read_key returns the value for an existing key."""
    env_file = tmp_path / "test.env"
    env_file.write_text("VITALS_HEIGHT_CM=185\nVITALS_SEX=male\n", encoding="utf-8")
    monkeypatch.setenv("VITALS_ENV_FILE", str(env_file))
    from web.services import env_writer
    import importlib; importlib.reload(env_writer)
    from web.services.env_writer import read_key
    assert read_key("VITALS_HEIGHT_CM") == "185"
    assert read_key("VITALS_SEX") == "male"
    assert read_key("MISSING_KEY") == ""


def test_env_writer_write_updates_existing_key(tmp_path, monkeypatch):
    """write_keys updates an existing key in-place."""
    env_file = tmp_path / "test.env"
    env_file.write_text(
        "# Comment\nVITALS_HEIGHT_CM=190\nVITALS_SEX=male\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("VITALS_ENV_FILE", str(env_file))
    from web.services.env_writer import write_keys, read_key
    write_keys({"VITALS_HEIGHT_CM": "180"})
    content = env_file.read_text(encoding="utf-8")
    assert "VITALS_HEIGHT_CM=180" in content
    assert "VITALS_SEX=male" in content
    assert "# Comment" in content  # comments preserved


def test_env_writer_write_appends_new_key(tmp_path, monkeypatch):
    """write_keys appends a key that doesn't already exist."""
    env_file = tmp_path / "test.env"
    env_file.write_text("VITALS_HEIGHT_CM=190\n", encoding="utf-8")
    monkeypatch.setenv("VITALS_ENV_FILE", str(env_file))
    from web.services.env_writer import write_keys
    write_keys({"VITALS_NEW_KEY": "hello"})
    content = env_file.read_text(encoding="utf-8")
    assert "VITALS_NEW_KEY=hello" in content
    assert "VITALS_HEIGHT_CM=190" in content


def test_env_writer_write_multiple_keys(tmp_path, monkeypatch):
    """write_keys handles multiple updates in a single call."""
    env_file = tmp_path / "test.env"
    env_file.write_text("VITALS_A=old_a\nVITALS_B=old_b\n", encoding="utf-8")
    monkeypatch.setenv("VITALS_ENV_FILE", str(env_file))
    from web.services.env_writer import write_keys
    write_keys({"VITALS_A": "new_a", "VITALS_B": "new_b", "VITALS_C": "new_c"})
    content = env_file.read_text(encoding="utf-8")
    assert "VITALS_A=new_a" in content
    assert "VITALS_B=new_b" in content
    assert "VITALS_C=new_c" in content


# ── settings page integration tests ──────────────────────────────────────────


async def test_settings_page_requires_auth(client):
    """GET /settings redirects to login when unauthenticated."""
    r = await client.get("/settings", headers={"Accept": "text/html"})
    assert r.status_code == 302
    assert "/login" in r.headers["location"]


async def test_settings_page_renders(auth_client):
    """GET /settings renders all four config sections."""
    r = await auth_client.get("/settings", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert "Профиль пользователя" in r.text
    assert "OpenRouter" in r.text
    assert "Hevy" in r.text
    assert "Garmin Connect" in r.text
    assert "Смена пароля" in r.text
    # Verify download links have hx-boost="false" to bypass HTMX boosting
    assert 'href="/settings/export" class="v-btn text-xs text-center" download hx-boost="false"' in r.text
    assert 'href="/settings/export-llm" class="v-btn-ghost text-xs text-center" download hx-boost="false"' in r.text


async def test_settings_page_has_gear_icon(auth_client):
    """The gear icon (⚙️ link to /settings) appears in the base layout."""
    r = await auth_client.get("/weight", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert 'href="/settings"' in r.text


async def test_settings_save_profile(auth_client, tmp_path, monkeypatch):
    """POST /settings/profile writes height and sex to the .env file."""
    env_file = tmp_path / "test.env"
    env_file.write_text("VITALS_HEIGHT_CM=190\nVITALS_SEX=male\n", encoding="utf-8")
    monkeypatch.setenv("VITALS_ENV_FILE", str(env_file))

    r = await auth_client.post(
        "/settings/profile",
        data={
            "height_cm": "185",
            "sex": "male",
            "user_age": "30",
            "timezone": "Europe/Chisinau",
            "user_program": "тест",
            "user_goals": "цель1, цель2",
        },
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/settings?saved=profile"

    content = env_file.read_text(encoding="utf-8")
    assert "VITALS_HEIGHT_CM=185" in content
    assert "VITALS_USER_AGE=30" in content
    assert "VITALS_USER_PROGRAM=тест" in content


async def test_settings_save_ai_key(auth_client, tmp_path, monkeypatch):
    """POST /settings/ai writes the OpenRouter API key."""
    env_file = tmp_path / "test.env"
    env_file.write_text("VITALS_OPENROUTER_API_KEY=\n", encoding="utf-8")
    monkeypatch.setenv("VITALS_ENV_FILE", str(env_file))

    r = await auth_client.post(
        "/settings/ai",
        data={
            "openrouter_api_key": "sk-or-test-123",
            "llm_model_digest": "anthropic/claude-sonnet-4.6",
            "llm_model_parser": "google/gemini-2.5-flash",
            "openrouter_base_url": "https://openrouter.ai/api/v1",
        },
    )
    assert r.status_code == 303
    assert "saved=ai" in r.headers["location"]

    content = env_file.read_text(encoding="utf-8")
    assert "VITALS_OPENROUTER_API_KEY=sk-or-test-123" in content


async def test_settings_save_ai_sentinel_not_overwritten(auth_client, tmp_path, monkeypatch):
    """When user submits sentinel value for secret field, existing key is NOT overwritten."""
    env_file = tmp_path / "test.env"
    env_file.write_text("VITALS_OPENROUTER_API_KEY=sk-or-real-key\n", encoding="utf-8")
    monkeypatch.setenv("VITALS_ENV_FILE", str(env_file))

    # Submitting an empty api_key (like when user leaves placeholder)
    r = await auth_client.post(
        "/settings/ai",
        data={
            "openrouter_api_key": "",  # empty = no change
            "llm_model_digest": "anthropic/claude-sonnet-4.6",
            "llm_model_parser": "google/gemini-2.5-flash",
            "openrouter_base_url": "https://openrouter.ai/api/v1",
        },
    )
    assert r.status_code == 303
    content = env_file.read_text(encoding="utf-8")
    # Original key must survive
    assert "VITALS_OPENROUTER_API_KEY=sk-or-real-key" in content


async def test_settings_save_hevy(auth_client, tmp_path, monkeypatch):
    """POST /settings/hevy writes the Hevy API key."""
    env_file = tmp_path / "test.env"
    env_file.write_text("VITALS_HEVY_API_KEY=\n", encoding="utf-8")
    monkeypatch.setenv("VITALS_ENV_FILE", str(env_file))

    r = await auth_client.post("/settings/hevy", data={"hevy_api_key": "hevy_abc123"})
    assert r.status_code == 303
    assert "saved=hevy" in r.headers["location"]

    content = env_file.read_text(encoding="utf-8")
    assert "VITALS_HEVY_API_KEY=hevy_abc123" in content


async def test_settings_save_garmin(auth_client, tmp_path, monkeypatch):
    """POST /settings/garmin writes email and password."""
    env_file = tmp_path / "test.env"
    env_file.write_text("VITALS_GARMIN_EMAIL=\nVITALS_GARMIN_PASSWORD=\n", encoding="utf-8")
    monkeypatch.setenv("VITALS_ENV_FILE", str(env_file))

    r = await auth_client.post(
        "/settings/garmin",
        data={"garmin_email": "user@example.com", "garmin_password": "hunter2"},
    )
    assert r.status_code == 303
    assert "saved=garmin" in r.headers["location"]

    content = env_file.read_text(encoding="utf-8")
    assert "VITALS_GARMIN_EMAIL=user@example.com" in content
    assert "VITALS_GARMIN_PASSWORD=hunter2" in content


async def test_settings_save_mcp(auth_client, tmp_path, monkeypatch):
    """POST /settings/mcp writes client id and secret."""
    env_file = tmp_path / "test.env"
    env_file.write_text("VITALS_MCP_CLIENT_ID=\nVITALS_MCP_CLIENT_SECRET=\n", encoding="utf-8")
    monkeypatch.setenv("VITALS_ENV_FILE", str(env_file))

    r = await auth_client.post(
        "/settings/mcp",
        data={"mcp_client_id": "test-id", "mcp_client_secret": "test-secret"},
    )
    assert r.status_code == 303
    assert "saved=mcp" in r.headers["location"]

    content = env_file.read_text(encoding="utf-8")
    assert "VITALS_MCP_CLIENT_ID=test-id" in content
    assert "VITALS_MCP_CLIENT_SECRET=test-secret" in content



async def test_settings_change_password_wrong_old(auth_client):
    """POST /settings/password with wrong current password shows error."""
    r = await auth_client.post(
        "/settings/password",
        data={
            "old_password": "wrongpassword",
            "new_password": "newpassword123",
            "new_password_confirm": "newpassword123",
        },
        headers={"Accept": "text/html"},
    )
    assert r.status_code == 200
    assert "Неверный текущий пароль" in r.text


async def test_settings_change_password_mismatch(auth_client):
    """POST /settings/password with mismatched new passwords shows error."""
    r = await auth_client.post(
        "/settings/password",
        data={
            "old_password": "password",
            "new_password": "newpass123",
            "new_password_confirm": "different456",
        },
        headers={"Accept": "text/html"},
    )
    assert r.status_code == 200
    assert "не совпадают" in r.text


async def test_settings_change_password_too_short(auth_client):
    """POST /settings/password with short new password shows error."""
    r = await auth_client.post(
        "/settings/password",
        data={
            "old_password": "password",
            "new_password": "short",
            "new_password_confirm": "short",
        },
        headers={"Accept": "text/html"},
    )
    assert r.status_code == 200
    assert "8 символов" in r.text


async def test_settings_change_password_success(auth_client, tmp_path, monkeypatch):
    """POST /settings/password with valid data updates the hash in .env."""
    env_file = tmp_path / "test.env"
    env_file.write_text("VITALS_AUTH_PASSWORD_HASH=old_hash\n", encoding="utf-8")
    monkeypatch.setenv("VITALS_ENV_FILE", str(env_file))
    # The handler now updates os.environ live; pin it so monkeypatch restores the
    # original hash on teardown (otherwise the new password leaks to later tests).
    monkeypatch.setenv("VITALS_AUTH_PASSWORD_HASH", os.environ["VITALS_AUTH_PASSWORD_HASH"])

    r = await auth_client.post(
        "/settings/password",
        data={
            "old_password": "password",  # matches TEST_PASSWORD in conftest
            "new_password": "mynewpassword",
            "new_password_confirm": "mynewpassword",
        },
    )
    assert r.status_code == 303
    assert "saved=password" in r.headers["location"]

    content = env_file.read_text(encoding="utf-8")
    # The hash was updated (bcrypt hashes start with $2b$)
    assert "$2b$" in content
    assert "old_hash" not in content


async def test_settings_change_password_takes_effect_live(auth_client, tmp_path, monkeypatch):
    """After a password change the new password authenticates and the old one no
    longer does — in the same process, without a container restart."""
    from web.auth import authenticate
    from web.security import hash_password

    env_file = tmp_path / "test.env"
    env_file.write_text("VITALS_AUTH_PASSWORD_HASH=old_hash\n", encoding="utf-8")
    monkeypatch.setenv("VITALS_ENV_FILE", str(env_file))
    # Pin a known starting hash so monkeypatch restores it on teardown — the
    # handler mutates os.environ directly, which would otherwise leak to later tests.
    monkeypatch.setenv("VITALS_AUTH_PASSWORD_HASH", hash_password("password"))

    r = await auth_client.post(
        "/settings/password",
        data={
            "old_password": "password",
            "new_password": "brandnewpass",
            "new_password_confirm": "brandnewpass",
        },
    )
    assert r.status_code == 303

    assert authenticate("tester", "password") is False
    assert authenticate("tester", "brandnewpass") is True


async def test_settings_restart_endpoint(auth_client, monkeypatch):
    """POST /settings/restart triggers a delayed restart without killing the process in tests."""
    killed = []

    def mock_kill(pid, sig):
        killed.append((pid, sig))

    monkeypatch.setattr("os.kill", mock_kill)

    r = await auth_client.post("/settings/restart")
    assert r.status_code == 200
    assert r.json() == {"status": "restarting"}

    # Wait for the background task to execute
    import asyncio
    await asyncio.sleep(0.6)

    import os
    assert len(killed) == 1
    assert killed[0] == (os.getpid(), 15)  # 15 is signal.SIGTERM

