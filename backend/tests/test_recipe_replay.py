"""Reusing a cleaning block on a new file, and not paying for the scan twice.

`preprocessing_version` already made cleaning reproducible — the plan is the
recipe and the source is immutable — but there was no way to point an existing
block at *different rows*, which is the actual recurring task: the same report
arrives monthly and has to be prepared the same way.

The tests that matter most here are the refusals. A recipe that quietly cleans
nothing hands back a dataset that looks prepared and is raw, and an approval
that carried over would authorise a row removal nobody measured.
"""

import pandas as pd
import pytest

from autoviz.services import dataset, execution, quality
from autoviz.services.registry import DatasetRegistry

TRIM_AND_FOLD = [
    {"op": "trim_whitespace", "columns": ["dept"]},
    {"op": "normalize_case", "column": "dept"},
]


def _register(registry, tmp_path, name, rows):
    path = tmp_path / name
    pd.DataFrame(rows).to_csv(path, index=False)
    return dataset.register_dataset(path.as_posix(), registry)["dataset_id"]


@pytest.fixture()
def january(registry, tmp_path):
    return _register(
        registry, tmp_path, "jan.csv",
        [{"dept": "Eng ", "n": 1}, {"dept": "eng", "n": 2}, {"dept": "Sales", "n": 3}],
    )


@pytest.fixture()
def february(registry, tmp_path):
    return _register(
        registry, tmp_path, "feb.csv",
        [{"dept": "Eng", "n": 7}, {"dept": " eng", "n": 8}, {"dept": "Sales", "n": 9}],
    )


@pytest.fixture()
def cleaned_january(registry, january):
    return execution.materialize_cleaned_dataset(january, TRIM_AND_FOLD, registry)


# --- reading a recipe back ---------------------------------------------------------


def test_a_cleaned_dataset_carries_its_recipe(registry, cleaned_january):
    recipe = execution.cleaning_recipe(cleaned_january["dataset_id"], registry)
    assert [o["op"] for o in recipe["preprocessing"]] == ["trim_whitespace", "normalize_case"]
    assert recipe["version_id"] == cleaned_january["version_id"]


def test_an_ordinary_upload_carries_none(registry, january):
    out = execution.cleaning_recipe(january, registry)
    assert "error" in out
    assert "not produced by cleaning" in out["error"]


# --- replay --------------------------------------------------------------------------


def test_a_recipe_cleans_a_second_file_the_same_way(registry, cleaned_january, february):
    out = execution.apply_cleaning_recipe(
        cleaned_january["dataset_id"], february, registry
    )
    assert "error" not in out, out
    assert out["recipe_from"] == cleaned_january["dataset_id"]
    assert out["parent_id"] == february
    # " eng" and "Eng" were separate categories in the source and are now one.
    cleaned = registry.get(out["dataset_id"]).df
    assert sorted(set(cleaned["dept"])) == ["Eng", "Sales"]


def test_the_result_is_an_ordinary_dataset(registry, cleaned_january, february):
    out = execution.apply_cleaning_recipe(
        cleaned_january["dataset_id"], february, registry
    )
    record = registry.get(out["dataset_id"])
    assert record is not None
    assert record.schema == {"dept": "string", "n": "number"}


def test_the_source_files_are_untouched(registry, cleaned_january, february):
    before = list(registry.get(february).df["dept"])
    execution.apply_cleaning_recipe(cleaned_january["dataset_id"], february, registry)
    assert list(registry.get(february).df["dept"]) == before


# --- the refusals ---------------------------------------------------------------------


def test_a_file_missing_a_column_is_refused_by_name(registry, cleaned_january, tmp_path):
    """The important one. Cleaning nothing and returning a dataset that looks
    prepared is far worse than failing, because nothing downstream would ever
    reveal it."""
    renamed = _register(registry, tmp_path, "renamed.csv", [{"team": "Eng", "n": 1}])
    out = execution.apply_cleaning_recipe(
        cleaned_january["dataset_id"], renamed, registry
    )
    assert "error" in out
    assert "dept" in out["error"]


def test_a_non_recipe_source_is_refused(registry, january, february):
    out = execution.apply_cleaning_recipe(january, february, registry)
    assert "error" in out
    assert "no recipe" in out["error"]


def test_an_unknown_target_is_refused(registry, cleaned_january):
    out = execution.apply_cleaning_recipe(
        cleaned_january["dataset_id"], "ds_nope", registry
    )
    assert out["error_code"] == "UNKNOWN_DATASET"


def test_approval_does_not_carry_over_to_the_new_file(registry, tmp_path):
    """A row removal that was harmless on one file can be catastrophic on the
    next. The token is bound to (dataset, ops), so the second run re-gates —
    and this test exists because that safety is inherited rather than written
    here, which is exactly the kind of property that quietly stops holding.
    """
    small = _register(
        registry, tmp_path, "small.csv",
        [{"v": 1}, {"v": 2}, {"v": 3}, {"v": 4}] + [{"v": None}],
    )
    drop = [{"op": "drop_nulls", "columns": ["v"], "how": "any"}]
    # 1 of 5 rows: under the gate, so it materialises with no approval needed.
    recipe = execution.materialize_cleaned_dataset(small, drop, registry)
    assert "error" not in recipe, recipe

    # The same rule against a file that is mostly null removes 80%.
    mostly_null = _register(
        registry, tmp_path, "gappy.csv",
        [{"v": 1}] + [{"v": None} for _ in range(4)],
    )
    out = execution.apply_cleaning_recipe(recipe["dataset_id"], mostly_null, registry)
    assert out["error_code"] == "CONFIRMATION_REQUIRED"
    # And it can be approved on its own terms, with a token for *this* pairing.
    approved = execution.apply_cleaning_recipe(
        recipe["dataset_id"], mostly_null, registry,
        approved_preprocessing_hash=out["confirmation"]["preprocessing_hash"],
    )
    assert "error" not in approved, approved
    assert approved["row_count"] == 1


# --- the scan cache ---------------------------------------------------------------------


def test_a_repeated_scan_is_served_from_the_record(registry, tmp_path):
    """The agent scans once per pass and re-enters the node for every cleaning
    question, so the same work was being repeated several times a turn."""
    ds = _register(
        registry, tmp_path, "cache.csv",
        [{"a": " x ", "b": 1} for _ in range(50)],
    )
    record = registry.get(ds)
    first = quality.scan(record, {"a"})
    assert record.scan_cache  # populated
    assert quality.scan(record, {"a"}) == first


def test_each_column_scope_is_cached_separately(registry, tmp_path):
    ds = _register(registry, tmp_path, "scopes.csv", [{"a": " x ", "b": " y "}] * 5)
    record = registry.get(ds)
    only_a = quality.scan(record, {"a"})
    both = quality.scan(record, {"a", "b"})
    assert len(both) > len(only_a)
    assert len(record.scan_cache) == 2


def test_a_caller_mutating_its_findings_cannot_corrupt_the_cache(registry, tmp_path):
    ds = _register(registry, tmp_path, "mutate.csv", [{"a": " x "}] * 5)
    record = registry.get(ds)
    expected = len(quality.scan(record, {"a"}))
    assert expected  # the fixture is dirty enough for the test to mean something
    quality.scan(record, {"a"}).clear()
    assert len(quality.scan(record, {"a"})) == expected


def test_a_reloaded_record_re_derives_rather_than_trusting_a_stale_cache(tmp_path):
    """The cache lives on the record, so eviction discards it. That is the
    correct lifetime: a frame restored from storage is re-derived, never handed
    an answer computed against something else."""
    registry = DatasetRegistry()
    path = tmp_path / "evict.csv"
    pd.DataFrame([{"a": " x "}] * 5).to_csv(path, index=False)
    ds = dataset.register_dataset(path.as_posix(), registry)["dataset_id"]
    quality.scan(registry.get(ds), {"a"})
    assert registry.get(ds).scan_cache

    registry.remove(ds)
    reloaded = dataset.register_dataset(path.as_posix(), registry)["dataset_id"]
    assert registry.get(reloaded).scan_cache == {}
