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


def test_group_by_capped_at_two(registry, iris_id):
    plan = _iris_plan(group_by=["species", "sepal_length", "sepal_width"])
    verdict = validate_analysis_plan(iris_id, plan, registry)
    assert not verdict["valid"]


def test_limit_clamped_via_repaired_plan(registry, iris_id):
    verdict = validate_analysis_plan(iris_id, _iris_plan(limit=999999), registry)
    assert verdict["valid"]
    assert verdict["repaired_plan"]["limit"] == 1000


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
