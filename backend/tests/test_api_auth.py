"""Auth flow over HTTP (SQLite-backed via the api_db fixture)."""

from fastapi.testclient import TestClient

from autoviz.api.main import create_app


def _client():
    return TestClient(create_app())


def test_register_login_me_flow(api_db):
    client = _client()
    creds = {"email": "a@example.com", "password": "hunter2pw", "username": "alice"}

    reg = client.post("/auth/register", json=creds)
    assert reg.status_code == 201
    assert reg.json()["email"] == "a@example.com"
    assert reg.json()["username"] == "alice"

    login = client.post("/auth/login", json=creds)
    assert login.status_code == 200
    token = login.json()["access_token"]
    assert login.json()["token_type"] == "bearer"
    assert login.json()["username"] == "alice"

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "a@example.com"
    assert me.json()["username"] == "alice"


def test_register_requires_username(api_db):
    client = _client()
    r = client.post("/auth/register", json={"email": "nou@example.com", "password": "pw12345678"})
    assert r.status_code == 422


def test_duplicate_email_409(api_db):
    client = _client()
    creds = {"email": "dup@example.com", "password": "pw12345678", "username": "dupuser"}
    assert client.post("/auth/register", json=creds).status_code == 201
    assert client.post("/auth/register", json=creds).status_code == 409


def test_login_wrong_password_401(api_db):
    client = _client()
    client.post(
        "/auth/register",
        json={"email": "b@example.com", "password": "correct-pw", "username": "bob"},
    )
    r = client.post("/auth/login", json={"email": "b@example.com", "password": "wrong-pw"})
    assert r.status_code == 401


def test_me_requires_token(api_db):
    client = _client()
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_logout_invalidates_token(api_db):
    client = _client()
    creds = {"email": "c@example.com", "password": "pw-abcdefgh", "username": "charlie"}
    client.post("/auth/register", json=creds)
    token = client.post("/auth/login", json=creds).json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}
    assert client.post("/auth/logout", headers=auth).status_code == 200
    assert client.get("/auth/me", headers=auth).status_code == 401


def test_oauth_only_login_requires_password_setup(api_db):
    from autoviz.api.oauth import sign_pending_oauth

    pending = sign_pending_oauth(
        provider="google",
        subject="google-sub-nopw",
        email="oauthonly@example.com",
        display_name="OAuth Only",
    )
    client = _client()
    reg = client.post(
        "/auth/oauth/register",
        json={"pending_token": pending, "username": "oauthonly"},
    )
    assert reg.status_code == 200
    assert reg.json()["has_password"] is False
    assert "google" in reg.json()["oauth_providers"]

    login = client.post(
        "/auth/login",
        json={"email": "oauthonly@example.com", "password": "anything1"},
    )
    assert login.status_code == 400
    assert "Google" in login.json()["detail"] or "GitHub" in login.json()["detail"]

    # Registering the same email with a password must not create a duplicate.
    conflict = client.post(
        "/auth/register",
        json={
            "email": "oauthonly@example.com",
            "password": "newpassword1",
            "username": "othername",
        },
    )
    assert conflict.status_code == 409
    assert "Forgot password" in conflict.json()["detail"]


def test_set_password_then_email_login(api_db):
    from autoviz.api.oauth import sign_pending_oauth

    pending = sign_pending_oauth(
        provider="google",
        subject="google-sub-setpw",
        email="linkpw@example.com",
        display_name="Link PW",
    )
    client = _client()
    token = client.post(
        "/auth/oauth/register",
        json={"pending_token": pending, "username": "linkpw"},
    ).json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}

    set_pw = client.post(
        "/auth/password",
        headers=auth,
        json={"password": "autovizpass1", "confirm_password": "autovizpass1"},
    )
    assert set_pw.status_code == 200
    me = client.get("/auth/me", headers=auth)
    assert me.json()["has_password"] is True
    assert me.json()["oauth_providers"] == ["google"]

    login = client.post(
        "/auth/login",
        json={"email": "linkpw@example.com", "password": "autovizpass1"},
    )
    assert login.status_code == 200
    assert login.json()["username"] == "linkpw"
    assert login.json()["has_password"] is True


def test_forgot_and_reset_password(api_db, monkeypatch):
    from autoviz.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "AUTOVIZ_EXPOSE_RESET_TOKENS", True)
    client = _client()
    client.post(
        "/auth/register",
        json={"email": "resetme@example.com", "password": "oldpassword1", "username": "resetme"},
    )

    forgot = client.post("/auth/forgot-password", json={"email": "resetme@example.com"})
    assert forgot.status_code == 200
    body = forgot.json()
    assert body["ok"] is True
    assert body["reset_token"]
    assert "/reset-password" in body["reset_url"]

    reset = client.post(
        "/auth/reset-password",
        json={
            "token": body["reset_token"],
            "password": "newpassword9",
            "confirm_password": "newpassword9",
        },
    )
    assert reset.status_code == 200

    assert (
        client.post(
            "/auth/login",
            json={"email": "resetme@example.com", "password": "oldpassword1"},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/auth/login",
            json={"email": "resetme@example.com", "password": "newpassword9"},
        ).status_code
        == 200
    )


def test_me_includes_has_password(api_db):
    client = _client()
    creds = {"email": "me@example.com", "password": "hunter2pw", "username": "meuser"}
    client.post("/auth/register", json=creds)
    token = client.post("/auth/login", json=creds).json()["access_token"]
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["has_password"] is True
    assert me.json()["email_verified"] is False
    assert me.json()["oauth_providers"] == []
