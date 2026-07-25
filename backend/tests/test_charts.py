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


def test_generate_chart_coded_category_encodes_nominal():
    # A numeric-coded category (survived 0/1) on the color channel must render as
    # discrete nominal groups, not a continuous quantitative scale.
    table = [{"pclass": 1, "avg_fare": 84.2}, {"pclass": 3, "avg_fare": 13.7}]
    out = generate_chart(
        table,
        {"type": "bar", "x": "pclass", "y": "avg_fare",
         "column_types": {"pclass": "categorical", "avg_fare": "number"}},
    )
    assert out["valid"]
    enc = out["vega_lite_spec"]["encoding"]
    assert enc["x"] == {"field": "pclass", "type": "nominal"}
    assert enc["y"] == {"field": "avg_fare", "type": "quantitative"}


def test_recommend_treats_coded_category_as_dimension():
    # pclass tagged "categorical" is the bar's x; the count stays the measure.
    schema = [{"name": "pclass", "type": "categorical"}, {"name": "n", "type": "number"}]
    rec = recommend_chart_type(schema, "distribution")
    assert rec["chart_type"] == "bar"
    assert rec["x"] == "pclass"


def test_generate_chart_rejects_disallowed_mark():
    out = generate_chart([], {"type": "heatmap", "x": "a", "y": "b"})
    assert not out["valid"]


def test_generate_chart_rejects_absent_column():
    out = generate_chart([{"a": 1}], {"type": "bar", "x": "a", "y": "missing"})
    assert not out["valid"]


def test_distribution_numeric_only_recommends_histogram():
    schema = [{"name": "price", "type": "number"}]
    rec = recommend_chart_type(schema, "distribution")
    assert rec["chart_type"] == "histogram"
    assert rec["x"] == "price"
    assert "y" not in rec


def test_generate_chart_histogram_spec():
    table = [{"price": 100}, {"price": 200}, {"price": 350}]
    out = generate_chart(table, {"type": "histogram", "x": "price"})
    assert out["valid"], out["warnings"]
    spec = out["vega_lite_spec"]
    assert spec["mark"] == "bar"
    assert spec["encoding"]["x"] == {"field": "price", "type": "quantitative", "bin": True}
    assert spec["encoding"]["y"] == {"aggregate": "count", "type": "quantitative"}


def test_generate_chart_histogram_rejects_y():
    out = generate_chart([{"price": 1}], {"type": "histogram", "x": "price", "y": "price"})
    assert not out["valid"]


def test_generate_chart_area_mark():
    table = [{"month": 1, "total": 5.0}, {"month": 2, "total": 3.0}]
    out = generate_chart(table, {"type": "area", "x": "month", "y": "total"})
    assert out["valid"]
    assert out["vega_lite_spec"]["mark"] == "area"


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


def test_pipeline_coded_category_group_by_renders_nominal(registry, titanic_id):
    # Grouping average fare by pclass: pclass is a numeric-coded category, so the
    # x axis must be nominal (discrete 1/2/3), not a continuous quantitative scale.
    plan = {
        "dataset_id": titanic_id,
        "intent": "comparison",
        "group_by": ["pclass"],
        "aggregations": [{"column": "fare", "fn": "mean", "as": "avg_fare"}],
    }
    out = run_pipeline(titanic_id, plan, registry)
    assert out["status"] == "ok", out
    enc = out["vega_lite_spec"]["encoding"]
    assert enc["x"] == {"field": "pclass", "type": "nominal"}
    assert enc["y"]["field"] == "avg_fare"
    assert enc["y"]["type"] == "quantitative"


def test_pipeline_partial_failure_keeps_executed_result(registry, iris_id):
    # Execution succeeds (string column only) but recommendation fails (no
    # numeric measure) — the computed result must still come back.
    plan = {
        "dataset_id": iris_id,
        "intent": "comparison",
        "select": ["species"],
    }
    out = run_pipeline(iris_id, plan, registry)
    assert out["status"] == "error"
    assert out["failed_step"] == "recommend_chart_type"
    assert out["result"]["row_count"] > 0  # partial result preserved


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
