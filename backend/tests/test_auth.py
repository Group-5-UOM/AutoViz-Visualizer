"""Tests for the /auth endpoints — Day 3-4 authentication.

Covers: register, duplicate email, login, wrong password, /me with cookie,
/me without cookie, logout, and immediate revocation after logout.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from autoviz.api.main import app
from autoviz.core.database import Base, get_db

# ── In-memory SQLite for tests ───────────────────────────────────────────

TEST_DATABASE_URL = "sqlite://"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_db():
    """Recreate all tables before each test for full isolation."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


TEST_EMAIL = "test@example.com"
TEST_PASSWORD = "securepassword123"


# ── Registration ─────────────────────────────────────────────────────────


def test_register_success():
    response = client.post(
        "/auth/register",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == TEST_EMAIL
    assert "id" in data
    assert "created_at" in data


def test_register_duplicate_email():
    client.post(
        "/auth/register",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
    )
    response = client.post(
        "/auth/register",
        json={"email": TEST_EMAIL, "password": "anotherpassword"},
    )
    assert response.status_code == 409


def test_register_short_password():
    response = client.post(
        "/auth/register",
        json={"email": "short@example.com", "password": "short"},
    )
    assert response.status_code == 422  # Pydantic validation error


def test_register_invalid_email():
    response = client.post(
        "/auth/register",
        json={"email": "not-an-email", "password": TEST_PASSWORD},
    )
    assert response.status_code == 422


# ── Login ────────────────────────────────────────────────────────────────


def test_login_success():
    client.post(
        "/auth/register",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
    )
    response = client.post(
        "/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == TEST_EMAIL

    # Cookie should be set
    assert "access_token" in response.cookies


def test_login_wrong_password():
    client.post(
        "/auth/register",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
    )
    response = client.post(
        "/auth/login",
        json={"email": TEST_EMAIL, "password": "wrongpassword"},
    )
    assert response.status_code == 401


def test_login_nonexistent_user():
    response = client.post(
        "/auth/login",
        json={"email": "nobody@example.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 401


# ── GET /auth/me ─────────────────────────────────────────────────────────


def test_me_with_valid_cookie():
    client.post(
        "/auth/register",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
    )
    login_resp = client.post(
        "/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
    )
    token = login_resp.cookies.get("access_token")

    response = client.get("/auth/me", cookies={"access_token": token})
    assert response.status_code == 200
    assert response.json()["email"] == TEST_EMAIL


def test_me_without_cookie():
    response = client.get("/auth/me")
    assert response.status_code == 401


def test_me_with_invalid_cookie():
    response = client.get("/auth/me", cookies={"access_token": "garbage-token"})
    assert response.status_code == 401


# ── Logout ───────────────────────────────────────────────────────────────


def test_logout_revokes_session():
    """After logout, /auth/me should return 401 immediately (FR-08)."""
    client.post(
        "/auth/register",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
    )
    login_resp = client.post(
        "/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
    )
    token = login_resp.cookies.get("access_token")

    # Logout
    logout_resp = client.post(
        "/auth/logout", cookies={"access_token": token}
    )
    assert logout_resp.status_code == 200
    assert logout_resp.json()["message"] == "Logged out successfully"

    # Token should no longer work — immediate revocation
    me_resp = client.get("/auth/me", cookies={"access_token": token})
    assert me_resp.status_code == 401
