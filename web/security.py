"""Password hashing (bcrypt) — ported from Boxly's ``web/security.py``.

Kept free of FastAPI imports so it is trivially unit-testable. Single-user app, so
there's no JWT/typ machinery here — sessions are signed cookies (see ``auth.py``).
"""
from __future__ import annotations

import os

import bcrypt

# bcrypt hashes at most the first 72 bytes; truncate explicitly so hashing and
# verification always agree on the same input.
_BCRYPT_MAX_BYTES = 72
_BCRYPT_ROUNDS = 4 if os.getenv("VITALS_TESTING") == "1" else 12


def _encode(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_encode(password), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(password: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(_encode(password), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# Throwaway hash to equalize login timing when the username doesn't match: we
# still run one bcrypt verification so "wrong user" and "wrong password" take the
# same wall-clock time (no username-enumeration timing oracle).
_DUMMY_HASH = bcrypt.hashpw(b"timing-equalizer", bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode("utf-8")


def verify_password_dummy(password: str) -> bool:
    verify_password(password, _DUMMY_HASH)
    return False
