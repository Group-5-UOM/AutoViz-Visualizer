"""Day 5: state-transition + end-to-end evaluation of the clarification loop.

Unit-level schema/binding/detector tests live in test_clarification.py,
test_ambiguity_detectors.py and test_ambiguity_value_column.py. This file covers
the *integration*: graph routing decisions and full run→interrupt→resume flows.
"""

from autoviz import observability
from autoviz.agent import routing
from autoviz.agent.service import AgentService
from autoviz.services.dataset import get_dataset_schema, register_dataset

from tests.test_agent import FakePlanner

# ---------------------------------------------------------------------------
# State-transition tests: routing decisions in isolation.
# ---------------------------------------------------------------------------

def test_route_after_context_success_goes_to_detect():
    assert routing.route_after_context({"status": "running"}) == "detect_ambiguity"


def test_route_after_context_failure_goes_to_record_failure():
    assert routing.route_after_context({"status": "failed"}) == "record_failure"


def test_route_after_detect_asks_when_pending_and_under_budget():
    state = {"pending_ambiguities": [{"slot": "metric"}], "clarification_count": 0}
    assert routing.route_after_detect(state) == "clarify"


def test_route_after_detect_proceeds_when_budget_exhausted():
    # Pending remains but the round cap is hit -> proceed best-effort.
    state = {"pending_ambiguities": [{"slot": "metric"}], "clarification_count": 2}
    assert routing.route_after_detect(state) == "classify_intent"


def test_route_after_detect_proceeds_when_nothing_pending():
    assert routing.route_after_detect({"pending_ambiguities": []}) == "classify_intent"


def test_route_after_clarify_detector_loops_back_to_detect():
    assert routing.route_after_clarify({"clarify_source": "detector"}) == "detect_ambiguity"


def test_route_after_clarify_llm_returns_to_classify():
    assert routing.route_after_clarify({"clarify_source": "llm"}) == "classify_intent"


# ---------------------------------------------------------------------------
# End-to-end evaluation through AgentService (FakePlanner + real services).
# ---------------------------------------------------------------------------

GOOD_IRIS_PLAN = {
    "intent": "comparison",
    "group_by": ["species"],
    "aggregations": [{"column": "sepal_length", "fn": "mean", "as": "avg_sepal_length"}],
}


def test_fully_specified_request_never_clarifies(registry, iris_id):
    fake = FakePlanner(plans=[GOOD_IRIS_PLAN])
    agent = AgentService(planner=fake, registry=registry)
    out = agent.run("average sepal length by species", dataset_id=iris_id)
    assert out["status"] == "completed", out
    # classify ran exactly once (no clarification round-trip).
    assert len(fake.classify_calls) == 1


def test_missing_metric_triggers_single_round_and_binds(registry, iris_id):
    fake = FakePlanner(plans=[GOOD_IRIS_PLAN])
    agent = AgentService(planner=fake, registry=registry)

    out = agent.run("which species is the best", dataset_id=iris_id)
    assert out["status"] == "waiting_for_user"
    assert "Average sepal length" in out["options"]

    resumed = agent.resume(out["thread_id"], "Average sepal length")
    assert resumed["status"] == "completed", resumed
    # The clicked option was bound deterministically into the planned task.
    assert "measure by mean of `sepal_length`" in fake.plan_calls[-1]["task"]


def test_bounded_multi_round_time_then_metric(registry, tmp_path):
    # A dataset with TWO date columns + a temporal, superlative request triggers
    # both the time_column and missing_metric detectors -> two clarification rounds.
    csv = tmp_path / "sales.csv"
    rows = ["signup_date,order_date,region,revenue"]
    for i in range(12):
        rows.append(f"2015-0{i % 9 + 1}-01,2016-0{i % 9 + 1}-01,{'NSEW'[i % 4]},{100 + i}")
    csv.write_text("\n".join(rows))
    ds = register_dataset(str(csv), registry)["dataset_id"]
    # Guard the fixture: both date columns must be typed datetime.
    types = {c["name"]: c["type"] for c in get_dataset_schema(ds, registry)["columns"]}
    assert types["signup_date"] == "datetime" and types["order_date"] == "datetime"

    plan = {
        "intent": "comparison",
        "group_by": ["region"],
        "aggregations": [{"column": "revenue", "fn": "mean", "as": "avg_revenue"}],
    }
    fake = FakePlanner(plans=[plan])
    agent = AgentService(planner=fake, registry=registry)

    # Round 1: which time column?
    r1 = agent.run("which region trends best over time", dataset_id=ds)
    assert r1["status"] == "waiting_for_user"
    assert r1["options"] == ["Signup date", "Order date"]

    # Round 2: which metric? (time_column resolved, missing_metric remains)
    r2 = agent.resume(r1["thread_id"], "Order date")
    assert r2["status"] == "waiting_for_user"
    assert "Average revenue" in r2["options"]

    # Resolved -> proceeds, with BOTH constraints folded into the task.
    r3 = agent.resume(r2["thread_id"], "Average revenue")
    assert r3["status"] == "completed", r3
    task = fake.plan_calls[-1]["task"]
    assert "use column `order_date` as the time axis" in task
    assert "measure by mean of `revenue`" in task


def test_clarification_emits_observability_event(registry, iris_id, monkeypatch):
    events: list[dict] = []
    monkeypatch.setattr(observability, "log_event", lambda event, **f: events.append({"event": event, **f}))

    fake = FakePlanner(plans=[GOOD_IRIS_PLAN])
    agent = AgentService(planner=fake, registry=registry)
    out = agent.run("which species is the best", dataset_id=iris_id)
    agent.resume(out["thread_id"], "Average sepal length")

    clar = [e for e in events if e["event"] == "clarification"]
    assert clar, "expected a clarification observability event"
    assert clar[-1]["source"] == "detector"
    assert clar[-1]["slot"] == "metric"
    assert clar[-1]["resolution"] in ("option", "free_text")
