"""Day 5: state-transition + end-to-end evaluation of the clarification loop.
Unit-level schema/binding/detector tests live in test_clarification.py,
test_ambiguity_detectors.py and test_ambiguity_value_column.py. This file covers
the *integration*: graph routing decisions and full run→interrupt→resume flows.
"""

from autoviz import observability
from autoviz.agent import routing
from autoviz.llm.client import PlannerError
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


def test_route_after_clarify_loops_back_to_detect_whoever_asked():
    # Both layers write to one queue, so both answers take one route: re-detect
    # against the resolved slots, then classify with the answer in hand. Sending
    # an LLM answer straight to the classifier used to skip the detectors
    # entirely on the second round.
    assert routing.route_after_clarify({"clarify_source": "detector"}) == "detect_ambiguity"
    assert routing.route_after_clarify({"clarify_source": "llm"}) == "detect_ambiguity"


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

# ---------------------------------------------------------------------------
# The LLM layer: what happens when it proposes, and when it cannot answer.
# ---------------------------------------------------------------------------

class DeadPlanner(FakePlanner):
    """A planner whose provider is down. Not hypothetical: Gemini answered 503
    for the whole of one benchmark run while this layer was being built."""

    def classify(self, *args, **kwargs):
        raise PlannerError("planner LLM call failed: 503 UNAVAILABLE")


def test_detectors_still_ask_when_the_planner_is_unreachable(registry, iris_id):
    """The deterministic layer is the floor, and the floor has to hold alone.

    This is the argument for keeping the detectors rather than moving detection
    wholesale to the model: a provider outage costs recall on the meaning-level
    half, and nothing else. The request is still questioned rather than guessed.
    """
    agent = AgentService(planner=DeadPlanner(plans=[GOOD_IRIS_PLAN]), registry=registry)
    out = agent.run("which species is the best", dataset_id=iris_id)
    assert out["status"] == "waiting_for_user", out
    assert "Average sepal length" in out["options"]


def test_a_dead_planner_still_answers_a_clear_request(registry, iris_id):
    agent = AgentService(planner=DeadPlanner(plans=[GOOD_IRIS_PLAN]), registry=registry)
    out = agent.run("average sepal length by species", dataset_id=iris_id)
    assert out["status"] == "completed", out


def test_an_ungrounded_llm_proposal_does_not_stall_the_run(registry, iris_id):
    """The model says "clarification" and offers columns that do not exist.

    Every option is dropped by the gate, which leaves no question worth asking —
    and `tasks` is empty, because the model expected to be asking one. Falling
    back to the request itself is what keeps this from fanning out to nothing.
    """
    from autoviz.llm.client import IntentDecision, ProposedAmbiguity, ProposedOption

    ask = IntentDecision(
        intent="clarification",
        ambiguity=ProposedAmbiguity(
            type="semantic",
            slot="metric",
            question="Which bloom measurement did you mean?",
            options=[
                ProposedOption(label="Stem length", resolves_to={"column": "stem_length"}),
                ProposedOption(label="Petal count", resolves_to={"column": "petal_count"}),
            ],
        ),
    )
    fake = FakePlanner(decisions=[ask], plans=[GOOD_IRIS_PLAN])
    agent = AgentService(planner=fake, registry=registry)

    out = agent.run("average sepal length by species", dataset_id=iris_id)
    assert out["status"] == "completed", out
    assert fake.plan_calls[-1]["task"] == "average sepal length by species"


def test_a_grounded_llm_proposal_is_asked_and_logged_as_llm_origin(
    registry, iris_id, monkeypatch
):
    from autoviz.llm.client import IntentDecision, ProposedAmbiguity, ProposedOption

    events: list[dict] = []
    monkeypatch.setattr(
        observability, "log_event", lambda event, **f: events.append({"event": event, **f})
    )

    ask = IntentDecision(
        intent="clarification",
        ambiguity=ProposedAmbiguity(
            type="semantic",
            slot="metric",
            question="Which measurement counts as size here?",
            options=[
                ProposedOption(label="Sepal length",
                               resolves_to={"column": "sepal_length", "fn": "mean"}),
                ProposedOption(label="Petal length",
                               resolves_to={"column": "petal_length", "fn": "mean"}),
            ],
        ),
    )
    proceed = IntentDecision(intent="analysis", tasks=["average size by species"])
    fake = FakePlanner(decisions=[ask, proceed], plans=[GOOD_IRIS_PLAN])
    agent = AgentService(planner=fake, registry=registry)

    out = agent.run("show the size of each species", dataset_id=iris_id)
    assert out["status"] == "waiting_for_user", out
    resumed = agent.resume(out["thread_id"], "Petal length")
    assert resumed["status"] == "completed", resumed
    # Bound, not re-guessed: the choice reaches the planner spelled out.
    assert "measure by mean of `petal_length`" in fake.plan_calls[-1]["task"]
    # And it is attributed, so "is the LLM layer earning its place" stays answerable.
    clar = [e for e in events if e["event"] == "clarification"]
    assert clar and clar[-1]["source"] == "llm"
    assert clar[-1]["resolution"] == "option"


def test_the_llm_never_re_asks_a_slot_the_user_already_settled(registry, iris_id):
    """classify runs again after every answer, and will happily propose the same
    thing twice. The round budget is the backstop; the gate is the fix."""
    from autoviz.llm.client import IntentDecision, ProposedAmbiguity, ProposedOption

    def _ask():
        return IntentDecision(
            intent="clarification",
            ambiguity=ProposedAmbiguity(
                type="semantic",
                slot="metric",
                question="Which measurement counts as size here?",
                options=[
                    ProposedOption(label="Sepal length",
                                   resolves_to={"column": "sepal_length", "fn": "mean"}),
                    ProposedOption(label="Petal length",
                                   resolves_to={"column": "petal_length", "fn": "mean"}),
                ],
            ),
        )

    # Both decisions ask the same question. Without the guard the second one is
    # asked too, and the user answers "which measurement?" twice over.
    fake = FakePlanner(decisions=[_ask(), _ask()], plans=[GOOD_IRIS_PLAN])
    agent = AgentService(planner=fake, registry=registry)

    out = agent.run("show the size of each species", dataset_id=iris_id)
    resumed = agent.resume(out["thread_id"], "Petal length")
    assert resumed["status"] == "completed", resumed
