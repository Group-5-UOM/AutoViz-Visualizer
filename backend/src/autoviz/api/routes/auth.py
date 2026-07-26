"""Auth routes — register / login / logout / me (Bearer-token sessions)."""

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from autoviz.api.deps import get_current_user, get_db
from autoviz.api.security import hash_password, verify_password
from autoviz.models import User
from autoviz.storage import repository

router = APIRouter()


class Credentials(BaseModel):
    email: str
    password: str


class RegisterRequest(Credentials):
    username: str = Field(min_length=2, max_length=64)


def _display_name(user: User) -> str:
    return user.username or user.email.split("@", 1)[0]


@router.post("/register", status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    username = body.username.strip()
    if len(username) < 2:
        raise HTTPException(status_code=422, detail="Username must be at least 2 characters")
    if repository.get_user_by_email(db, body.email):
        raise HTTPException(status_code=409, detail="Email already registered")
    if repository.get_user_by_username(db, username):
        raise HTTPException(status_code=409, detail="Username already taken")
    user = repository.create_user(
        db,
        body.email,
        hash_password(body.password),
        username=username,
    )
    return {"id": user.id, "email": user.email, "username": user.username}


@router.post("/login")
def login(body: Credentials, db: Session = Depends(get_db)):
    user = repository.get_user_by_email(db, body.email)
    # Same message whether the email is unknown or the password is wrong, so the
    # endpoint cannot be used to discover which emails have accounts.
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = repository.create_token(db, user.id)
    return {
        "access_token": token.token,
        "token_type": "bearer",
        "expires_at": token.expires_at.isoformat(),
        "email": user.email,
        "username": _display_name(user),
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
    return {"id": user.id, "email": user.email, "username": _display_name(user)}
