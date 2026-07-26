"""HTTP analysis routes via TestClient over a real registry + DuckDB."""

from fastapi.testclient import TestClient

from autoviz.api.deps import get_registry
from autoviz.api.main import create_app
from autoviz.services.dataset import register_dataset
from autoviz.services.registry import DatasetRegistry
from tests.conftest import data_path


def _client_with_iris():
    reg = DatasetRegistry()
    dataset_id = register_dataset(data_path("general-testing", "iris.csv"), reg)["dataset_id"]
    app = create_app()
    app.dependency_overrides[get_registry] = lambda: reg
    return TestClient(app), dataset_id


def test_health():
    client = TestClient(create_app())
    assert client.get("/health").json() == {"status": "ok"}


def test_pipeline_ok_returns_chart():
    client, ds = _client_with_iris()
    plan = {
        "dataset_id": ds,
        "intent": "comparison",
        "group_by": ["species"],
        "aggregations": [{"column": "sepal_length", "fn": "mean", "as": "avg"}],
    }
    r = client.post("/analysis/pipeline", json={"dataset_id": ds, "analysis_plan": plan})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["vega_lite_spec"]["mark"]
    assert body["result"]["row_count"] == 3


def test_execute_ok():
    client, ds = _client_with_iris()
    plan = {"dataset_id": ds, "intent": "distribution", "select": ["species", "sepal_length"], "limit": 1000}
    r = client.post("/analysis/execute", json={"dataset_id": ds, "analysis_plan": plan})
    assert r.status_code == 200
    assert r.json()["row_count"] == 150


def test_validate_unknown_dataset_404():
    client, _ = _client_with_iris()
    r = client.post(
        "/analysis/validate",
        json={"dataset_id": "ds_nope", "analysis_plan": {"dataset_id": "ds_nope", "intent": "comparison", "select": ["x"]}},
    )
    assert r.status_code == 404
    assert r.json()["error_code"] == "UNKNOWN_DATASET"


def test_execute_invalid_plan_422():
    client, ds = _client_with_iris()
    plan = {
        "dataset_id": ds,
        "intent": "comparison",
        "group_by": ["not_a_column"],
        "aggregations": [{"column": "sepal_length", "fn": "sum", "as": "s"}],
    }
    r = client.post("/analysis/execute", json={"dataset_id": ds, "analysis_plan": plan})
    assert r.status_code == 422
    assert r.json()["error_code"] == "INVALID_PLAN"
