"""End-to-end Titanic workflow across the real services:

    register -> profile -> plan -> validate -> execute -> chart

Exercises the canonical host-LLM path (the granular tools' business logic) with
no LLM and no mocks — deterministic DuckDB + Vega-Lite the whole way.
"""

from autoviz.services.charts import generate_chart, recommend_chart_type
from autoviz.services.dataset import (
    get_dataset_profile,
    get_dataset_schema,
    register_dataset,
)
from autoviz.services.execution import execute_analysis
from autoviz.services.orchestrator import run_pipeline
from autoviz.services.validation import validate_analysis_plan
from tests.conftest import data_path

# "Average fare by passenger class" — one bar chart, three groups.
FARE_BY_CLASS = {
    "intent": "comparison",
    "group_by": ["class"],
    "aggregations": [{"column": "fare", "fn": "mean", "as": "avg_fare"}],
    "sort": [{"by": "avg_fare", "dir": "desc"}],
}


def test_titanic_full_workflow(registry):
    # 1. register -----------------------------------------------------------
    registered = register_dataset(data_path("general-testing", "titanic.csv"), registry)
    assert "error" not in registered, registered
    dataset_id = registered["dataset_id"]
    assert registered["row_count"] == 891
    assert registered["column_count"] == 15

    # 2. profile ------------------------------------------------------------
    profile = get_dataset_profile(dataset_id, registry)
    assert profile["null_counts"]["age"] > 0  # Titanic ages are famously missing
    assert profile["cardinality"]["class"] == 3
    assert "fare" in profile["summary_stats"]

    schema = {c["name"]: c["type"] for c in get_dataset_schema(dataset_id, registry)["columns"]}
    assert schema["fare"] == "number"
    assert schema["class"] == "string"

    # 3. plan + 4. validate -------------------------------------------------
    plan = {"dataset_id": dataset_id, **FARE_BY_CLASS}
    verdict = validate_analysis_plan(dataset_id, plan, registry)
    assert verdict["valid"] is True, verdict

    # 5. execute ------------------------------------------------------------
    executed = execute_analysis(dataset_id, plan, registry)
    assert "error" not in executed, executed
    assert executed["row_count"] == 3  # First / Second / Third
    fares = [r["avg_fare"] for r in executed["result_table"]]
    assert fares == sorted(fares, reverse=True)  # First class paid the most
    assert executed["provenance"]["sql"].startswith("WITH base AS")

    # 6. chart (via the orchestrated pipeline) ------------------------------
    piped = run_pipeline(dataset_id, plan, registry)
    assert piped["status"] == "ok", piped
    assert piped["chart_spec"]["type"] == "bar"  # ranking/comparison over categorical
    assert piped["vega_lite_spec"]["mark"]
    assert piped["recommendation"]["chart_type"] == "bar"


def test_titanic_drop_nulls_reports_exact_effect(registry):
    """Explicit cleaning end-to-end. Counts are derived from the profile, never
    hardcoded — dropping age-nulls must remove exactly the profiled null count."""
    dataset_id = register_dataset(data_path("general-testing", "titanic.csv"), registry)[
        "dataset_id"
    ]
    profile = get_dataset_profile(dataset_id, registry)
    age_nulls = profile["null_counts"]["age"]
    assert age_nulls > 0  # Titanic ages are famously missing

    plan = {
        "dataset_id": dataset_id,
        "intent": "comparison",
        "preprocessing": [{"op": "drop_nulls", "columns": ["age"], "how": "any"}],
        "group_by": ["class"],
        "aggregations": [{"column": "age", "fn": "mean", "as": "avg_age"}],
    }
    executed = execute_analysis(dataset_id, plan, registry)
    assert executed["input_rows"] == 891
    assert executed["preprocessing"][0]["rows_affected"] == age_nulls
    assert executed["output_rows"] == 891 - age_nulls

    # Dropping age-nulls is well under the 30% gate, so the pipeline runs directly.
    piped = run_pipeline(dataset_id, plan, registry)
    assert piped["status"] == "ok", piped
    # Source frame untouched: the nulls are still there.
    assert int(registry.get(dataset_id).df["age"].isna().sum()) == age_nulls


def test_titanic_chart_step_in_isolation(registry):
    """The recommend -> generate half of the workflow on the executed table."""
    dataset_id = register_dataset(data_path("general-testing", "titanic.csv"), registry)[
        "dataset_id"
    ]
    plan = {"dataset_id": dataset_id, **FARE_BY_CLASS}
    result_table = execute_analysis(dataset_id, plan, registry)["result_table"]

    result_schema = [{"name": "class", "type": "string"}, {"name": "avg_fare", "type": "number"}]
    rec = recommend_chart_type(result_schema, "comparison")
    assert "error" not in rec
    chart = generate_chart(result_table, {"type": rec["chart_type"], "x": rec["x"], "y": rec["y"]})
    assert chart["valid"] is True, chart["warnings"]
    assert chart["vega_lite_spec"]["mark"]
