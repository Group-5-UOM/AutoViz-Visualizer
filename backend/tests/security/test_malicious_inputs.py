import pytest
from fastapi.testclient import TestClient
from autoviz.api.main import create_app

def _client():
    return TestClient(create_app())

def _register_and_login(client, email, username, password="password123"):
    client.post("/auth/register", json={"email": email, "username": username, "password": password})
    res = client.post("/auth/login", json={"email": email, "password": password})
    return res.json()["access_token"]

def test_sql_injection_dashboard_name(api_db):
    client = _client()
    token = _register_and_login(client, "sql_tester@test.com", "sql_tester")
    
    # Try to inject SQL into dashboard name
    malicious_name = "Dash'; DROP TABLE dashboards; --"
    res = client.post(
        "/dashboards",
        json={"name": malicious_name, "widgets": []},
        headers={"Authorization": f"Bearer {token}"}
    )
    
    # Should either escape the SQL safely (and create a dashboard with that literal name)
    # or reject it. If it creates it, we verify the name is literal.
    assert res.status_code in (200, 201)
    
    # Fetch it back to ensure it wasn't executed as SQL
    dashboard_id = res.json()["id"]
    fetch_res = client.get(
        f"/dashboards/{dashboard_id}",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert fetch_res.status_code == 200
    assert fetch_res.json()["name"] == malicious_name

def test_sql_injection_dataset_query(api_db):
    client = _client()
    token = _register_and_login(client, "sql_query_tester@test.com", "sql_query_tester")
    
    csv_content = b"id,name\n1,Test"
    upload_res = client.post(
        "/datasets/upload",
        files={"file": ("test.csv", csv_content, "text/csv")},
        headers={"Authorization": f"Bearer {token}"}
    )
    dataset_id = upload_res.json()["dataset_id"]
    
    # Try to execute a raw SQL injection as a dataset query
    # The API should reject or escape this.
    malicious_query = "SELECT * FROM users; DROP TABLE datasets;"
    query_res = client.post(
        f"/datasets/{dataset_id}/cleaned",
        json={"query": malicious_query},
        headers={"Authorization": f"Bearer {token}"}
    )
    
    # The API should reject this or handle it safely (usually 4xx or 5xx if invalid query syntax, but not execute it!)
    # We just ensure it doesn't return users data or crash the database.
    assert query_res.status_code in (400, 422, 500)
