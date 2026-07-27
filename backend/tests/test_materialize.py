"""Promoting a cleaned working view into a dataset of its own.

Materialising is the one place cleaning *writes* something, so the tests are
mostly about what that does and does not entitle it to: the parent stays
untouched, the gate still applies, and the result is an ordinary dataset that
happens to know where it came from.
"""

from autoviz.errors import CONFIRMATION_REQUIRED, INVALID_PLAN
from autoviz.schema.analysis_plan import AnalysisPlan
from autoviz.services import dataset
from autoviz.services.execution import execute_analysis, materialize_cleaned_dataset


def _register(registry, tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return dataset.register_dataset(p.as_posix(), registry)["dataset_id"]


MESSY = "dept,salary\n Eng ,100\neng,200\nENG,300\nSales,400\n sales,500\n"

SAFE_BLOCK = [
    {"op": "trim_whitespace", "columns": ["dept"]},
    {"op": "normalize_case", "column": "dept"},
]


def _token(ds, preprocessing):
    return AnalysisPlan.model_validate(
        {"dataset_id": ds, "intent": "comparison", "preprocessing": preprocessing}
    ).preprocessing_version(ds)


# --- what it produces ----------------------------------------------------------


def test_cleaned_dataset_is_an_ordinary_dataset(registry, tmp_path):
    ds = _register(registry, tmp_path, "messy.csv", MESSY)
    out = materialize_cleaned_dataset(ds, SAFE_BLOCK, registry)

    assert "error" not in out, out
    assert out["parent_id"] == ds
    assert out["version_id"].startswith("pp_")
    assert out["row_count"] == 5 and out["column_count"] == 2

    # It behaves like any other dataset from here on — schema, profile, queries.
    new = registry.get(out["dataset_id"])
    assert new is not None
    assert new.schema == {"dept": "string", "salary": "number"}
    assert set(new.df["dept"]) == {"eng", "sales"}  # the cleaning is baked in


def test_the_parent_is_untouched(registry, tmp_path):
    ds = _register(registry, tmp_path, "parent.csv", MESSY)
    before = registry.get(ds).df.copy(deep=True)
    materialize_cleaned_dataset(ds, SAFE_BLOCK, registry)
    assert registry.get(ds).df.equals(before)


def test_lineage_is_recorded_on_the_new_dataset(registry, tmp_path):
    ds = _register(registry, tmp_path, "lineage.csv", MESSY)
    out = materialize_cleaned_dataset(ds, SAFE_BLOCK, registry)

    lineage = registry.get(out["dataset_id"]).profile["lineage"]
    assert lineage["parent_id"] == ds
    assert lineage["version_id"] == out["version_id"]
    assert [op["op"] for op in lineage["preprocessing"]] == [
        "trim_whitespace",
        "normalize_case",
    ]
    assert lineage["input_rows"] == 5 and lineage["output_rows"] == 5
    assert lineage["confirmed_by_user"] is False  # nothing needed approving


def test_the_cleaned_copy_is_profiled_like_a_fresh_upload(registry, tmp_path):
    """Same profiling code as register_dataset — a cleaned copy that reported its
    nulls differently from a fresh upload of the same rows would be worse than
    useless for deciding what to clean next."""
    ds = _register(registry, tmp_path, "profiled.csv", "dept,salary\n a ,1\nb,\n")
    out = materialize_cleaned_dataset(
        ds, [{"op": "trim_whitespace", "columns": ["dept"]}], registry
    )
    profile = registry.get(out["dataset_id"]).profile
    assert profile["null_counts"]["salary"] == 1
    assert profile["cardinality"]["dept"] == 2
    assert "summary_stats" in profile and "sample_values" in profile


def test_analyses_run_against_the_cleaned_dataset(registry, tmp_path):
    ds = _register(registry, tmp_path, "chainable.csv", MESSY)
    made = materialize_cleaned_dataset(ds, SAFE_BLOCK, registry)
    cleaned, cleaned_version = made["dataset_id"], made["version_id"]

    out = execute_analysis(
        cleaned,
        {
            "dataset_id": cleaned,
            "intent": "comparison",
            "group_by": ["dept"],
            "aggregations": [{"column": "salary", "fn": "sum", "as": "total"}],
        },
        registry,
    )
    assert "error" not in out, out
    # No preprocessing needed in the plan — it is already applied.
    assert {r["dept"]: r["total"] for r in out["result_table"]} == {"eng": 600, "sales": 900}

    # Both halves of the lineage: which dataset these rows came from, and which
    # cleaning produced them. Either alone stops the trail one link short.
    provenance = out["provenance"]["cleaning"]
    assert provenance["parent"] == ds
    assert provenance["source_version_id"] == cleaned_version
    assert provenance["steps"] == []  # this plan itself cleans nothing


# --- it is a write, so the same rules apply ------------------------------------


def test_a_large_removal_still_needs_approval(registry, tmp_path):
    """Materialising a 60% row removal is no less consequential for being
    deliberate — the gate is the same one execution uses."""
    ds = _register(registry, tmp_path, "gated.csv", "dept,salary\na,1\n,2\n,3\n,4\n,5\n")
    block = [{"op": "drop_nulls", "columns": ["dept"], "how": "any"}]

    refused = materialize_cleaned_dataset(ds, block, registry)
    assert refused["error_code"] == CONFIRMATION_REQUIRED
    assert refused["confirmation"]["impact"]["dropped"] == 4

    allowed = materialize_cleaned_dataset(
        ds, block, registry, approved_preprocessing_hash=_token(ds, block)
    )
    assert "error" not in allowed, allowed
    assert allowed["row_count"] == 1
    assert registry.get(allowed["dataset_id"]).profile["lineage"]["confirmed_by_user"] is True


def test_the_block_is_validated_like_any_other(registry, tmp_path):
    ds = _register(registry, tmp_path, "invalid.csv", "dept,salary\na,1\n")
    out = materialize_cleaned_dataset(
        ds, [{"op": "trim_whitespace", "columns": ["ghost"]}], registry
    )
    assert out["error_code"] == INVALID_PLAN
    assert any("does not exist" in e for e in out["validation_errors"])


def test_an_empty_block_is_refused(registry, tmp_path):
    """Materialising nothing would just be an expensive copy of the parent."""
    ds = _register(registry, tmp_path, "empty.csv", "dept,salary\na,1\n")
    out = materialize_cleaned_dataset(ds, [], registry)
    assert out["error_code"] == INVALID_PLAN
    assert "at least one cleaning step" in out["error"]


def test_unknown_dataset_is_refused(registry):
    out = materialize_cleaned_dataset("ds_nope", SAFE_BLOCK, registry)
    assert out["error_code"] == "UNKNOWN_DATASET"


def test_version_id_is_stable_and_dataset_bound(registry, tmp_path):
    a = _register(registry, tmp_path, "a.csv", MESSY)
    b = _register(registry, tmp_path, "b.csv", MESSY)
    first = materialize_cleaned_dataset(a, SAFE_BLOCK, registry)["version_id"]
    again = materialize_cleaned_dataset(a, SAFE_BLOCK, registry)["version_id"]
    other = materialize_cleaned_dataset(b, SAFE_BLOCK, registry)["version_id"]

    assert first == again  # same block, same data -> same logical version
    assert first != other  # identical rows, different dataset -> different version
