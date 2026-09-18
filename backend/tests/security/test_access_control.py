import pytest
from fastapi.testclient import TestClient
from autoviz.api.main import create_app

def _client():
    return TestClient(create_app())

def _register_and_login(client, email, username, password="password123"):
    client.post("/auth/register", json={"email": email, "username": username, "password": password})
    res = client.post("/auth/login", json={"email": email, "password": password})
    return res.json()["access_token"]

def test_user_cannot_access_other_users_dataset(api_db):
    client = _client()
    token_alice = _register_and_login(client, "alice@test.com", "alice")
    
    csv_content = b"id,name\n1,Test"
    res = client.post(
        "/datasets/upload",
        files={"file": ("test.csv", csv_content, "text/csv")},
        headers={"Authorization": f"Bearer {token_alice}"}
    )
    dataset_id = res.json()["dataset_id"]
    
    token_bob = _register_and_login(client, "bob@test.com", "bob")
    res_bob = client.get(
        f"/datasets/{dataset_id}/profile",
        headers={"Authorization": f"Bearer {token_bob}"}
    )
    assert res_bob.status_code in (403, 404)

def test_user_cannot_access_other_users_dashboard(api_db):
    client = _client()
    token_alice = _register_and_login(client, "alice2@test.com", "alice2")
    
    res = client.post(
        "/dashboards",
        json={"name": "Alice Dashboard", "widgets": []},
        headers={"Authorization": f"Bearer {token_alice}"}
    )
    dashboard_id = res.json()["id"]
    
    token_bob = _register_and_login(client, "bob2@test.com", "bob2")
    res_bob = client.get(
        f"/dashboards/{dashboard_id}",
        headers={"Authorization": f"Bearer {token_bob}"}
    )
    assert res_bob.status_code in (403, 404)
