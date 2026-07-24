"""Password hashing with the standard library only (no bcrypt/passlib dep).

PBKDF2-HMAC-SHA256 with a per-user random salt and a high iteration count. The
salt and iteration count are encoded into a single ``password_hash`` string
(``pbkdf2_sha256$iterations$salt$hash``) so it fits the users.password_hash column.
"""

import hashlib
import hmac
import secrets

_ALGO = "pbkdf2_sha256"
_ITERATIONS = 200_000


def hash_password(password: str, *, salt: str | None = None, iterations: int = _ITERATIONS) -> str:
    """Return a self-describing ``pbkdf2_sha256$iterations$salt$hash`` string."""
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations)
    return f"{_ALGO}${iterations}${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time verify against a stored ``pbkdf2_sha256$...`` string."""
    try:
        algo, iterations, salt, expected = stored.split("$", 3)
    except ValueError:
        return False
    if algo != _ALGO:
        return False
    candidate = hash_password(password, salt=salt, iterations=int(iterations))
    return hmac.compare_digest(candidate, stored)
