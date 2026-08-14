"""Trends over time: truncation vs extraction.

`date_part('month', d)` returns a bare 1-12, so grouping a two-year dataset by it
adds January 2025 to January 2026 and plots twelve points. The result is a chart
that looks entirely reasonable and reports numbers that were never measured.

Nothing raises, so only a test that checks the *shape of the answer* catches it.
These pin both halves: the truncating fns produce one point per real period, and
the extracting fns keep doing what they are for.
"""

import pandas as pd
import pytest

from autoviz.services import dataset
from autoviz.services.execution import execute_analysis
from autoviz.services.validation import validate_analysis_plan

# Two years, one row per month, revenue distinguishable per year so a collapse is
# visible in the value and not only in the row count.
TWO_YEARS = [
    {"d": f"{year}-{month:02d}-15", "rev": (1 if year == 2025 else 10) * month}
    for year in (2025, 2026)
    for month in range(1, 13)
]


@pytest.fixture()
def trend_id(registry, tmp_path):
    path = tmp_path / "trend.csv"
    pd.DataFrame(TWO_YEARS).to_csv(path, index=False)
    return dataset.register_dataset(path.as_posix(), registry)["dataset_id"]


def _grouped(registry, ds, fn):
    return execute_analysis(
        ds,
        {
            "dataset_id": ds,
            "intent": "trend",
            "derive": [{"name": "period", "from": "d", "fn": fn}],
            "group_by": ["period"],
            "aggregations": [{"column": "rev", "fn": "sum", "as": "total"}],
            "sort": [{"by": "period", "dir": "asc"}],
        },
        registry,
    )


def test_month_start_keeps_the_years_apart(registry, trend_id):
    out = _grouped(registry, trend_id, "month_start")
    assert out["row_count"] == 24
    first, last = out["result_table"][0], out["result_table"][-1]
    assert first["period"].startswith("2025-01") and first["total"] == 1
    assert last["period"].startswith("2026-12") and last["total"] == 120


def test_month_collapses_the_years_together(registry, trend_id):
    """Not a bug — the documented behaviour of an extraction, and the right answer
    to "which month is busiest?". It is only wrong when asked for a trend, which
    is why the two fns exist separately and the plan guide says which to use."""
    out = _grouped(registry, trend_id, "month")
    assert out["row_count"] == 12
    # January 2025 (1) + January 2026 (10) — the sum the trend must not report.
    assert out["result_table"][0] == {"period": 1, "total": 11}


@pytest.mark.parametrize(
    "fn,expected",
    [("year_start", 2), ("quarter_start", 8), ("month_start", 24), ("week_start", 24)],
)
def test_each_truncation_yields_one_point_per_period(registry, trend_id, fn, expected):
    assert _grouped(registry, trend_id, fn)["row_count"] == expected


def test_truncation_produces_a_datetime_not_a_number(registry, trend_id):
    """The type matters beyond tidiness: mistyped as a number, a truncated period
    passes a numeric aggregation check it should fail and lands on a quantitative
    axis, where 2026-01 sits a fixed distance from 2025-01 for the wrong reason."""
    verdict = validate_analysis_plan(
        trend_id,
        {
            "dataset_id": trend_id,
            "intent": "trend",
            "derive": [{"name": "period", "from": "d", "fn": "month_start"}],
            # mean of a period is meaningless; it is only reachable if the derive
            # was typed as a number.
            "aggregations": [{"column": "period", "fn": "mean", "as": "avg"}],
        },
        registry,
    )
    assert verdict["valid"] is False
    assert any("requires a numeric column" in e for e in verdict["errors"])


def test_extraction_is_still_a_number(registry, trend_id):
    verdict = validate_analysis_plan(
        trend_id,
        {
            "dataset_id": trend_id,
            "intent": "trend",
            "derive": [{"name": "m", "from": "d", "fn": "month"}],
            "aggregations": [{"column": "m", "fn": "mean", "as": "avg"}],
        },
        registry,
    )
    assert verdict["valid"] is True


def test_truncation_needs_a_datetime_column(registry, trend_id):
    verdict = validate_analysis_plan(
        trend_id,
        {
            "dataset_id": trend_id,
            "intent": "trend",
            "derive": [{"name": "period", "from": "rev", "fn": "month_start"}],
        },
        registry,
    )
    assert verdict["valid"] is False
    assert any("requires a datetime column" in e for e in verdict["errors"])
