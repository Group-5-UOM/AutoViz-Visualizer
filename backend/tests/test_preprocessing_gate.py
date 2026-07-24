"""Shared-pipeline confirmation gate: run_pipeline enforces the row-removal rule
regardless of caller, and approval is bound to the preprocessing block's hash."""

from autoviz.schema.analysis_plan import AnalysisPlan
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


def test_over_threshold_returns_confirmation_required(registry, nulls_id):
    out = run_pipeline(nulls_id, _drop_plan(nulls_id), registry)
    assert out["status"] == "confirmation_required"
    conf = out["confirmation"]
    assert conf["impact"]["dropped"] == 4
    assert conf["options"] == ["Proceed with cleaning", "Skip cleaning (keep all rows)"]
    assert conf["preprocessing_hash"] == AnalysisPlan.model_validate(_drop_plan(nulls_id)).preprocessing_hash()


def test_matching_hash_executes(registry, nulls_id):
    plan = _drop_plan(nulls_id)
    approved = AnalysisPlan.model_validate(plan).preprocessing_hash()
    out = run_pipeline(nulls_id, plan, registry, approved_preprocessing_hash=approved)
    assert out["status"] == "ok", out
    assert out["result"]["output_rows"] == 6


def test_wrong_hash_still_gates(registry, nulls_id):
    out = run_pipeline(nulls_id, _drop_plan(nulls_id), registry, approved_preprocessing_hash="deadbeef")
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
