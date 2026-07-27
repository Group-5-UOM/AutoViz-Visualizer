"""Invariants the preprocessing layer must keep as ops are added to it.

Everything here pins a behaviour that was previously unpinned, and in several
cases wrong. The unifying theme is that a cleaning layer's failure modes are all
*quiet* — an op that isn't recognised, a disclosure that gets overwritten, an
imputation nobody was asked about. Loud failure is the property being tested.
"""

import threading

import pytest

from autoviz.errors import INVALID_PLAN
from autoviz.schema.allowlists import Risk
from autoviz.schema.analysis_plan import AnalysisPlan, _PreprocessOpBase
from autoviz.services import dataset
from autoviz.services.execution import (
    DUCKDB_THREADS,
    _governed_connection,
    execute_analysis,
    preprocessing_impact,
)
from autoviz.services.validation import validate_analysis_plan


def _plan(ds, **extra):
    base = {"dataset_id": ds, "intent": "comparison"}
    base.update(extra)
    return base


# --- an op must declare its own behaviour -------------------------------------


def test_op_model_must_declare_risk_and_row_behaviour():
    """Forgetting either flag is a definition-time error, not a runtime surprise.

    Both defaults would fail open: an op not recognised as row-dropping skips the
    confirmation gate and survives "Skip cleaning".
    """
    with pytest.raises(TypeError, match="must declare"):

        class Forgetful(_PreprocessOpBase):
            op: str = "forgetful"


def test_declared_flags_drive_the_gate_not_the_op_name(nulls_id):
    plan = AnalysisPlan.model_validate(
        _plan(nulls_id, preprocessing=[{"op": "fill_nulls", "column": "age", "strategy": "median"}])
    )
    assert plan.has_row_dropping_preprocessing() is False
    assert all(op.risk is Risk.VALUE_CHANGING for op in plan.preprocessing)

    plan = AnalysisPlan.model_validate(
        _plan(nulls_id, preprocessing=[{"op": "drop_exact_duplicates"}])
    )
    assert plan.has_row_dropping_preprocessing() is True


def test_columns_touched_feeds_validation(registry, nulls_id):
    """A column named only by preprocessing is still checked for existence."""
    v = validate_analysis_plan(
        nulls_id,
        _plan(nulls_id, preprocessing=[{"op": "drop_nulls", "columns": ["nope"], "how": "any"}]),
        registry,
    )
    assert not v["valid"]
    assert any("does not exist" in e for e in v["errors"])


# --- chained ops: parameter ordering and prefix bookkeeping --------------------


def test_two_fill_nulls_bind_their_values_in_order(registry, nulls_id):
    """Two fills in one plan — the case that breaks first if CTE params and
    placeholders ever drift out of lockstep. No previous test had more than one."""
    plan = _plan(
        nulls_id,
        preprocessing=[
            {"op": "fill_nulls", "column": "fare", "strategy": "constant", "value": 99},
            {"op": "fill_nulls", "column": "age", "strategy": "constant", "value": 7},
        ],
        select=["cls", "fare", "age"],
    )
    out = execute_analysis(nulls_id, plan, registry)
    assert "error" not in out, out
    rows = out["result_table"]
    assert [r["fare"] for r in rows].count(99) == 3  # idx 1, 4, 7
    assert [r["age"] for r in rows].count(7) == 2  # idx 2, 6
    # Each op reports its own effect, measured over the chain prefix it saw.
    assert [s["rows_affected"] for s in out["preprocessing"]] == [3, 2]


def test_fill_plus_value_bearing_filter_keeps_params_aligned(registry, nulls_id):
    """Preprocessing params are bound ahead of WHERE params. Nothing exercised
    both being non-empty, so a swap would have gone unnoticed."""
    plan = _plan(
        nulls_id,
        preprocessing=[
            {"op": "fill_nulls", "column": "fare", "strategy": "constant", "value": 99}
        ],
        filters=[{"column": "cls", "op": "eq", "value": "a"}],
        select=["cls", "fare"],
    )
    out = execute_analysis(nulls_id, plan, registry)
    assert "error" not in out, out
    assert {r["cls"] for r in out["result_table"]} == {"a"}
    # cls="a" rows are idx 0,1,4,6,8 -> fares 10, null, null, 40, 10; the two
    # nulls take the fill value and the filter literal is bound separately.
    assert sorted(r["fare"] for r in out["result_table"]) == [10, 10, 40, 99, 99]


def test_duplicates_created_by_an_earlier_fill_are_removed(registry, tmp_path):
    """Op order is semantic: filling first *creates* the duplicate rows that
    de-duplicating then removes."""
    p = tmp_path / "fill_then_dedupe.csv"
    p.write_text("a,b\n1,x\n1,\n2,y\n")
    ds = dataset.register_dataset(p.as_posix(), registry)["dataset_id"]
    plan = _plan(
        ds,
        preprocessing=[
            {"op": "fill_nulls", "column": "b", "strategy": "constant", "value": "x"},
            {"op": "drop_exact_duplicates"},
        ],
        select=["a", "b"],
    )
    approved = AnalysisPlan.model_validate(plan).preprocessing_version(ds)
    out = execute_analysis(ds, plan, registry, approved_preprocessing_hash=approved)
    assert "error" not in out, out
    assert out["input_rows"] == 3 and out["output_rows"] == 2
    assert out["preprocessing"][1]["rows_affected"] == 1


# --- a step that cannot be computed is a plan defect, not an engine fault ------


def test_column_all_null_only_within_the_working_view(registry, tmp_path):
    """PreprocessError's live path: `b` is not all-null in the source, so
    validation passes, but every surviving row after the drop has b null — the
    median only becomes uncomputable *inside* the chain."""
    p = tmp_path / "conditional_null.csv"
    p.write_text("a,b\n1,\n,2\n,3\n")
    ds = dataset.register_dataset(p.as_posix(), registry)["dataset_id"]
    plan = _plan(
        ds,
        preprocessing=[
            {"op": "drop_nulls", "columns": ["a"], "how": "any"},
            {"op": "fill_nulls", "column": "b", "strategy": "median"},
        ],
        select=["a", "b"],
    )
    assert validate_analysis_plan(ds, plan, registry)["valid"]  # raw frame looks fine

    approved = AnalysisPlan.model_validate(plan).preprocessing_version(ds)
    out = execute_analysis(ds, plan, registry, approved_preprocessing_hash=approved)
    assert out["error_code"] == INVALID_PLAN, out
    assert "entirely null at this stage" in out["error"]


def test_bad_datetime_constant_is_rejected_before_execution(registry, tmp_path):
    """An unparseable date must fail as a repairable plan defect. As a runtime
    DuckDB error it was classified retryable, so the agent re-ran an identical
    failing plan and the planner was never told to fix the literal."""
    p = tmp_path / "dates.csv"
    p.write_text("when,v\n2024-01-01,1\n,2\n2024-03-01,3\n")
    ds = dataset.register_dataset(p.as_posix(), registry)["dataset_id"]
    plan = _plan(
        ds,
        preprocessing=[
            {"op": "fill_nulls", "column": "when", "strategy": "constant", "value": "not-a-date"}
        ],
        select=["when", "v"],
    )
    v = validate_analysis_plan(ds, plan, registry)
    assert not v["valid"]
    assert any("not a recognisable date/time" in e for e in v["errors"])

    out = execute_analysis(ds, plan, registry)
    assert out["error_code"] == INVALID_PLAN


def test_good_datetime_constant_still_fills(registry, tmp_path):
    p = tmp_path / "dates_ok.csv"
    p.write_text("when,v\n2024-01-01,1\n,2\n2024-03-01,3\n")
    ds = dataset.register_dataset(p.as_posix(), registry)["dataset_id"]
    plan = _plan(
        ds,
        preprocessing=[
            {"op": "fill_nulls", "column": "when", "strategy": "constant", "value": "2024-02-01"}
        ],
        select=["when", "v"],
    )
    out = execute_analysis(ds, plan, registry)
    assert "error" not in out, out
    assert all(r["when"] is not None for r in out["result_table"])


# --- disclosure survives cleaning ---------------------------------------------


def test_imputing_does_not_erase_the_null_exclusion_notice(registry, nulls_id):
    """Measured before cleaning, so the plan that hides more does not report less.

    Both plans average `fare`, which has 3 nulls. The filled one substitutes a
    value for every one of them — that average is 30% synthetic and must say so.
    """
    base = _plan(
        nulls_id,
        group_by=["cls"],
        aggregations=[{"column": "fare", "fn": "mean", "as": "avg_fare"}],
    )
    plain = execute_analysis(nulls_id, base, registry)
    assert plain["provenance"]["implicit_null_exclusions"]["fare"] == 3

    filled = execute_analysis(
        nulls_id,
        {
            **base,
            "preprocessing": [
                {"op": "fill_nulls", "column": "fare", "strategy": "constant", "value": 0}
            ],
        },
        registry,
    )
    # The disclosure is still there — imputing cannot quietly clear it.
    assert filled["provenance"]["implicit_null_exclusions"]["fare"] == 3
    notices = filled["provenance"]["imputation_notices"]
    assert len(notices) == 1
    assert notices[0]["column"] == "fare" and notices[0]["rows_imputed"] == 3


def test_small_imputation_gets_no_notice(registry, tmp_path):
    """Below the notice threshold the number is not meaningfully affected."""
    rows = "\n".join("a,1" for _ in range(99))
    p = tmp_path / "one_null.csv"
    p.write_text(f"cls,v\n{rows}\na,\n")
    ds = dataset.register_dataset(p.as_posix(), registry)["dataset_id"]
    out = execute_analysis(
        ds,
        _plan(
            ds,
            preprocessing=[
                {"op": "fill_nulls", "column": "v", "strategy": "constant", "value": 1}
            ],
            group_by=["cls"],
            aggregations=[{"column": "v", "fn": "mean", "as": "avg_v"}],
        ),
        registry,
    )
    assert out["provenance"]["imputation_notices"] == []  # 1/100 = 1%


def test_cleaning_columns_are_reported_as_used(registry, nulls_id):
    """`fare` decides which rows survive, so it is used even though it appears in
    neither the grouping nor the aggregation."""
    out = execute_analysis(
        nulls_id,
        _plan(
            nulls_id,
            preprocessing=[{"op": "drop_nulls", "columns": ["fare"], "how": "any"}],
            group_by=["cls"],
            aggregations=[{"column": "age", "fn": "mean", "as": "avg_age"}],
        ),
        registry,
    )
    assert "error" not in out, out
    assert "fare" in out["provenance"]["columns_used"]


def test_provenance_carries_the_logical_version(registry, nulls_id):
    plan = _plan(
        nulls_id,
        preprocessing=[
            {"op": "fill_nulls", "column": "age", "strategy": "median"}
        ],
        select=["age"],
    )
    out = execute_analysis(nulls_id, plan, registry)
    version = out["provenance"]["preprocessing_version"]
    assert version.startswith("pp_")
    assert version == AnalysisPlan.model_validate(plan).preprocessing_version(nulls_id)


# --- the impact measurement runs under the same governors as the query ---------


def test_governed_connection_applies_the_resource_limits():
    """Deterministic check that the governors are actually set — the ungoverned
    path had no memory cap, no thread cap and no watchdog at all."""
    with _governed_connection() as (con, _guard):
        threads = con.execute("SELECT current_setting('threads')").fetchone()[0]
        memory = con.execute("SELECT current_setting('memory_limit')").fetchone()[0]
    assert str(threads) == DUCKDB_THREADS
    assert memory  # normalised by DuckDB (e.g. "1.0 GiB"), just has to be set


def test_governed_connection_observes_cancellation():
    """A governed connection watches the cancel event and interrupts on it.

    Asserted on the watcher rather than on a query that loses a race: whether any
    given query is still in flight when the interrupt lands is timing, but the
    watcher noticing is the property that has to hold.
    """
    cancel = threading.Event()
    with _governed_connection(cancel) as (_con, guard):
        assert not guard.cancelled.is_set()
        cancel.set()
        assert guard.cancelled.wait(timeout=5.0)


def test_preprocessing_impact_measures_without_mutating(registry, nulls_id):
    """The gate's measurement is counts-only over the same chain the query runs."""
    record = registry.get(nulls_id)
    before = record.df.copy(deep=True)
    plan = _plan(
        nulls_id, preprocessing=[{"op": "drop_nulls", "columns": ["cls", "fare"], "how": "any"}]
    )
    impact = preprocessing_impact(record, plan)
    assert impact["input_rows"] == 10
    assert impact["output_rows"] == 6
    assert impact["dropped"] == 4 and impact["fraction"] == 0.4
    assert record.df.equals(before)  # source frame untouched
