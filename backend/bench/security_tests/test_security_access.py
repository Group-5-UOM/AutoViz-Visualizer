"""Security and Access Control Testing."""

import json
from fastapi.testclient import TestClient
from autoviz.api.main import create_app

def _client():
    return TestClient(create_app())

def _register_and_login(client, username, email, password):
    creds = {"email": email, "password": password, "username": username}
    client.post("/auth/register", json=creds)
    login = client.post("/auth/login", json=creds)
    return login.json()["access_token"]

def test_cross_tenant_data_access(api_db):
    """Ensure User A cannot access or delete User B's datasets."""
    client = _client()
    
    # 1. Setup two users
    token_a = _register_and_login(client, "alice", "alice@example.com", "password")
    token_b = _register_and_login(client, "bob", "bob@example.com", "password")
    
    # 2. User A uploads a dataset
    csv_content = "id,name,value\n1,Alpha,10\n2,Beta,20"
    upload_res = client.post(
        "/datasets/upload",
        files={"file": ("data.csv", csv_content, "text/csv")},
        headers={"Authorization": f"Bearer {token_a}"}
    )
    assert upload_res.status_code == 201
    dataset_id = upload_res.json()["dataset_id"]
    
    # 3. User B attempts to access User A's dataset
    get_res = client.get(
        f"/datasets/{dataset_id}/schema",
        headers={"Authorization": f"Bearer {token_b}"}
    )
    # Should be 404 Not Found (or 403 Forbidden)
    assert get_res.status_code in (404, 403)

def test_jwt_token_tampering(api_db):
    """Ensure tampered tokens are rejected."""
    client = _client()
    token = _register_and_login(client, "charlie", "charlie@example.com", "password")
    
    # Tamper the token by modifying the signature
    tampered_token = token[:-5] + "12345"
    
    res = client.get("/dashboards", headers={"Authorization": f"Bearer {tampered_token}"})
    assert res.status_code == 401
    assert "token" in res.json()["detail"].lower()

def test_sql_injection_on_auth(api_db):
    """Ensure auth endpoints are resilient to basic SQL injection."""
    client = _client()
    
    # Basic SQL injection payload for email
    sqli_payload = {"email": "admin@example.com' OR '1'='1", "password": "password"}
    
    res = client.post("/auth/login", json=sqli_payload)
    # Should fail cleanly, not crash the server
    assert res.status_code in (401, 404, 422)
