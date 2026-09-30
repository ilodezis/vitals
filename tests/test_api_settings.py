"""Tests for /api/v1/settings endpoints and strict secret leak prevention."""
from __future__ import annotations

import io
import json
import os
import pytest

from vitals.services import twofa_service
from web.services.env_writer import read_key, write_keys

URL = "/api/v1/settings"


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch):
    keys = [
        "VITALS_OPENROUTER_API_KEY",
        "VITALS_HEVY_API_KEY",
        "VITALS_GARMIN_EMAIL",
        "VITALS_GARMIN_PASSWORD",
        "VITALS_MCP_CLIENT_ID",
        "VITALS_MCP_CLIENT_SECRET",
        "VITALS_AUTH_PASSWORD_HASH",
        "VITALS_ENV_FILE",
    ]
    for k in keys:
        if k in os.environ:
            monkeypatch.setenv(k, os.environ[k])
        else:
            monkeypatch.setenv(k, "")
            del os.environ[k]


async def test_settings_unauthenticated(client):
    r = await client.get(URL)
    assert r.status_code == 401
    assert r.json() == {"error": "unauthenticated"}


async def test_settings_read_get_structure(auth_client, tmp_path, monkeypatch):
    env_file = tmp_path / "test.env"
    secret_token = "SUPER_SECRET_AI_KEY_12345"
    garmin_pw = "GARMIN_SECRET_PASS_999"
    mcp_secret = "MCP_SECRET_VAL_777"
    env_file.write_text(
        f"VITALS_OPENROUTER_API_KEY={secret_token}\n"
        f"VITALS_GARMIN_EMAIL=test@example.com\n"
        f"VITALS_GARMIN_PASSWORD={garmin_pw}\n"
        f"VITALS_MCP_CLIENT_SECRET={mcp_secret}\n"
        f"VITALS_HEVY_API_KEY=HEVY_KEY_000\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("VITALS_ENV_FILE", str(env_file))

    r = await auth_client.get(URL)
    assert r.status_code == 200
    data = r.json()

    # Structural sections
    assert "username" in data
    assert "profile" in data
    assert "nutrition_goals" in data
    assert "language" in data
    assert "modules" in data
    assert "ai" in data
    assert "hevy" in data
    assert "garmin" in data
    assert "mcp" in data
    assert "security" in data
    assert "proactive" in data

    # CRITICAL SECURITY RULE: No secret strings may appear anywhere in the body!
    raw_text = r.text
    assert secret_token not in raw_text
    assert garmin_pw not in raw_text
    assert mcp_secret not in raw_text
    assert "HEVY_KEY_000" not in raw_text

    # Indicators only
    assert data["ai"]["openrouter_api_key_set"] is True
    assert "openrouter_api_key" not in data["ai"]
    assert data["garmin"]["garmin_password_set"] is True
    assert "garmin_password" not in data["garmin"]
    assert data["mcp"]["mcp_client_secret_set"] is True
    assert "mcp_client_secret" not in data["mcp"]
    assert data["hevy"]["hevy_api_key_set"] is True
    assert "hevy_api_key" not in data["hevy"]
    assert "secret" not in data["security"]


async def test_settings_update_profile(auth_client, tmp_path, monkeypatch):
    env_file = tmp_path / "test.env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("VITALS_ENV_FILE", str(env_file))

    payload = {
        "height_cm": "185",
        "sex": "female",
        "user_age": "30",
        "timezone": "Europe/Berlin",
        "user_program": "Fat loss and toning",
        "user_goals": "Sub 20% fat",
    }
    r = await auth_client.post(f"{URL}/profile", json=payload)
    assert r.status_code == 200
    assert r.json()["saved"] is True

    assert read_key("VITALS_HEIGHT_CM") == "185"
    assert read_key("VITALS_SEX") == "female"
    assert read_key("VITALS_USER_AGE") == "30"
    assert read_key("VITALS_TIMEZONE") == "Europe/Berlin"
    assert read_key("VITALS_USER_PROGRAM") == "Fat loss and toning"
    assert read_key("VITALS_USER_GOALS") == "Sub 20% fat"


async def test_settings_update_nutrition_goals(auth_client, tmp_path, monkeypatch):
    env_file = tmp_path / "test.env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("VITALS_ENV_FILE", str(env_file))

    payload = {
        "nutrition_protein_target_g": "160",
        "nutrition_calories_min": "1500",
        "nutrition_calories_max": "1900",
    }
    r = await auth_client.post(f"{URL}/nutrition", json=payload)
    assert r.status_code == 200
    assert r.json()["saved"] is True

    assert read_key("VITALS_NUTRITION_PROTEIN_TARGET_G") == "160"
    assert read_key("VITALS_NUTRITION_CALORIES_MIN") == "1500"
    assert read_key("VITALS_NUTRITION_CALORIES_MAX") == "1900"


async def test_settings_update_language(auth_client, db_session, redis):
    r = await auth_client.post(f"{URL}/language", json={"language": "en"})
    assert r.status_code == 200
    assert r.json()["saved"] is True

    # Switching back to ru
    r2 = await auth_client.post(f"{URL}/language", json={"language": "ru"})
    assert r2.status_code == 200


async def test_settings_toggle_modules(auth_client, db_session, redis):
    # Toggle an optional module
    r = await auth_client.post(f"{URL}/modules", json={"module": "genetics", "enabled": False})
    assert r.status_code == 200
    assert r.json()["saved"] is True

    # Toggling an invalid / core module should fail
    r_bad = await auth_client.post(f"{URL}/modules", json={"module": "today", "enabled": False})
    assert r_bad.status_code == 400


async def test_settings_update_ai(auth_client, tmp_path, monkeypatch):
    env_file = tmp_path / "test.env"
    env_file.write_text("VITALS_OPENROUTER_API_KEY=existing_key\n", encoding="utf-8")
    monkeypatch.setenv("VITALS_ENV_FILE", str(env_file))

    # Updating with sentinel must not overwrite existing key
    payload = {
        "openrouter_api_key": "••••••••",
        "llm_model_digest": "anthropic/claude-3-opus",
    }
    r = await auth_client.post(f"{URL}/ai", json=payload)
    assert r.status_code == 200
    assert read_key("VITALS_OPENROUTER_API_KEY") == "existing_key"
    assert read_key("VITALS_LLM_MODEL_DIGEST") == "anthropic/claude-3-opus"

    # Updating with real key overwrites
    payload2 = {"openrouter_api_key": "new_secret_key_555"}
    r2 = await auth_client.post(f"{URL}/ai", json=payload2)
    assert r2.status_code == 200
    assert read_key("VITALS_OPENROUTER_API_KEY") == "new_secret_key_555"
    assert "new_secret_key_555" not in r2.text


async def test_settings_update_hevy(auth_client, tmp_path, monkeypatch):
    env_file = tmp_path / "test.env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("VITALS_ENV_FILE", str(env_file))

    r = await auth_client.post(f"{URL}/hevy", json={"hevy_api_key": "hevy_test_secret"})
    assert r.status_code == 200
    assert read_key("VITALS_HEVY_API_KEY") == "hevy_test_secret"
    assert "hevy_test_secret" not in r.text


async def test_settings_update_garmin(auth_client, tmp_path, monkeypatch):
    env_file = tmp_path / "test.env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("VITALS_ENV_FILE", str(env_file))

    r = await auth_client.post(
        f"{URL}/garmin",
        json={"garmin_email": "runner@example.com", "garmin_password": "supersecretpassword"},
    )
    assert r.status_code == 200
    assert read_key("VITALS_GARMIN_EMAIL") == "runner@example.com"
    assert read_key("VITALS_GARMIN_PASSWORD") == "supersecretpassword"
    assert "supersecretpassword" not in r.text


async def test_settings_garmin_weight_actions(auth_client, db_session, tmp_path, monkeypatch):
    env_file = tmp_path / "test.env"
    env_file.write_text("VITALS_GARMIN_EMAIL=a@b.com\nVITALS_GARMIN_PASSWORD=pass\n", encoding="utf-8")
    monkeypatch.setenv("VITALS_ENV_FILE", str(env_file))

    r_toggle = await auth_client.post(f"{URL}/garmin/weight-toggle", json={"enabled": True})
    assert r_toggle.status_code == 200
    assert r_toggle.json()["saved"] is True

    r_send = await auth_client.post(f"{URL}/garmin/weight/send-now")
    assert r_send.status_code == 200
    assert "status" in r_send.json()


async def test_sending_the_weight_with_the_export_off_says_so(auth_client):
    """The screen words its message from this status; "off" must not read as sent."""
    r = await auth_client.post(f"{URL}/garmin/weight/send-now")
    assert r.status_code == 200
    assert r.json() == {"status": "disabled"}


async def test_settings_update_mcp(auth_client, tmp_path, monkeypatch):
    env_file = tmp_path / "test.env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("VITALS_ENV_FILE", str(env_file))

    r = await auth_client.post(
        f"{URL}/mcp",
        json={"mcp_client_id": "custom-connector", "mcp_client_secret": "connector-secret"},
    )
    assert r.status_code == 200
    assert read_key("VITALS_MCP_CLIENT_ID") == "custom-connector"
    assert read_key("VITALS_MCP_CLIENT_SECRET") == "connector-secret"
    assert "connector-secret" not in r.text


async def test_settings_password_change(auth_client, tmp_path, monkeypatch):
    from vitals.utils.passwords import hash_password

    env_file = tmp_path / "test.env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("VITALS_ENV_FILE", str(env_file))
    monkeypatch.setenv("VITALS_AUTH_PASSWORD_HASH", hash_password("password"))

    # Bad old password
    r_bad_old = await auth_client.post(
        f"{URL}/password",
        json={
            "old_password": "wrongpassword",
            "new_password": "newpassword123",
            "new_password_confirm": "newpassword123",
        },
    )
    assert r_bad_old.status_code == 400

    # Short password
    r_short = await auth_client.post(
        f"{URL}/password",
        json={
            "old_password": "password",
            "new_password": "short",
            "new_password_confirm": "short",
        },
    )
    assert r_short.status_code == 400

    # Mismatched password
    r_mismatch = await auth_client.post(
        f"{URL}/password",
        json={
            "old_password": "password",
            "new_password": "validpassword123",
            "new_password_confirm": "differentpassword",
        },
    )
    assert r_mismatch.status_code == 400

    # Valid change
    r_ok = await auth_client.post(
        f"{URL}/password",
        json={
            "old_password": "password",
            "new_password": "freshpassword123",
            "new_password_confirm": "freshpassword123",
        },
    )
    assert r_ok.status_code == 200
    assert r_ok.json()["saved"] is True


async def test_settings_twofa_lifecycle(auth_client, db_session):
    # 1. Start 2FA -> returns QR code, otpauth URI, and secret
    r_start = await auth_client.post(f"{URL}/2fa/start")
    assert r_start.status_code == 200
    data = r_start.json()
    assert "secret" in data
    assert "otpauth_uri" in data
    assert "qr_svg" in data
    assert data["otpauth_uri"].startswith("otpauth://totp/")
    assert "<svg" in data["qr_svg"]

    # 2. Try bad code -> 400
    r_bad = await auth_client.post(f"{URL}/2fa/enable", json={"code": "000000"})
    assert r_bad.status_code == 400

    # 3. Confirm with valid code
    state = await twofa_service.get_state(db_session)
    valid_code = twofa_service.code_at(state.secret, int(twofa_service.time.time() // 30))
    r_enable = await auth_client.post(f"{URL}/2fa/enable", json={"code": valid_code})
    assert r_enable.status_code == 200
    assert r_enable.json()["saved"] is True

    # 4. Starting again when already enabled should fail
    r_start_again = await auth_client.post(f"{URL}/2fa/start")
    assert r_start_again.status_code == 400

    # 5. Disable with correct code
    r_disable = await auth_client.post(f"{URL}/2fa/disable", json={"code": valid_code})
    assert r_disable.status_code == 200
    assert r_disable.json()["saved"] is True


async def test_settings_proactive(auth_client, db_session):
    payload = {
        "brief_time": "10:30",
        "evening_time": "21:00",
        "daily_budget": 5,
        "nudges": ["activity", "nutrition"],
        "week_template": {
            "monday": {"where": "office", "gym": "rest", "load": "normal"},
            "tuesday": {"where": "home", "gym": "workout", "load": "hard"},
        },
    }
    r = await auth_client.post(f"{URL}/proactive", json=payload)
    assert r.status_code == 200
    assert r.json()["saved"] is True


async def test_settings_exports(auth_client):
    r_full = await auth_client.get(f"{URL}/export")
    assert r_full.status_code == 200
    assert "attachment" in r_full.headers.get("content-disposition", "")
    full_data = json.loads(r_full.text)
    assert isinstance(full_data, dict)

    r_llm = await auth_client.get(f"{URL}/export-llm")
    assert r_llm.status_code == 200
    assert "attachment" in r_llm.headers.get("content-disposition", "")
    llm_data = json.loads(r_llm.text)
    assert isinstance(llm_data, dict)


async def test_settings_import(auth_client, db_session):
    from vitals.services.data_portability_service import export_full

    # Malformed file extension
    files = {"backup_file": ("backup.txt", io.BytesIO(b"not json"), "text/plain")}
    r_bad_ext = await auth_client.post(f"{URL}/import", files=files)
    assert r_bad_ext.status_code in (400, 415, 422)

    # Valid JSON backup
    snap = await export_full(db_session)
    files_ok = {"backup_file": ("backup.json", io.BytesIO(json.dumps(snap).encode("utf-8")), "application/json")}
    r_ok = await auth_client.post(f"{URL}/import", files=files_ok)
    assert r_ok.status_code == 200
    assert r_ok.json()["restored"] is True


async def test_settings_restart(auth_client, monkeypatch):
    # Intercept kill to not really kill pytest process
    monkeypatch.setattr("os.kill", lambda pid, sig: None)
    r = await auth_client.post(f"{URL}/restart")
    assert r.status_code == 200
    assert r.json()["status"] == "restarting"
