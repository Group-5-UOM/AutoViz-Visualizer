"""OAuth helpers and provider start redirects (mocked Google/GitHub HTTP)."""

import urllib.parse
from unittest.mock import patch

from fastapi.testclient import TestClient

from autoviz.api.main import create_app
from autoviz.api.oauth import sign_oauth_state, verify_oauth_state


def _client():
    return TestClient(create_app())


def test_oauth_state_roundtrip():
    state = sign_oauth_state("github")
    verify_oauth_state(state, "github")


def test_oauth_state_rejects_wrong_provider():
    state = sign_oauth_state("github")
    try:
        verify_oauth_state(state, "google")
        assert False, "expected mismatch"
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 400


def test_google_callback_creates_session(api_db, monkeypatch):
    from autoviz.core import config as config_mod

    monkeypatch.setattr(
        config_mod.settings,
        "GOOGLE_OAUTH_CLIENT_ID",
        "test-google-client.apps.googleusercontent.com",
    )
    monkeypatch.setattr(config_mod.settings, "GOOGLE_OAUTH_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr(config_mod.settings, "AUTOVIZ_FRONTEND_URL", "http://localhost:5173")

    state = sign_oauth_state("google")
    client = _client()

    def fake_http_json(url, **kwargs):
        if "oauth2.googleapis.com/token" in url:
            return {"access_token": "g-access"}
        if "userinfo" in url:
            return {
                "sub": "google-sub-1",
                "email": "googler@example.com",
                "email_verified": True,
                "name": "Googler",
            }
        raise AssertionError(f"unexpected url {url}")

    with patch("autoviz.api.oauth._http_json", side_effect=fake_http_json):
        res = client.get(
            f"/auth/oauth/google/callback?code=fake-code&state={state}",
            follow_redirects=False,
        )
    assert res.status_code == 302, res.text
    loc = res.headers["location"]
    # New email → register flow (pending token), not an immediate session.
    assert "pending_token=" in loc
    assert "email=googler%40example.com" in loc or "email=googler@example.com" in loc
    assert "token=" not in loc.split("pending_token")[0] or "pending_token=" in loc


def test_oauth_register_creates_user_and_session(api_db, monkeypatch):
    from autoviz.api.oauth import sign_pending_oauth

    pending = sign_pending_oauth(
        provider="google",
        subject="google-sub-99",
        email="newbie@example.com",
        display_name="Newbie",
    )
    client = _client()
    res = client.post(
        "/auth/oauth/register",
        json={"pending_token": pending, "username": "newbie"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["email"] == "newbie@example.com"
    assert body["username"] == "newbie"
    assert body["access_token"]

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["username"] == "newbie"
    assert me.json()["has_password"] is False
    assert me.json()["email_verified"] is True
    assert me.json()["oauth_providers"] == ["google"]


def test_google_oauth_existing_email_logs_in(api_db, monkeypatch):
    from autoviz.core import config as config_mod

    monkeypatch.setattr(
        config_mod.settings,
        "GOOGLE_OAUTH_CLIENT_ID",
        "test-google-client.apps.googleusercontent.com",
    )
    monkeypatch.setattr(config_mod.settings, "GOOGLE_OAUTH_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr(config_mod.settings, "AUTOVIZ_FRONTEND_URL", "http://localhost:5173")

    client = _client()
    client.post(
        "/auth/register",
        json={
            "email": "existing@example.com",
            "password": "pw12345678",
            "username": "existing",
        },
    )

    state = sign_oauth_state("google")

    def fake_http_json(url, **kwargs):
        if "oauth2.googleapis.com/token" in url:
            return {"access_token": "g-access"}
        if "userinfo" in url:
            return {
                "sub": "google-sub-existing",
                "email": "existing@example.com",
                "email_verified": True,
                "name": "Existing",
            }
        raise AssertionError(f"unexpected url {url}")

    with patch("autoviz.api.oauth._http_json", side_effect=fake_http_json):
        res = client.get(
            f"/auth/oauth/google/callback?code=fake-code&state={state}",
            follow_redirects=False,
        )
    assert res.status_code == 302, res.text
    loc = res.headers["location"]
    assert "token=" in loc
    assert "username=existing" in loc
    assert "pending_token=" not in loc


def test_github_start_redirects_when_configured(api_db, monkeypatch):
    from autoviz.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "GITHUB_OAUTH_CLIENT_ID", "gh-client")
    monkeypatch.setattr(config_mod.settings, "GITHUB_OAUTH_CLIENT_SECRET", "gh-secret")
    client = _client()
    res = client.get("/auth/oauth/github/start", follow_redirects=False)
    assert res.status_code == 302
    loc = res.headers["location"]
    assert "github.com/login?" in loc
    assert "return_to=" in loc
    decoded = urllib.parse.unquote(loc)
    assert "/login/oauth/authorize" in decoded


def test_google_start_redirects_when_configured(api_db, monkeypatch):
    from autoviz.core import config as config_mod

    monkeypatch.setattr(
        config_mod.settings,
        "GOOGLE_OAUTH_CLIENT_ID",
        "test-google-client.apps.googleusercontent.com",
    )
    monkeypatch.setattr(config_mod.settings, "GOOGLE_OAUTH_CLIENT_SECRET", "test-secret")
    client = _client()
    res = client.get("/auth/oauth/google/start", follow_redirects=False)
    assert res.status_code == 302
    assert "accounts.google.com" in res.headers["location"]
