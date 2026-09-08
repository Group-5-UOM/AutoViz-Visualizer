"""FR-81 per-user LLM rate limit on agent routes."""

from fastapi.testclient import TestClient

from autoviz.api.main import create_app
from autoviz.api.rate_limit import reset_rate_limits
from autoviz.core import config as config_mod


def _client():
    return TestClient(create_app())


def test_llm_rate_limit_blocks_analyze(api_db, monkeypatch):
    reset_rate_limits()
    monkeypatch.setattr(config_mod.settings, "AUTOVIZ_LLM_RATE_LIMIT", 2)
    monkeypatch.setattr(config_mod.settings, "AUTOVIZ_LLM_RATE_WINDOW_S", 3600.0)

    client = _client()
    creds = {"email": "rl@example.com", "password": "pw12345678", "username": "rluser"}
    client.post("/auth/register", json=creds)
    token = client.post("/auth/login", json=creds).json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}

    # No dataset needed — the limiter runs before ownership checks.
    first = client.post(
        "/agent/analyze",
        headers=auth,
        json={"request": "show something", "dataset_id": None},
    )
    second = client.post(
        "/agent/analyze",
        headers=auth,
        json={"request": "show something", "dataset_id": None},
    )
    third = client.post(
        "/agent/analyze",
        headers=auth,
        json={"request": "show something", "dataset_id": None},
    )
    # First two may fail for other reasons (no dataset / planner), but not 429.
    assert first.status_code != 429
    assert second.status_code != 429
    assert third.status_code == 429
    assert "limit" in third.json()["detail"].lower()

    other = {"email": "rl2@example.com", "password": "pw12345678", "username": "rluser2"}
    client.post("/auth/register", json=other)
    other_token = client.post("/auth/login", json=other).json()["access_token"]
    other_auth = {"Authorization": f"Bearer {other_token}"}
    ok = client.post(
        "/agent/analyze",
        headers=other_auth,
        json={"request": "show something", "dataset_id": None},
    )
    assert ok.status_code != 429
