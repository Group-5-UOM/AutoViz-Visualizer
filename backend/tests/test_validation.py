from autoviz.services.validation import validate_analysis_plan


def _iris_plan(**overrides):
    plan = {
        "dataset_id": "unused",
        "intent": "comparison",
        "select": [],
        "group_by": ["species"],
        "aggregations": [{"column": "sepal_length", "fn": "mean", "as": "avg_sepal_length"}],
        "chart": {"type": "bar", "x": "species", "y": "avg_sepal_length"},
    }
    plan.update(overrides)
    return plan


def test_valid_plan_passes(registry, iris_id):
    verdict = validate_analysis_plan(iris_id, _iris_plan(), registry)
    assert verdict["valid"], verdict["errors"]


def test_unknown_dataset_fails(registry):
    verdict = validate_analysis_plan("ds_nope", _iris_plan(), registry)
    assert not verdict["valid"]


def test_unknown_column_fails(registry, iris_id):
    verdict = validate_analysis_plan(iris_id, _iris_plan(group_by=["speciez"]), registry)
    assert not verdict["valid"]
    assert any("speciez" in e for e in verdict["errors"])


def test_sum_on_string_column_fails(registry, iris_id):
    plan = _iris_plan(
        aggregations=[{"column": "species", "fn": "sum", "as": "nonsense"}],
        chart=None,
    )
    verdict = validate_analysis_plan(iris_id, plan, registry)
    assert not verdict["valid"]
    assert any("numeric" in e for e in verdict["errors"])


def test_op_outside_allowlist_fails(registry, iris_id):
    plan = _iris_plan(filters=[{"column": "sepal_length", "op": "regex", "value": ".*"}])
    verdict = validate_analysis_plan(iris_id, plan, registry)
    assert not verdict["valid"]


def test_agg_fn_outside_allowlist_fails(registry, iris_id):
    plan = _iris_plan(
        aggregations=[{"column": "sepal_length", "fn": "variance", "as": "var"}], chart=None
    )
    verdict = validate_analysis_plan(iris_id, plan, registry)
    assert not verdict["valid"]


def test_unknown_top_level_field_fails(registry, iris_id):
    verdict = validate_analysis_plan(iris_id, _iris_plan(sql="SELECT 1"), registry)
    assert not verdict["valid"]


def test_group_by_capped_at_two(registry, iris_id):
    plan = _iris_plan(group_by=["species", "sepal_length", "sepal_width"])
    verdict = validate_analysis_plan(iris_id, plan, registry)
    assert not verdict["valid"]


def test_limit_clamped_via_repaired_plan(registry, iris_id):
    verdict = validate_analysis_plan(iris_id, _iris_plan(limit=999999), registry)
    assert verdict["valid"]
    assert verdict["repaired_plan"]["limit"] == 100000


def test_chart_channel_must_be_produced(registry, iris_id):
    plan = _iris_plan(chart={"type": "bar", "x": "species", "y": "petal_width"})
    verdict = validate_analysis_plan(iris_id, plan, registry)
    assert not verdict["valid"]
    assert any("chart.y" in e for e in verdict["errors"])


def test_month_derive_on_non_date_fails(registry, iris_id):
    plan = _iris_plan(derive=[{"name": "m", "from": "species", "fn": "month"}])
    verdict = validate_analysis_plan(iris_id, plan, registry)
    assert not verdict["valid"]


def test_month_derive_on_date_passes(registry, weather_id):
    plan = {
        "dataset_id": "unused",
        "intent": "trend",
        "derive": [{"name": "month", "from": "date", "fn": "month"}],
        "group_by": ["month"],
        "aggregations": [{"column": "precipitation", "fn": "sum", "as": "total_precip"}],
        "chart": {"type": "line", "x": "month", "y": "total_precip"},
    }
    verdict = validate_analysis_plan(weather_id, plan, registry)
    assert verdict["valid"], verdict["errors"]


def test_injection_like_filter_value_rejected(registry, iris_id):
    plan = _iris_plan(
        filters=[{"column": "species", "op": "contains", "value": "x'; DROP TABLE df; --"}]
    )
    verdict = validate_analysis_plan(iris_id, plan, registry)
    assert not verdict["valid"]
    assert any("resembles code" in e for e in verdict["errors"])


def test_between_requires_two_values(registry, iris_id):
    plan = _iris_plan(
        filters=[{"column": "sepal_length", "op": "between", "value": [1.0]}]
    )
    verdict = validate_analysis_plan(iris_id, plan, registry)
    assert not verdict["valid"]
    assert any("exactly 2" in e for e in verdict["errors"])


def test_between_two_values_passes(registry, iris_id):
    plan = _iris_plan(
        filters=[{"column": "sepal_length", "op": "between", "value": [4.0, 6.0]}]
    )
    verdict = validate_analysis_plan(iris_id, plan, registry)
    assert verdict["valid"], verdict["errors"]


def test_in_requires_a_list(registry, iris_id):
    plan = _iris_plan(filters=[{"column": "species", "op": "in", "value": "setosa"}])
    verdict = validate_analysis_plan(iris_id, plan, registry)
    assert not verdict["valid"]
    assert any("list" in e for e in verdict["errors"])


def test_scalar_op_rejects_list_value(registry, iris_id):
    plan = _iris_plan(filters=[{"column": "species", "op": "eq", "value": ["setosa"]}])
    verdict = validate_analysis_plan(iris_id, plan, registry)
    assert not verdict["valid"]
    assert any("scalar" in e for e in verdict["errors"])


def test_injection_inside_in_list_rejected(registry, iris_id):
    plan = _iris_plan(
        filters=[{"column": "species", "op": "in", "value": ["setosa", "x; DROP TABLE df"]}]
    )
    verdict = validate_analysis_plan(iris_id, plan, registry)
    assert not verdict["valid"]
    assert any("resembles code" in e for e in verdict["errors"])


def test_median_on_string_column_fails(registry, iris_id):
    plan = _iris_plan(
        aggregations=[{"column": "species", "fn": "median", "as": "med"}], chart=None
    )
    verdict = validate_analysis_plan(iris_id, plan, registry)
    assert not verdict["valid"]
    assert any("numeric" in e for e in verdict["errors"])


def test_gte_on_string_column_fails(registry, iris_id):
    plan = _iris_plan(filters=[{"column": "species", "op": "gte", "value": "a"}])
    verdict = validate_analysis_plan(iris_id, plan, registry)
    assert not verdict["valid"]


def test_histogram_rejects_non_numeric_x(registry, iris_id):
    plan = _iris_plan(
        group_by=["species"],
        aggregations=[{"column": "sepal_length", "fn": "mean", "as": "avg"}],
        chart={"type": "histogram", "x": "species"},
    )
    verdict = validate_analysis_plan(iris_id, plan, registry)
    assert not verdict["valid"]
    assert any("numeric" in e for e in verdict["errors"])


def test_histogram_without_y_passes(registry, iris_id):
    plan = {
        "dataset_id": "unused",
        "intent": "distribution",
        "select": ["sepal_length"],
        "chart": {"type": "histogram", "x": "sepal_length"},
    }
    verdict = validate_analysis_plan(iris_id, plan, registry)
    assert verdict["valid"], verdict["errors"]


def test_non_histogram_requires_y(registry, iris_id):
    plan = _iris_plan(chart={"type": "bar", "x": "species"})
    verdict = validate_analysis_plan(iris_id, plan, registry)
    assert not verdict["valid"]
    assert any("chart.y" in e for e in verdict["errors"])
