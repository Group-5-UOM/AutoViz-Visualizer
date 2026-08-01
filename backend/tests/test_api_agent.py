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

CREDS = {"email": "agent@example.com", "password": "hunter2pw", "username": "agentuser"}


def _client_with_agent(planner, reg):
    app = create_app()
    # One agent for the whole client, as in production (deps.get_agent is a
    # singleton): a per-request instance would carry its own checkpointer, so a
    # run paused by /agent/analyze would not exist by the time /agent/answer
    # tried to resume it.
    agent = AgentService(planner=planner, registry=reg)
    app.dependency_overrides[get_agent] = lambda: agent
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


def _paused_client(api_db):
    """A run parked on the row-removal gate, ready to be answered over HTTP."""
    reg = DatasetRegistry()
    plan = {
        "intent": "comparison",
        "preprocessing": [{"op": "drop_nulls", "columns": ["deck"], "how": "any"}],
        "group_by": ["class"],
        "aggregations": [{"column": "fare", "fn": "mean", "as": "avg_fare"}],
    }
    client = _client_with_agent(FakePlanner(plans=[plan]), reg)
    headers = _auth(client)
    ds = client.post(
        "/datasets",
        json={"file_ref": data_path("general-testing", "titanic.csv")},
        headers=headers,
    ).json()["dataset_id"]
    paused = client.post(
        "/agent/analyze",
        json={"request": "avg fare by class without missing decks", "dataset_id": ds},
        headers=headers,
    ).json()
    assert paused["status"] == "waiting_for_user", paused
    return client, headers, paused


def test_a_pause_carries_the_fields_needed_to_answer_it(api_db):
    _, _, paused = _paused_client(api_db)
    assert paused["interrupt_id"]
    assert paused["pending_count"] >= 1


def test_answer_accepts_an_interrupt_id(api_db):
    client, headers, paused = _paused_client(api_db)
    r = client.post(
        "/agent/answer",
        json={
            "thread_id": paused["thread_id"],
            "answer": "Skip cleaning (keep all rows)",
            "interrupt_id": paused["interrupt_id"],
        },
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "completed", r.json()


def test_answer_without_an_interrupt_id_still_works(api_db):
    client, headers, paused = _paused_client(api_db)
    r = client.post(
        "/agent/answer",
        json={"thread_id": paused["thread_id"], "answer": "Skip cleaning (keep all rows)"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "completed", r.json()
