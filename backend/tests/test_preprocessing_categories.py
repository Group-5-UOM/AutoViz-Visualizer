"""Category cleaning: explicit relabelling and long-tail bucketing.

Both merge values that were distinct, so both are VALUE_CHANGING. The tests lean
on the cases where "obviously right" and "actually safe" come apart — an inferred
mapping, a bucketed null, a tie broken by scan order.
"""

from autoviz.schema.allowlists import Risk
from autoviz.schema.analysis_plan import AnalysisPlan
from autoviz.services import dataset, quality
from autoviz.services.execution import execute_analysis
from autoviz.services.validation import validate_analysis_plan


def _plan(ds, **extra):
    base = {"dataset_id": ds, "intent": "comparison"}
    base.update(extra)
    return base


def _register(registry, tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return dataset.register_dataset(p.as_posix(), registry)["dataset_id"]


def _counts(out, key="country"):
    return {r[key]: r["n"] for r in out["result_table"]}


def _count_plan(ds, column, preprocessing):
    return _plan(
        ds,
        preprocessing=preprocessing,
        group_by=[column],
        aggregations=[{"column": column, "fn": "count", "as": "n"}],
    )


# --- tier ---------------------------------------------------------------------


def test_category_ops_are_value_changing_not_safe():
    """Merging categories can put two rows that meant different things in one bar.
    Usually right is not the same as semantics-preserving."""
    plan = AnalysisPlan.model_validate(
        {
            "dataset_id": "ds_x",
            "intent": "comparison",
            "preprocessing": [
                {"op": "clean_categories", "column": "c", "mapping": {"a": "b"}},
                {"op": "group_rare_categories", "column": "c", "top_n": 3},
            ],
        }
    )
    assert all(op.risk is Risk.VALUE_CHANGING for op in plan.preprocessing)
    assert not plan.has_row_dropping_preprocessing()  # relabels, never drops


# --- clean_categories ----------------------------------------------------------


def test_explicit_mapping_merges_only_what_it_names(registry, tmp_path):
    ds = _register(
        registry, tmp_path, "countries.csv",
        "country\nUK\nU.K.\nUnited Kingdom\nFrance\nSpain\n",
    )
    out = execute_analysis(
        ds,
        _count_plan(
            ds, "country",
            [{
                "op": "clean_categories", "column": "country",
                "mapping": {"U.K.": "UK", "United Kingdom": "UK"},
            }],
        ),
        registry,
    )
    assert "error" not in out, out
    # France and Spain were not named, so they are untouched.
    assert _counts(out) == {"UK": 3, "France": 1, "Spain": 1}
    step = out["preprocessing"][0]
    assert step["operation"] == "clean_categories" and step["rows_affected"] == 2


def test_mapping_values_are_bound_not_interpolated(registry, tmp_path):
    """Category labels are data. A quote or a SQL keyword in one is a value, not
    syntax — the CASE arms bind every literal."""
    ds = _register(registry, tmp_path, "quotes.csv", "country\nA\nB\n")
    out = execute_analysis(
        ds,
        _count_plan(
            ds, "country",
            [{
                "op": "clean_categories", "column": "country",
                "mapping": {"A": "O'Brien; DROP TABLE t--", "B": 'say "hi"'},
            }],
        ),
        registry,
    )
    assert "error" not in out, out
    assert _counts(out) == {"O'Brien; DROP TABLE t--": 1, 'say "hi"': 1}


def test_mapping_is_rejected_on_a_numeric_column(registry, nulls_id):
    v = validate_analysis_plan(
        nulls_id,
        _plan(
            nulls_id,
            preprocessing=[
                {"op": "clean_categories", "column": "fare", "mapping": {"1": "2"}}
            ],
        ),
        registry,
    )
    assert not v["valid"]
    assert any("requires a categorical" in e for e in v["errors"])


def test_nothing_ever_infers_a_mapping(registry, tmp_path):
    """The recommender must not guess that "U.K." means "UK". Exact whitespace and
    case equivalence is handled by the SAFE ops; anything beyond that is a guess,
    and a wrong guess silently merges two real categories."""
    ds = _register(
        registry, tmp_path, "similar.csv", "country\nUK\nU.K.\nUnited Kingdom\n"
    )
    record = registry.get(ds)
    auto, proposals = quality.recommend(quality.scan(record), len(record.df))
    assert all(op["op"] != "clean_categories" for op in auto)
    assert all(
        o.op is None or o.op["op"] != "clean_categories"
        for p in proposals
        for o in p.options
    )


# --- group_rare_categories -----------------------------------------------------


def test_top_n_keeps_the_commonest_and_buckets_the_rest(registry, tmp_path):
    rows = ["a"] * 5 + ["b"] * 4 + ["c"] * 3 + ["d"] * 2 + ["e"]
    ds = _register(registry, tmp_path, "tail.csv", "country\n" + "\n".join(rows) + "\n")
    out = execute_analysis(
        ds,
        _count_plan(
            ds, "country",
            [{"op": "group_rare_categories", "column": "country", "top_n": 2}],
        ),
        registry,
    )
    assert "error" not in out, out
    assert _counts(out) == {"a": 5, "b": 4, "Other": 6}
    assert out["preprocessing"][0]["rows_affected"] == 6


def test_min_frequency_keeps_anything_common_enough(registry, tmp_path):
    rows = ["a"] * 5 + ["b"] * 4 + ["c"] * 3 + ["d"] * 2 + ["e"]
    ds = _register(registry, tmp_path, "freq.csv", "country\n" + "\n".join(rows) + "\n")
    out = execute_analysis(
        ds,
        _count_plan(
            ds, "country",
            [{"op": "group_rare_categories", "column": "country", "min_frequency": 3}],
        ),
        registry,
    )
    assert "error" not in out, out
    assert _counts(out) == {"a": 5, "b": 4, "c": 3, "Other": 3}


def test_nulls_are_never_bucketed(registry, tmp_path):
    """Missing is not the same as rare — folding nulls into "Other" would turn an
    absence into a category, and hide it from the null accounting."""
    ds = _register(registry, tmp_path, "nulls.csv", "country,v\na,1\na,2\nb,3\n,4\n,5\n")
    out = execute_analysis(
        ds,
        _count_plan(
            ds, "country",
            [{"op": "group_rare_categories", "column": "country", "top_n": 1}],
        ),
        registry,
    )
    assert "error" not in out, out
    counts = _counts(out)
    # "a" (2) is kept, "b" (1) is bucketed, and the two null rows stay their own
    # group rather than joining "Other".
    assert set(counts) == {"a", "Other", None}
    assert counts["a"] == 2 and counts["Other"] == 1
    assert counts[None] == 0  # count() skips nulls; the group itself remains


def test_tie_break_is_deterministic(registry, tmp_path):
    """Equal frequencies must not resolve by scan order, or the same request could
    bucket a different category on a re-run."""
    ds = _register(registry, tmp_path, "tie.csv", "country\nb\nb\na\na\nc\n")
    plan = _count_plan(
        ds, "country", [{"op": "group_rare_categories", "column": "country", "top_n": 1}]
    )
    first = _counts(execute_analysis(ds, plan, registry))
    second = _counts(execute_analysis(ds, plan, registry))
    assert first == second
    assert "a" in first  # frequency desc, then value asc — "a" wins the tie with "b"


def test_custom_other_label(registry, tmp_path):
    ds = _register(registry, tmp_path, "label.csv", "country\na\na\nb\n")
    out = execute_analysis(
        ds,
        _count_plan(
            ds, "country",
            [{
                "op": "group_rare_categories", "column": "country",
                "top_n": 1, "other_label": "Everything else",
            }],
        ),
        registry,
    )
    assert "Everything else" in _counts(out)


def test_exactly_one_of_top_n_or_min_frequency(registry, tmp_path):
    ds = _register(registry, tmp_path, "both.csv", "country\na\nb\n")
    for preprocessing in (
        [{"op": "group_rare_categories", "column": "country", "top_n": 2, "min_frequency": 3}],
        [{"op": "group_rare_categories", "column": "country"}],
    ):
        v = validate_analysis_plan(ds, _plan(ds, preprocessing=preprocessing), registry)
        assert not v["valid"]
        assert any("exactly one of top_n or min_frequency" in e for e in v["errors"])


# --- composition with the rest of the chain ------------------------------------


def test_bucketing_runs_after_the_safe_repairs(registry, tmp_path):
    """Order matters: folding case variants first means " A " and "a" are one
    category *before* frequencies are counted, so the tail is measured correctly."""
    ds = _register(
        registry, tmp_path, "combo.csv",
        "country\n A \na\nA\nb\nc\n",
    )
    out = execute_analysis(
        ds,
        _count_plan(
            ds, "country",
            [
                {"op": "trim_whitespace", "columns": ["country"]},
                {"op": "normalize_case", "column": "country"},
                {"op": "group_rare_categories", "column": "country", "top_n": 1},
            ],
        ),
        registry,
    )
    assert "error" not in out, out
    # Three spellings of "a" counted as one, so it is the clear top category.
    # The label is the spelling the column used, which normalize_case preserves.
    assert _counts(out) == {"A": 3, "Other": 2}
