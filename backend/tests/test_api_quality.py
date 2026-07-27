"""The read-only quality surface over HTTP.

Read-only is the property worth pinning: these routes tell a caller what is wrong
and what it would cost to fix, but applying anything still goes through the one
gated write path.
"""

from fastapi.testclient import TestClient

from autoviz.api.deps import get_registry
from autoviz.api.main import create_app
from autoviz.services.dataset import register_dataset
from autoviz.services.registry import DatasetRegistry


def _client(tmp_path, text, name="q.csv"):
    reg = DatasetRegistry()
    p = tmp_path / name
    p.write_text(text)
    ds = register_dataset(p.as_posix(), reg)["dataset_id"]
    app = create_app()
    app.dependency_overrides[get_registry] = lambda: reg
    return TestClient(app), ds, reg


def test_quality_report_splits_auto_from_asked(tmp_path):
    client, ds, _ = _client(
        tmp_path, "sex,salary\nMale,100\nmale,\nMALE,300\nFemale,400\n"
    )
    body = client.post("/analysis/quality", json={"dataset_id": ds}).json()

    assert body["row_count"] == 4
    # Case folding is semantics-preserving: applied without asking.
    assert {"op": "normalize_case", "column": "sex"} in body["auto_apply"]
    # A missing salary changes the number: it becomes a question, never an auto-fix.
    assert [p["slot"] for p in body["proposals"]] == ["missing:salary"]
    options = body["proposals"][0]["options"]
    assert sum(1 for o in options if o["recommended"]) == 1
    assert any("median" in o["technique"] for o in options)


def test_quality_report_honours_the_column_scope(tmp_path):
    client, ds, _ = _client(tmp_path, "clean,messy\na,  x  \nb,  y  \n")
    scoped = client.post(
        "/analysis/quality", json={"dataset_id": ds, "columns": ["clean"]}
    ).json()
    assert scoped["issues"] == [] and scoped["auto_apply"] == []

    whole = client.post("/analysis/quality", json={"dataset_id": ds}).json()
    assert any(i["kind"] == "untrimmed_whitespace" for i in whole["issues"])


def test_quality_report_rejects_an_unknown_dataset(tmp_path):
    client, _ds, _ = _client(tmp_path, "a\n1\n")
    body = client.post("/analysis/quality", json={"dataset_id": "ds_nope"}).json()
    assert body["error_code"] == "UNKNOWN_DATASET"


def test_preview_preprocessing_counts_without_running_anything(tmp_path):
    client, ds, reg = _client(tmp_path, "cls,fare\na,1\nb,\nc,\nd,4\n")
    before = reg.get(ds).df.copy(deep=True)
    body = client.post(
        "/analysis/preview-preprocessing",
        json={
            "dataset_id": ds,
            "analysis_plan": {
                "dataset_id": ds,
                "intent": "comparison",
                "preprocessing": [{"op": "drop_nulls", "columns": ["fare"], "how": "any"}],
                "select": ["cls", "fare"],
            },
        },
    ).json()

    assert body["input_rows"] == 4 and body["output_rows"] == 2
    assert body["dropped"] == 2 and body["fraction"] == 0.5
    assert body["preprocessing"][0]["rows_affected"] == 2
    assert "result_table" not in body  # measured, not executed
    assert reg.get(ds).df.equals(before)  # and the source is untouched


def test_preview_preprocessing_reports_an_invalid_plan(tmp_path):
    client, ds, _ = _client(tmp_path, "a\n1\n")
    body = client.post(
        "/analysis/preview-preprocessing",
        json={
            "dataset_id": ds,
            "analysis_plan": {
                "dataset_id": ds,
                "intent": "comparison",
                "preprocessing": [{"op": "drop_nulls", "columns": ["ghost"], "how": "any"}],
            },
        },
    ).json()
    assert body["valid"] is False
    assert any("does not exist" in e for e in body["errors"])


def test_preview_does_not_gate_because_it_never_executes(tmp_path):
    """Previewing a removal above the threshold is exactly how a caller shows the
    user what they are being asked to approve — so it must not itself demand
    approval."""
    client, ds, _ = _client(tmp_path, "cls,fare\na,1\nb,\nc,\nd,\n")
    body = client.post(
        "/analysis/preview-preprocessing",
        json={
            "dataset_id": ds,
            "analysis_plan": {
                "dataset_id": ds,
                "intent": "comparison",
                "preprocessing": [{"op": "drop_nulls", "columns": ["fare"], "how": "any"}],
                "select": ["cls", "fare"],
            },
        },
    ).json()
    assert body["dropped"] == 3  # 75%, well over the gate
    assert "error_code" not in body
