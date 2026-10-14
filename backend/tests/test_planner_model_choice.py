from types import SimpleNamespace

from autoviz.agent.service import AgentService
from autoviz.llm import client as llm_client
from autoviz.llm.client import (
    GeminiPlanner,
    IntentDecision,
    _selected_model,
    use_planner_model,
)
from autoviz.services.registry import DatasetRegistry
from tests.conftest import data_path
from tests.test_agent import FakePlanner
from tests.test_api_agent import _auth, _client_with_agent


class RecordingPlanner(FakePlanner):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.seen: list[str | None] = []

    def classify(self, *args, **kwargs):
        self.seen.append(_selected_model.get())
        return super().classify(*args, **kwargs)

    def generate_plan(self, *args, **kwargs):
        self.seen.append(_selected_model.get())
        return super().generate_plan(*args, **kwargs)


def test_choice_reaches_parallel_workers(registry, titanic_id):
    fare_task, age_task = "average fare by class", "age distribution"
    planner = RecordingPlanner(
        decisions=[IntentDecision(intent="analysis", tasks=[fare_task, age_task])],
        plans={
            fare_task: {
                "intent": "comparison",
                "group_by": ["class"],
                "aggregations": [{"column": "fare", "fn": "mean", "as": "avg_fare"}],
            },
            age_task: {"intent": "distribution", "select": ["age"]},
        },
    )
    agent = AgentService(planner=planner, registry=registry)
    with use_planner_model("qwen3.5-4b"):
        out = agent.run("fare by class, and separately ages", dataset_id=titanic_id)
    assert out["status"] == "completed", out
    assert len(planner.seen) == 3
    assert set(planner.seen) == {"qwen3.5-4b"}
    assert _selected_model.get() is None


def _fake_chat_model():
    return SimpleNamespace(invoke=lambda messages: SimpleNamespace(content="ok"))


def test_only_qwen_is_delayed(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(llm_client.time, "sleep", slept.append)
    planner = GeminiPlanner()
    planner._model = _fake_chat_model()

    with use_planner_model("gemini-3.5-flash"):
        assert planner._invoke_text("s", "u") == "ok"
    planner._invoke_text("s", "u")
    assert slept == []

    with use_planner_model("qwen3.5-4b"):
        assert planner._invoke_text("s", "u") == "ok"
    assert len(slept) == 1 and slept[0] > 0


def test_api_accepts_known_and_rejects_unknown_models(api_db):
    reg = DatasetRegistry()
    planner = RecordingPlanner(plans=[{
        "intent": "comparison",
        "group_by": ["species"],
        "aggregations": [{"column": "sepal_length", "fn": "mean", "as": "avg"}],
    }])
    client = _client_with_agent(planner, reg)
    headers = _auth(client)

    listed = client.get("/agent/models", headers=headers).json()
    assert {m["key"] for m in listed["models"]} == {"gemini-3.5-flash", "qwen3.5-4b"}

    ds = client.post(
        "/datasets",
        json={"file_ref": data_path("general-testing", "iris.csv")},
        headers=headers,
    ).json()["dataset_id"]

    bad = client.post(
        "/agent/analyze",
        json={"request": "x", "dataset_id": ds, "model": "gpt-9"},
        headers=headers,
    )
    assert bad.status_code == 422

    ok = client.post(
        "/agent/analyze",
        json={"request": "avg sepal length by species", "dataset_id": ds, "model": "qwen3.5-4b"},
        headers=headers,
    )
    assert ok.json()["status"] == "completed"
    assert set(planner.seen) == {"qwen3.5-4b"}
