import pytest
import asyncio
from fastapi.testclient import TestClient
from autoviz.api.main import create_app
from autoviz.llm.client import PlannerError

def test_ai_gateway_timeout_fallback():
    # We will override the agent planner to simulate a Timeout from the AI Gateway.
    app = create_app()
    
    class TimeoutPlanner:
        def classify(self, *args, **kwargs):
            raise PlannerError("AI Gateway timed out while classifying request")
            
        def generate_plan(self, *args, **kwargs):
            raise PlannerError("AI Gateway timed out while generating plan")
            
        def compose(self, *args, **kwargs):
            raise PlannerError("AI Gateway timed out while composing response")

    # In fastapi, we can override dependencies.
    from autoviz.api.deps import get_planner
    app.dependency_overrides[get_planner] = lambda: TimeoutPlanner()
    
    client = TestClient(app)
    
    # We need to register & login to use the agent endpoint.
    client.post("/auth/register", json={"email": "timeout@test.com", "username": "timeout", "password": "password"})
    token = client.post("/auth/login", json={"email": "timeout@test.com", "password": "password"}).json()["access_token"]
    
    # Create dataset
    csv_content = b"id,name\n1,Test"
    res = client.post(
        "/datasets/upload",
        files={"file": ("test.csv", csv_content, "text/csv")},
        headers={"Authorization": f"Bearer {token}"}
    )
    dataset_id = res.json()["dataset_id"]
    
    # Hit the conversational agent
    res = client.post(
        "/agent/analyze",
        json={"dataset_id": dataset_id, "request": "Plot the count of records by name"},
        headers={"Authorization": f"Bearer {token}"}
    )
    
    # Assert that the API doesn't crash with 500, but rather handles it gracefully
    # It might return a 503 or 504, or 200 with an error message in the chat response.
    # In AutoViz, PlannerErrors usually return 500 or 503, or a graceful message.
    assert res.status_code in (503, 504, 200)
    
    if res.status_code == 200:
        data = res.json()
        assert "error" in str(data).lower() or "timeout" in str(data).lower() or "failed" in str(data).lower()
