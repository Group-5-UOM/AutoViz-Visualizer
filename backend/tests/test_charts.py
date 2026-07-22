from autoviz.services.charts import generate_chart, recommend_chart_type
from autoviz.services.orchestrator import run_pipeline


def test_trend_with_datetime_recommends_line():
    schema = [{"name": "date", "type": "datetime"}, {"name": "total", "type": "number"}]
    rec = recommend_chart_type(schema, "trend")
    assert rec["chart_type"] == "line"
    assert rec["x"] == "date"
    assert rec["y"] == "total"
    assert rec["rationale"]


def test_relationship_two_numeric_recommends_scatter():
    schema = [{"name": "a", "type": "number"}, {"name": "b", "type": "number"}]
    rec = recommend_chart_type(schema, "relationship")
    assert rec["chart_type"] == "scatter"


def test_comparison_categorical_recommends_bar():
    schema = [{"name": "region", "type": "string"}, {"name": "revenue", "type": "number"}]
    rec = recommend_chart_type(schema, "comparison")
    assert rec["chart_type"] == "bar"


def test_no_numeric_column_is_structured_error():
    rec = recommend_chart_type([{"name": "region", "type": "string"}], "comparison")
    assert "error" in rec


def test_generate_chart_bar_spec():
    table = [{"species": "setosa", "avg": 5.0}, {"species": "virginica", "avg": 6.6}]
    out = generate_chart(table, {"type": "bar", "x": "species", "y": "avg"})
    assert out["valid"]
    spec = out["vega_lite_spec"]
    assert spec["mark"] == "bar"
    assert spec["encoding"]["x"] == {"field": "species", "type": "nominal"}
    assert spec["encoding"]["y"] == {"field": "avg", "type": "quantitative"}
    assert spec["data"]["values"] == table


def test_generate_chart_rejects_disallowed_mark():
    out = generate_chart([], {"type": "heatmap", "x": "a", "y": "b"})
    assert not out["valid"]


def test_generate_chart_rejects_absent_column():
    out = generate_chart([{"a": 1}], {"type": "bar", "x": "a", "y": "missing"})
    assert not out["valid"]


def test_pipeline_end_to_end_iris(registry, iris_id):
    plan = {
        "dataset_id": iris_id,
        "intent": "comparison",
        "group_by": ["species"],
        "aggregations": [{"column": "sepal_length", "fn": "mean", "as": "avg_sepal_length"}],
    }
    out = run_pipeline(iris_id, plan, registry)
    assert out["status"] == "ok", out
    assert out["recommendation"]["chart_type"] == "bar"
    assert out["vega_lite_spec"]["mark"] == "bar"
    assert out["result"]["row_count"] == 3


def test_pipeline_structured_error_names_failed_step(registry, iris_id):
    plan = {
        "dataset_id": iris_id,
        "intent": "comparison",
        "group_by": ["ghost"],
        "aggregations": [{"column": "sepal_length", "fn": "mean", "as": "avg"}],
    }
    out = run_pipeline(iris_id, plan, registry)
    assert out["status"] == "error"
    assert out["failed_step"] == "validate_analysis_plan"
