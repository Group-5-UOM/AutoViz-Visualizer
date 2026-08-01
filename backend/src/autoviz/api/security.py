"""Password hashing via pwdlib (Argon2id), with legacy PBKDF2 verify for old rows."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from pwdlib import PasswordHash

_hasher = PasswordHash.recommended()

_LEGACY_ALGO = "pbkdf2_sha256"
_LEGACY_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    """Hash a password with the recommended algorithm (Argon2id via pwdlib)."""
    return _hasher.hash(password)


def verify_password(plain_password: str, stored_hash: str | None) -> bool:
    """Return True if ``plain_password`` matches ``stored_hash``.

    Supports new pwdlib hashes and legacy ``pbkdf2_sha256$...`` values written
    before the Argon2 migration.
    """
    if not stored_hash:
        return False
    if stored_hash.startswith(_LEGACY_ALGO + "$"):
        return _verify_legacy_pbkdf2(plain_password, stored_hash)
    try:
        return _hasher.verify(plain_password, stored_hash)
    except Exception:
        return False


def needs_rehash(stored_hash: str | None) -> bool:
    """True when the stored hash should be upgraded to Argon2 on next login."""
    if not stored_hash:
        return False
    return stored_hash.startswith(_LEGACY_ALGO + "$")


def _verify_legacy_pbkdf2(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt, _expected = stored.split("$", 3)
    except ValueError:
        return False
    if algo != _LEGACY_ALGO:
        return False
    salt = salt
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        int(iterations),
    )
    candidate = f"{_LEGACY_ALGO}${iterations}${salt}${dk.hex()}"
    return hmac.compare_digest(candidate, stored)


def legacy_hash_password_for_tests(password: str) -> str:
    """Keep a PBKDF2 helper available for migration tests only."""
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), _LEGACY_ITERATIONS
    )
    return f"{_LEGACY_ALGO}${_LEGACY_ITERATIONS}${salt}${dk.hex()}"
