"""Token-session guarantees of ``GarminClient`` against the real ``garminconnect``.

The service tests drive a fake client, so nothing else exercises the library
itself. These pin the two properties a ``garminconnect`` upgrade could silently
break: a stored session still round-trips, and a session the API rejects never
escalates into a credential login (the path that gets the account blocked).
No network is touched — the profile fetch and the SSO login are stubbed.
"""
from __future__ import annotations

import base64
import json
import time

import pytest

garminconnect = pytest.importorskip("garminconnect")

from garminconnect import Garmin  # noqa: E402
from garminconnect.exceptions import GarminConnectAuthenticationError  # noqa: E402

from vitals.config import Config  # noqa: E402
from vitals.integrations.garmin_client import GarminClient  # noqa: E402


def _b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


def _session_token() -> str:
    """A session shaped like ``client.dumps()``: a JWT that is not about to
    expire (so no refresh call), padded to the size of a real one."""
    jwt = f"{_b64({'alg': 'none'})}.{_b64({'exp': int(time.time()) + 86400, 'pad': 'x' * 1500})}.sig"
    return json.dumps({"di_token": jwt, "di_refresh_token": "refresh", "di_client_id": "client"})


@pytest.fixture
def credential_logins(monkeypatch):
    calls: list[tuple] = []
    client_cls = type(Garmin("user@example.com", "secret").client)

    def _refuse(self, *args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("credential login attempted")

    monkeypatch.setattr(client_cls, "login", _refuse)
    return calls


def _client(tmp_path) -> GarminClient:
    return GarminClient(
        Config(
            database_url="", redis_url="",
            garmin_email="user@example.com", garmin_password="secret",
            garmin_token_dir=str(tmp_path / "no-session"),
        )
    )


def test_stored_session_resumes_and_round_trips(tmp_path, monkeypatch, credential_logins):
    monkeypatch.setattr(Garmin, "_load_profile_and_settings", lambda self: None)
    token = _session_token()

    garmin = _client(tmp_path)._resume_blocking(token)

    assert garmin is not None
    assert json.loads(garmin.client.dumps()) == json.loads(token)
    assert credential_logins == []


def test_rejected_session_never_escalates_to_credential_login(
    tmp_path, monkeypatch, credential_logins
):
    def _rejected(self):
        raise GarminConnectAuthenticationError("401 token rejected")

    monkeypatch.setattr(Garmin, "_load_profile_and_settings", _rejected)

    assert _client(tmp_path)._resume_blocking(_session_token()) is None
    assert credential_logins == []
