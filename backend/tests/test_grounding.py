"""Grounding the composed answer against the results it claims to describe.

`compose` is the only `PlannerLLM` job whose output nothing validated
(`Docs/16 §1.1`) — and it writes the prose the user actually reads. These tests
pin both halves of the guard: it catches a number with no source, and it does
not fire on the many truthful ways a real summary states a real one.

The second half matters more than the first. A false positive throws away a good
answer, so every "does not fire" case below is a sentence a correct composer
plausibly writes.
"""

import pytest

from autoviz.services.grounding import (
    is_checkable,
    is_grounded,
    result_cells,
    ungrounded_numbers,
)

RESULTS = [
    {
        "task": "average fare by class",
        "status": "ok",
        "plan": {
            "dataset_id": "ds_1",
            "intent": "comparison",
            "group_by": ["pclass"],
            "aggregations": [{"column": "fare", "fn": "mean", "as": "avg_fare"}],
            "filters": [{"column": "fare", "op": "gt", "value": 100}],
        },
        "chart_spec": {"type": "bar"},
        "result": {
            "result_table": [
                {"pclass": 1, "avg_fare": 84.154687},
                {"pclass": 2, "avg_fare": 20.662183},
                {"pclass": 3, "avg_fare": 13.675550},
            ],
            "row_count": 3,
            "input_rows": 891,
            "output_rows": 891,
        },
        "notices": [],
    }
]


def _flag(answer: str) -> list[str]:
    return ungrounded_numbers(answer, RESULTS)


# --- catches what it exists to catch ------------------------------------------


def test_an_invented_figure_is_caught():
    assert _flag("First class paid 45.67 on average.") == ["45.67"]


def test_a_plausible_but_absent_figure_is_caught():
    """Close to a real value is still not the real value."""
    assert _flag("First class averaged 88.40.") == ["88.40"]


def test_an_invented_total_is_caught():
    assert _flag("Across all classes the total was 1234.5.") == ["1234.5"]


def test_several_offenders_are_all_reported():
    assert _flag("Values were 45.67, 88.40 and 1234.5.") == ["45.67", "88.40", "1234.5"]


# --- does not fire on truthful prose ------------------------------------------


def test_exact_values_are_grounded():
    assert is_grounded(
        "First class averaged 84.154687, second 20.662183, third 13.675550.", RESULTS
    )


@pytest.mark.parametrize("answer", [
    "First class averaged 84.15.",
    "First class averaged 84.2.",
    "First class averaged 84.",
])
def test_rounded_values_are_grounded(answer):
    """A composer rounds; rounding is not invention."""
    assert is_grounded(answer, RESULTS)


def test_row_accounting_is_grounded():
    assert is_grounded("Computed over all 891 passengers, returning 3 groups.", RESULTS)


def test_a_filter_literal_the_user_supplied_is_grounded():
    """`100` is in the request and the plan, never in a result cell."""
    assert is_grounded("Only fares above 100 were included.", RESULTS)


def test_counts_and_ordinals_are_grounded():
    assert is_grounded("All 3 classes are shown; the top 2 are first and second.", RESULTS)


def test_a_percentage_conversion_is_grounded():
    """A rate of 0.42 reported as 42% is a unit change, not a new number."""
    results = [{
        "status": "ok",
        "result": {"result_table": [{"sex": "female", "rate": 0.742}], "row_count": 1},
    }]
    assert is_grounded("Women survived at 74.2%.", results)


def test_numbers_inside_our_own_notices_are_grounded():
    """Notice prose is written by us from the same counts."""
    results = [{
        "status": "ok",
        "result": {"result_table": [{"a": 1.0}], "row_count": 1},
        "notices": [{
            "severity": "disclosed",
            "note": "177 of 891 values in 'age' (19.9%) were filled in, not measured.",
        }],
    }]
    assert is_grounded(
        "177 of 891 values in 'age' (19.9%) were filled in, not measured.", results
    )


def test_a_date_present_in_the_data_is_grounded():
    results = [{
        "status": "ok",
        "result": {
            "result_table": [{"month": "2012-01-01T00:00:00", "total": 5.0}],
            "row_count": 1,
        },
    }]
    assert is_grounded("The series starts on 2012-01-01.", results)


def test_a_date_absent_from_the_data_is_caught():
    results = [{
        "status": "ok",
        "result": {"result_table": [{"month": "2012-01-01", "total": 5.0}], "row_count": 1},
    }]
    assert ungrounded_numbers("The series starts on 2019-07-04.", results) == ["2019-07-04"]


def test_a_markdown_table_of_real_values_is_grounded():
    """The composer is told to use pipe tables; the rules must not read as claims."""
    answer = (
        "| Class | Average fare |\n|---|---|\n"
        "| 1 | 84.15 |\n| 2 | 20.66 |\n| 3 | 13.68 |"
    )
    assert is_grounded(answer, RESULTS)


def test_prose_with_no_numbers_is_grounded():
    assert is_grounded("Fares fall steadily from first class to third.", RESULTS)


def test_empty_answer_is_grounded():
    assert is_grounded("", RESULTS)


# --- the budget, and why it fails open ----------------------------------------
#
# Above MAX_GROUNDABLE_CELLS the check is switched off. Both reasons are
# measured: a 100k-row result costs seconds to build a grounded set for, and
# long before that the set is so dense that invented figures match by
# coincidence. A check with no power that also costs seconds is worse than none.


def _wide(rows: int) -> list[dict]:
    return [{
        "status": "ok",
        "result": {
            "result_table": [{"a": i * 1.5, "b": i * 2.25, "c": f"lab{i}"} for i in range(rows)],
            "row_count": rows,
        },
    }]


def test_a_small_result_is_checkable():
    assert is_checkable(_wide(60))


def test_a_large_result_is_not_checkable():
    assert not is_checkable(_wide(5_000))


def test_the_check_still_bites_at_the_top_of_the_budget():
    assert ungrounded_numbers("The value was 45.67.", _wide(660)) == ["45.67"]


def test_an_oversized_result_fails_open_rather_than_flagging_everything():
    """Reported as grounded, not as suspect — a false positive is the costly error."""
    assert ungrounded_numbers("The value was 45.67.", _wide(5_000)) == []


def test_result_cells_counts_every_column():
    assert result_cells(_wide(10)) == 30


# --- the guard as wired into the agent ---------------------------------------
#
# Unit-checking the predicate is not enough: the point is that a fabricated
# figure never reaches the user, which is a property of `compose_response`.

from autoviz.agent.service import AgentService  # noqa: E402
from autoviz.llm.client import IntentDecision  # noqa: E402

IRIS_PLAN = {
    "intent": "comparison",
    "group_by": ["species"],
    "aggregations": [{"column": "sepal_length", "fn": "mean", "as": "avg_sepal_length"}],
}


class _Composer:
    """A planner whose only interesting behaviour is what it writes as prose."""

    def __init__(self, answer: str):
        self.answer = answer

    def classify(self, request, schema, profile, history, clarification_answer=None):
        return IntentDecision(intent="analysis", tasks=[request])

    def generate_plan(self, task, dataset_id, schema, profile, **kw):
        return dict(IRIS_PLAN)

    def compose(self, request, results):
        return self.answer


def _run(answer: str, registry, iris_id):
    agent = AgentService(planner=_Composer(answer), registry=registry)
    return agent.run("average sepal length by species", dataset_id=iris_id)


def test_a_grounded_answer_is_served_as_written(registry, iris_id):
    out = _run("Setosa averages the shortest sepals of the three species.", registry, iris_id)
    assert out["status"] == "completed"
    assert out["answer"].startswith("Setosa averages")


def test_a_fabricated_figure_never_reaches_the_user(registry, iris_id):
    """Fluency lost, correctness kept — the right way round for a data tool."""
    out = _run("Setosa averaged 42.99 cm, far above the rest.", registry, iris_id)
    assert out["status"] == "completed"
    assert "42.99" not in out["answer"]
    # Replaced by the template summary, which is grounded by construction.
    assert "row(s)" in out["answer"]


def test_the_charts_survive_a_rejected_answer(registry, iris_id):
    """Only the prose was wrong; the analysis behind it was fine."""
    out = _run("Setosa averaged 42.99 cm.", registry, iris_id)
    assert len(out["charts"]) == 1
    assert out["charts"][0]["status"] == "ok"
    assert out["charts"][0]["result"]["row_count"] == 3


# --- the three false positives found by running it for real -------------------
#
# The first version of this module flagged 3 of 32 real benchmark answers. All
# three were correct answers, and discarding a correct answer is the expensive
# error here — so each root cause gets a test with the shape that produced it.


def test_a_rate_printed_to_six_decimals_is_grounded():
    """Root cause 1: the data must be rounded to the prose's precision.

    No fixed set of roundings on the *value* can anticipate a composer printing
    0.9680851063829787 as "0.968085".
    """
    results = [{
        "status": "ok",
        "result": {
            "row_count": 2,
            "result_table": [
                {"sex": "female", "survival_rate": 0.9680851063829787},
                {"sex": "male", "survival_rate": 0.13544668587896252},
            ],
        },
    }]
    answer = "Females survived at 0.968085 and males at 0.135447."
    assert is_grounded(answer, results), ungrounded_numbers(answer, results)
    # …and at every shorter precision the composer might have chosen instead.
    for written in ("0.97", "0.968", "0.9681"):
        assert is_grounded(f"The rate was {written}.", results), written


def test_a_year_taken_from_a_truncated_timestamp_is_grounded():
    """Root cause 2: `year_start` stores 2012-01-01; the composer writes 2012."""
    results = [{
        "status": "ok",
        "result": {
            "row_count": 2,
            "result_table": [
                {"yr": "2012-01-01T00:00:00", "avg": 15.27},
                {"yr": "2015-01-01T00:00:00", "avg": 17.43},
            ],
        },
    }]
    assert is_grounded("Temperatures rose from 2012 through 2015.", results)


def test_a_year_from_a_date_range_filter_is_grounded():
    """Same fact reaching the plan the other common way."""
    results = [{
        "status": "ok",
        "plan": {"filters": [
            {"column": "date", "op": "between", "value": ["2014-01-01", "2014-12-31"]}
        ]},
        "result": {"row_count": 1, "result_table": [{"weather": "sun", "days": 187}]},
    }]
    assert is_grounded("There were 187 sunny days in 2014.", results)


def test_a_figure_ending_a_sentence_is_not_a_different_number():
    """Root cause 3: the regex swallowed the full stop, so "2014." missed 2014."""
    results = [{
        "status": "ok",
        "result": {"row_count": 1, "result_table": [{"yr": 2014, "n": 5.0}]},
    }]
    assert is_grounded("The data covers 2014.", results)


def test_a_trailing_decimal_point_does_not_hide_a_fabrication():
    """The regex fix must not become a way through the check."""
    results = [{
        "status": "ok",
        "result": {"row_count": 1, "result_table": [{"a": 1.0}]},
    }]
    assert ungrounded_numbers("The total was 987.65.", results) == ["987.65"]
