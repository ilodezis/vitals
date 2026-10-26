"""Passkeys: registration, sign-in, and everything that must refuse to sign in.

The authenticator here is real cryptography, not a mock of the verifier: a P-256
key signing the same bytes a browser hands over (authenticator data, client data
JSON, an attestation object in CBOR). A passkey check that only agrees with a
fake of itself is exactly the one that turns every real iPhone away.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import time

import cbor2
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select
from webauthn.helpers import bytes_to_base64url

from vitals.models.passkey import Passkey
from vitals.services import data_portability_service, passkey_service, twofa_service
from web.config import PASSKEY_CEREMONY_COOKIE, SESSION_COOKIE

# Spelled out rather than imported from conftest — see test_twofa.py.
TEST_USERNAME = "tester"
TEST_PASSWORD = "password"

ORIGIN = "https://vitals.test"
RP_ID = "vitals.test"

OPTIONS = "/login/passkey/options"
VERIFY = "/login/passkey/verify"
REGISTER_OPTIONS = "/api/v1/settings/passkeys/register/options"
REGISTER_VERIFY = "/api/v1/settings/passkeys/register/verify"

_UP, _UV, _BE, _BS, _AT = 0x01, 0x04, 0x08, 0x10, 0x40


class SoftAuthenticator:
    """One passkey on one pretend device. ``synced`` is iCloud/Google style (counter
    stays 0, backup flags set); otherwise it is a hardware key that counts."""

    def __init__(self, *, synced: bool = True) -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(16)
        self.synced = synced
        self.counter = 0
        self.user_handle: str | None = None

    @property
    def id(self) -> str:
        return bytes_to_base64url(self.credential_id)

    def _flags(self, *, uv: bool, attested: bool = False) -> bytes:
        flags = _UP | (_UV if uv else 0) | (_AT if attested else 0)
        if self.synced:
            flags |= _BE | _BS
        return bytes([flags])

    def _count(self) -> bytes:
        if not self.synced:
            self.counter += 1
        return struct.pack(">I", self.counter)

    def _cose_key(self) -> bytes:
        numbers = self.key.public_key().public_numbers()
        return cbor2.dumps(
            {1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")}
        )

    @staticmethod
    def _client_data(kind: str, challenge: str, origin: str) -> bytes:
        return json.dumps(
            {"type": kind, "challenge": challenge, "origin": origin, "crossOrigin": False}
        ).encode()

    def create(self, options: dict, *, origin: str = ORIGIN, uv: bool = True) -> dict:
        self.user_handle = options["user"]["id"]
        auth_data = (
            hashlib.sha256(options["rp"]["id"].encode()).digest()
            + self._flags(uv=uv, attested=True)
            + self._count()
            + bytes(16)  # AAGUID: none, as with attestation "none"
            + struct.pack(">H", len(self.credential_id))
            + self.credential_id
            + self._cose_key()
        )
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        client_data = self._client_data("webauthn.create", options["challenge"], origin)
        return {
            "id": self.id,
            "rawId": self.id,
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "attestationObject": bytes_to_base64url(attestation),
                "transports": ["internal", "hybrid"],
            },
            "clientExtensionResults": {},
        }

    def get(
        self, options: dict, *, origin: str = ORIGIN, rp_id: str | None = None, uv: bool = True
    ) -> dict:
        auth_data = (
            hashlib.sha256((rp_id or options["rpId"]).encode()).digest()
            + self._flags(uv=uv)
            + self._count()
        )
        client_data = self._client_data("webauthn.get", options["challenge"], origin)
        signature = self.key.sign(
            auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256())
        )
        return {
            "id": self.id,
            "rawId": self.id,
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "authenticatorData": bytes_to_base64url(auth_data),
                "signature": bytes_to_base64url(signature),
                "userHandle": self.user_handle,
            },
            "clientExtensionResults": {},
        }


@pytest.fixture
def passkeys_on(monkeypatch):
    monkeypatch.setenv("VITALS_PUBLIC_ORIGIN", ORIGIN)


async def _register(client, authenticator: SoftAuthenticator, *, name: str = "iPhone", **kwargs):
    options = (await client.post(REGISTER_OPTIONS)).json()
    return await client.post(
        REGISTER_VERIFY, json={"credential": authenticator.create(options, **kwargs), "name": name}
    )


async def _registered(auth_client, **kwargs) -> SoftAuthenticator:
    """A passkey registered while signed in, then the session dropped."""
    authenticator = SoftAuthenticator(**kwargs)
    r = await _register(auth_client, authenticator)
    assert r.status_code == 200, r.text
    auth_client.cookies.clear()
    return authenticator


async def _sign_in(client, authenticator: SoftAuthenticator, *, next: str | None = None, **kwargs):
    options = (await client.post(OPTIONS)).json()
    body = {"credential": authenticator.get(options, **kwargs)}
    if next is not None:
        body["next"] = next
    return await client.post(VERIFY, json=body)


# ── Where passkeys are bound ──────────────────────────────────────────────────
@pytest.mark.parametrize(
    "configured, rp_id, origin",
    [
        ("https://vitals.example.com", "vitals.example.com", "https://vitals.example.com"),
        ("https://Vitals.Example.com/", "vitals.example.com", "https://vitals.example.com"),
        ("https://vitals.example.com:8443", "vitals.example.com", "https://vitals.example.com:8443"),
        ("http://localhost:8000", "localhost", "http://localhost:8000"),
    ],
)
def test_the_relying_party_comes_from_the_public_origin(configured, rp_id, origin):
    assert passkey_service.relying_party(configured) == passkey_service.RelyingParty(rp_id, origin)


@pytest.mark.parametrize(
    "configured",
    [
        "",
        None,
        "vitals.example.com",  # no scheme
        "http://vitals.example.com",  # plain http is only a secure context on localhost
        "https://vitals.example.com/app",  # an RP is a host, not a path
        "https://vitals.example.com/?x=1",
        "https://user@vitals.example.com",
        "https://192.168.1.10",  # browsers refuse an IP address as an RP ID
        "http://127.0.0.1:8000",
        "https://[::1]",
        "ftp://vitals.example.com",
    ],
)
def test_an_origin_passkeys_cannot_use_switches_them_off(configured):
    assert passkey_service.relying_party(configured) is None


async def test_off_without_a_public_origin(client):
    page = await client.get("/login")
    assert "data-passkey" not in page.text
    assert "webauthn" not in page.text
    assert (await client.post(OPTIONS)).status_code == 404


async def test_settings_say_why_passkeys_are_off(auth_client):
    security = (await auth_client.get("/api/v1/settings")).json()["security"]
    assert security["passkeys_available"] is False
    assert security["passkeys"] == []
    assert (await auth_client.post(REGISTER_OPTIONS)).status_code == 400


async def test_the_login_page_offers_the_passkey_when_on(client, passkeys_on):
    page = (await client.get("/login")).text
    assert "data-passkey" in page
    assert 'autocomplete="username webauthn"' in page
    # Still nothing inline for the CSP to have to allow.
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", page)
    assert not re.search(r"\son(click|submit|change|load|input)=", page)


# ── Registration ──────────────────────────────────────────────────────────────
async def test_a_registered_passkey_shows_in_settings(auth_client, passkeys_on):
    authenticator = SoftAuthenticator()
    r = await _register(auth_client, authenticator, name="  iPhone  ")
    assert r.status_code == 200, r.text

    security = (await auth_client.get("/api/v1/settings")).json()["security"]
    assert security["passkeys_available"] is True
    assert security["passkey_rp_id"] == RP_ID
    assert security["passkey_user_id"] == authenticator.user_handle
    [item] = security["passkeys"]
    assert item["name"] == "iPhone"
    assert item["credential_id"] == authenticator.id
    assert item["backed_up"] is True
    assert item["last_used_at"] is None


async def test_options_ask_for_a_discoverable_key_with_user_verification(auth_client, passkeys_on):
    options = (await auth_client.post(REGISTER_OPTIONS)).json()
    assert options["rp"]["id"] == RP_ID
    assert options["authenticatorSelection"]["residentKey"] == "required"
    assert options["authenticatorSelection"]["userVerification"] == "required"
    assert options["attestation"] == "none"
    assert PASSKEY_CEREMONY_COOKIE in auth_client.cookies


async def test_a_second_device_keeps_the_user_handle_and_excludes_the_first(auth_client, passkeys_on):
    first = SoftAuthenticator()
    await _register(auth_client, first)
    options = (await auth_client.post(REGISTER_OPTIONS)).json()
    assert options["user"]["id"] == first.user_handle
    assert [c["id"] for c in options["excludeCredentials"]] == [first.id]


async def test_registration_needs_user_verification(auth_client, passkeys_on, db_session):
    """A key that skips Face ID / PIN would make a passkey sign-in one factor."""
    r = await _register(auth_client, SoftAuthenticator(), uv=False)
    assert r.status_code == 400
    assert await passkey_service.list_passkeys(db_session) == []


async def test_registration_from_another_origin_is_refused(auth_client, passkeys_on, db_session):
    r = await _register(auth_client, SoftAuthenticator(), origin="https://vitals.test.evil.example")
    assert r.status_code == 400
    assert await passkey_service.list_passkeys(db_session) == []


async def test_registration_without_its_options_is_refused(auth_client, passkeys_on):
    options = {"challenge": "AAAA", "rp": {"id": RP_ID}, "user": {"id": "AQID"}}
    r = await auth_client.post(
        REGISTER_VERIFY, json={"credential": SoftAuthenticator().create(options)}
    )
    assert r.status_code == 400


async def test_a_blank_name_gets_a_default(auth_client, passkeys_on, db_session):
    await _register(auth_client, SoftAuthenticator(), name="   ")
    [row] = await passkey_service.list_passkeys(db_session)
    assert row.name  # the client fixture runs in Russian: "Ключ доступа"


# ── Sign-in ───────────────────────────────────────────────────────────────────
async def test_a_passkey_signs_in(auth_client, passkeys_on, db_session):
    authenticator = await _registered(auth_client)
    assert (await auth_client.get("/api/v1/session")).status_code == 401

    r = await _sign_in(auth_client, authenticator, next="/weight")
    assert r.status_code == 200, r.text
    assert r.json() == {"redirect": "/weight"}
    assert SESSION_COOKIE in r.cookies
    assert (await auth_client.get("/api/v1/session")).status_code == 200

    [row] = await passkey_service.list_passkeys(db_session)
    await db_session.refresh(row)
    assert row.last_used_at is not None


async def test_a_passkey_does_not_ask_for_the_totp_code(auth_client, passkeys_on, db_session):
    """The decision this feature rests on: the authenticator already checked the
    owner's face or PIN, so the passkey is the whole sign-in."""
    secret = await twofa_service.start_enrolment(db_session)
    code = twofa_service.code_at(secret, int(time.time()) // twofa_service.STEP_SECONDS)
    assert await twofa_service.confirm_enrolment(db_session, code)
    await db_session.commit()

    authenticator = await _registered(auth_client)
    r = await _sign_in(auth_client, authenticator)
    assert r.status_code == 200
    assert SESSION_COOKIE in r.cookies


async def test_the_redirect_stays_on_this_site(auth_client, passkeys_on):
    authenticator = await _registered(auth_client)
    r = await _sign_in(auth_client, authenticator, next="//evil.example/steal")
    assert r.json() == {"redirect": "/"}


async def test_an_assertion_cannot_be_replayed(auth_client, passkeys_on):
    authenticator = await _registered(auth_client)
    options = (await auth_client.post(OPTIONS)).json()
    assertion = authenticator.get(options)
    assert (await auth_client.post(VERIFY, json={"credential": assertion})).status_code == 200
    auth_client.cookies.delete(SESSION_COOKIE)

    # Same ceremony again: the challenge was spent.
    again = await auth_client.post(VERIFY, json={"credential": assertion})
    assert again.status_code == 400
    assert again.json() == {"error": "expired"}

    # A fresh ceremony: the old signature is over the old challenge.
    await auth_client.post(OPTIONS)
    later = await auth_client.post(VERIFY, json={"credential": assertion})
    assert later.status_code == 400
    assert SESSION_COOKIE not in later.cookies


async def test_sign_in_needs_user_verification(auth_client, passkeys_on):
    authenticator = await _registered(auth_client)
    r = await _sign_in(auth_client, authenticator, uv=False)
    assert r.status_code == 400
    assert SESSION_COOKIE not in r.cookies


@pytest.mark.parametrize(
    "tamper",
    [{"origin": "https://evil.example"}, {"rp_id": "evil.example"}],
    ids=["origin", "rp_id"],
)
async def test_a_signature_for_another_site_is_refused(auth_client, passkeys_on, tamper):
    authenticator = await _registered(auth_client)
    r = await _sign_in(auth_client, authenticator, **tamper)
    assert r.status_code == 400
    assert SESSION_COOKIE not in r.cookies


async def test_a_forged_signature_is_refused(auth_client, passkeys_on):
    authenticator = await _registered(auth_client)
    impostor = SoftAuthenticator()
    impostor.credential_id = authenticator.credential_id  # right id, wrong key
    r = await _sign_in(auth_client, impostor)
    assert r.status_code == 400


async def test_a_key_unknown_here_is_named_so_the_phone_can_forget_it(auth_client, passkeys_on):
    r = await _sign_in(auth_client, SoftAuthenticator())
    assert r.status_code == 400
    assert r.json() == {"error": "unknown_credential"}


async def test_a_registration_challenge_cannot_complete_a_sign_in(auth_client, passkeys_on):
    authenticator = SoftAuthenticator()
    await _register(auth_client, authenticator)
    options = (await auth_client.post(REGISTER_OPTIONS)).json()
    auth_client.cookies.delete(SESSION_COOKIE)
    r = await auth_client.post(
        VERIFY, json={"credential": authenticator.get({**options, "rpId": RP_ID})}
    )
    assert r.json() == {"error": "expired"}
    assert SESSION_COOKIE not in r.cookies


async def test_without_the_ceremony_cookie_nothing_completes(auth_client, passkeys_on):
    authenticator = await _registered(auth_client)
    options = (await auth_client.post(OPTIONS)).json()
    auth_client.cookies.delete(PASSKEY_CEREMONY_COOKIE)
    r = await auth_client.post(VERIFY, json={"credential": authenticator.get(options)})
    assert r.json() == {"error": "expired"}


async def test_a_counter_going_backwards_reads_as_a_cloned_key(auth_client, passkeys_on):
    authenticator = await _registered(auth_client, synced=False)
    assert (await _sign_in(auth_client, authenticator)).status_code == 200
    auth_client.cookies.delete(SESSION_COOKIE)
    authenticator.counter = 0
    r = await _sign_in(auth_client, authenticator)
    assert r.status_code == 400
    assert SESSION_COOKIE not in r.cookies


class _DeadRedis:
    async def set(self, *args, **kwargs):
        raise ConnectionError("redis is down")

    async def getdel(self, *args, **kwargs):
        raise ConnectionError("redis is down")

    async def incr(self, *args, **kwargs):
        raise ConnectionError("redis is down")

    async def expire(self, *args, **kwargs):
        raise ConnectionError("redis is down")


async def test_without_redis_passkeys_fail_closed(client, passkeys_on):
    """No store, no way to tell a fresh assertion from a replayed one."""
    from web.deps import get_redis
    from web.main import app

    async def _dead():
        return _DeadRedis()

    app.dependency_overrides[get_redis] = _dead
    assert (await client.post(OPTIONS)).status_code == 503
    assert await passkey_service.take_ceremony(_DeadRedis(), "any", passkey_service.LOGIN) is None
    # The password form doesn't depend on it.
    r = await client.post("/login", data={"username": TEST_USERNAME, "password": TEST_PASSWORD})
    assert r.status_code == 303


# ── Removing one ──────────────────────────────────────────────────────────────
async def test_a_removed_passkey_signs_nobody_in(auth_client, passkeys_on, db_session):
    authenticator = SoftAuthenticator()
    await _register(auth_client, authenticator)
    [item] = (await auth_client.get("/api/v1/settings")).json()["security"]["passkeys"]
    assert (await auth_client.delete(f"/api/v1/settings/passkeys/{item['id']}")).status_code == 200
    assert (await auth_client.delete(f"/api/v1/settings/passkeys/{item['id']}")).status_code == 404

    auth_client.cookies.clear()
    r = await _sign_in(auth_client, authenticator)
    assert r.json() == {"error": "unknown_credential"}


# ── Backups ───────────────────────────────────────────────────────────────────
async def test_a_backup_neither_carries_nor_plants_passkeys(auth_client, passkeys_on, db_session):
    """Every row is a way in: a crafted backup must not be able to add one, and
    restoring a real one must not drop the keys the owner enrolled."""
    await _register(auth_client, SoftAuthenticator())
    [mine] = await passkey_service.list_passkeys(db_session)
    mine_id = mine.credential_id

    snapshot = await data_portability_service.export_full(db_session)
    assert "passkeys" not in snapshot

    planted = SoftAuthenticator()
    snapshot["passkeys"] = [
        {
            "id": 99,
            "credential_id": bytes_to_base64url(planted.credential_id),
            "public_key": bytes_to_base64url(planted._cose_key()),
            "sign_count": 0,
            "transports": [],
            "aaguid": "00000000-0000-0000-0000-000000000000",
            "backed_up": False,
            "name": "planted",
        }
    ]
    await data_portability_service.import_full(db_session, snapshot)
    await db_session.commit()

    rows = (await db_session.execute(select(Passkey))).scalars().all()
    assert [r.credential_id for r in rows] == [mine_id]
