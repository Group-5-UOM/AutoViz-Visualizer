"""HTTP agent routes via TestClient with an injected FakePlanner (offline)."""

from fastapi.testclient import TestClient

from autoviz.agent.service import AgentService
from autoviz.api.deps import get_agent
from autoviz.api.main import create_app
from autoviz.services.dataset import register_dataset
from autoviz.services.registry import DatasetRegistry
from tests.conftest import data_path
from tests.test_agent import GOOD_IRIS_PLAN, FakePlanner


def _client_with_agent(planner, reg):
    app = create_app()
    app.dependency_overrides[get_agent] = lambda: AgentService(planner=planner, registry=reg)
    return TestClient(app)


def test_analyze_happy_path():
    reg = DatasetRegistry()
    ds = register_dataset(data_path("general-testing", "iris.csv"), reg)["dataset_id"]
    client = _client_with_agent(FakePlanner(plans=[GOOD_IRIS_PLAN]), reg)
    r = client.post("/agent/analyze", json={"request": "avg sepal length by species", "dataset_id": ds})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["thread_id"]
    assert len(body["charts"]) == 1
    assert body["charts"][0]["status"] == "ok"


def test_answer_without_paused_run_is_structured():
    reg = DatasetRegistry()
    client = _client_with_agent(FakePlanner(), reg)
    r = client.post("/agent/answer", json={"thread_id": "th_nope", "answer": "x"})
    assert r.status_code == 200  # structured envelope, not an HTTP error
    assert r.json()["status"] == "failed"
