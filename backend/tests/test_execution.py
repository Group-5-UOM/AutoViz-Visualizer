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


def test_distribution_without_limit_returns_all_rows(registry, titanic_id):
    # Regression: a distribution plan with no explicit limit must NOT be capped
    # at the old default of 100 — the histogram needs every value. Titanic has
    # 891 rows; all must come through (they're under the 100000 ceiling).
    plan = {"dataset_id": titanic_id, "intent": "distribution", "select": ["age"]}
    result = execute_analysis(titanic_id, plan, registry)
    assert "error" not in result, result
    assert result["row_count"] == 891
    assert result["provenance"]["sql"].endswith("LIMIT 100000")


def test_explicit_limit_is_still_honored(registry, titanic_id):
    # A ranking/top-N plan that sets an explicit small limit is respected.
    plan = {
        "dataset_id": titanic_id,
        "intent": "ranking",
        "select": ["fare"],
        "sort": [{"by": "fare", "dir": "desc"}],
        "limit": 10,
    }
    result = execute_analysis(titanic_id, plan, registry)
    assert "error" not in result, result
    assert result["row_count"] == 10


def test_hard_row_ceiling_on_diamonds(registry, diamonds_id):
    plan = {
        "dataset_id": diamonds_id,
        "intent": "distribution",
        "select": ["carat", "price"],
        "limit": 999999,
    }
    result = execute_analysis(diamonds_id, plan, registry)
    assert "error" not in result, result
    # diamonds has 53,940 rows, so after clamping to 100000 the whole result fits.
    assert result["row_count"] == 53940
    assert result["provenance"]["sql"].endswith("LIMIT 100000")


def test_mean_ignores_missing_values_on_penguins(registry):
    from autoviz.services.dataset import register_dataset
    from tests.conftest import data_path

    penguins_id = register_dataset(data_path("general-testing", "penguins.csv"), registry)[
        "dataset_id"
    ]
    plan = {
        "dataset_id": penguins_id,
        "intent": "comparison",
        "group_by": ["species"],
        "aggregations": [{"column": "body_mass_g", "fn": "mean", "as": "avg_mass"}],
    }
    result = execute_analysis(penguins_id, plan, registry)
    assert "error" not in result, result
    # body_mass_g has real NaNs; DuckDB's avg skips NULLs, so means must be
    # present and plausible for all 3 species, never null.
    assert result["row_count"] == 3
    assert all(2500 < r["avg_mass"] < 7000 for r in result["result_table"])


def test_between_date_range_on_seattle_weather(registry, weather_id):
    plan = {
        "dataset_id": weather_id,
        "intent": "trend",
        "filters": [
            {"column": "date", "op": "between", "value": ["2015-06-01", "2015-08-31"]}
        ],
        "derive": [{"name": "month", "from": "date", "fn": "month"}],
        "group_by": ["month"],
        "aggregations": [{"column": "precipitation", "fn": "sum", "as": "total_precip"}],
        "sort": [{"by": "month", "dir": "asc"}],
    }
    result = execute_analysis(weather_id, plan, registry)
    assert "error" not in result, result
    months = [r["month"] for r in result["result_table"]]
    assert months == [6, 7, 8]


def test_in_filter_on_iris_species(registry, iris_id):
    plan = {
        "dataset_id": iris_id,
        "intent": "comparison",
        "select": ["species", "sepal_length"],
        "filters": [{"column": "species", "op": "in", "value": ["setosa", "virginica"]}],
        "limit": 1000,
    }
    result = execute_analysis(iris_id, plan, registry)
    assert "error" not in result, result
    assert result["row_count"] == 100
    assert {r["species"] for r in result["result_table"]} == {"setosa", "virginica"}


def test_count_distinct_on_titanic(registry, titanic_id):
    plan = {
        "dataset_id": titanic_id,
        "intent": "comparison",
        "aggregations": [
            {"column": "embark_town", "fn": "count_distinct", "as": "n_towns"}
        ],
    }
    result = execute_analysis(titanic_id, plan, registry)
    assert "error" not in result, result
    assert result["result_table"][0]["n_towns"] == 3


def test_median_grouped_on_iris(registry, iris_id):
    plan = {
        "dataset_id": iris_id,
        "intent": "comparison",
        "group_by": ["species"],
        "aggregations": [
            {"column": "sepal_length", "fn": "median", "as": "median_sepal_length"}
        ],
    }
    result = execute_analysis(iris_id, plan, registry)
    assert "error" not in result, result
    assert result["row_count"] == 3
    assert all(4.0 < r["median_sepal_length"] < 8.0 for r in result["result_table"])


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


# --- null predicates ---------------------------------------------------------
#
# `is_null` / `is_not_null` were in FILTER_OPS and accepted by validation from
# the start, but `build_sql` had no rule for either, so a plan that validated
# cleanly raised KeyError inside the engine — reported as a *retryable*
# EXECUTION_ERROR, which sent the agent into a backoff loop re-running a plan
# that could never succeed. Found by bench/nl_suite.py T05.


def test_is_not_null_filters_out_missing(registry, titanic_id):
    plan = {
        "dataset_id": titanic_id,
        "intent": "comparison",
        "filters": [{"column": "embark_town", "op": "is_not_null"}],
        "group_by": ["embark_town"],
        "aggregations": [{"column": "fare", "fn": "mean", "as": "avg_fare"}],
    }
    result = execute_analysis(titanic_id, plan, registry)
    assert "error" not in result, result
    towns = [r["embark_town"] for r in result["result_table"]]
    assert None not in towns
    assert "IS NOT NULL" in result["provenance"]["sql"]


def test_is_null_selects_only_missing(registry, titanic_id):
    plan = {
        "dataset_id": titanic_id,
        "intent": "comparison",
        "filters": [{"column": "embark_town", "op": "is_null"}],
        "group_by": ["embark_town"],
        "aggregations": [{"column": "fare", "fn": "mean", "as": "avg_fare"}],
    }
    result = execute_analysis(titanic_id, plan, registry)
    assert "error" not in result, result
    assert [r["embark_town"] for r in result["result_table"]] == [None]
    assert "IS NULL" in result["provenance"]["sql"]


def test_null_predicates_bind_no_parameters(registry, titanic_id):
    """A stray placeholder here would shift every later filter's parameter."""
    plan = {
        "dataset_id": titanic_id,
        "intent": "comparison",
        "filters": [
            {"column": "embark_town", "op": "is_not_null"},
            {"column": "fare", "op": "gt", "value": 50},
        ],
        "group_by": ["embark_town"],
        "aggregations": [{"column": "fare", "fn": "min", "as": "min_fare"}],
    }
    result = execute_analysis(titanic_id, plan, registry)
    assert "error" not in result, result
    assert all(r["min_fare"] > 50 for r in result["result_table"])
