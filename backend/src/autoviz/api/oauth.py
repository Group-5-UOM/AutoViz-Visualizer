"""OAuth helpers for Google and GitHub (authorization-code flows)."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fastapi import HTTPException

from autoviz.core.config import settings

_STATE_TTL_SECONDS = 600


def _b64url(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    import base64

    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def sign_oauth_state(provider: str) -> str:
    """Return a signed opaque state string bound to ``provider``."""
    nonce = secrets.token_urlsafe(16)
    exp = int(time.time()) + _STATE_TTL_SECONDS
    payload = f"{provider}.{nonce}.{exp}"
    sig = hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return _b64url(f"{payload}.{sig}".encode("utf-8"))


def verify_oauth_state(state: str, provider: str) -> None:
    try:
        raw = _b64url_decode(state).decode("utf-8")
        provider_part, nonce, exp_s, sig = raw.rsplit(".", 3)
        payload = f"{provider_part}.{nonce}.{exp_s}"
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid OAuth state") from exc
    expected = hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    if provider_part != provider:
        raise HTTPException(status_code=400, detail="OAuth provider mismatch")
    if int(exp_s) < int(time.time()):
        raise HTTPException(status_code=400, detail="OAuth state expired")


def sign_pending_oauth(
    *,
    provider: str,
    subject: str,
    email: str,
    display_name: str = "",
) -> str:
    """Signed one-time payload for finishing OAuth registration on the frontend."""
    exp = int(time.time()) + _STATE_TTL_SECONDS
    body = {
        "provider": provider,
        "subject": subject,
        "email": email.strip().lower(),
        "display_name": (display_name or "").strip(),
        "exp": exp,
    }
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True)
    sig = hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        raw.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return _b64url(f"{raw}.{sig}".encode("utf-8"))


def verify_pending_oauth(token: str) -> dict[str, Any]:
    try:
        decoded = _b64url_decode(token).decode("utf-8")
        raw, sig = decoded.rsplit(".", 1)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid OAuth signup token") from exc
    expected = hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        raw.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=400, detail="Invalid OAuth signup token")
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid OAuth signup token") from exc
    if int(body.get("exp", 0)) < int(time.time()):
        raise HTTPException(status_code=400, detail="OAuth signup expired — try again")
    for key in ("provider", "subject", "email"):
        if not body.get(key):
            raise HTTPException(status_code=400, detail="Invalid OAuth signup token")
    return body


def _http_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    form: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    basic_auth: tuple[str, str] | None = None,
) -> Any:
    data = None
    req_headers = {"Accept": "application/json", "User-Agent": "AutoViz-AI"}
    if headers:
        req_headers.update(headers)
    if basic_auth is not None:
        import base64

        raw = f"{basic_auth[0]}:{basic_auth[1]}".encode("utf-8")
        req_headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")
    if form is not None:
        data = urllib.parse.urlencode(form).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        req_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise HTTPException(
            status_code=502, detail=f"OAuth provider error ({exc.code}): {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=502, detail=f"OAuth provider unreachable: {exc}") from exc
    if not body:
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="OAuth provider returned non-JSON") from exc


def github_authorize_url(state: str) -> str:
    """Build GitHub OAuth URL via /login so the user can switch accounts.

    Going straight to /login/oauth/authorize silently continues the active
    GitHub browser session. Landing on /login first surfaces the account UI.
    """
    client_id = settings.GITHUB_OAUTH_CLIENT_ID.strip()
    if not client_id:
        raise HTTPException(status_code=503, detail="GitHub OAuth is not configured")
    params = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": settings.github_callback_url,
            "scope": "read:user user:email",
            "state": state,
            "allow_signup": "true",
        }
    )
    # return_to must be a path on github.com (not a full URL).
    return_to = f"/login/oauth/authorize?{params}"
    return "https://github.com/login?" + urllib.parse.urlencode({"return_to": return_to})


def exchange_github_code(code: str) -> tuple[str, str, str, str]:
    """Return ``(subject, email, display_name, access_token)`` for a GitHub auth code."""
    client_id = settings.GITHUB_OAUTH_CLIENT_ID.strip()
    client_secret = settings.GITHUB_OAUTH_CLIENT_SECRET.strip()
    if not client_id or not client_secret:
        raise HTTPException(status_code=503, detail="GitHub OAuth is not configured")

    token_payload = _http_json(
        "https://github.com/login/oauth/access_token",
        method="POST",
        form={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": settings.github_callback_url,
        },
    )
    access_token = token_payload.get("access_token")
    if not access_token:
        raise HTTPException(status_code=401, detail="GitHub did not return an access token")

    profile = _http_json(
        "https://api.github.com/user",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    subject = str(profile.get("id") or "")
    if not subject:
        raise HTTPException(status_code=401, detail="GitHub profile missing id")

    email = (profile.get("email") or "").strip()
    if not email:
        emails = _http_json(
            "https://api.github.com/user/emails",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if isinstance(emails, list):
            primary = next(
                (
                    row
                    for row in emails
                    if isinstance(row, dict) and row.get("primary") and row.get("verified")
                ),
                None,
            )
            if primary is None:
                primary = next(
                    (
                        row
                        for row in emails
                        if isinstance(row, dict) and row.get("verified")
                    ),
                    None,
                )
            if primary:
                email = str(primary.get("email") or "").strip()

    if not email:
        raise HTTPException(
            status_code=400,
            detail="GitHub account has no verified email. Add one in GitHub settings.",
        )

    name = (profile.get("login") or profile.get("name") or email.split("@", 1)[0]).strip()
    return subject, email, name, str(access_token)


def revoke_github_token(access_token: str) -> None:
    """Revoke the OAuth *grant* so the next login shows Authorize again."""
    client_id = settings.GITHUB_OAUTH_CLIENT_ID.strip()
    client_secret = settings.GITHUB_OAUTH_CLIENT_SECRET.strip()
    if not client_id or not client_secret or not access_token:
        return
    try:
        # /grant removes the whole app authorization (not just one token).
        _http_json(
            f"https://api.github.com/applications/{client_id}/grant",
            method="DELETE",
            basic_auth=(client_id, client_secret),
            json_body={"access_token": access_token},
        )
    except HTTPException:
        try:
            _http_json(
                f"https://api.github.com/applications/{client_id}/token",
                method="DELETE",
                basic_auth=(client_id, client_secret),
                json_body={"access_token": access_token},
            )
        except HTTPException:
            pass


def google_authorize_url(state: str, *, force_consent: bool = False) -> str:
    """Authorization-code flow (backend exchanges code with client secret)."""
    client_id = settings.GOOGLE_OAUTH_CLIENT_ID.strip()
    if not client_id:
        raise HTTPException(status_code=503, detail="Google OAuth is not configured")
    params: dict[str, str] = {
        "client_id": client_id,
        "redirect_uri": settings.google_callback_url,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "consent select_account" if force_consent else "select_account",
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"


def exchange_google_code(code: str) -> tuple[str, str, str, str]:
    """Return ``(subject, email, display_name, access_token)`` for a Google auth code."""
    client_id = settings.GOOGLE_OAUTH_CLIENT_ID.strip()
    client_secret = settings.GOOGLE_OAUTH_CLIENT_SECRET.strip()
    if not client_id or not client_secret:
        raise HTTPException(status_code=503, detail="Google OAuth is not configured")

    token_payload = _http_json(
        "https://oauth2.googleapis.com/token",
        method="POST",
        form={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": settings.google_callback_url,
            "grant_type": "authorization_code",
        },
    )
    access_token = token_payload.get("access_token")
    if not access_token:
        raise HTTPException(status_code=401, detail="Google did not return an access token")

    info = _http_json(
        "https://openidconnect.googleapis.com/v1/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    subject = str(info.get("sub") or "").strip()
    email = str(info.get("email") or "").strip()
    if info.get("email_verified") in (False, "false", "0"):
        raise HTTPException(status_code=401, detail="Google email is not verified")
    if not subject or not email:
        raise HTTPException(status_code=401, detail="Google profile missing email or subject")
    name = str(info.get("name") or info.get("given_name") or email.split("@", 1)[0]).strip()
    return subject, email, name, str(access_token)


def revoke_google_token(access_token: str) -> None:
    """Best-effort revoke so the next Google login shows the account picker."""
    if not access_token:
        return
    try:
        _http_json(
            "https://oauth2.googleapis.com/revoke",
            method="POST",
            form={"token": access_token},
        )
    except HTTPException:
        pass
