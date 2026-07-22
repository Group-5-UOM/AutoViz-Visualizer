from autoviz.services.execution import execute_analysis


def test_group_by_sum_shape(registry, iris_id):
    plan = {
        "dataset_id": iris_id,
        "intent": "comparison",
        "group_by": ["species"],
        "aggregations": [{"column": "sepal_length", "fn": "mean", "as": "avg_sepal_length"}],
        "sort": [{"by": "avg_sepal_length", "dir": "desc"}],
    }
    result = execute_analysis(iris_id, plan, registry)
    assert "error" not in result, result
    assert result["row_count"] == 3
    rows = result["result_table"]
    assert set(rows[0].keys()) == {"species", "avg_sepal_length"}
    values = [r["avg_sepal_length"] for r in rows]
    assert values == sorted(values, reverse=True)
    assert result["provenance"]["sql"].startswith("WITH base AS")


def test_month_derive_on_seattle_weather(registry, weather_id):
    plan = {
        "dataset_id": weather_id,
        "intent": "trend",
        "derive": [{"name": "month", "from": "date", "fn": "month"}],
        "group_by": ["month"],
        "aggregations": [{"column": "precipitation", "fn": "sum", "as": "total_precip"}],
        "sort": [{"by": "month", "dir": "asc"}],
    }
    result = execute_analysis(weather_id, plan, registry)
    assert "error" not in result, result
    assert result["row_count"] == 12
    months = [r["month"] for r in result["result_table"]]
    assert months == list(range(1, 13))


def test_filter_eq(registry, iris_id):
    plan = {
        "dataset_id": iris_id,
        "intent": "distribution",
        "select": ["species", "sepal_length"],
        "filters": [{"column": "species", "op": "eq", "value": "setosa"}],
        "limit": 1000,
    }
    result = execute_analysis(iris_id, plan, registry)
    assert "error" not in result, result
    assert result["row_count"] == 50
    assert all(r["species"] == "setosa" for r in result["result_table"])


def test_hard_row_ceiling_on_diamonds(registry, diamonds_id):
    plan = {
        "dataset_id": diamonds_id,
        "intent": "distribution",
        "select": ["carat", "price"],
        "limit": 1000,
    }
    result = execute_analysis(diamonds_id, plan, registry)
    assert "error" not in result, result
    # diamonds has 53,940 rows; ceiling must hold.
    assert result["row_count"] <= 1000


def test_invalid_plan_returns_structured_error(registry, iris_id):
    plan = {
        "dataset_id": iris_id,
        "intent": "comparison",
        "group_by": ["not_a_column"],
        "aggregations": [{"column": "sepal_length", "fn": "sum", "as": "s"}],
    }
    result = execute_analysis(iris_id, plan, registry)
    assert result["error"] == "Plan failed validation"
    assert result["validation_errors"]
