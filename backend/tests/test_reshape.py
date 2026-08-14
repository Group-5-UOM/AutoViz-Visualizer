"""Reshape: pivot_longer and split_column.

These are the first ops that change the table's *shape* rather than its values,
so the tests split in two. Half are about the reshape itself. The other half are
about everything downstream believing it — validation and the chart encoder both
have to see the post-cleaning table, and the failure mode when they do not is a
plan rejected for naming a column that exists, or an axis typed against a column
that no longer does.
"""

import pandas as pd
import pytest

from autoviz.schema.allowlists import Risk
from autoviz.schema.analysis_plan import AnalysisPlan
from autoviz.services import dataset
from autoviz.services.execution import execute_analysis
from autoviz.services.orchestrator import run_pipeline
from autoviz.services.validation import validate_analysis_plan

# The archetypal spreadsheet export: one column per month.
WIDE = [
    {"region": "North", "Jan": 10, "Feb": 20, "Mar": 30},
    {"region": "South", "Jan": 5, "Feb": 15, "Mar": 25},
]

FOLD = {
    "op": "pivot_longer",
    "columns": ["Jan", "Feb", "Mar"],
    "names_to": "month",
    "values_to": "revenue",
}


def _register(registry, tmp_path, name, rows):
    path = tmp_path / name
    pd.DataFrame(rows).to_csv(path, index=False)
    return dataset.register_dataset(path.as_posix(), registry)["dataset_id"]


@pytest.fixture()
def wide_id(registry, tmp_path):
    return _register(registry, tmp_path, "wide.csv", WIDE)


def _plan(ds, **extra):
    base = {"dataset_id": ds, "intent": "comparison"}
    base.update(extra)
    return base


def _x_type(spec: dict) -> str:
    """The x channel's Vega type, whether or not the spec was layered.

    Bar charts get a value-label layer bolted on, which moves `encoding` down a
    level; line charts do not. Reading `spec["encoding"]` directly therefore
    works for one and KeyErrors on the other.
    """
    if "encoding" in spec:
        return spec["encoding"]["x"]["type"]
    return spec["layer"][0]["encoding"]["x"]["type"]


# --- tier ----------------------------------------------------------------------


def test_reshape_ops_are_safe_and_do_not_remove_rows():
    """Changing shape is not changing meaning. Neither op alters, invents or
    discards a value, so neither needs consent — but neither is ever proposed
    automatically either, because whether twelve columns are one repeated
    measurement is a question about the data's meaning, not its contents."""
    plan = AnalysisPlan.model_validate(
        {
            "dataset_id": "ds_x",
            "intent": "comparison",
            "preprocessing": [
                FOLD,
                {"op": "split_column", "column": "region", "separator": "-",
                 "into": ["a", "b"]},
            ],
        }
    )
    assert all(op.risk is Risk.SAFE for op in plan.preprocessing)
    assert not plan.has_row_dropping_preprocessing()


# --- pivot_longer ---------------------------------------------------------------


def test_a_wide_file_becomes_groupable(registry, wide_id):
    """The capability, in one assertion: "revenue by month" is unanswerable on a
    file where month is a header, because group_by takes values, not names."""
    out = execute_analysis(
        wide_id,
        _plan(
            wide_id,
            intent="trend",
            preprocessing=[FOLD],
            group_by=["month"],
            aggregations=[{"column": "revenue", "fn": "sum", "as": "total"}],
            sort=[{"by": "total", "dir": "desc"}],
        ),
        registry,
    )
    assert "error" not in out, out
    assert [(r["month"], r["total"]) for r in out["result_table"]] == [
        ("Mar", 55.0), ("Feb", 35.0), ("Jan", 15.0)
    ]


def test_unfolded_columns_are_carried_down(registry, wide_id):
    out = execute_analysis(
        wide_id,
        _plan(wide_id, preprocessing=[FOLD], select=["region", "month", "revenue"]),
        registry,
    )
    assert "error" not in out, out
    assert out["row_count"] == 6  # 2 regions x 3 months
    north = [r for r in out["result_table"] if r["region"] == "North"]
    assert {r["month"]: r["revenue"] for r in north} == {"Jan": 10, "Feb": 20, "Mar": 30}


def test_pivot_multiplies_rows_without_tripping_the_removal_gate(registry, wide_id):
    """The gate measures rows lost. This op only ever adds them, and a naive
    `input - output` reading would go negative rather than large."""
    out = execute_analysis(
        wide_id, _plan(wide_id, preprocessing=[FOLD], select=["month"]), registry
    )
    assert "error" not in out, out
    assert out["input_rows"] == 2 and out["output_rows"] == 6


def test_folded_columns_stop_existing(registry, wide_id):
    """Referencing a folded column is a plan error, not a runtime one — the
    column is genuinely gone by the time the query runs."""
    verdict = validate_analysis_plan(
        wide_id, _plan(wide_id, preprocessing=[FOLD], select=["Jan"]), registry
    )
    assert verdict["valid"] is False
    assert any("'Jan' does not exist" in e for e in verdict["errors"])


def test_the_new_columns_start_existing(registry, wide_id):
    verdict = validate_analysis_plan(
        wide_id,
        _plan(
            wide_id,
            preprocessing=[FOLD],
            filters=[{"column": "month", "op": "eq", "value": "Jan"}],
            aggregations=[{"column": "revenue", "fn": "sum", "as": "t"}],
        ),
        registry,
    )
    assert verdict["valid"] is True, verdict


def test_mixed_types_are_refused_rather_than_stringified(registry, tmp_path):
    """SQL stacks the folded columns into one, so they need a common type.
    Silently widening everything to text would break the aggregation downstream
    with an error that no longer mentions the pivot."""
    ds = _register(
        registry, tmp_path, "mixed.csv",
        [{"k": "a", "num": 1, "txt": "x"}, {"k": "b", "num": 2, "txt": "y"}],
    )
    verdict = validate_analysis_plan(
        ds,
        _plan(ds, preprocessing=[{
            "op": "pivot_longer", "columns": ["num", "txt"],
            "names_to": "n", "values_to": "v",
        }]),
        registry,
    )
    assert verdict["valid"] is False
    assert any("share one type" in e for e in verdict["errors"])


def test_new_names_may_not_collide_with_a_surviving_column(registry, wide_id):
    verdict = validate_analysis_plan(
        wide_id,
        _plan(wide_id, preprocessing=[{
            "op": "pivot_longer", "columns": ["Jan", "Feb", "Mar"],
            "names_to": "region", "values_to": "revenue",
        }]),
        registry,
    )
    assert verdict["valid"] is False
    assert any("collides" in e for e in verdict["errors"])


def test_pivot_discloses_the_reshape(registry, wide_id):
    out = execute_analysis(
        wide_id, _plan(wide_id, preprocessing=[FOLD], select=["month"]), registry
    )
    note = next(n for n in out["provenance"]["notices"] if n["kind"] == "pivot_longer")
    assert "2 row(s) became 6" in note["note"]
    # No percentage: affected/input is over 100% here and would read as a bug.
    assert "%" not in note["note"]


# --- split_column ----------------------------------------------------------------


PERIODS = [
    {"period": "2026-Q3", "v": 1},
    {"period": "2025-Q1", "v": 2},
    {"period": "unknown", "v": 3},
]

SPLIT = {
    "op": "split_column", "column": "period", "separator": "-",
    "into": ["year", "quarter"],
}


def test_split_adds_the_parts_and_keeps_the_source(registry, tmp_path):
    ds = _register(registry, tmp_path, "periods.csv", PERIODS)
    out = execute_analysis(
        ds, _plan(ds, preprocessing=[SPLIT], select=["period", "year", "quarter"]), registry
    )
    assert "error" not in out, out
    rows = {r["period"]: (r["year"], r["quarter"]) for r in out["result_table"]}
    assert rows["2026-Q3"] == ("2026", "Q3")
    # A row without the separator keeps what there was and nulls the rest, rather
    # than failing the whole op — one odd row is not a reason to refuse.
    assert rows["unknown"] == ("unknown", None)


def test_split_reports_how_often_the_separator_was_found(registry, tmp_path):
    """A split that fires on 2 of 3 rows may be fine; one that fires on 3 of 900
    is the wrong separator, and nothing else in the output would say so."""
    ds = _register(registry, tmp_path, "periods2.csv", PERIODS)
    out = execute_analysis(ds, _plan(ds, preprocessing=[SPLIT], select=["year"]), registry)
    note = next(n for n in out["provenance"]["notices"] if n["kind"] == "split_column")
    assert "2 of 3" in note["note"]


def test_split_parts_are_text_until_explicitly_parsed(registry, tmp_path):
    """Summing 'year' must be a type error: the split cannot quietly retype, or a
    zip code beginning 0 silently becomes a number and loses its leading digit."""
    ds = _register(registry, tmp_path, "periods3.csv", PERIODS)
    verdict = validate_analysis_plan(
        ds,
        _plan(ds, preprocessing=[SPLIT],
              aggregations=[{"column": "year", "fn": "sum", "as": "t"}]),
        registry,
    )
    assert verdict["valid"] is False
    assert any("requires a numeric column" in e for e in verdict["errors"])


def test_split_then_parse_number_makes_a_part_aggregatable(registry, tmp_path):
    """And the explicit route works: ops see each other's output in order."""
    ds = _register(registry, tmp_path, "periods4.csv", PERIODS[:2])
    plan = _plan(
        ds,
        preprocessing=[SPLIT, {"op": "parse_number", "columns": ["year"]}],
        aggregations=[{"column": "year", "fn": "max", "as": "latest"}],
    )
    assert validate_analysis_plan(ds, plan, registry)["valid"] is True
    out = execute_analysis(ds, plan, registry)
    assert out["result_table"][0]["latest"] == 2026.0


def test_split_refuses_to_overwrite_an_existing_column(registry, tmp_path):
    ds = _register(registry, tmp_path, "clash.csv", [{"period": "a-b", "year": 1}])
    verdict = validate_analysis_plan(
        ds, _plan(ds, preprocessing=[SPLIT]), registry
    )
    assert verdict["valid"] is False
    assert any("already exists" in e for e in verdict["errors"])


# --- downstream belief -----------------------------------------------------------


def test_a_pivoted_trend_reaches_the_chart_as_a_real_time_axis(registry, tmp_path):
    """The whole stack at once: fold the month columns, parse the labels into
    dates, truncate, and check the encoder received a temporal axis.

    This is also the regression for a bug the earlier phase left behind — the
    chart encoder had its own copy of the derive-type mapping, so a truncated
    period arrived as `quantitative` and an ISO timestamp was plotted on a linear
    scale. Validation alone would not have caught it.
    """
    rows = [{"region": "North", "2026-01-15": 10, "2026-02-15": 20}]
    ds = _register(registry, tmp_path, "wide_dates.csv", rows)
    out = run_pipeline(
        ds,
        _plan(
            ds,
            intent="trend",
            preprocessing=[
                {"op": "pivot_longer", "columns": ["2026-01-15", "2026-02-15"],
                 "names_to": "day", "values_to": "revenue"},
                {"op": "cast_column", "column": "day", "to": "datetime"},
            ],
            derive=[{"name": "period", "from": "day", "fn": "month_start"}],
            group_by=["period"],
            aggregations=[{"column": "revenue", "fn": "sum", "as": "total"}],
            chart={"type": "line", "x": "period", "y": "total"},
        ),
        registry,
    )
    assert out["status"] == "ok", out
    assert _x_type(out["vega_lite_spec"]) == "temporal"


def test_an_extracted_month_still_reaches_the_chart_as_a_number(registry, tmp_path):
    """The other half of the same mapping, so a fix to one does not silently
    swap the other."""
    rows = [{"d": "2026-01-15", "rev": 10}, {"d": "2026-02-15", "rev": 20}]
    ds = _register(registry, tmp_path, "narrow.csv", rows)
    out = run_pipeline(
        ds,
        _plan(
            ds,
            intent="comparison",
            derive=[{"name": "m", "from": "d", "fn": "month"}],
            group_by=["m"],
            aggregations=[{"column": "rev", "fn": "sum", "as": "total"}],
            chart={"type": "bar", "x": "m", "y": "total"},
        ),
        registry,
    )
    assert out["status"] == "ok", out
    assert _x_type(out["vega_lite_spec"]) == "quantitative"
