"""HTTP agent routes via TestClient with an injected FakePlanner (offline).

The agent routes are owner-scoped like every other user-data route, so these
tests go through the real register -> login -> upload path to get an owned
dataset_id, then drive /agent/analyze with the resulting Bearer token.
"""

from fastapi.testclient import TestClient

from autoviz.agent.service import AgentService
from autoviz.api.deps import get_agent, get_registry
from autoviz.api.main import create_app
from autoviz.services.registry import DatasetRegistry
from tests.conftest import data_path
from tests.test_agent import GOOD_IRIS_PLAN, FakePlanner

CREDS = {"email": "agent@example.com", "password": "hunter2pw"}


def _client_with_agent(planner, reg):
    app = create_app()
    app.dependency_overrides[get_agent] = lambda: AgentService(planner=planner, registry=reg)
    # The routes' ownership gate must consult the same registry the agent uses.
    app.dependency_overrides[get_registry] = lambda: reg
    return TestClient(app)


def _auth(client: TestClient) -> dict[str, str]:
    client.post("/auth/register", json=CREDS)
    token = client.post("/auth/login", json=CREDS).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_analyze_happy_path(api_db):
    reg = DatasetRegistry()
    client = _client_with_agent(FakePlanner(plans=[GOOD_IRIS_PLAN]), reg)
    headers = _auth(client)

    registered = client.post(
        "/datasets",
        json={"file_ref": data_path("general-testing", "iris.csv")},
        headers=headers,
    )
    assert registered.status_code == 201
    ds = registered.json()["dataset_id"]

    r = client.post(
        "/agent/analyze",
        json={"request": "avg sepal length by species", "dataset_id": ds},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["thread_id"]
    assert len(body["charts"]) == 1
    assert body["charts"][0]["status"] == "ok"


def test_analyze_requires_auth(api_db):
    client = _client_with_agent(FakePlanner(), DatasetRegistry())
    r = client.post("/agent/analyze", json={"request": "anything", "dataset_id": "ds_x"})
    assert r.status_code == 401


def test_analyze_unknown_dataset_404(api_db):
    client = _client_with_agent(FakePlanner(), DatasetRegistry())
    headers = _auth(client)
    r = client.post(
        "/agent/analyze",
        json={"request": "anything", "dataset_id": "ds_nope"},
        headers=headers,
    )
    assert r.status_code == 404


def test_answer_without_paused_run_is_structured(api_db):
    reg = DatasetRegistry()
    client = _client_with_agent(FakePlanner(), reg)
    headers = _auth(client)
    r = client.post(
        "/agent/answer",
        json={"thread_id": "th_nope", "answer": "x"},
        headers=headers,
    )
    assert r.status_code == 200  # structured envelope, not an HTTP error
    assert r.json()["status"] == "failed"
