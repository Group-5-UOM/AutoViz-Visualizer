"""The row-removal confirmation gate.

The property under test is not "run_pipeline gates" but "*nothing* runs an
unapproved large row removal". That distinction is the whole point: the gate used
to live in run_pipeline while the code it guards lives in execute_analysis, which
two public entry points reach directly — so the rule held for one caller and
silently did not for the others.
"""

from fastapi.testclient import TestClient

from autoviz.api.deps import get_registry
from autoviz.api.main import app
from autoviz.errors import CONFIRMATION_REQUIRED
from autoviz.schema.analysis_plan import AnalysisPlan
from autoviz.services.execution import execute_analysis
from autoviz.services.orchestrator import run_pipeline


def _drop_plan(ds):
    # drop_nulls(cls, fare) removes 4/10 = 40% (> 30% gate) on the nulls_id fixture.
    return {
        "dataset_id": ds,
        "intent": "comparison",
        "preprocessing": [{"op": "drop_nulls", "columns": ["cls", "fare"], "how": "any"}],
        "group_by": ["cls"],
        "aggregations": [{"column": "fare", "fn": "mean", "as": "avg_fare"}],
    }


def _token(ds, plan):
    return AnalysisPlan.model_validate(plan).preprocessing_version(ds)


# --- the gate is unbypassable -------------------------------------------------


def test_execute_analysis_refuses_unapproved_removal(registry, nulls_id):
    """The service entry point, which is what actually runs the cleaning stage."""
    out = execute_analysis(nulls_id, _drop_plan(nulls_id), registry)
    assert out["error_code"] == CONFIRMATION_REQUIRED
    assert "result_table" not in out  # nothing ran
    assert out["confirmation"]["impact"]["dropped"] == 4


def test_http_execute_route_refuses_unapproved_removal(registry, nulls_id):
    """POST /analysis/execute — reaches the cleaning stage without run_pipeline."""
    app.dependency_overrides[get_registry] = lambda: registry
    try:
        client = TestClient(app)
        res = client.post(
            "/analysis/execute",
            json={"dataset_id": nulls_id, "analysis_plan": _drop_plan(nulls_id)},
        )
        body = res.json()
        assert body.get("error_code") == CONFIRMATION_REQUIRED, body
        assert "result_table" not in body
    finally:
        app.dependency_overrides.clear()


def test_execute_analysis_runs_with_a_matching_token(registry, nulls_id):
    plan = _drop_plan(nulls_id)
    out = execute_analysis(
        nulls_id, plan, registry, approved_preprocessing_hash=_token(nulls_id, plan)
    )
    assert "error" not in out, out
    assert out["output_rows"] == 6


# --- consent is bound to the block AND the dataset ----------------------------


def test_token_from_another_dataset_is_refused(registry, nulls_id, tmp_path):
    """Consent was given for a *measured impact*, so it cannot travel to other data.

    The identical cleaning block removes 4 of 10 rows on one frame and 3 of 4 on
    another; a token covering only the op list would authorise both.
    """
    from autoviz.services import dataset

    p = tmp_path / "other.csv"
    p.write_text("cls,fare\nA,1\n,\n,\n,\n")
    other = dataset.register_dataset(p.as_posix(), registry)["dataset_id"]

    plan_here = _drop_plan(nulls_id)
    plan_there = {**_drop_plan(other), "dataset_id": other}
    # Same preprocessing block, different dataset.
    assert plan_here["preprocessing"] == plan_there["preprocessing"]

    stolen = _token(nulls_id, plan_here)
    out = execute_analysis(
        other, plan_there, registry, approved_preprocessing_hash=stolen
    )
    assert out["error_code"] == CONFIRMATION_REQUIRED


def test_token_is_stable_under_column_reordering(registry, nulls_id):
    """["cls","fare"] and ["fare","cls"] are the same predicate, so a replan that
    reorders them must not re-prompt a user who already approved it."""
    a = _drop_plan(nulls_id)
    b = _drop_plan(nulls_id)
    b["preprocessing"][0]["columns"] = ["fare", "cls"]
    assert _token(nulls_id, a) == _token(nulls_id, b)

    out = execute_analysis(
        nulls_id, b, registry, approved_preprocessing_hash=_token(nulls_id, a)
    )
    assert "error" not in out, out


def test_op_order_still_changes_the_token(registry, nulls_id):
    """Op *order* is semantic — filling then de-duplicating is not the reverse."""
    fill = {"op": "fill_nulls", "column": "fare", "strategy": "constant", "value": 0}
    dedupe = {"op": "drop_exact_duplicates"}
    one = {"dataset_id": nulls_id, "intent": "comparison", "preprocessing": [fill, dedupe]}
    two = {"dataset_id": nulls_id, "intent": "comparison", "preprocessing": [dedupe, fill]}
    assert _token(nulls_id, one) != _token(nulls_id, two)


# --- pipeline translation and thresholds --------------------------------------


def test_over_threshold_returns_confirmation_required(registry, nulls_id):
    out = run_pipeline(nulls_id, _drop_plan(nulls_id), registry)
    assert out["status"] == "confirmation_required"
    conf = out["confirmation"]
    assert conf["impact"]["dropped"] == 4
    assert conf["options"] == ["Proceed with cleaning", "Skip cleaning (keep all rows)"]
    assert conf["preprocessing_hash"] == _token(nulls_id, _drop_plan(nulls_id))


def test_matching_hash_executes(registry, nulls_id):
    plan = _drop_plan(nulls_id)
    out = run_pipeline(
        nulls_id, plan, registry, approved_preprocessing_hash=_token(nulls_id, plan)
    )
    assert out["status"] == "ok", out
    assert out["result"]["output_rows"] == 6


def test_wrong_hash_still_gates(registry, nulls_id):
    out = run_pipeline(
        nulls_id, _drop_plan(nulls_id), registry, approved_preprocessing_hash="deadbeef"
    )
    assert out["status"] == "confirmation_required"


def test_under_threshold_never_gates(registry, nulls_id):
    # drop only fare-nulls = 3/10 = 30%, which is NOT strictly greater than 30%.
    plan = {
        "dataset_id": nulls_id,
        "intent": "comparison",
        "preprocessing": [{"op": "drop_nulls", "columns": ["fare"], "how": "any"}],
        "select": ["fare"],
    }
    out = run_pipeline(nulls_id, plan, registry)
    assert out["status"] == "ok", out


def test_fill_only_plan_never_gates(registry, nulls_id):
    plan = {
        "dataset_id": nulls_id,
        "intent": "comparison",
        "preprocessing": [{"op": "fill_nulls", "column": "fare", "strategy": "constant", "value": 0}],
        "group_by": ["cls"],
        "aggregations": [{"column": "fare", "fn": "mean", "as": "avg_fare"}],
    }
    out = run_pipeline(nulls_id, plan, registry)
    assert out["status"] == "ok", out
