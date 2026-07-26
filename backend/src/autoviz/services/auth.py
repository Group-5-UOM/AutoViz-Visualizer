"""Authentication service — password hashing, JWT creation/decoding, user CRUD.

All business logic lives here; routes are thin adapters.
"""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from sqlalchemy.orm import Session

from autoviz.core.config import settings
from autoviz.models.user import User

# ── Password hashing ────────────────────────────────────────────────────


def hash_password(plain: str) -> str:
    """One-way bcrypt hash."""
    salt = bcrypt.gensalt()
    hashed_bytes = bcrypt.hashpw(plain.encode("utf-8"), salt)
    return hashed_bytes.decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Check a plain-text password against its bcrypt hash."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ── JWT tokens ───────────────────────────────────────────────────────────


def create_access_token(user_id: str) -> tuple[str, datetime]:
    """Create a signed JWT and return ``(token, expires_at)``.

    The caller needs *expires_at* to write the matching ``sessions`` row and
    to set the cookie's ``max_age``.
    """
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": user_id,
        "exp": expires_at,
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return token, expires_at


def decode_access_token(token: str) -> str | None:
    """Decode a JWT and return the ``user_id`` (the ``sub`` claim).

    Returns ``None`` on any failure (bad signature, expired, malformed).
    """
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        return payload.get("sub")
    except jwt.PyJWTError:
        return None


# ── User operations ──────────────────────────────────────────────────────


def register_user(db: Session, email: str, password: str) -> User:
    """Create a new user account.

    Raises ``ValueError`` if the email is already taken (FR-03).
    """
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise ValueError("An account with this email already exists.")

    user = User(
        email=email,
        password_hash=hash_password(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    """Verify credentials and return the ``User``, or ``None`` on failure."""
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user
