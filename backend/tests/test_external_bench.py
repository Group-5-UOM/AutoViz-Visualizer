"""The external benchmark checked against itself: offline, no LLM, no download.

A scorer that cannot recognise the gold chart as correct would report every
planner as worse than it is, and nothing would fail until a model was scored.
So every frozen case is scored against a chart drawn from its own published
data, and must pass; the same chart with one value changed must not.
"""

from __future__ import annotations

import pytest

from bench.external_run import score
from bench.external_suite import FAMILIES, gold_points, load_cases, norm_x

CASES = load_cases()


def _gold_chart(case, bump=0.0):
    vo = case["vis_obj"]
    series = vo["classify"] or [None]
    rows = []
    for i, ys in enumerate(vo["y_data"]):
        xs = vo["x_data"][i] if len(vo["x_data"]) > 1 else vo["x_data"][0]
        for x, y in zip(xs, ys):
            row = {"x_col": x, "y_col": y}
            if vo["classify"]:
                row["series_col"] = series[i]
            rows.append(row)
    if bump:
        rows[0]["y_col"] = float(rows[0]["y_col"]) + bump
    return {
        "status": "completed",
        "charts": [{
            "chart_spec": {"type": min(FAMILIES[case["chart"]]), "x": "x_col", "y": "y_col"},
            "vega_lite_spec": {"mark": "bar"},
            "result": {"result_table": rows},
        }],
    }


def test_two_disjoint_samples_of_100():
    by = {s: [c for c in CASES if c["source"] == s] for s in ("nvbench", "viseval")}
    assert len(by["nvbench"]) == len(by["viseval"]) == 100
    assert len({c["id"] for c in CASES}) == 200
    base = {s: {c["key"].split("@")[0] for c in cs} for s, cs in by.items()}
    assert not base["nvbench"] & base["viseval"]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_gold_chart_scores_correct(case):
    assert case["chart"] in FAMILIES
    assert gold_points(case["vis_obj"], None)
    verdict = score(case, _gold_chart(case), validator=None)
    assert verdict["outcome"] == "correct", verdict
    assert verdict["chart"]["structural"]


@pytest.mark.parametrize("case", CASES[::10], ids=[c["id"] for c in CASES[::10]])
def test_one_changed_value_scores_wrong(case):
    assert score(case, _gold_chart(case, bump=1.0), validator=None)["outcome"] == "wrong"


def test_zero_filled_gold_bins_need_not_be_drawn():
    """nvBench draws a 0 for every empty bin; a GROUP BY returns no row for it."""
    case = {"chart": "Line", "binning": "BIN d BY YEAR",
            "vis_obj": {"x_data": [["2003", "2004", "2005"]], "y_data": [[1, 0, 6]], "classify": []}}
    rows = [{"d": 2003, "n": 1}, {"d": 2005, "n": 6}]
    response = {"status": "completed", "charts": [{
        "chart_spec": {"type": "line"}, "vega_lite_spec": {"mark": "line"},
        "result": {"result_table": rows}}]}
    verdict = score(case, response, validator=None)
    assert verdict["outcome"] == "correct"
    assert verdict["chart"]["x"]


def test_pause_and_no_chart_are_not_scored_on_properties():
    case = CASES[0]
    assert score(case, {"status": "waiting_for_user"}, None) == {"outcome": "asked", "chart": None}
    assert score(case, {"status": "failed"}, None) == {"outcome": "failed", "chart": None}


@pytest.mark.parametrize(
    ("value", "unit", "want"),
    [
        (3, None, "3"), (3.0, None, "3"), ("3", None, "3"), (" Professor ", None, "professor"),
        ("2018-01-01T00:00:00", "year", "2018"), (2018, "year", "2018"),
        ("2009-02-14", "month", "feb"), ("February", "month", "feb"),
        ("2024-10-03", "weekday", "thu"), ("Thur", "weekday", "thu"), ("Thursday", "weekday", "thu"),
        ("2024-10-03 00:00:00", None, "2024-10-03"),
        ("9–1", None, "9-1"), ("May19 –October26", None, "may19 -october26"),
        (0, "weekday", "sun"), (4.0, "weekday", "thu"), (2, "month", "feb"), (2, None, "2"),
    ],
)
def test_normalisation(value, unit, want):
    assert norm_x(value, unit) == want
