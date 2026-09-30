"""Tests for the env_writer utility and the settings rules behind /api/v1/settings
(secret placeholders, Garmin weight export, password change, restart, proactive clamping)."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# No module-level ``pytest.mark.asyncio``: pytest.ini runs asyncio_mode=auto, and
# the mark on this file's *sync* env_writer tests only produced warnings.


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


def test_env_writer_write_rejects_newline_in_value(tmp_path, monkeypatch):
    """write_keys refuses a value containing \\n or \\r — unescaped, it would
    break out of its KEY=value line and inject/overwrite another env var."""
    env_file = tmp_path / "test.env"
    env_file.write_text("VITALS_A=old_a\n", encoding="utf-8")
    monkeypatch.setenv("VITALS_ENV_FILE", str(env_file))
    from web.services.env_writer import write_keys

    with pytest.raises(ValueError):
        write_keys({"VITALS_A": "evil\nVITALS_SESSION_SECRET=hijacked"})
    with pytest.raises(ValueError):
        write_keys({"VITALS_A": "evil\rcarriage"})

    # Rejected write must not have touched the file.
    content = env_file.read_text(encoding="utf-8")
    assert content == "VITALS_A=old_a\n"


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


# ── settings API rules ───────────────────────────────────────────────────────

URL = "/api/v1/settings"


async def test_settings_page_requires_auth(client):
    """GET /settings redirects to login when unauthenticated."""
    r = await client.get("/settings", headers={"Accept": "text/html"})
    assert r.status_code == 302
    assert "/login" in r.headers["location"]


async def test_settings_save_ai_empty_key_not_overwritten(auth_client, tmp_path, monkeypatch):
    """An empty key field means "no change": the stored key survives while the
    other AI fields are saved."""
    env_file = tmp_path / "test.env"
    env_file.write_text("VITALS_OPENROUTER_API_KEY=sk-or-real-key\n", encoding="utf-8")
    monkeypatch.setenv("VITALS_ENV_FILE", str(env_file))

    r = await auth_client.post(
        f"{URL}/ai",
        json={
            "openrouter_api_key": "",  # empty = no change
            "llm_model_digest": "anthropic/claude-sonnet-4.6",
            "llm_model_parser": "google/gemini-2.5-flash",
            "openrouter_base_url": "https://openrouter.ai/api/v1",
        },
    )
    assert r.status_code == 200
    content = env_file.read_text(encoding="utf-8")
    assert "VITALS_OPENROUTER_API_KEY=sk-or-real-key" in content
    assert "VITALS_LLM_MODEL_DIGEST=anthropic/claude-sonnet-4.6" in content


async def test_settings_save_garmin_is_live_and_leaves_export_off(
    auth_client, db_session, tmp_path, monkeypatch
):
    """Credential saves are live, while export remains a separate explicit opt-in."""
    env_file = tmp_path / "test.env"
    env_file.write_text("VITALS_GARMIN_EMAIL=\nVITALS_GARMIN_PASSWORD=\n", encoding="utf-8")
    monkeypatch.setenv("VITALS_ENV_FILE", str(env_file))
    monkeypatch.setenv("VITALS_GARMIN_EMAIL", "")
    monkeypatch.setenv("VITALS_GARMIN_PASSWORD", "")

    r = await auth_client.post(
        f"{URL}/garmin",
        json={"garmin_email": "user@example.com", "garmin_password": "hunter2"},
    )
    assert r.status_code == 200

    content = env_file.read_text(encoding="utf-8")
    assert "VITALS_GARMIN_EMAIL=user@example.com" in content
    assert "VITALS_GARMIN_PASSWORD=hunter2" in content

    from vitals.services import garmin_weight_service

    assert os.environ["VITALS_GARMIN_EMAIL"] == "user@example.com"
    assert os.environ["VITALS_GARMIN_PASSWORD"] == "hunter2"
    assert await garmin_weight_service.is_enabled(db_session) is False


async def test_garmin_weight_toggle_refuses_missing_credentials(
    auth_client, db_session, tmp_path, monkeypatch
):
    env_file = tmp_path / "test.env"
    env_file.write_text("VITALS_GARMIN_EMAIL=\nVITALS_GARMIN_PASSWORD=\n", encoding="utf-8")
    monkeypatch.setenv("VITALS_ENV_FILE", str(env_file))
    monkeypatch.setenv("VITALS_GARMIN_EMAIL", "")
    monkeypatch.setenv("VITALS_GARMIN_PASSWORD", "")

    r = await auth_client.post(f"{URL}/garmin/weight-toggle", json={"enabled": True})

    assert r.status_code == 400
    assert "credentials_required" in r.text
    from vitals.services import garmin_weight_service

    assert await garmin_weight_service.is_enabled(db_session) is False


async def test_garmin_weight_toggle_applies_live_and_can_turn_off(
    auth_client, db_session, tmp_path, monkeypatch
):
    env_file = tmp_path / "test.env"
    env_file.write_text(
        "VITALS_GARMIN_EMAIL=user@example.com\nVITALS_GARMIN_PASSWORD=hunter2\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("VITALS_ENV_FILE", str(env_file))
    monkeypatch.setenv("VITALS_GARMIN_EMAIL", "")
    monkeypatch.setenv("VITALS_GARMIN_PASSWORD", "")

    enabled = await auth_client.post(f"{URL}/garmin/weight-toggle", json={"enabled": True})

    assert enabled.status_code == 200
    assert os.environ["VITALS_GARMIN_EMAIL"] == "user@example.com"
    assert os.environ["VITALS_GARMIN_PASSWORD"] == "hunter2"

    from vitals.services import garmin_weight_service

    assert await garmin_weight_service.is_enabled(db_session) is True

    disabled = await auth_client.post(f"{URL}/garmin/weight-toggle", json={"enabled": False})
    assert disabled.status_code == 200
    assert await garmin_weight_service.is_enabled(db_session) is False


async def test_garmin_weight_send_now_calls_safe_service(auth_client, monkeypatch):
    from vitals.services import garmin_weight_service

    called = {}

    async def _send_now(session, *, redis=None):
        called["session"] = session
        called["redis"] = redis
        return {"status": "sent", "sent": True}

    monkeypatch.setattr(garmin_weight_service, "send_now", _send_now)
    r = await auth_client.post(f"{URL}/garmin/weight/send-now")

    assert r.status_code == 200
    assert r.json() == {"status": "sent"}
    assert called["session"] is not None
    assert called["redis"] is not None


@pytest.mark.parametrize(
    "old, new, confirm, reason",
    [
        ("wrongpassword", "newpassword123", "newpassword123", "wrong_password"),
        ("password", "newpass123", "different456", "password_mismatch"),
        ("password", "short", "short", "password_too_short"),
    ],
)
async def test_settings_change_password_rejections_name_their_reason(
    auth_client, tmp_path, monkeypatch, old, new, confirm, reason
):
    from vitals.utils.passwords import hash_password

    env_file = tmp_path / "test.env"
    env_file.write_text("VITALS_AUTH_PASSWORD_HASH=old_hash\n", encoding="utf-8")
    monkeypatch.setenv("VITALS_ENV_FILE", str(env_file))
    monkeypatch.setenv("VITALS_AUTH_PASSWORD_HASH", hash_password("password"))

    r = await auth_client.post(
        f"{URL}/password",
        json={"old_password": old, "new_password": new, "new_password_confirm": confirm},
    )
    assert r.status_code == 400
    assert reason in r.text
    # A rejected change leaves the stored hash alone.
    assert env_file.read_text(encoding="utf-8") == "VITALS_AUTH_PASSWORD_HASH=old_hash\n"


async def test_settings_change_password_writes_hash_and_takes_effect_live(
    auth_client, tmp_path, monkeypatch
):
    """After a password change the new hash is stored, the new password
    authenticates and the old one no longer does — in the same process, without
    a container restart."""
    from web.auth import authenticate
    from vitals.utils.passwords import hash_password

    env_file = tmp_path / "test.env"
    env_file.write_text("VITALS_AUTH_PASSWORD_HASH=old_hash\n", encoding="utf-8")
    monkeypatch.setenv("VITALS_ENV_FILE", str(env_file))
    # Pin a known starting hash so monkeypatch restores it on teardown — the
    # handler mutates os.environ directly, which would otherwise leak to later tests.
    monkeypatch.setenv("VITALS_AUTH_PASSWORD_HASH", hash_password("password"))

    r = await auth_client.post(
        f"{URL}/password",
        json={
            "old_password": "password",  # matches TEST_PASSWORD in conftest
            "new_password": "brandnewpass",
            "new_password_confirm": "brandnewpass",
        },
    )
    assert r.status_code == 200

    content = env_file.read_text(encoding="utf-8")
    assert "$2b$" in content  # bcrypt hash
    assert "old_hash" not in content

    assert authenticate("tester", "password") is False
    assert authenticate("tester", "brandnewpass") is True


async def test_settings_restart_schedules_a_sigterm(auth_client, monkeypatch):
    """POST /settings/restart triggers a delayed restart without killing the process in tests."""
    killed = []

    def mock_kill(pid, sig):
        killed.append((pid, sig))

    monkeypatch.setattr("os.kill", mock_kill)

    r = await auth_client.post(f"{URL}/restart")
    assert r.status_code == 200
    assert r.json() == {"status": "restarting"}

    # Wait for the background task to execute
    import asyncio
    await asyncio.sleep(0.6)

    assert len(killed) == 1
    assert killed[0] == (os.getpid(), 15)  # 15 is signal.SIGTERM


# ── proactive settings regressions ────────────────────────────────────────────

PROACTIVE_FORM = {
    "brief_time": "11:00",
    "evening_time": "23:45",
    "quiet_start": "02:00",
    "quiet_end": "10:00",
    "garmin_sync_hours": 6,
    "pulse_seconds": 900,
    "pulse_start_hour": 8,
    "pulse_end_hour": 24,
}


async def test_settings_save_proactive_flags_adjusted_values(auth_client):
    """prefs.sanitize() (called inside prefs.set_prefs) silently clamps
    out-of-range input. The response must say so instead of a bare "saved",
    or the user has no way to know their number was changed underneath them."""
    r = await auth_client.post(
        f"{URL}/proactive",
        json={**PROACTIVE_FORM, "daily_budget": 9000},  # BUDGET_RANGE is (1, 12) — gets clamped
    )
    assert r.status_code == 200
    assert r.json()["saved"] is True
    assert r.json()["adjusted"] is True


async def test_settings_save_proactive_no_adjusted_flag_in_range(auth_client):
    """The flip side: an in-range save must not claim anything was adjusted."""
    r = await auth_client.post(f"{URL}/proactive", json={**PROACTIVE_FORM, "daily_budget": 4})
    assert r.status_code == 200
    assert r.json()["saved"] is True
    assert not r.json()["adjusted"]
