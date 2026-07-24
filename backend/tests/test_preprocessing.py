"""Explicit, provenance-tracked preprocessing: execution, validation, profiling.

Uses the `nulls_id` fixture (conftest) whose null/duplicate counts are documented
and fixed, so every assertion checks an exact, known effect.
"""

from autoviz.errors import INVALID_PLAN
from autoviz.services import dataset
from autoviz.services.execution import execute_analysis, preprocessing_impact
from autoviz.services.validation import validate_analysis_plan


def _plan(ds, **extra):
    base = {"dataset_id": ds, "intent": "comparison"}
    base.update(extra)
    return base


# --- profiling ----------------------------------------------------------------


def test_profile_reports_null_percentage_and_no_unusable(registry, nulls_id):
    prof = dataset.get_dataset_profile(nulls_id, registry)
    assert prof["null_percentage"]["fare"] == 30.0
    assert prof["null_percentage"]["age"] == 20.0
    assert prof["null_percentage"]["cls"] == 10.0
    assert prof["unusable_columns"] == []
    # null_counts kept for backward compatibility.
    assert prof["null_counts"]["fare"] == 3


def test_fully_null_column_marked_unusable(registry, tmp_path):
    p = tmp_path / "empty_col.csv"
    p.write_text("a,b\n1,\n2,\n3,\n")
    ds = dataset.register_dataset(p.as_posix(), registry)["dataset_id"]
    prof = dataset.get_dataset_profile(ds, registry)
    assert prof["unusable_columns"] == ["b"]
    assert prof["null_percentage"]["b"] == 100.0


def test_empty_csv_rejected(registry, tmp_path):
    p = tmp_path / "headers_only.csv"
    p.write_text("a,b,c\n")  # header, no data rows
    out = dataset.register_dataset(p.as_posix(), registry)
    assert "error" in out and "no data rows" in out["error"]


# --- execution: drop_nulls ----------------------------------------------------


def test_drop_nulls_any_removes_rows_with_any_null(registry, nulls_id):
    plan = _plan(
        nulls_id,
        preprocessing=[{"op": "drop_nulls", "columns": ["cls", "fare"], "how": "any"}],
        select=["cls", "fare"],
    )
    out = execute_analysis(nulls_id, plan, registry)
    assert "error" not in out, out
    assert out["input_rows"] == 10
    assert out["output_rows"] == 6  # 4 rows dropped (cls-null or fare-null)
    step = out["preprocessing"][0]
    assert step["operation"] == "drop_nulls" and step["rows_affected"] == 4
    assert all(r["fare"] is not None and r["cls"] is not None for r in out["result_table"])


def test_drop_nulls_all_only_removes_rows_null_in_every_column(registry, tmp_path):
    p = tmp_path / "how_all.csv"
    # row2 is null in BOTH a and b; row1 only in a.
    p.write_text("a,b\n1,x\n,y\n,\n2,z\n")
    ds = dataset.register_dataset(p.as_posix(), registry)["dataset_id"]
    plan = _plan(ds, preprocessing=[{"op": "drop_nulls", "columns": ["a", "b"], "how": "all"}], select=["a", "b"])
    out = execute_analysis(ds, plan, registry)
    assert out["output_rows"] == 3  # only the all-null row removed
    assert out["preprocessing"][0]["rows_affected"] == 1


# --- execution: fill_nulls ----------------------------------------------------


def test_fill_median_imputes_and_reports_value(registry, nulls_id):
    plan = _plan(
        nulls_id,
        preprocessing=[{"op": "fill_nulls", "column": "age", "strategy": "median"}],
        select=["age"],
    )
    out = execute_analysis(nulls_id, plan, registry)
    step = out["preprocessing"][0]
    assert step["strategy"] == "median" and step["fill_value"] == 5.5
    assert step["rows_affected"] == 2  # two nulls filled
    assert out["output_rows"] == 10  # imputation never changes row count
    assert all(r["age"] is not None for r in out["result_table"])


def test_fill_mode_is_deterministic_on_ties(registry, nulls_id):
    # cls: a and b both appear 4 times -> tie broken by smallest value ("a").
    plan = _plan(
        nulls_id,
        preprocessing=[{"op": "fill_nulls", "column": "cls", "strategy": "mode"}],
        select=["cls"],
    )
    out = execute_analysis(nulls_id, plan, registry)
    assert out["preprocessing"][0]["fill_value"] == "a"


def test_fill_constant(registry, nulls_id):
    plan = _plan(
        nulls_id,
        preprocessing=[{"op": "fill_nulls", "column": "fare", "strategy": "constant", "value": 0}],
        select=["fare"],
    )
    out = execute_analysis(nulls_id, plan, registry)
    assert out["preprocessing"][0]["fill_value"] == 0
    assert all(r["fare"] is not None for r in out["result_table"])


def test_fill_median_on_all_null_column_is_structured_error(registry, tmp_path):
    p = tmp_path / "allnull.csv"
    p.write_text("a,b\n1,\n2,\n")
    ds = dataset.register_dataset(p.as_posix(), registry)["dataset_id"]
    # Validation already blocks a fully-null column, so bypass it by registering a
    # column that only becomes all-null after an earlier drop is not possible here;
    # instead assert the validation gate fires.
    plan = _plan(ds, preprocessing=[{"op": "fill_nulls", "column": "b", "strategy": "median"}], select=["a"])
    v = validate_analysis_plan(ds, plan, registry)
    assert not v["valid"]
    assert any("entirely null" in e for e in v["errors"])


# --- execution: drop_exact_duplicates -----------------------------------------


def test_drop_exact_duplicates(registry, tmp_path):
    p = tmp_path / "dups.csv"
    p.write_text("a,b\n1,x\n1,x\n2,y\n1,x\n")  # 3 identical (1,x) rows
    ds = dataset.register_dataset(p.as_posix(), registry)["dataset_id"]
    plan = _plan(ds, preprocessing=[{"op": "drop_exact_duplicates"}], select=["a", "b"])
    out = execute_analysis(ds, plan, registry)
    assert out["input_rows"] == 4 and out["output_rows"] == 2
    assert out["preprocessing"][0]["rows_affected"] == 2


# --- provenance & immutability ------------------------------------------------


def test_provenance_and_source_immutability(registry, nulls_id):
    plan = _plan(
        nulls_id,
        preprocessing=[{"op": "drop_nulls", "columns": ["fare"], "how": "any"}],
        group_by=["cls"],
        aggregations=[{"column": "fare", "fn": "mean", "as": "avg_fare"}],
    )
    out = execute_analysis(nulls_id, plan, registry)
    prov = out["provenance"]
    assert prov["preprocessing"] == out["preprocessing"]
    assert any("df_raw" in cte for cte in prov["preprocessing_sql"])
    # The raw frame in the registry still holds its nulls — nothing was mutated.
    assert int(registry.get(nulls_id).df["fare"].isna().sum()) == 3


def test_implicit_null_exclusions_noted_for_aggregated_column(registry, nulls_id):
    # avg over fare (which has nulls, no drop applied) -> provenance states the count.
    plan = _plan(
        nulls_id,
        group_by=["cls"],
        aggregations=[{"column": "fare", "fn": "mean", "as": "avg_fare"}],
    )
    out = execute_analysis(nulls_id, plan, registry)
    assert out["provenance"]["implicit_null_exclusions"].get("fare") == 3


# --- preprocessing_impact (gate input) ----------------------------------------


def test_preprocessing_impact_counts_only(registry, nulls_id):
    plan = _plan(
        nulls_id,
        preprocessing=[{"op": "drop_nulls", "columns": ["cls", "fare"], "how": "any"}],
    )
    impact = preprocessing_impact(registry.get(nulls_id), plan)
    assert impact["input_rows"] == 10 and impact["output_rows"] == 6
    assert impact["dropped"] == 4 and impact["fraction"] == 0.4


# --- validation ---------------------------------------------------------------


def _invalid(registry, ds, preprocessing, **extra):
    v = validate_analysis_plan(ds, _plan(ds, preprocessing=preprocessing, **extra), registry)
    assert not v["valid"], "expected validation failure"
    return v["errors"]


def test_valid_preprocessing_plan_passes(registry, nulls_id):
    v = validate_analysis_plan(
        nulls_id,
        _plan(
            nulls_id,
            preprocessing=[
                {"op": "drop_nulls", "columns": ["cls"], "how": "any"},
                {"op": "fill_nulls", "column": "age", "strategy": "median"},
            ],
            select=["cls", "age"],
        ),
        registry,
    )
    assert v["valid"], v["errors"]


def test_median_on_string_rejected(registry, nulls_id):
    errs = _invalid(registry, nulls_id, [{"op": "fill_nulls", "column": "cls", "strategy": "median"}])
    assert any("requires a numeric column" in e for e in errs)


def test_mode_on_numeric_rejected(registry, nulls_id):
    errs = _invalid(registry, nulls_id, [{"op": "fill_nulls", "column": "fare", "strategy": "mode"}])
    assert any("categorical" in e for e in errs)


def test_constant_without_value_rejected(registry, nulls_id):
    errs = _invalid(registry, nulls_id, [{"op": "fill_nulls", "column": "fare", "strategy": "constant"}])
    assert any("requires a value" in e for e in errs)


def test_constant_type_mismatch_rejected(registry, nulls_id):
    errs = _invalid(
        registry, nulls_id, [{"op": "fill_nulls", "column": "fare", "strategy": "constant", "value": "n/a"}]
    )
    assert any("numeric constant" in e for e in errs)


def test_unknown_preprocessing_column_rejected(registry, nulls_id):
    errs = _invalid(registry, nulls_id, [{"op": "drop_nulls", "columns": ["nope"], "how": "any"}])
    assert any("does not exist" in e for e in errs)


def test_is_null_filter_with_value_rejected(registry, nulls_id):
    v = validate_analysis_plan(
        nulls_id,
        _plan(nulls_id, filters=[{"column": "fare", "op": "is_null", "value": 1}], select=["fare"]),
        registry,
    )
    assert not v["valid"]
    assert any("takes no value" in e for e in v["errors"])


def test_is_not_null_filter_valid_on_any_type(registry, nulls_id):
    v = validate_analysis_plan(
        nulls_id,
        _plan(nulls_id, filters=[{"column": "cls", "op": "is_not_null"}], select=["cls"]),
        registry,
    )
    assert v["valid"], v["errors"]


def test_conflicting_fill_and_drop_on_same_column_rejected(registry, nulls_id):
    errs = _invalid(
        registry,
        nulls_id,
        [
            {"op": "fill_nulls", "column": "fare", "strategy": "median"},
            {"op": "drop_nulls", "columns": ["fare"], "how": "any"},
        ],
    )
    assert any("conflicting" in e for e in errs)


def test_too_many_preprocessing_steps_rejected(registry, nulls_id):
    steps = [{"op": "drop_exact_duplicates"} for _ in range(11)]
    v = validate_analysis_plan(nulls_id, _plan(nulls_id, preprocessing=steps), registry)
    assert not v["valid"]  # schema max_length=10 -> INVALID_PLAN
    assert v["error_code"] == INVALID_PLAN
