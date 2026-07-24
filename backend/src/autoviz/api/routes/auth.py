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
