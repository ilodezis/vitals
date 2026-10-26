"""Passkeys (WebAuthn) — sign in with Face ID / Touch ID / a security key.

A passkey is a sign-in of its own, not a step after the password: the
authenticator proves possession of the device *and* checks the owner's face,
fingerprint or PIN before it signs (``userVerification: required``, enforced
server-side below). That is two factors in one gesture, so a passkey sign-in
mints the session directly and does not ask for the TOTP code. The password
(plus 2FA, when on) stays as the way back in.

The verification is py_webauthn's. TOTP is twenty lines of HMAC and lives in the
stdlib (``twofa_service``); WebAuthn is CBOR, COSE keys, authenticator-data flags
and three signature algorithms — precisely the parsing where a home-grown copy
grows holes. Attestation is ``none``: Vitals has one user and no policy about
which vendor made the key, so there is no certificate chain to check.

Challenges live in Redis for :data:`CEREMONY_TTL` seconds, keyed by a random
ceremony id the browser carries in a cookie, and are taken with ``GETDEL`` so
each one is spent once. Unlike the 2FA replay store this **fails closed**: with
Redis down there is no way to tell a fresh assertion from a replayed one, so
passkey sign-in is unavailable and the password form still works.
"""
from __future__ import annotations

import json
import logging
import secrets
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import (
    base64url_to_bytes,
    bytes_to_base64url,
    parse_authentication_credential_json,
    parse_registration_credential_json,
)
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from vitals.models.app_settings import AppSetting
from vitals.models.passkey import Passkey
from vitals.utils.timeutils import now_local

logger = logging.getLogger(__name__)

# The WebAuthn user.id every passkey is registered under. Random, stable, and no
# personal data in it (the spec forbids that). Stable matters: re-registering on
# the same phone then replaces its old Vitals passkey instead of adding a second
# one beside it.
USER_HANDLE_KEY = "passkey_user_handle"

RP_NAME = "Vitals"
CEREMONY_TTL = 300
NAME_MAX = 64

LOGIN = "login"
REGISTER = "register"


class PasskeyError(Exception):
    """A ceremony that must not complete. ``code`` is what the client switches on."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# ── Relying party ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class RelyingParty:
    rp_id: str
    origin: str


def relying_party(public_origin: Optional[str]) -> Optional[RelyingParty]:
    """The RP behind ``VITALS_PUBLIC_ORIGIN``, or None when passkeys can't work.

    A bare origin only: https, or http on ``localhost`` (the one plain-http host a
    browser treats as a secure context). The RP ID is its host — never an IP
    address, which browsers refuse as an RP ID.
    """
    raw = (public_origin or "").strip().rstrip("/")
    if not raw:
        return None
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if not host or parts.username or parts.password:
        return None
    if parts.path or parts.query or parts.fragment:
        return None
    if parts.scheme == "http":
        if host != "localhost":
            return None
    elif parts.scheme != "https":
        return None
    if host.replace(".", "").isdigit() or ":" in host:
        return None
    origin = f"{parts.scheme}://{host}" + (f":{port}" if port is not None else "")
    return RelyingParty(rp_id=host, origin=origin)


# ── Stored credentials ───────────────────────────────────────────────────────
async def peek_user_handle(session: AsyncSession) -> Optional[bytes]:
    """The owner's WebAuthn user handle, or None before the first registration."""
    row = await session.get(AppSetting, USER_HANDLE_KEY)
    if row is None or not isinstance(row.value, str):
        return None
    try:
        return base64url_to_bytes(row.value) or None
    except ValueError:
        return None


async def get_user_handle(session: AsyncSession) -> bytes:
    """The owner's WebAuthn user handle, minted on first use. Flushes; caller commits."""
    handle = await peek_user_handle(session)
    if handle:
        return handle
    handle = secrets.token_bytes(32)
    row = await session.get(AppSetting, USER_HANDLE_KEY)
    if row is None:
        session.add(AppSetting(key=USER_HANDLE_KEY, value=bytes_to_base64url(handle)))
    else:
        row.value = bytes_to_base64url(handle)
    await session.flush()
    return handle


async def list_passkeys(session: AsyncSession) -> list[Passkey]:
    result = await session.execute(select(Passkey).order_by(Passkey.created_at, Passkey.id))
    return list(result.scalars().all())


async def delete_passkey(session: AsyncSession, passkey_id: int) -> bool:
    row = await session.get(Passkey, passkey_id)
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


async def _by_credential_id(session: AsyncSession, credential_id: bytes) -> Optional[Passkey]:
    result = await session.execute(select(Passkey).where(Passkey.credential_id == credential_id))
    return result.scalar_one_or_none()


def _transports(values: Any) -> list[AuthenticatorTransport]:
    out = []
    for value in values or ():
        try:
            out.append(AuthenticatorTransport(value))
        except ValueError:
            continue
    return out


# ── Registration (signed-in owner adds a passkey) ─────────────────────────────
async def registration_options(
    session: AsyncSession, rp: RelyingParty, *, username: str
) -> tuple[str, bytes]:
    """Options for ``navigator.credentials.create()`` as JSON, and their challenge.

    Every key already registered is excluded, so the browser says "this device is
    already set up" instead of quietly minting a duplicate.
    """
    existing = await list_passkeys(session)
    options = generate_registration_options(
        rp_id=rp.rp_id,
        rp_name=RP_NAME,
        user_id=await get_user_handle(session),
        user_name=username,
        user_display_name=username,
        timeout=CEREMONY_TTL * 1000,
        authenticator_selection=AuthenticatorSelectionCriteria(
            # Discoverable: sign-in then needs no username, and the key shows up
            # in the login field's autofill.
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=p.credential_id, transports=_transports(p.transports))
            for p in existing
        ],
    )
    return options_to_json(options), options.challenge


async def finish_registration(
    session: AsyncSession,
    rp: RelyingParty,
    *,
    credential: Any,
    challenge: bytes,
    name: str,
) -> Passkey:
    """Check the browser's answer to :func:`registration_options` and store the key.

    Raises :class:`PasskeyError` (``invalid`` / ``already_registered``). Flushes;
    caller commits.
    """
    try:
        parsed = parse_registration_credential_json(credential)
        verified = verify_registration_response(
            credential=parsed,
            expected_challenge=challenge,
            expected_rp_id=rp.rp_id,
            expected_origin=rp.origin,
            # A key that skips the face/PIN check would make a passkey sign-in a
            # single factor while it bypasses the TOTP step. The library's
            # default is False.
            require_user_verification=True,
        )
    except WebAuthnException as exc:
        logger.info("passkey registration rejected: %s", exc)
        raise PasskeyError("invalid") from exc

    if await _by_credential_id(session, verified.credential_id) is not None:
        raise PasskeyError("already_registered")

    row = Passkey(
        credential_id=verified.credential_id,
        public_key=verified.credential_public_key,
        sign_count=verified.sign_count,
        transports=[t.value for t in parsed.response.transports or ()],
        aaguid=verified.aaguid,
        backed_up=verified.credential_backed_up,
        name=name.strip()[:NAME_MAX],
        # Local wall-clock, like ``last_used_at``: the server default is the
        # database's clock (UTC), and the list shows the two side by side.
        created_at=now_local(),
    )
    session.add(row)
    await session.flush()
    return row


# ── Sign-in ───────────────────────────────────────────────────────────────────
def authentication_options(rp: RelyingParty) -> tuple[str, bytes]:
    """Options for ``navigator.credentials.get()`` as JSON, and their challenge.

    No allow-list: the browser offers whichever Vitals passkey it holds, which is
    what lets the login form show it in autofill before anything is typed.
    """
    options = generate_authentication_options(
        rp_id=rp.rp_id,
        timeout=CEREMONY_TTL * 1000,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return options_to_json(options), options.challenge


async def finish_authentication(
    session: AsyncSession,
    rp: RelyingParty,
    *,
    credential: Any,
    challenge: bytes,
) -> Passkey:
    """Check a signed assertion and return the passkey that made it.

    Raises :class:`PasskeyError`: ``unknown_credential`` when no stored key has
    that id (deleted here, still on the phone), ``invalid`` for everything else.
    Records the use. Flushes; caller commits.
    """
    try:
        parsed = parse_authentication_credential_json(credential)
    except WebAuthnException as exc:
        raise PasskeyError("invalid") from exc

    row = await _by_credential_id(session, parsed.raw_id)
    if row is None:
        raise PasskeyError("unknown_credential")

    try:
        verified = verify_authentication_response(
            credential=parsed,
            expected_challenge=challenge,
            expected_rp_id=rp.rp_id,
            expected_origin=rp.origin,
            credential_public_key=row.public_key,
            credential_current_sign_count=row.sign_count,
            require_user_verification=True,
        )
    except WebAuthnException as exc:
        logger.info("passkey sign-in rejected for passkey %s: %s", row.id, exc)
        raise PasskeyError("invalid") from exc

    row.sign_count = verified.new_sign_count
    row.backed_up = verified.credential_backed_up
    row.last_used_at = now_local()
    await session.flush()
    return row


# ── Ceremony store (Redis) ───────────────────────────────────────────────────
def _ceremony_key(ceremony_id: str) -> str:
    return f"passkey:ceremony:{ceremony_id}"


async def start_ceremony(redis, kind: str, challenge: bytes) -> str:
    """Remember a challenge for :data:`CEREMONY_TTL` seconds; return its ceremony id.

    Raises whatever Redis raises — a ceremony that can't be remembered can't be
    finished, and saying so now beats a failure after the Face ID prompt.
    """
    ceremony_id = secrets.token_urlsafe(32)
    payload = json.dumps({"kind": kind, "challenge": bytes_to_base64url(challenge)})
    await redis.set(_ceremony_key(ceremony_id), payload, ex=CEREMONY_TTL)
    return ceremony_id


async def take_ceremony(redis, ceremony_id: Optional[str], kind: str) -> Optional[bytes]:
    """Spend a ceremony: its challenge, or None if absent, expired, used, of the
    other kind — or if Redis can't be asked (fail closed, see the module doc)."""
    if not ceremony_id or redis is None:
        return None
    try:
        raw = await redis.getdel(_ceremony_key(ceremony_id))
    except Exception:
        logger.warning("passkey ceremony store unavailable; refusing", exc_info=True)
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if data.get("kind") != kind:
            return None
        return base64url_to_bytes(data["challenge"])
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


def credential_id_text(passkey: Passkey) -> str:
    """The credential id as the browser spells it (base64url)."""
    return bytes_to_base64url(passkey.credential_id)


def user_handle_text(handle: bytes) -> str:
    return bytes_to_base64url(handle)
