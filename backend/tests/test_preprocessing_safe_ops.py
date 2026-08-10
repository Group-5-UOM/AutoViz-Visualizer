"""The SAFE tier: repairs that change how a value is written, not what it means.

These are the ops the system is allowed to apply without asking, so the tests
that matter most are the ones pinning the *boundary* — what makes an op safe, and
what disqualifies it.
"""

from autoviz.schema.allowlists import Risk
from autoviz.schema.analysis_plan import AnalysisPlan
from autoviz.services import dataset
from autoviz.services.execution import execute_analysis
from autoviz.services.orchestrator import run_pipeline
from autoviz.services.validation import validate_analysis_plan


def _plan(ds, **extra):
    base = {"dataset_id": ds, "intent": "comparison"}
    base.update(extra)
    return base


def _register(registry, tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return dataset.register_dataset(p.as_posix(), registry)["dataset_id"]


# --- tier declarations --------------------------------------------------------


def test_safe_ops_declare_the_safe_tier():
    plan = AnalysisPlan.model_validate(
        {
            "dataset_id": "ds_x",
            "intent": "comparison",
            "preprocessing": [
                {"op": "trim_whitespace", "columns": ["a"]},
                {"op": "empty_string_to_null", "columns": ["a"]},
                {"op": "normalize_case", "column": "a"},
                {"op": "drop_empty_rows"},
                {"op": "cast_column", "column": "a", "to": "number"},
            ],
        }
    )
    assert all(op.risk is Risk.SAFE for op in plan.preprocessing)


def test_drop_empty_rows_is_safe_but_still_removes_rows():
    """The two flags are independent — being safe does not exempt an op from the
    row-removal backstop."""
    plan = AnalysisPlan.model_validate(
        {"dataset_id": "ds_x", "intent": "comparison", "preprocessing": [{"op": "drop_empty_rows"}]}
    )
    op = plan.preprocessing[0]
    assert op.risk is Risk.SAFE and op.removes_rows is True
    assert plan.has_row_dropping_preprocessing() is True


# --- trim / empty-string / case ------------------------------------------------


def test_trim_whitespace_merges_padded_categories(registry, tmp_path):
    ds = _register(registry, tmp_path, "padded.csv", "cls,v\n a,1\na ,2\na,3\nb,4\n")
    out = execute_analysis(
        ds,
        _plan(
            ds,
            preprocessing=[{"op": "trim_whitespace", "columns": ["cls"]}],
            group_by=["cls"],
            aggregations=[{"column": "v", "fn": "sum", "as": "total"}],
        ),
        registry,
    )
    assert "error" not in out, out
    by_cls = {r["cls"]: r["total"] for r in out["result_table"]}
    assert by_cls == {"a": 6, "b": 4}  # three spellings of "a" became one group
    assert out["preprocessing"][0]["rows_affected"] == 2  # " a" and "a "


def test_empty_string_becomes_null_and_is_then_skipped(registry, tmp_path):
    """Blank text is an absent value; making it null lets the rest of the system
    treat it as one."""
    ds = _register(registry, tmp_path, "blanks.csv", "cls,note\na,x\nb,\nc,   \n")
    plan = _plan(
        ds,
        preprocessing=[{"op": "empty_string_to_null", "columns": ["note"]}],
        group_by=["cls"],
        aggregations=[{"column": "note", "fn": "count", "as": "n"}],
    )
    out = execute_analysis(ds, plan, registry)
    assert "error" not in out, out
    assert {r["cls"]: r["n"] for r in out["result_table"]} == {"a": 1, "b": 0, "c": 0}


def test_normalize_case_folds_variants(registry, tmp_path):
    ds = _register(registry, tmp_path, "case.csv", "sex,v\nMale,1\nmale,2\nMALE,3\nFemale,4\n")
    out = execute_analysis(
        ds,
        _plan(
            ds,
            preprocessing=[{"op": "normalize_case", "column": "sex"}],
            group_by=["sex"],
            aggregations=[{"column": "v", "fn": "sum", "as": "total"}],
        ),
        registry,
    )
    assert "error" not in out, out
    # The three spellings merge, and the surviving label is a spelling the column
    # actually used — not lower(). All three appear once, so the tie breaks toward
    # the one that reads as a label rather than the one that sorts first ("MALE").
    assert {r["sex"]: r["total"] for r in out["result_table"]} == {"Male": 6, "Female": 4}


def test_normalize_case_keeps_the_commonest_spelling(registry, tmp_path):
    """Frequency decides, before the tie-break ever applies: a column that says
    "USA" four times and "usa" once should still read "USA" on the axis."""
    ds = _register(
        registry, tmp_path, "usa.csv",
        "country,v\nUSA,1\nUSA,1\nUSA,1\nUSA,1\nusa,1\nCanada,1\n",
    )
    out = execute_analysis(
        ds,
        _plan(
            ds,
            preprocessing=[{"op": "normalize_case", "column": "country"}],
            group_by=["country"],
            aggregations=[{"column": "v", "fn": "sum", "as": "total"}],
        ),
        registry,
    )
    assert "error" not in out, out
    assert {r["country"]: r["total"] for r in out["result_table"]} == {"USA": 5, "Canada": 1}


def test_normalize_case_leaves_a_column_with_nothing_to_merge_alone(registry, tmp_path):
    ds = _register(registry, tmp_path, "nofold.csv", "k,v\nAlpha,1\nBeta,2\n")
    out = execute_analysis(
        ds,
        _plan(ds, preprocessing=[{"op": "normalize_case", "column": "k"}], select=["k"]),
        registry,
    )
    assert "error" not in out, out
    assert {r["k"] for r in out["result_table"]} == {"Alpha", "Beta"}
    step = next(s for s in out["preprocessing"] if s["operation"] == "normalize_case")
    assert step["rows_affected"] == 0


def test_text_repairs_are_rejected_on_non_text_columns(registry, nulls_id):
    v = validate_analysis_plan(
        nulls_id, _plan(nulls_id, preprocessing=[{"op": "trim_whitespace", "columns": ["fare"]}]), registry
    )
    assert not v["valid"]
    assert any("requires a string column" in e for e in v["errors"])


# --- drop_empty_rows -----------------------------------------------------------


def test_drop_empty_rows_removes_only_all_null_rows(registry, tmp_path):
    ds = _register(registry, tmp_path, "empties.csv", "a,b\n1,x\n,\n2,\n,y\n")
    plan = _plan(ds, preprocessing=[{"op": "drop_empty_rows"}], select=["a", "b"])
    out = execute_analysis(ds, plan, registry)
    assert "error" not in out, out
    assert out["input_rows"] == 4 and out["output_rows"] == 3  # only the blank row
    assert out["preprocessing"][0]["rows_affected"] == 1


def test_a_mostly_blank_file_still_hits_the_backstop(registry, tmp_path):
    """Safe does not mean unlimited: removing most of the file needs consent."""
    ds = _register(registry, tmp_path, "mostly_blank.csv", "a,b\n1,x\n,\n,\n,\n")
    out = run_pipeline(ds, _plan(ds, preprocessing=[{"op": "drop_empty_rows"}], select=["a", "b"]), registry)
    assert out["status"] == "confirmation_required"
    assert out["confirmation"]["impact"]["dropped"] == 3


# --- cast_column ---------------------------------------------------------------


def test_cast_column_rejects_a_lossy_conversion(registry, tmp_path):
    """A column that is *mostly* numeric is a refusal naming the cost, not a
    partial success that quietly nulls the rest."""
    # "unknown" rather than "n/a": pandas treats the latter as a NA sentinel and
    # would parse the column as numeric before we ever get to cast it.
    ds = _register(registry, tmp_path, "lossy.csv", "cls,amount\na,10\nb,20\nc,unknown\n")
    assert registry.get(ds).schema["amount"] == "string"
    plan = _plan(
        ds,
        preprocessing=[{"op": "cast_column", "column": "amount", "to": "number"}],
        select=["amount"],
    )
    out = execute_analysis(ds, plan, registry)
    assert out["error_code"] == "INVALID_PLAN", out
    assert "1 of 3 value(s) would not convert" in out["error"]


def test_cast_column_after_nulling_blanks_then_aggregates(registry, tmp_path):
    """End to end: text column with blank cells -> nulled -> cast -> summed.

    This is the capability that did not exist before: a text-typed numeric column
    could not be aggregated at all, because sum/mean require a numeric column.
    """
    ds = _register(registry, tmp_path, "blanknum.csv", "cls,amount\na,10\na,   \nb,30\nb,x\n")
    assert registry.get(ds).schema["amount"] == "string"

    # With "x" still present the cast is refused...
    lossy = _plan(
        ds,
        preprocessing=[
            {"op": "empty_string_to_null", "columns": ["amount"]},
            {"op": "cast_column", "column": "amount", "to": "number"},
        ],
        select=["amount"],
    )
    assert execute_analysis(ds, lossy, registry)["error_code"] == "INVALID_PLAN"

    # ...and once the offending row is filtered out, it converts and aggregates.
    ds2 = _register(registry, tmp_path, "blanknum2.csv", "cls,amount\na,10\na,   \nb,30\n")
    plan = _plan(
        ds2,
        preprocessing=[
            {"op": "empty_string_to_null", "columns": ["amount"]},
            {"op": "cast_column", "column": "amount", "to": "number"},
        ],
        group_by=["cls"],
        aggregations=[{"column": "amount", "fn": "sum", "as": "total"}],
    )
    v = validate_analysis_plan(ds2, plan, registry)
    assert v["valid"], v  # sum() on a cast column validates against the new type
    out = execute_analysis(ds2, plan, registry)
    assert "error" not in out, out
    assert {r["cls"]: r["total"] for r in out["result_table"]} == {"a": 10.0, "b": 30.0}


def test_cast_column_refuses_an_already_typed_column(registry, nulls_id):
    v = validate_analysis_plan(
        nulls_id,
        _plan(nulls_id, preprocessing=[{"op": "cast_column", "column": "fare", "to": "number"}]),
        registry,
    )
    assert not v["valid"]
    assert any("already typed" in e for e in v["errors"])


# --- parse_number ---------------------------------------------------------------
# The op exists because cast_column cannot: TRY_CAST('$1,234.50' AS DOUBLE) is
# null, so a money column stayed text that no aggregation would accept. What keeps
# it SAFE is not that it strips less, but that it strips a *closed set* and then
# demands the remainder convert in full.


def test_parse_number_declares_the_safe_tier():
    plan = AnalysisPlan.model_validate(
        {
            "dataset_id": "ds_x",
            "intent": "comparison",
            "preprocessing": [{"op": "parse_number", "columns": ["a"]}],
        }
    )
    op = plan.preprocessing[0]
    assert op.risk is Risk.SAFE and op.removes_rows is False


def _sum_amount(registry, tmp_path, name, body, **op_fields):
    ds = _register(registry, tmp_path, name, body)
    plan = _plan(
        ds,
        preprocessing=[{"op": "parse_number", "columns": ["amount"], **op_fields}],
        aggregations=[{"column": "amount", "fn": "sum", "as": "total"}],
    )
    return ds, plan, execute_analysis(ds, plan, registry)


def test_parse_number_reads_us_currency(registry, tmp_path):
    _ds, _plan_, out = _sum_amount(
        registry, tmp_path, "usd.csv",
        'amount\n"$1,234.50"\n"$2,000.00"\n', thousands=",",
    )
    assert out["result_table"][0]["total"] == 3234.50


def test_parse_number_reads_european_notation(registry, tmp_path):
    """Quoted, because unquoted European decimals in a comma-delimited file are
    genuinely ambiguous — 1.234,50 is two fields by every rule the reader has, and
    services/ingest.py only treats a comma as a decimal point behind a semicolon
    delimiter. Quoting is what real exports do, and it is what leaves the value
    intact for this op to parse."""
    _ds, _plan_, out = _sum_amount(
        registry, tmp_path, "eur.csv",
        'amount\n"1.234,50"\n"2.000,00"\n', decimal=",", thousands=".",
    )
    assert out["result_table"][0]["total"] == 3234.50


def test_parse_number_makes_the_column_numeric_for_validation(registry, tmp_path):
    """sum() on a string column is a type error; the override is what admits it."""
    ds, plan, _out = _sum_amount(
        registry, tmp_path, "typed.csv", 'amount\n"$10.00"\n"$20.00"\n', thousands=","
    )
    assert validate_analysis_plan(ds, plan, registry)["valid"] is True


def test_parse_number_refuses_text_that_merely_starts_with_digits(registry, tmp_path):
    """The failure a permissive strip would produce: '12 apples' -> 12, reported as
    a successful repair. Stripping only known decoration leaves '12apples', which
    cannot convert, so the op refuses instead."""
    _ds, _plan_, out = _sum_amount(
        registry, tmp_path, "apples.csv", "amount\n12 apples\n5\n", thousands=","
    )
    assert out["error_code"] == "INVALID_PLAN"
    assert "would not convert" in out["error"]


def test_parse_number_refuses_percentages(registry, tmp_path):
    """45% is either 45 or 0.45 and the column does not say which."""
    _ds, _plan_, out = _sum_amount(registry, tmp_path, "pct.csv", "amount\n45%\n55%\n")
    assert out["error_code"] == "INVALID_PLAN"


def test_parse_number_refuses_an_already_numeric_column(registry, nulls_id):
    v = validate_analysis_plan(
        nulls_id,
        _plan(nulls_id, preprocessing=[{"op": "parse_number", "columns": ["fare"]}]),
        registry,
    )
    assert not v["valid"]
    assert any("already typed" in e for e in v["errors"])


def test_parse_number_rejects_identical_separators(registry, nulls_id):
    v = validate_analysis_plan(
        nulls_id,
        _plan(
            nulls_id,
            preprocessing=[
                {"op": "parse_number", "columns": ["cls"], "decimal": ",", "thousands": ","}
            ],
        ),
        registry,
    )
    assert not v["valid"]
    assert any("cannot both be" in e for e in v["errors"])


def test_parse_number_discloses_what_it_did(registry, tmp_path):
    _ds, _plan_, out = _sum_amount(
        registry, tmp_path, "disclosed.csv", 'amount\n"$10.00"\n"$20.00"\n', thousands=","
    )
    notes = [n for n in out["provenance"]["notices"] if n["kind"] == "parse_number"]
    assert len(notes) == 1
    assert notes[0]["severity"] == "applied"  # SAFE: told, not asked
    assert "amount" in notes[0]["note"]
