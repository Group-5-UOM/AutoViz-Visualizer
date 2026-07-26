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


def test_duplicate_username_409(api_db):
    client = _client()
    first = {"email": "one@example.com", "password": "pw12345678", "username": "sameuser"}
    second = {"email": "two@example.com", "password": "pw12345678", "username": "sameuser"}
    assert client.post("/auth/register", json=first).status_code == 201
    assert client.post("/auth/register", json=second).status_code == 409


def test_login_wrong_password_401(api_db):
    client = _client()
    client.post(
        "/auth/register",
        json={"email": "b@example.com", "password": "correct-pw", "username": "bob"},
    )
    r = client.post("/auth/login", json={"email": "b@example.com", "password": "wrong-pw"})
    assert r.status_code == 401


def test_login_unknown_email_is_indistinguishable_from_wrong_password(api_db):
    client = _client()
    client.post(
        "/auth/register",
        json={"email": "known@example.com", "password": "correct-pw", "username": "known"},
    )
    wrong_pw = client.post(
        "/auth/login", json={"email": "known@example.com", "password": "nope-nope"}
    )
    unknown = client.post(
        "/auth/login", json={"email": "ghost@example.com", "password": "nope-nope"}
    )
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json()["detail"] == unknown.json()["detail"]


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
