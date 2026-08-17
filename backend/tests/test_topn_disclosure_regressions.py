"""Four defects found by running the synthetic messy fixture through the agent.

Each test pins the *observable* wrong behaviour rather than the internals that
produced it, because in every case the internals were defensible on their own and
only the visible result gave the problem away.
"""

from autoviz.agent.nodes import _normalize_note, compose_response, finalize_worker
from autoviz.services import dataset, fidelity, quality
from autoviz.services.execution import execute_analysis


def _register(registry, tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return dataset.register_dataset(p.as_posix(), registry)["dataset_id"]


# Volume and value disagree by construction: `quiet` logs the fewest orders and
# earns the most, `noisy` the reverse. Frequency ranking keeps the wrong one.
_SKEWED = "rep,revenue\n" + (
    "noisy,1\n" * 12
    + "mid,10\n" * 6
    + "quiet,500\n" * 3
    + "tail,1\n" * 2
)


def _cardinality_issue(column="rep", distinct=4):
    return quality.QualityIssue(
        kind="high_cardinality",
        column=column,
        affected=distinct,
        fraction=0.0,
        detail={"distinct": distinct},
    )


# --- 1. top-N follows the plotted measure, not row frequency ------------------


def test_top_n_keeps_the_categories_that_lead_on_the_measure(registry, tmp_path):
    """A revenue chart must not bury the top earner because it logged few rows."""
    ds = _register(registry, tmp_path, "reps.csv", _SKEWED)
    plan = {
        "dataset_id": ds,
        "intent": "ranking",
        "preprocessing": [
            {
                "op": "group_rare_categories",
                "column": "rep",
                "top_n": 2,
                "other_label": "Other",
                "rank_by": {"column": "revenue", "fn": "sum"},
            }
        ],
        "group_by": ["rep"],
        "aggregations": [{"column": "revenue", "fn": "sum", "as": "total"}],
    }
    out = execute_analysis(ds, plan, registry)
    kept = {r["rep"] for r in out["result_table"]}
    # quiet: 3 rows but 1500 revenue — the top earner, and the one frequency drops.
    assert "quiet" in kept
    assert "noisy" not in kept


def test_top_n_without_rank_by_still_ranks_by_frequency(registry, tmp_path):
    """The old behaviour stays reachable — this is a widening, not a swap."""
    ds = _register(registry, tmp_path, "reps.csv", _SKEWED)
    plan = {
        "dataset_id": ds,
        "intent": "ranking",
        "preprocessing": [
            {"op": "group_rare_categories", "column": "rep", "top_n": 2,
             "other_label": "Other"}
        ],
        "group_by": ["rep"],
        "aggregations": [{"column": "revenue", "fn": "sum", "as": "total"}],
    }
    out = execute_analysis(ds, plan, registry)
    kept = {r["rep"] for r in out["result_table"]}
    assert "noisy" in kept  # 12 rows
    assert "quiet" not in kept


def test_proposal_carries_the_plans_measure_into_rank_by():
    _, proposals = quality.recommend(
        [_cardinality_issue()], total_rows=100, measure=("revenue", "sum")
    )
    option = next(o for o in proposals[0].options if o.recommended)
    assert option.op["rank_by"] == {"column": "revenue", "fn": "sum"}
    # The label has to stop promising "commonest" once it no longer means it.
    assert "commonest" not in option.detail
    assert "sum of revenue" in option.detail


def test_proposal_falls_back_to_frequency_without_an_aggregation():
    _, proposals = quality.recommend([_cardinality_issue()], total_rows=100)
    option = next(o for o in proposals[0].options if o.recommended)
    assert "rank_by" not in option.op
    assert "commonest" in option.detail


# --- 2. an answered cardinality question is not re-asked -----------------------


def test_group_rare_categories_suppresses_its_own_slot():
    """A refinement carries the prior plan's preprocessing; the question is done."""
    assert quality.suppressed_slots(
        [{"op": "group_rare_categories", "column": "sales_rep", "top_n": 10}]
    ) == {"cardinality:sales_rep"}


def test_unrelated_op_does_not_suppress_the_cardinality_slot():
    assert quality.suppressed_slots([{"op": "trim_whitespace", "columns": ["sales_rep"]}]) == set()


# --- 3. anything asked for and not delivered is said out loud -----------------


def _outcome(chart_type, spec=None, plan=None):
    return fidelity.ChartOutcome(
        chart_type=chart_type, vega_lite_spec=spec or {}, plan=plan or {}
    )


_LOG_SPEC = {"encoding": {"y": {"field": "revenue", "scale": {"type": "log"}}}}


def test_log_request_on_a_bar_is_declined_in_words():
    (notice,) = fidelity.unmet_requests(
        "make a log scaled version of this chart", _outcome("bar")
    )
    assert notice.kind == "request_not_applied"
    assert "unchanged" in notice.note


def test_log_request_honoured_on_a_line_says_nothing():
    assert fidelity.unmet_requests("make it log scaled", _outcome("line", _LOG_SPEC)) == []


def test_log_request_that_quietly_did_nothing_is_disclosed():
    """A scalable chart whose data was not skewed enough still owes an answer."""
    (notice,) = fidelity.unmet_requests("make it log scaled", _outcome("line"))
    assert "still linear" in notice.note


def test_log_scale_is_found_inside_a_layered_spec():
    """Label layers make the spec layered; the scale check must still see it."""
    layered = {"layer": [_LOG_SPEC, {"mark": "text"}]}
    assert fidelity.unmet_requests("log scale please", _outcome("line", layered)) == []


def test_a_request_that_never_mentioned_log_is_left_alone():
    assert fidelity.unmet_requests("total revenue by sales rep", _outcome("bar")) == []


def test_a_substituted_chart_type_is_disclosed():
    (notice,) = fidelity.unmet_requests("show it as a pie chart", _outcome("donut"))
    assert "not the pie chart that was asked for" in notice.note


def test_the_chart_type_that_was_asked_for_says_nothing():
    assert fidelity.unmet_requests("show it as a bar chart", _outcome("bar")) == []


def test_grouped_bar_is_not_read_as_bar():
    """Longest-phrase-first matching, or 'grouped bar' silently means 'bar'."""
    assert fidelity.unmet_requests("as a grouped bar chart", _outcome("grouped_bar")) == []
    assert fidelity.unmet_requests("as a grouped bar chart", _outcome("bar")) != []


# --- 3b. a sub-type that was named and not delivered --------------------------
# The family check cannot see these: ask for a violin, get a box plot, and both
# are `boxplot` — so it reads the request as honoured. These compare the
# modifier on the produced plan instead.


def _charted(chart_type, **chart):
    return _outcome(chart_type, plan={"chart": {"type": chart_type, **chart}})


def test_a_requested_violin_that_came_back_a_box_is_disclosed():
    (notice,) = fidelity.unmet_requests("show it as a violin plot", _charted("boxplot"))
    assert "not a violin plot" in notice.note
    assert notice.detail["modifier"] == "form"


def test_a_violin_that_was_delivered_says_nothing():
    assert fidelity.unmet_requests(
        "show it as a violin plot", _charted("boxplot", form="violin")
    ) == []


def test_a_requested_horizontal_bar_that_stayed_vertical_is_disclosed():
    (notice,) = fidelity.unmet_requests("as a horizontal bar chart", _charted("bar"))
    assert "horizontal bar chart" in notice.note


def test_a_horizontal_bar_that_was_delivered_says_nothing():
    assert fidelity.unmet_requests(
        "as a horizontal bar chart", _charted("bar", orientation="horizontal")
    ) == []


def test_a_bubble_request_is_honoured_by_any_size_column():
    assert fidelity.unmet_requests(
        "a bubble chart of gdp against life expectancy",
        _charted("scatter", size="population"),
    ) == []
    assert fidelity.unmet_requests("a bubble chart", _charted("scatter")) != []


def test_plain_stacked_is_not_read_as_a_request_for_100_percent():
    """A bar with a colour column already stacks, so "stacked bar" asks for the
    default. Reporting a refusal that never happened is the louder failure."""
    assert fidelity.unmet_requests("a stacked bar chart", _charted("bar", color="grp")) == []


def test_a_density_heatmap_request_is_not_disclosed_twice():
    """It contains "heatmap", so the family check speaks; the modifier check
    must stay quiet or the user is told one thing in two different sentences."""
    notices = fidelity.unmet_requests("a density heatmap", _charted("scatter"))
    assert len(notices) == 1


def test_an_ignored_sort_request_is_disclosed():
    (notice,) = fidelity.unmet_requests(
        "revenue by rep sorted descending", _outcome("bar", plan={"intent": "comparison"})
    )
    assert "not sorted by value" in notice.note


def test_a_ranking_plan_counts_as_sorted():
    """Ranking bars sort at render time with no explicit sort block."""
    assert (
        fidelity.unmet_requests(
            "rank them by revenue", _outcome("bar", plan={"intent": "ranking"})
        )
        == []
    )


def test_an_explicit_sort_block_counts_as_sorted():
    plan = {"intent": "comparison", "sort": [{"by": "total", "dir": "desc"}]}
    assert fidelity.unmet_requests("sorted by total", _outcome("bar", plan=plan)) == []


def test_several_unmet_requests_are_all_reported():
    """The checks are independent — one firing must not hide another."""
    notes = fidelity.unmet_requests(
        "show it as a log scaled pie chart sorted descending",
        _outcome("bar", plan={"intent": "comparison"}),
    )
    assert len(notes) == 3


def _ok_worker_state(task, chart_type):
    return {
        "task": task,
        "analysis_plan": {},
        "pipeline_output": {
            "status": "ok",
            "result": {"result_table": [], "provenance": {"notices": []}},
            "chart_spec": {"type": chart_type},
            "vega_lite_spec": {},
            "notices": [],
        },
    }


def test_the_refusal_reaches_the_worker_result():
    """The wiring, not just the helper: a refusal nobody attaches is a silent one."""
    out = finalize_worker(_ok_worker_state("make a log scaled version", "bar"))
    kinds = [n["kind"] for n in out["chart_results"][0]["notices"]]
    assert "request_not_applied" in kinds


def test_no_refusal_is_attached_when_the_request_was_honoured():
    state = _ok_worker_state("make a log scaled version", "line")
    state["pipeline_output"]["vega_lite_spec"] = _LOG_SPEC
    out = finalize_worker(state)
    kinds = [n["kind"] for n in out["chart_results"][0]["notices"]]
    assert "request_not_applied" not in kinds


# --- 4. a disclosure is never printed twice -----------------------------------


def test_normalize_note_folds_the_dash_the_composer_rewrites():
    """An em dash retyped as a hyphen is the same sentence to a reader."""
    em = "'revenue' is dominated by one value — about 19x the typical."
    hyphen = "'revenue' is dominated by one value - about 19x the typical."
    assert _normalize_note(em) == _normalize_note(hyphen)


def test_normalize_note_folds_case_and_wrapped_whitespace():
    assert _normalize_note("Rows  were\nskipped.") == _normalize_note("rows were skipped.")


class _EchoPlanner:
    """Composer that re-types the disclosure with a plain hyphen, as a real one does."""

    def __init__(self, answer):
        self.answer = answer

    def compose(self, request, results):
        return self.answer


_NOTE = "'total revenue' is dominated by one value — about 19x the typical 62,400,519."


def _state(*notice_lists):
    return {
        "user_request": "revenue by sales rep",
        "chart_results": [
            {"status": "ok", "task": "t", "plan": {}, "chart_id": f"ch_{i}", "notices": n}
            for i, n in enumerate(notice_lists)
        ],
    }


def _advisory(note):
    return {"kind": "skewed_axis", "severity": "advisory", "note": note}


def test_disclosure_is_not_repeated_when_the_composer_rewrote_the_dash():
    """The bug as seen: the same sentence printed twice, differing only in a dash."""
    retyped = _NOTE.replace("—", "-")
    out = compose_response(
        _state([_advisory(_NOTE)]), planner=_EchoPlanner(f"A bar chart. {retyped}")
    )
    assert out["final_response"]["answer"].count("dominated by one value") == 1


def test_the_same_disclosure_from_two_workers_is_said_once():
    out = compose_response(
        _state([_advisory(_NOTE)], [_advisory(_NOTE)]), planner=_EchoPlanner("A bar chart.")
    )
    assert out["final_response"]["answer"].count("dominated by one value") == 1


def test_a_disclosure_the_composer_omitted_is_still_appended():
    """Dedup must not become a way for a caveat to go missing."""
    out = compose_response(_state([_advisory(_NOTE)]), planner=_EchoPlanner("A bar chart."))
    assert "dominated by one value" in out["final_response"]["answer"]
