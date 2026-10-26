"""Passkeys — WebAuthn credentials that sign the owner in without a password.

One row per authenticator the owner registered (iCloud Keychain, Google Password
Manager, a hardware key). The server keeps only the public half: ``public_key``
is useless to anyone holding a copy of the database, which is the whole point.

A service table, like ``shared_reports``: no ``InsightsMixin``. Kept out of the
backup in both directions (``data_portability_service._EXCLUDED_TABLES``) — the
key is public, but a restore that *accepted* rows here would let a crafted backup
file plant a way in.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, Integer, LargeBinary, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from vitals.models.base import Base, TimestampMixin

_JSON_TYPE = JSONB().with_variant(JSON(), "sqlite")


class Passkey(Base, TimestampMixin):
    __tablename__ = "passkeys"

    id: Mapped[int] = mapped_column(primary_key=True)
    # The authenticator's handle for this credential — what a sign-in names.
    credential_id: Mapped[bytes] = mapped_column(
        LargeBinary, nullable=False, unique=True, index=True
    )
    # COSE-encoded, as the authenticator handed it over at registration.
    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # Synced passkeys always report 0; a hardware key counts up, and a counter
    # that goes backwards means a cloned key.
    sign_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # usb / nfc / ble / internal / hybrid — handed back to the browser so it
    # knows where to look for this key when excluding it from a re-registration.
    transports: Mapped[Any] = mapped_column(_JSON_TYPE, nullable=False)
    aaguid: Mapped[str] = mapped_column(String(36), nullable=False)
    # Lives in a synced keychain rather than on one device.
    backed_up: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
