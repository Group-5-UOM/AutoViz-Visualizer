"""Authentication service — password hashing, JWT creation/decoding, user CRUD.

All business logic lives here; routes are thin adapters.
"""

from datetime import datetime, timedelta, timezone

import bcrypt
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
