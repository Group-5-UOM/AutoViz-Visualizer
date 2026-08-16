"""The Arrow scan source, and the pandas fallback behind it.

`execute_analysis` hands DuckDB a cached Arrow view of the frame instead of the
frame itself, because re-crossing the pandas boundary on every query dominated
query latency. These tests pin the two properties that make that safe: the
conversion is transparent to results, and a frame that will not convert still
runs.
"""

import pandas as pd
import pytest

from autoviz.services.dataset import build_record
from autoviz.services.execution import execute_analysis
from autoviz.services.registry import DatasetRecord


def _plan(dataset_id: str) -> dict:
    return {
        "dataset_id": dataset_id,
        "intent": "comparison",
        "group_by": ["team"],
        "aggregations": [
            {"column": "score", "fn": "sum", "as": "total"},
            {"column": "score", "fn": "median", "as": "mid"},
        ],
        "sort": [{"by": "team", "dir": "asc"}],
    }


@pytest.fixture()
def frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "team": ["a", "b", "a", "b", "c"],
            "score": [1.5, 2.0, 3.0, 4.5, 10.0],
            "when": pd.to_datetime(
                ["2026-01-01", "2026-02-01", "2026-01-15", "2026-03-01", "2026-02-20"]
            ),
        }
    )


def test_record_exposes_an_arrow_table(registry, frame):
    record = build_record(frame, "arrow-src", registry)
    table = record.arrow()
    assert table is not None
    assert table.num_rows == 5
    assert set(table.column_names) == {"team", "score", "when"}


def test_arrow_table_is_converted_once(registry, frame):
    record = build_record(frame, "arrow-src", registry)
    assert record.arrow() is record.arrow()


def test_arrow_view_is_not_billed_to_the_memory_budget(registry, frame):
    """nbytes() must not grow once the Arrow view exists.

    The view shares the frame's buffers, so counting it would bill the same
    bytes twice and evict datasets that fit.
    """
    record = build_record(frame, "arrow-src", registry)
    before = record.nbytes()
    record.arrow()
    assert record.nbytes() == before


def test_results_match_the_pandas_path(registry, frame):
    """The scan source is an implementation detail, not a semantic one."""
    record = build_record(frame, "arrow-src", registry)
    registry.add(record)
    via_arrow = execute_analysis(record.dataset_id, _plan(record.dataset_id), registry)

    # Force the fallback on an otherwise identical record.
    plain = build_record(frame, "pandas-src", registry)
    plain._arrow = False  # sentinel: "tried once, cannot convert"
    registry.add(plain)
    via_pandas = execute_analysis(plain.dataset_id, _plan(plain.dataset_id), registry)

    assert "error" not in via_arrow, via_arrow
    assert "error" not in via_pandas, via_pandas
    assert via_arrow["result_table"] == via_pandas["result_table"]


def test_unconvertible_frame_falls_back_instead_of_failing(registry):
    """A column of genuinely mixed Python types is what messy CSVs produce.

    Arrow refuses it; the query must not.
    """
    mixed = pd.DataFrame(
        {
            "team": ["a", "b", "a"],
            "score": [1.0, 2.0, 3.0],
            # object dtype holding a dict — no Arrow type covers this
            "junk": [{"k": 1}, ["x"], object()],
        }
    )
    record = DatasetRecord(
        dataset_id="ds_mixed",
        source="mixed",
        df=mixed,
        schema={"team": "string", "score": "number", "junk": "string"},
    )
    registry.add(record)

    assert record.arrow() is None  # refused, and remembered
    result = execute_analysis("ds_mixed", _plan("ds_mixed"), registry)
    assert "error" not in result, result
    assert result["row_count"] == 2
