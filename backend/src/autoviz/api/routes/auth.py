"""Authentication routes — registration, login, logout, and session check.

    POST /auth/register   Create a new user account          (FR-01–FR-03)
    POST /auth/login      Authenticate, set HttpOnly cookie  (FR-04–FR-06)
    POST /auth/logout     Delete session row, clear cookie   (FR-08)
    GET  /auth/me         Return authenticated user info
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from autoviz.api.deps import get_current_user
from autoviz.api.schemas_auth import (
    ErrorResponse,
    LoginRequest,
    MessageResponse,
    RegisterRequest,
    UserResponse,
)
from autoviz.core.database import get_db
from autoviz.models.session import UserSession
from autoviz.models.user import User
from autoviz.services.auth import (
    authenticate_user,
    create_access_token,
    decode_access_token,
    register_user,
)

router = APIRouter(tags=["auth"])


# ── POST /auth/register ─────────────────────────────────────────────────


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    """Create a new user account (FR-01, FR-02, FR-03)."""
    try:
        user = register_user(db, email=body.email, password=body.password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    return user


# ── POST /auth/login ────────────────────────────────────────────────────


@router.post(
    "/login",
    response_model=UserResponse,
    responses={
        401: {"model": ErrorResponse},
    },
)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)):
    """Authenticate and set an HttpOnly cookie with the JWT (FR-04, FR-05, FR-06).

    On success:
    1. Creates a JWT token via ``create_access_token(user.id)``.
    2. Inserts a ``sessions`` row with the token + expiry.
    3. Sets the ``access_token`` HttpOnly cookie.
    4. Returns ``UserResponse`` (no raw token in the body).
    """
    user = authenticate_user(db, email=body.email, password=body.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token, expires_at = create_access_token(user.id)

    # Persist the session row for hybrid auth
    session = UserSession(
        user_id=user.id,
        token=token,
        expires_at=expires_at,
    )
    db.add(session)
    db.commit()

    # Calculate max_age in seconds for the cookie
    max_age_seconds = int(
        (expires_at - datetime.now(timezone.utc)).total_seconds()
    )

    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=max_age_seconds,
    )

    return user


# ── POST /auth/logout ───────────────────────────────────────────────────


@router.post(
    "/logout",
    response_model=MessageResponse,
)
def logout(
    response: Response,
    current_user: User = Depends(get_current_user),
    access_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    """Revoke the session immediately and clear the cookie (FR-08).

    Deletes the matching ``sessions`` row (found via the cookie's token)
    and calls ``response.delete_cookie('access_token')``.
    """
    if access_token:
        db.query(UserSession).filter(
            UserSession.token == access_token,
            UserSession.user_id == current_user.id,
        ).delete()
        db.commit()

    response.delete_cookie("access_token")
    return MessageResponse(message="Logged out successfully")


# ── GET /auth/me ─────────────────────────────────────────────────────────


@router.get(
    "/me",
    response_model=UserResponse,
    responses={
        401: {"model": ErrorResponse},
    },
)
def get_me(current_user: User = Depends(get_current_user)):
    """Return the authenticated user's profile."""
    return current_user
"""Auth routes — register / login / logout / me (Bearer-token sessions)."""

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from autoviz.api.deps import get_current_user, get_db
from autoviz.api.security import hash_password, verify_password
from autoviz.models import User
from autoviz.storage import repository

router = APIRouter()


class Credentials(BaseModel):
    email: str
    password: str


@router.post("/register", status_code=201)
def register(body: Credentials, db: Session = Depends(get_db)):
    if repository.get_user_by_email(db, body.email):
        raise HTTPException(status_code=409, detail="Email already registered")
    user = repository.create_user(db, body.email, hash_password(body.password))
    return {"id": user.id, "email": user.email}


@router.post("/login")
def login(body: Credentials, db: Session = Depends(get_db)):
    user = repository.get_user_by_email(db, body.email)
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = repository.create_token(db, user.id)
    return {
        "access_token": token.token,
        "token_type": "bearer",
        "expires_at": token.expires_at.isoformat(),
    }


@router.post("/logout")
def logout(
    authorization: str = Header(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),  # enforces a valid token
):
    token = authorization.split(" ", 1)[1]
    repository.delete_token(db, token)
    return {"logged_out": True}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {"id": user.id, "email": user.email}
