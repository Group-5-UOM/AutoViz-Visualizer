"""Findings that need to know what a value *means*, not just how it is written.

Three things the scanner could not previously see: a number standing in for
"not recorded", a word doing the same, and a column that is almost but not
quite a set of email addresses. Plus the imputation that respects group
structure instead of flattening it.

The recurring risk in all of this is false positives. A placeholder detector
that fires on real data trains the user to dismiss the question, which costs
more than never asking — so most of these tests are about what must *not* be
flagged.
"""

import pandas as pd
import pytest

from autoviz.schema.allowlists import Risk
from autoviz.schema.analysis_plan import AnalysisPlan
from autoviz.services import dataset, notices, quality
from autoviz.services.execution import execute_analysis
from autoviz.services.validation import validate_analysis_plan


def _record(registry, tmp_path, name, rows):
    path = tmp_path / name
    pd.DataFrame(rows).to_csv(path, index=False)
    ds = dataset.register_dataset(path.as_posix(), registry)["dataset_id"]
    return ds, registry.get(ds)


def _kinds(issues):
    return {i.kind for i in issues}


def _ages(extra):
    """A realistic age column (18-71) plus whatever is being tested."""
    return [{"age": 18 + (i % 54)} for i in range(40)] + [{"age": v} for v in extra]


# --- numeric sentinels ------------------------------------------------------------


def test_a_code_far_outside_the_distribution_is_flagged(registry, tmp_path):
    _ds, rec = _record(registry, tmp_path, "sentinel.csv", _ages([999, 999, 999]))
    issue = next(i for i in quality.scan(rec, {"age"}) if i.kind == "suspect_values")
    assert issue.detail["values"] == [999]
    assert issue.affected == 3


def test_the_same_code_inside_the_distribution_is_not_flagged(registry, tmp_path):
    """999 is a placeholder among ages and an ordinary reading among prices.

    The number alone cannot tell you which, which is why the check needs the
    distribution as well as the code list — and why this test matters more than
    the one above it.
    """
    rows = [{"price": 100 * (i + 1)} for i in range(40)] + [{"price": 999}] * 3
    _ds, rec = _record(registry, tmp_path, "prices.csv", rows)
    assert "suspect_values" not in _kinds(quality.scan(rec, {"price"}))


def test_a_single_stray_code_is_not_worth_a_question(registry, tmp_path):
    """One -1 is likelier a typo than a convention, and a question about a single
    row costs more attention than it saves."""
    _ds, rec = _record(registry, tmp_path, "one.csv", _ages([-999]))
    assert "suspect_values" not in _kinds(quality.scan(rec, {"age"}))


def test_a_constant_column_is_not_all_outliers(registry, tmp_path):
    """With no spread there is no "far outside", and a naive fence would flag
    every value that is not the repeated one."""
    rows = [{"v": 5} for _ in range(20)] + [{"v": 999}, {"v": 999}]
    _ds, rec = _record(registry, tmp_path, "flat.csv", rows)
    assert "suspect_values" not in _kinds(quality.scan(rec, {"v"}))


def test_an_ordinary_extreme_value_is_not_flagged(registry, tmp_path):
    """Being an outlier is not enough either — it has to be a known code.
    Genuine extremes are handled at the axis (Docs/14), not by nulling them."""
    _ds, rec = _record(registry, tmp_path, "whale.csv", _ages([840, 840]))
    assert "suspect_values" not in _kinds(quality.scan(rec, {"age"}))


# --- text placeholders -------------------------------------------------------------


@pytest.mark.parametrize("token", ["unknown", "UNKNOWN", " Unknown ", "n/a.", "-", "?", "TBD"])
def test_placeholder_words_are_flagged_however_they_are_written(registry, tmp_path, token):
    rows = [{"status": "active"} for _ in range(10)] + [{"status": token}] * 2
    _ds, rec = _record(registry, tmp_path, f"t{abs(hash(token))}.csv", rows)
    issues = [i for i in quality.scan(rec, {"status"}) if i.kind == "suspect_values"]
    if token == "n/a.":  # not in the token set; the plain "n/a" is nulled at read time
        assert issues == []
        return
    assert issues and issues[0].affected == 2


def test_a_real_word_is_not_a_placeholder(registry, tmp_path):
    rows = [{"status": "active"} for _ in range(10)] + [{"status": "pending"}] * 2
    _ds, rec = _record(registry, tmp_path, "real.csv", rows)
    assert "suspect_values" not in _kinds(quality.scan(rec, {"status"}))


# --- the proposal and the op --------------------------------------------------------


def test_the_proposal_recommends_treating_a_code_as_missing(registry, tmp_path):
    """Recommended, unusually for a value-changing op. The asymmetry is
    deliberate: counting a code as a measurement corrupts every average over the
    column, while treating a genuine 999 as missing costs a few rows from an
    aggregate that already discloses its exclusions."""
    _ds, rec = _record(registry, tmp_path, "prop.csv", _ages([999, 999, 999]))
    _auto, proposals = quality.recommend(quality.scan(rec, {"age"}), len(rec.df))
    proposal = next(p for p in proposals if p.slot == "suspect:age")
    recommended = next(o for o in proposal.options if o.recommended)
    assert recommended.op == {"op": "nullify_values", "column": "age", "values": [999]}


def test_nullify_values_is_value_changing_and_keeps_every_row():
    plan = AnalysisPlan.model_validate({
        "dataset_id": "d", "intent": "comparison",
        "preprocessing": [{"op": "nullify_values", "column": "a", "values": [999]}],
    })
    op = plan.preprocessing[0]
    assert op.risk is Risk.VALUE_CHANGING and op.removes_rows is False


def test_nullifying_a_code_changes_the_average(registry, tmp_path):
    """The whole point, in one number: 999s dragged the mean far above every
    real age, and nothing in the output would have said so."""
    ds, _rec = _record(registry, tmp_path, "avg.csv", _ages([999, 999, 999]))
    plan = {
        "dataset_id": ds, "intent": "comparison",
        "aggregations": [{"column": "age", "fn": "mean", "as": "avg"}],
    }
    before = execute_analysis(ds, plan, registry)["result_table"][0]["avg"]
    after = execute_analysis(
        ds,
        {**plan, "preprocessing": [
            {"op": "nullify_values", "column": "age", "values": [999]}
        ]},
        registry,
    )["result_table"][0]["avg"]
    assert before > 100 and after < 75


def test_nullify_discloses_itself(registry, tmp_path):
    ds, _rec = _record(registry, tmp_path, "disc.csv", _ages([999, 999, 999]))
    out = execute_analysis(
        ds,
        {"dataset_id": ds, "intent": "comparison",
         "preprocessing": [{"op": "nullify_values", "column": "age", "values": [999]}],
         "aggregations": [{"column": "age", "fn": "mean", "as": "avg"}]},
        registry,
    )
    note = next(n for n in out["provenance"]["notices"] if n["kind"] == "nullify_values")
    assert "999" in note["note"] and "missing" in note["note"]


def test_nullifying_a_value_the_column_cannot_hold_is_rejected(registry, tmp_path):
    """A silent no-op is the failure here: the op runs, matches nothing, and the
    user believes the sentinel was dealt with."""
    ds, _rec = _record(registry, tmp_path, "type.csv", _ages([999]))
    verdict = validate_analysis_plan(
        ds,
        {"dataset_id": ds, "intent": "comparison",
         "preprocessing": [{"op": "nullify_values", "column": "age", "values": ["999"]}]},
        registry,
    )
    assert verdict["valid"] is False
    assert any("cannot occur in a number column" in e for e in verdict["errors"])


def test_an_explicit_nullify_suppresses_the_question(registry, tmp_path):
    """An instruction already given must not be re-litigated."""
    slots = quality.suppressed_slots(
        [{"op": "nullify_values", "column": "age", "values": [999]}]
    )
    assert "suspect:age" in slots


# --- data roles ---------------------------------------------------------------------


def _emails(bad):
    return [{"email": f"user{i}@example.com"} for i in range(20)] + [{"email": b} for b in bad]


def test_a_mostly_email_column_flags_its_exceptions(registry, tmp_path):
    _ds, rec = _record(registry, tmp_path, "mail.csv", _emails(["not an email", "also bad"]))
    issue = next(i for i in quality.scan(rec, {"email"}) if i.kind == "invalid_domain_values")
    assert issue.affected == 2
    assert issue.detail["domain"] == "email address"


def test_a_clean_email_column_says_nothing(registry, tmp_path):
    _ds, rec = _record(registry, tmp_path, "clean_mail.csv", _emails([]))
    assert "invalid_domain_values" not in _kinds(quality.scan(rec, {"email"}))


def test_a_column_that_is_merely_not_emails_is_not_broken(registry, tmp_path):
    """A notes field containing two addresses is a notes field. Flagging the
    other 90% as invalid would be the detector inventing a domain."""
    rows = [{"note": f"call back on tuesday {i}"} for i in range(20)]
    rows += [{"note": "a@b.com"}, {"note": "c@d.com"}]
    _ds, rec = _record(registry, tmp_path, "notes.csv", rows)
    assert "invalid_domain_values" not in _kinds(quality.scan(rec, {"note"}))


def test_domain_failures_become_an_advisory_with_no_repair_offered(registry, tmp_path):
    """There is no op that can invent the right address, and dropping the rows is
    a decision about the analysis rather than about the data. So it is stated and
    left alone."""
    _ds, rec = _record(registry, tmp_path, "adv.csv", _emails(["bad", "worse"]))
    issues = quality.scan(rec, {"email"})
    _auto, proposals = quality.recommend(issues, len(rec.df))
    assert not [p for p in proposals if p.issue.kind == "invalid_domain_values"]

    produced = notices.from_quality_issues([i.to_wire() for i in issues])
    assert [n.kind for n in produced] == ["invalid_domain_values"]
    assert produced[0].severity == notices.ADVISORY


# --- group-wise imputation -----------------------------------------------------------


def _salaries():
    """Two departments with very different pay, and a gap in each."""
    rows = [{"dept": "Eng", "salary": 100 + i} for i in range(10)]
    rows += [{"dept": "Sales", "salary": 500 + i} for i in range(10)]
    rows += [{"dept": "Eng", "salary": None}, {"dept": "Sales", "salary": None}]
    return rows


def _avg_by_dept(registry, ds, pre):
    out = execute_analysis(
        ds,
        {"dataset_id": ds, "intent": "comparison", "preprocessing": pre,
         "group_by": ["dept"],
         "aggregations": [{"column": "salary", "fn": "mean", "as": "avg"}]},
        registry,
    )
    assert "error" not in out, out
    return {r["dept"]: r["avg"] for r in out["result_table"]}


def test_a_global_median_pulls_every_group_toward_the_middle(registry, tmp_path):
    """The behaviour `by` exists to avoid, pinned so the comparison below means
    something: the Sales gap is filled with a company-wide figure that no
    salesperson earns."""
    ds, _rec = _record(registry, tmp_path, "sal.csv", _salaries())
    avg = _avg_by_dept(
        registry, ds, [{"op": "fill_nulls", "column": "salary", "strategy": "median"}]
    )
    assert avg["Sales"] < 500  # dragged down by engineering salaries


def test_a_group_wise_median_preserves_the_spread(registry, tmp_path):
    ds, _rec = _record(registry, tmp_path, "sal2.csv", _salaries())
    avg = _avg_by_dept(
        registry, ds,
        [{"op": "fill_nulls", "column": "salary", "strategy": "median", "by": ["dept"]}],
    )
    assert avg["Sales"] > 500 and avg["Eng"] < 120


def test_group_wise_fill_names_the_grouping_in_its_disclosure(registry, tmp_path):
    ds, _rec = _record(registry, tmp_path, "sal3.csv", _salaries())
    out = execute_analysis(
        ds,
        {"dataset_id": ds, "intent": "comparison",
         "preprocessing": [
             {"op": "fill_nulls", "column": "salary", "strategy": "median", "by": ["dept"]}
         ],
         "aggregations": [{"column": "salary", "fn": "mean", "as": "avg"}]},
        registry,
    )
    note = next(n for n in out["provenance"]["notices"] if n["kind"] == "fill_nulls")
    assert "within each 'dept'" in note["note"]


def test_a_group_with_nothing_to_impute_from_stays_missing_and_says_so(registry, tmp_path):
    """An empty group has no median. Leaving those rows null is the honest
    outcome, and silence would let the reader assume the column is complete."""
    rows = _salaries() + [{"dept": "Legal", "salary": None}, {"dept": "Legal", "salary": None}]
    ds, _rec = _record(registry, tmp_path, "sal4.csv", rows)
    out = execute_analysis(
        ds,
        {"dataset_id": ds, "intent": "comparison",
         "preprocessing": [
             {"op": "fill_nulls", "column": "salary", "strategy": "median", "by": ["dept"]}
         ],
         "select": ["dept", "salary"]},
        registry,
    )
    step = next(s for s in out["preprocessing"] if s["operation"] == "fill_nulls")
    assert step["rows_still_null"] == 2
    note = next(n for n in out["provenance"]["notices"] if n["kind"] == "fill_nulls")
    assert "could not be filled" in note["note"]


def test_group_wise_mode_is_refused_rather_than_silently_global(registry, tmp_path):
    """A deterministic per-group mode needs a second window pass; an arbitrary
    tie-break is what this codebase refuses everywhere else. Falling back to a
    global fill would look like it worked."""
    ds, _rec = _record(registry, tmp_path, "sal5.csv", _salaries())
    verdict = validate_analysis_plan(
        ds,
        {"dataset_id": ds, "intent": "comparison",
         "preprocessing": [
             {"op": "fill_nulls", "column": "dept", "strategy": "mode", "by": ["salary"]}
         ]},
        registry,
    )
    assert verdict["valid"] is False
    assert any("median strategy only" in e for e in verdict["errors"])


def test_grouping_by_the_filled_column_is_refused(registry, tmp_path):
    ds, _rec = _record(registry, tmp_path, "sal6.csv", _salaries())
    verdict = validate_analysis_plan(
        ds,
        {"dataset_id": ds, "intent": "comparison",
         "preprocessing": [
             {"op": "fill_nulls", "column": "salary", "strategy": "median",
              "by": ["salary"]}
         ]},
        registry,
    )
    assert verdict["valid"] is False
    assert any("same column being filled" in e for e in verdict["errors"])
