"""Auth routes — email/password + Google/GitHub OAuth with account linking.

Identities live in ``oauth_accounts`` (provider + provider_user_id / Google sub).
``users.password_hash`` is optional until the user sets an AutoViz password.
"""

from __future__ import annotations

import datetime
import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from autoviz.api.deps import get_current_user, get_db
from autoviz.api.oauth import (
    exchange_github_code,
    exchange_google_code,
    google_authorize_url,
    github_authorize_url,
    revoke_github_token,
    revoke_google_token,
    sign_oauth_state,
    sign_pending_oauth,
    verify_oauth_state,
    verify_pending_oauth,
)
from autoviz.api.security import hash_password, needs_rehash, verify_password
from autoviz.core.config import settings
from autoviz.models import User
from autoviz.storage import repository

router = APIRouter()
_log = logging.getLogger("autoviz.observability")

_OAUTH_EXISTS_MSG = (
    "An account with this email already exists through Google or GitHub. "
    "Sign in with that provider, or set a password using Forgot password."
)


class Credentials(BaseModel):
    email: str
    password: str


class RegisterRequest(Credentials):
    username: str = Field(min_length=2, max_length=64)


class OAuthRegisterRequest(BaseModel):
    pending_token: str = Field(min_length=20)
    username: str = Field(min_length=2, max_length=64)


class SetPasswordRequest(BaseModel):
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=20)
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)


def _display_name(user: User) -> str:
    return (user.username or user.email.split("@", 1)[0]).strip()


def _session_payload(user: User, token, db: Session | None = None) -> dict:
    providers: list[str] = []
    if db is not None:
        providers = repository.list_oauth_providers(db, user.id)
    return {
        "access_token": token.token,
        "token_type": "bearer",
        "expires_at": token.expires_at.isoformat(),
        "email": user.email,
        "username": _display_name(user),
        "has_password": bool(user.password_hash),
        "oauth_providers": providers,
    }


def _frontend_oauth_redirect(
    *,
    token: str = "",
    email: str = "",
    username: str = "",
    pending_token: str = "",
    error: str | None = None,
) -> RedirectResponse:
    base = settings.AUTOVIZ_FRONTEND_URL.rstrip("/") + "/oauth/callback"
    if error:
        return RedirectResponse(f"{base}?{urlencode({'error': error})}", status_code=302)
    if pending_token:
        return RedirectResponse(
            f"{base}?{urlencode({'pending_token': pending_token, 'email': email})}",
            status_code=302,
        )
    return RedirectResponse(
        f"{base}?{urlencode({'token': token, 'email': email, 'username': username})}",
        status_code=302,
    )


def _finish_oauth_login_or_register(
    db: Session,
    *,
    provider: str,
    subject: str,
    email: str,
    display_name: str,
    provider_token: str | None = None,
) -> RedirectResponse:
    email = email.strip().lower()
    user = repository.get_user_by_oauth(db, provider, subject)
    if user is None:
        user = repository.get_user_by_email(db, email)

    if user is not None:
        try:
            repository.link_oauth_account(
                db,
                user,
                provider=provider,
                provider_user_id=subject,
                access_token=provider_token if provider == "google" else None,
            )
        except ValueError:
            return _frontend_oauth_redirect(
                error="This OAuth account is already linked to another user."
            )
        if not user.username:
            fallback = (display_name or email.split("@", 1)[0]).strip() or "user"
            user.username = repository.unique_username(db, fallback)
        user.email_verified = True
        db.commit()
        session = repository.create_token(db, user.id)
        if provider == "github" and provider_token:
            revoke_github_token(provider_token)
        return _frontend_oauth_redirect(
            token=session.token, email=user.email, username=_display_name(user)
        )

    pending = sign_pending_oauth(
        provider=provider,
        subject=subject,
        email=email,
        display_name=display_name,
    )
    if provider == "github" and provider_token:
        revoke_github_token(provider_token)
    return _frontend_oauth_redirect(pending_token=pending, email=email)


@router.post("/register", status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    username = body.username.strip()
    email = body.email.strip().lower()
    if len(username) < 2:
        raise HTTPException(status_code=422, detail="Username must be at least 2 characters")
    existing = repository.get_user_by_email(db, email)
    if existing is not None:
        providers = repository.list_oauth_providers(db, existing.id)
        if providers and not existing.password_hash:
            raise HTTPException(status_code=409, detail=_OAUTH_EXISTS_MSG)
        raise HTTPException(status_code=409, detail="Email already registered")
    if repository.get_user_by_username(db, username):
        raise HTTPException(status_code=409, detail="Username already taken")
    user = repository.create_user(
        db, email, hash_password(body.password), username=username, email_verified=False
    )
    return {"id": user.id, "email": user.email, "username": user.username}


@router.post("/login")
def login(body: Credentials, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    user = repository.get_user_by_email(db, email)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if user.password_hash is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "This account currently uses Google or GitHub sign-in. "
                "Use that provider, or set a password via Forgot password."
            ),
        )
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if needs_rehash(user.password_hash):
        repository.set_user_password(db, user, hash_password(body.password))
    token = repository.create_token(db, user.id)
    return _session_payload(user, token, db)


@router.post("/logout")
def logout(
    authorization: str = Header(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    pairs = repository.clear_oauth_access_tokens(db, user.id)
    repository.delete_all_tokens_for_user(db, user.id)
    for provider, token in pairs:
        if provider == "github":
            revoke_github_token(token)
        elif provider == "google":
            revoke_google_token(token)
    return {"logged_out": True}


@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {
        "id": user.id,
        "email": user.email,
        "username": _display_name(user),
        "has_password": bool(user.password_hash),
        "email_verified": bool(user.email_verified),
        "oauth_providers": repository.list_oauth_providers(db, user.id),
    }


@router.post("/password")
def set_password(
    body: SetPasswordRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Add or replace the AutoViz (local) password for the signed-in user."""
    if body.password != body.confirm_password:
        raise HTTPException(status_code=422, detail="Passwords do not match")
    if len(body.password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")
    repository.set_user_password(db, user, hash_password(body.password))
    return {"password_set": True}


@router.post("/forgot-password")
def forgot_password(body: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Start password setup/reset. Always returns a generic message."""
    email = body.email.strip().lower()
    user = repository.get_user_by_email(db, email)
    response: dict = {
        "ok": True,
        "detail": "If an account exists for that email, a reset link is available.",
    }
    if user is None:
        return response
    row = repository.create_password_reset_token(db, user.id)
    reset_url = (
        f"{settings.AUTOVIZ_FRONTEND_URL.rstrip('/')}/reset-password"
        f"?{urlencode({'token': row.token})}"
    )
    _log.info("password reset for %s → %s", email, reset_url)
    if settings.AUTOVIZ_EXPOSE_RESET_TOKENS:
        response["reset_token"] = row.token
        response["reset_url"] = reset_url
    return response


@router.post("/reset-password")
def reset_password(body: ResetPasswordRequest, db: Session = Depends(get_db)):
    from datetime import datetime, timezone

    if body.password != body.confirm_password:
        raise HTTPException(status_code=422, detail="Passwords do not match")
    row = repository.get_password_reset_token(db, body.token)
    if row is None or row.used_at is not None:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")
    user = db.get(User, row.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")
    repository.set_user_password(db, user, hash_password(body.password))
    row.used_at = datetime.now(timezone.utc)
    db.commit()
    return {"password_set": True}


@router.post("/oauth/register")
def oauth_register(body: OAuthRegisterRequest, db: Session = Depends(get_db)):
    pending = verify_pending_oauth(body.pending_token)
    username = body.username.strip()
    if len(username) < 2:
        raise HTTPException(status_code=422, detail="Username must be at least 2 characters")
    email = str(pending["email"]).strip().lower()
    provider = str(pending["provider"])
    subject = str(pending["subject"])

    if repository.get_user_by_email(db, email):
        raise HTTPException(status_code=409, detail=_OAUTH_EXISTS_MSG)
    if repository.get_user_by_username(db, username):
        raise HTTPException(status_code=409, detail="Username already taken")
    if repository.get_user_by_oauth(db, provider, subject):
        raise HTTPException(status_code=409, detail="Account already linked — sign in instead")

    user = repository.create_user(
        db,
        email,
        password_hash=None,
        username=username,
        email_verified=True,
    )
    repository.link_oauth_account(
        db, user, provider=provider, provider_user_id=subject, access_token=None
    )
    token = repository.create_token(db, user.id)
    return _session_payload(user, token, db)


@router.get("/oauth/github/start")
def oauth_github_start():
    state = sign_oauth_state("github")
    return RedirectResponse(github_authorize_url(state), status_code=302)


@router.get("/oauth/github/callback")
def oauth_github_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    if error:
        return _frontend_oauth_redirect(error=f"GitHub: {error}")
    if not code or not state:
        return _frontend_oauth_redirect(error="Missing GitHub OAuth code")
    try:
        verify_oauth_state(state, "github")
        subject, email, name, provider_token = exchange_github_code(code)
        return _finish_oauth_login_or_register(
            db,
            provider="github",
            subject=subject,
            email=email,
            display_name=name,
            provider_token=provider_token,
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "GitHub sign-in failed"
        return _frontend_oauth_redirect(error=detail)


@router.get("/oauth/google/start")
def oauth_google_start():
    state = sign_oauth_state("google")
    return RedirectResponse(google_authorize_url(state), status_code=302)


@router.get("/oauth/google/callback")
def oauth_google_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    if error:
        _log.warning("google oauth denied: %s", error)
        return _frontend_oauth_redirect(error=f"Google: {error}")
    if not code or not state:
        return _frontend_oauth_redirect(error="Missing Google OAuth code")
    try:
        verify_oauth_state(state, "google")
        subject, email, name, provider_token = exchange_google_code(code)
        return _finish_oauth_login_or_register(
            db,
            provider="google",
            subject=subject,
            email=email,
            display_name=name,
            provider_token=provider_token,
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "Google sign-in failed"
        _log.warning("google oauth failed: %s", detail)
        return _frontend_oauth_redirect(error=detail)


# --- MCP connection keys -----------------------------------------------------
#
# The link a user pastes into Gemini or Claude to give it access to *their*
# AutoViz data (`Docs/26`). These live on the auth router because they are
# account credentials, not data — and deliberately in their own table, so
# revoking one does not log the person out of their browser.


class McpKeyCreate(BaseModel):
    label: str = Field(default="", max_length=120)
    # `host` excludes AutoViz's own agent tools: a foreign host has its own
    # model, and calling ours from inside it is a costly passthrough.
    profile: str = Field(default="host", pattern="^(host|default|advanced)$")
    expires_in_days: int | None = Field(default=90, ge=1, le=3650)


class McpKeyOut(BaseModel):
    id: str
    label: str
    profile: str
    created_at: str | None = None
    last_used_at: str | None = None
    expires_at: str | None = None
    revoked: bool = False


class McpKeyCreated(McpKeyOut):
    """The one and only response that carries the key itself."""

    key: str
    url: str


def _key_out(row) -> dict:
    def iso(value):
        return value.isoformat() if value is not None else None

    return {
        "id": row.id,
        "label": row.label,
        "profile": row.profile,
        "created_at": iso(row.created_at),
        "last_used_at": iso(row.last_used_at),
        "expires_at": iso(row.expires_at),
        "revoked": row.revoked_at is not None,
    }


def _connection_url(key: str) -> str:
    """The URL the user pastes into their MCP host.

    Ends in `/mcp` because that is what every host's placeholder shows and what
    a client may append or normalise; the secret therefore sits in the middle.
    """
    base = settings.AUTOVIZ_API_PUBLIC_URL.rstrip("/")
    # The MCP endpoint is mounted on the app root, beside /api rather than under
    # it, so strip a trailing /api if the public URL carries one.
    if base.endswith("/api"):
        base = base[: -len("/api")]
    return f"{base}/c/{key}/mcp"


@router.post("/mcp-keys", response_model=McpKeyCreated, status_code=201)
def create_mcp_key(
    body: McpKeyCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Mint a connection link. The key is returned **once** and never again."""
    expires_at = None
    if body.expires_in_days is not None:
        expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
            days=body.expires_in_days
        )
    row, plaintext = repository.create_mcp_key(
        db, user.id, label=body.label, profile=body.profile, expires_at=expires_at
    )
    return {**_key_out(row), "key": plaintext, "url": _connection_url(plaintext)}


@router.get("/mcp-keys", response_model=list[McpKeyOut])
def list_mcp_keys(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Every key this user has minted. Never includes the key itself."""
    return [_key_out(r) for r in repository.list_mcp_keys(db, user.id)]


@router.delete("/mcp-keys/{key_id}", status_code=204)
def revoke_mcp_key(
    key_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Revoke a key. Scoped to the owner, and idempotent."""
    if not repository.revoke_mcp_key(db, user.id, key_id):
        raise HTTPException(status_code=404, detail="No such connection key")
