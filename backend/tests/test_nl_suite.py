"""The NL benchmark checked against itself: offline, no LLM.

Three things a hand-written held-out set gets wrong without anyone noticing,
because nothing fails until a model is scored on it:

* an expectation that names a column, aggregate, intent or chart type the
  product does not have — the case can then never pass, for any planner;
* an edit to a v1 case — every published number was measured on those 39;
* an expectation stricter than the question — a *correct* answer scored wrong.

The third is the expensive one, so every answerable v2 case carries a reference
plan here. It is run through the real agent (detectors, cleaning pass,
validator, DuckDB, chart recommendation) with a scripted planner standing in for
the LLM, and the response is scored by `nl_run.score` itself. A perfect planner
must score `correct`; if it does not, the case is wrong, not the planner.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, get_args

import pytest

from autoviz.agent.service import AgentService
from autoviz.llm.client import IntentDecision, PlannerError
from autoviz.schema.analysis_plan import AggFn, ChartType, Intent
from autoviz.services.dataset import register_dataset
from autoviz.services.registry import DatasetRegistry
from bench.nl_run import score
from bench.nl_suite import CASES, DATASETS, SUITES, V1_IDS

REPO = Path(__file__).resolve().parents[2]

EXPECTS = {"analysis", "clarification", "clarification_or_analysis", "refusal_or_clarification"}

# sha256 of the 39 v1 cases as canonical JSON (sets sorted). Equal to the list
# at app commit 037969f, before v2 was appended. If this fails, a v1 case was
# edited: revert it. Add a new case instead — see bench/README.md.
V1_FINGERPRINT = "5b41d2a913eda2af28ee16401330b7b1383dd9ad78ae94d3fbd95c83c210d1dc"


def _canonical(obj: Any) -> Any:
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    if isinstance(obj, dict):
        return {k: _canonical(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_canonical(v) for v in obj]
    return obj


def _header(dataset: str) -> set[str]:
    with open(REPO / DATASETS[dataset], encoding="utf-8", newline="") as fh:
        return set(next(csv.reader(fh)))


# --- shape ---------------------------------------------------------------------


def test_suite_sizes():
    assert len(CASES) == 100
    assert len(SUITES["v1"]) == 39 and len(V1_IDS) == 39
    assert len(SUITES["v2"]) == 61
    assert len({c["id"] for c in CASES}) == len(CASES), "duplicate case id"


def test_v1_is_unchanged():
    blob = json.dumps(_canonical(SUITES["v1"]), sort_keys=True, ensure_ascii=False)
    assert hashlib.sha256(blob.encode("utf-8")).hexdigest() == V1_FINGERPRINT


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_case_is_answerable_by_this_product(case):
    """Every name an expectation uses must exist, or the case can never pass."""
    assert case["dataset"] in DATASETS
    assert (REPO / DATASETS[case["dataset"]]).is_file()
    assert case["expect"] in EXPECTS
    assert case["prompt"].strip()

    header = _header(case["dataset"])
    named = set(case.get("must_columns") or ()) | set(case.get("forbid_columns") or ())
    for group in case.get("any_of") or ():
        named |= set(group)
    assert named <= header, f"not columns of {case['dataset']}: {sorted(named - header)}"

    assert set(case.get("agg") or ()) <= set(get_args(AggFn))
    assert set(case.get("intent") or ()) <= set(get_args(Intent))
    assert set(case.get("chart_family") or ()) <= set(get_args(ChartType))

    if case["expect"] in ("clarification", "refusal_or_clarification"):
        # Nothing is answered, so nothing past the outcome is ever checked.
        assert not (named or case.get("agg") or case.get("chart_family")), (
            "assertions on a case that must not produce an answer are dead code"
        )


# --- a perfect planner must score correct ----------------------------------------


def _cnt(col: str, alias: str) -> dict[str, Any]:
    return {"column": col, "fn": "count", "as": alias}


# One right answer per answerable v2 case — not *the* answer; the case asserts
# only what every right answer shares, which is exactly what this checks.
REFERENCE_PLANS: dict[str, dict[str, Any]] = {
    # titanic
    "T13": {"intent": "comparison", "group_by": ["who"],
            "aggregations": [{"column": "survived", "fn": "mean", "as": "survival_rate"}]},
    "T14": {"intent": "composition", "group_by": ["alone"],
            "aggregations": [_cnt("alone", "passengers")]},
    "T15": {"intent": "comparison", "group_by": ["class"],
            "aggregations": [{"column": "fare", "fn": "max", "as": "max_fare"}]},
    "T16": {"intent": "distribution", "group_by": ["sibsp"],
            "aggregations": [_cnt("sibsp", "passengers")],
            "sort": [{"by": "sibsp", "dir": "asc"}]},
    "T17": {"intent": "relationship", "select": ["age", "fare"],
            "chart": {"type": "scatter", "x": "age", "y": "fare"}},
    "T18": {"intent": "comparison",
            "filters": [{"column": "age", "op": "lt", "value": 18}],
            "group_by": ["class"],
            "aggregations": [{"column": "survived", "fn": "mean", "as": "survival_rate"}]},
    "T19": {"intent": "ranking",
            "filters": [{"column": "pclass", "op": "eq", "value": 1}],
            "group_by": ["embark_town"],
            "aggregations": [_cnt("embark_town", "passengers")],
            "sort": [{"by": "passengers", "dir": "desc"}]},
    "T20": {"intent": "comparison",
            "filters": [{"column": "survived", "op": "eq", "value": 0}],
            "group_by": ["sex"],
            "aggregations": [{"column": "age", "fn": "mean", "as": "avg_age"}]},
    "T21": {"intent": "distribution",
            "filters": [{"column": "embark_town", "op": "eq", "value": "Cherbourg"}],
            "select": ["fare"], "chart": {"type": "histogram", "x": "fare"}},
    # tips
    "P09": {"intent": "composition", "group_by": ["time"],
            "aggregations": [_cnt("time", "tables")]},
    "P10": {"intent": "comparison", "group_by": ["day"],
            "aggregations": [{"column": "total_bill", "fn": "max", "as": "largest_bill"}]},
    "P11": {"intent": "distribution", "select": ["tip"],
            "chart": {"type": "histogram", "x": "tip"}},
    "P12": {"intent": "comparison",
            "filters": [{"column": "day", "op": "in", "value": ["Sat", "Sun"]}],
            "group_by": ["sex"],
            "aggregations": [{"column": "total_bill", "fn": "mean", "as": "avg_bill"}]},
    "P13": {"intent": "comparison",
            "filters": [{"column": "size", "op": "gte", "value": 4}],
            "group_by": ["time"],
            "aggregations": [{"column": "tip", "fn": "median", "as": "median_tip"}]},
    "P14": {"intent": "distribution", "select": ["smoker", "tip"],
            "chart": {"type": "boxplot", "x": "smoker", "y": "tip"}},
    "P15": {"intent": "ranking", "group_by": ["size"],
            "aggregations": [{"column": "total_bill", "fn": "mean", "as": "avg_bill"}],
            "sort": [{"by": "avg_bill", "dir": "asc"}]},
    "R04": {"intent": "comparison", "group_by": ["smoker", "day"],
            "aggregations": [{"column": "tip", "fn": "mean", "as": "avg_tip"}]},
    # weather
    "W08": {"intent": "trend",
            "derive": [{"name": "month", "from": "date", "fn": "month_start"}],
            "group_by": ["month"],
            "aggregations": [{"column": "wind", "fn": "mean", "as": "avg_wind"}],
            "sort": [{"by": "month", "dir": "asc"}]},
    "W09": {"intent": "comparison",
            "filters": [{"column": "weather", "op": "eq", "value": "rain"}],
            "derive": [{"name": "year", "from": "date", "fn": "year"}],
            "group_by": ["year"],
            "aggregations": [_cnt("weather", "rainy_days")]},
    "W10": {"intent": "ranking",
            "derive": [{"name": "month", "from": "date", "fn": "month"}],
            "group_by": ["month"],
            "aggregations": [{"column": "temp_min", "fn": "mean", "as": "avg_temp_min"}],
            "sort": [{"by": "avg_temp_min", "dir": "desc"}]},
    "W11": {"intent": "trend",
            "filters": [{"column": "date", "op": "gte", "value": "2015-01-01"}],
            "select": ["date", "temp_max"],
            "chart": {"type": "line", "x": "date", "y": "temp_max"}},
    "W12": {"intent": "trend",
            "filters": [{"column": "date", "op": "between",
                         "value": ["2013-01-01", "2013-12-31"]}],
            "derive": [{"name": "month", "from": "date", "fn": "month_start"}],
            "group_by": ["month"],
            "aggregations": [{"column": "precipitation", "fn": "sum", "as": "total_precipitation"}],
            "sort": [{"by": "month", "dir": "asc"}]},
    "W13": {"intent": "ranking", "group_by": ["weather"],
            "aggregations": [_cnt("weather", "days")],
            "sort": [{"by": "days", "dir": "desc"}]},
    "W14": {"intent": "relationship", "select": ["temp_min", "temp_max"],
            "chart": {"type": "scatter", "x": "temp_min", "y": "temp_max"}},
    "W15": {"intent": "trend",
            "derive": [{"name": "month", "from": "date", "fn": "month_start"}],
            "group_by": ["month"],
            "aggregations": [{"column": "precipitation", "fn": "mean", "as": "avg_precipitation"}],
            "sort": [{"by": "month", "dir": "asc"}]},
    "W16": {"intent": "ranking", "group_by": ["weather"],
            "aggregations": [{"column": "wind", "fn": "mean", "as": "avg_wind"}],
            "sort": [{"by": "avg_wind", "dir": "desc"}]},
    "W17": {"intent": "comparison",
            "derive": [{"name": "year", "from": "date", "fn": "year"}],
            "group_by": ["year"],
            "aggregations": [{"column": "temp_max", "fn": "max", "as": "highest_temp"}]},
    "R05": {"intent": "trend",
            "derive": [{"name": "month", "from": "date", "fn": "month_start"}],
            "group_by": ["month"],
            "aggregations": [{"column": "precipitation", "fn": "sum", "as": "total_precipitation"}],
            "sort": [{"by": "month", "dir": "asc"}]},
    # iris
    "I04": {"intent": "ranking", "group_by": ["species"],
            "aggregations": [{"column": "sepal_width", "fn": "mean", "as": "avg_sepal_width"}],
            "sort": [{"by": "avg_sepal_width", "dir": "desc"}]},
    "I05": {"intent": "distribution", "select": ["species", "sepal_length"],
            "chart": {"type": "boxplot", "x": "species", "y": "sepal_length"}},
    "I06": {"intent": "relationship", "select": ["petal_length", "petal_width"],
            "chart": {"type": "scatter", "x": "petal_length", "y": "petal_width"}},
    "I07": {"intent": "comparison",
            "filters": [{"column": "petal_length", "op": "gt", "value": 5}],
            "group_by": ["species"],
            "aggregations": [_cnt("species", "flowers")]},
    # penguins
    "G01": {"intent": "comparison", "group_by": ["species"],
            "aggregations": [{"column": "body_mass_g", "fn": "mean", "as": "avg_body_mass"}]},
    "G02": {"intent": "comparison", "group_by": ["island"],
            "aggregations": [_cnt("island", "penguins")]},
    "G03": {"intent": "relationship", "select": ["flipper_length_mm", "body_mass_g"],
            "chart": {"type": "scatter", "x": "flipper_length_mm", "y": "body_mass_g"}},
    "G04": {"intent": "comparison", "group_by": ["species", "island"],
            "aggregations": [_cnt("species", "penguins")]},
    "G05": {"intent": "comparison", "group_by": ["species", "sex"],
            "aggregations": [{"column": "bill_length_mm", "fn": "mean", "as": "avg_bill_length"}]},
    "G06": {"intent": "distribution", "select": ["flipper_length_mm"],
            "chart": {"type": "histogram", "x": "flipper_length_mm"}},
    "G07": {"intent": "ranking",
            "filters": [{"column": "species", "op": "eq", "value": "Adelie"}],
            "group_by": ["island"],
            "aggregations": [{"column": "body_mass_g", "fn": "mean", "as": "avg_body_mass"}],
            "sort": [{"by": "avg_body_mass", "dir": "desc"}]},
    "G08": {"intent": "comparison",
            "filters": [{"column": "sex", "op": "eq", "value": "FEMALE"}],
            "group_by": ["species"],
            "aggregations": [{"column": "bill_depth_mm", "fn": "median", "as": "median_bill_depth"}]},
    "G09": {"intent": "relationship",
            "select": ["bill_length_mm", "bill_depth_mm", "species"],
            "chart": {"type": "scatter", "x": "bill_length_mm", "y": "bill_depth_mm",
                      "color": "species"}},
    "A07": {"intent": "distribution", "select": ["body_mass_g"],
            "chart": {"type": "histogram", "x": "body_mass_g"}},
    # mpg
    "M01": {"intent": "comparison", "group_by": ["origin"],
            "aggregations": [{"column": "mpg", "fn": "mean", "as": "avg_mpg"}]},
    "M02": {"intent": "trend", "group_by": ["model_year"],
            "aggregations": [{"column": "mpg", "fn": "mean", "as": "avg_mpg"}],
            "sort": [{"by": "model_year", "dir": "asc"}],
            "chart": {"type": "line", "x": "model_year", "y": "avg_mpg"}},
    "M03": {"intent": "distribution", "group_by": ["cylinders"],
            "aggregations": [_cnt("cylinders", "cars")]},
    "M04": {"intent": "relationship", "select": ["weight", "horsepower"],
            "chart": {"type": "scatter", "x": "weight", "y": "horsepower"}},
    "M05": {"intent": "ranking", "group_by": ["origin"],
            "aggregations": [{"column": "weight", "fn": "mean", "as": "avg_weight"}],
            "sort": [{"by": "avg_weight", "dir": "desc"}]},
    "M06": {"intent": "distribution", "select": ["acceleration"],
            "chart": {"type": "histogram", "x": "acceleration"}},
    "M07": {"intent": "comparison",
            "filters": [{"column": "origin", "op": "eq", "value": "usa"}],
            "group_by": ["cylinders"],
            "aggregations": [{"column": "mpg", "fn": "mean", "as": "avg_mpg"}]},
    "M08": {"intent": "ranking", "select": ["name", "weight"],
            "sort": [{"by": "weight", "dir": "desc"}], "limit": 5,
            "chart": {"type": "bar", "x": "name", "y": "weight"}},
    "M09": {"intent": "comparison", "group_by": ["origin"],
            "aggregations": [{"column": "name", "fn": "count_distinct", "as": "models"}]},
    "M10": {"intent": "comparison", "group_by": ["origin", "cylinders"],
            "aggregations": [{"column": "horsepower", "fn": "mean", "as": "avg_horsepower"}]},
    "A08": {"intent": "comparison", "group_by": ["origin"],
            "aggregations": [{"column": "horsepower", "fn": "mean", "as": "avg_horsepower"}]},
}

# Multi-task cases: the split the classifier should produce, and a plan per part.
REFERENCE_TASKS: dict[str, dict[str, dict[str, Any]]] = {
    "R06": {
        "Average body mass by species.": REFERENCE_PLANS["G01"],
        "Plot flipper length against body mass.": REFERENCE_PLANS["G03"],
    },
}


class _PerfectPlanner:
    """Scripted PlannerLLM: classifies as analysis and returns known-good plans."""

    def __init__(self, plans: dict[str, dict[str, Any]]):
        self.plans = plans

    def classify(self, request, schema, profile, history, **_: Any):
        return IntentDecision(intent="analysis", tasks=list(self.plans))

    def generate_plan(self, task, dataset_id, schema, profile, **_: Any):
        for name, plan in self.plans.items():
            if task.startswith(name):
                return json.loads(json.dumps(plan))
        raise PlannerError(f"no reference plan for task {task!r}")

    def compose(self, request, results):
        return f"summary of {len(results)} result(s)"


ANSWERABLE_V2 = [
    c for c in SUITES["v2"] if c["expect"] in ("analysis", "clarification_or_analysis")
]

# Cases the deterministic detectors pause on before any planner is called, so
# every arm — Gemini, the base 4B, the fine-tune — would score them
# `over_asked`. The prompts are right and a detector is wrong; the bench does
# not get reworded around a defect it found. A case listed here runs as a
# strict xfail, so fixing the detector turns it into an unexpected pass and the
# entry has to go.
#
# Empty since 2026-09-25: this test found nine on its first run (T19, P10, W13,
# M08 — a superlative whose measure was implied; G03, G05, G08, G09, R06 — a
# word several columns share, pinned by its neighbour) and both detectors were
# fixed. See the regression tests in test_ambiguity_detectors.py.
KNOWN_DETECTOR_OVERASKS: dict[str, str] = {}


def _perfect_planner_params():
    for case in ANSWERABLE_V2:
        reason = KNOWN_DETECTOR_OVERASKS.get(case["id"])
        marks = [pytest.mark.xfail(strict=True, reason=reason)] if reason else []
        yield pytest.param(case, id=case["id"], marks=marks)


def test_every_answerable_v2_case_has_a_reference():
    have = set(REFERENCE_PLANS) | set(REFERENCE_TASKS)
    assert {c["id"] for c in ANSWERABLE_V2} <= have


@pytest.fixture(scope="module")
def bench_ids() -> tuple[DatasetRegistry, dict[str, str]]:
    registry = DatasetRegistry()
    ids = {}
    for name, rel in DATASETS.items():
        registered = register_dataset(str(REPO / rel), registry)
        assert "error" not in registered, registered
        ids[name] = registered["dataset_id"]
    return registry, ids


@pytest.mark.parametrize("case", list(_perfect_planner_params()))
def test_a_perfect_planner_scores_correct(case, bench_ids):
    registry, ids = bench_ids
    plans = REFERENCE_TASKS.get(case["id"]) or {case["prompt"]: REFERENCE_PLANS[case["id"]]}
    agent = AgentService(planner=_PerfectPlanner(plans), registry=registry)

    response = agent.run(case["prompt"], dataset_id=ids[case["dataset"]])
    verdict = score(case, response)

    assert verdict["outcome"] == "correct", (
        f"{case['id']}: a correct plan scored {verdict['outcome']} — "
        f"{verdict['failures']}; status={response.get('status')} "
        f"question={response.get('question')!r} errors={response.get('errors')}"
    )
