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


def test_change_password_requires_current_password(api_db):
    client = _client()
    creds = {"email": "chg@example.com", "password": "oldpassword1", "username": "chguser"}
    client.post("/auth/register", json=creds)
    token = client.post("/auth/login", json=creds).json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}

    wrong = client.post(
        "/auth/password",
        headers=auth,
        json={
            "password": "newpassword9",
            "confirm_password": "newpassword9",
            "current_password": "nope-wrong",
        },
    )
    assert wrong.status_code == 401

    ok = client.post(
        "/auth/password",
        headers=auth,
        json={
            "password": "newpassword9",
            "confirm_password": "newpassword9",
            "current_password": "oldpassword1",
        },
    )
    assert ok.status_code == 200
    assert ok.json()["access_token"]
    # Old session is dead after a password change.
    assert client.get("/auth/me", headers=auth).status_code == 401
    new_auth = {"Authorization": f"Bearer {ok.json()['access_token']}"}
    assert client.get("/auth/me", headers=new_auth).status_code == 200
    assert (
        client.post(
            "/auth/login",
            json={"email": "chg@example.com", "password": "newpassword9"},
        ).status_code
        == 200
    )


def test_delete_account_removes_owned_data(api_db):
    client = _client()
    creds = {"email": "gone@example.com", "password": "pw12345678", "username": "goneuser"}
    client.post("/auth/register", json=creds)
    token = client.post("/auth/login", json=creds).json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}

    up = client.post(
        "/datasets/upload",
        headers=auth,
        files={"file": ("tiny.csv", b"a,b\n1,2\n3,4\n", "text/csv")},
    )
    assert up.status_code == 201
    dataset_id = up.json()["dataset_id"]

    other = {"email": "keep@example.com", "password": "pw12345678", "username": "keepuser"}
    client.post("/auth/register", json=other)
    other_token = client.post("/auth/login", json=other).json()["access_token"]
    other_auth = {"Authorization": f"Bearer {other_token}"}

    deleted = client.request(
        "DELETE",
        "/auth/me",
        headers=auth,
        json={"password": "pw12345678"},
    )
    assert deleted.status_code == 204
    assert client.get("/auth/me", headers=auth).status_code == 401
    assert client.get(f"/datasets/{dataset_id}/schema", headers=other_auth).status_code in (
        403,
        404,
    )
    # Other user still works.
    assert client.get("/auth/me", headers=other_auth).status_code == 200


def test_idle_session_is_rejected(api_db, monkeypatch):
    import datetime

    from autoviz.core import config as config_mod
    from autoviz.core.database import get_sessionmaker
    from autoviz.models import UserSession
    from sqlalchemy import select

    monkeypatch.setattr(config_mod.settings, "AUTOVIZ_IDLE_TIMEOUT_MINUTES", 30)
    client = _client()
    creds = {"email": "idle@example.com", "password": "pw12345678", "username": "idleuser"}
    client.post("/auth/register", json=creds)
    token = client.post("/auth/login", json=creds).json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}

    db = get_sessionmaker()()
    try:
        row = db.scalar(select(UserSession).where(UserSession.token == token))
        assert row is not None
        row.last_active_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            minutes=31
        )
        db.commit()
    finally:
        db.close()

    assert client.get("/auth/me", headers=auth).status_code == 401


def test_request_id_echoed_on_response(api_db):
    client = _client()
    r = client.get("/health", headers={"X-Request-ID": "test-corr-123"})
    assert r.status_code == 200
    assert r.headers.get("X-Request-ID") == "test-corr-123"


def test_dataset_retention_policy(api_db):
    client = _client()
    creds = {"email": "ret@example.com", "password": "pw12345678", "username": "retuser"}
    client.post("/auth/register", json=creds)
    token = client.post("/auth/login", json=creds).json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}
    r = client.get("/datasets/retention", headers=auth)
    assert r.status_code == 200
    assert r.json()["retention_days"] == 90
    assert "days" in r.json()["message"]
