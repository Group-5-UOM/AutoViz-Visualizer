import pytest
from fastapi.testclient import TestClient
from autoviz.api.main import create_app

def _client():
    return TestClient(create_app())

def test_missing_token(api_db):
    client = _client()
    res = client.get("/dashboards")
    assert res.status_code == 401
    
def test_malformed_token(api_db):
    client = _client()
    res = client.get("/dashboards", headers={"Authorization": "Bearer not_a_real_token_123"})
    assert res.status_code == 401

def test_expired_token(api_db):
    # This might require mocking datetime if the system doesn't have an easy way to generate an expired token.
    # For now, we verify that invalid tokens are rejected.
    client = _client()
    import jwt
    import datetime
    
    # Generate a fake JWT that is technically valid syntax but has bad signature and is expired
    payload = {
        "sub": "1",
        "exp": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    }
    bad_token = jwt.encode(payload, "secret", algorithm="HS256")
    
    res = client.get("/dashboards", headers={"Authorization": f"Bearer {bad_token}"})
    assert res.status_code == 401
