"""Agentic workflow tests: FakePlanner (offline) + real services + real DuckDB."""

from typing import Any

from autoviz.agent.service import AgentService
from autoviz.llm.client import Clarification, IntentDecision, PlannerError


class FakePlanner:
    """Scripted PlannerLLM. decisions: consumed FIFO by classify().
    plans: FIFO list, or a {task: plan} dict for parallel workers."""

    def __init__(self, decisions=None, plans=None):
        self.decisions = list(decisions or [])
        self.plans = plans if isinstance(plans, dict) else list(plans or [])
        self.classify_calls: list[dict[str, Any]] = []
        self.plan_calls: list[dict[str, Any]] = []

    def classify(self, request, schema, profile, history, clarification_answer=None):
        self.classify_calls.append(
            {"request": request, "history": history, "clarification_answer": clarification_answer}
        )
        if self.decisions:
            return self.decisions.pop(0)
        return IntentDecision(intent="analysis", tasks=[request])

    def generate_plan(
        self, task, dataset_id, schema, profile, prior_plan=None, rejected_plan=None, errors=None
    ):
        self.plan_calls.append(
            {"task": task, "prior_plan": prior_plan, "rejected_plan": rejected_plan, "errors": errors}
        )
        if isinstance(self.plans, dict):
            return dict(self.plans[task])
        if not self.plans:
            raise PlannerError("no scripted plan left")
        return dict(self.plans.pop(0))

    def compose(self, request, results):
        return f"summary of {len(results)} result(s)"


GOOD_IRIS_PLAN = {
    "intent": "comparison",
    "group_by": ["species"],
    "aggregations": [{"column": "sepal_length", "fn": "mean", "as": "avg_sepal_length"}],
}

BAD_IRIS_PLAN = {
    "intent": "comparison",
    "group_by": ["speciez"],  # unknown column -> validation error
    "aggregations": [{"column": "sepal_length", "fn": "mean", "as": "avg_sepal_length"}],
}


def test_happy_path_single_chart(registry, iris_id):
    agent = AgentService(planner=FakePlanner(plans=[GOOD_IRIS_PLAN]), registry=registry)
    out = agent.run("average sepal length by species", dataset_id=iris_id)
    assert out["status"] == "completed", out
    assert out["thread_id"]
    assert len(out["charts"]) == 1
    chart = out["charts"][0]
    assert chart["status"] == "ok"
    assert chart["result"]["row_count"] == 3
    assert chart["vega_lite_spec"]["mark"]
    assert "summary" in out["answer"]


def test_repair_loop_recovers(registry, iris_id):
    fake = FakePlanner(plans=[BAD_IRIS_PLAN, GOOD_IRIS_PLAN])
    agent = AgentService(planner=fake, registry=registry)
    out = agent.run("average sepal length by species", dataset_id=iris_id)
    assert out["status"] == "completed", out
    assert out["charts"][0]["status"] == "ok"
    assert out["charts"][0]["attempts"] == 2
    # The repair call received the rejected plan and the exact validator errors.
    repair_call = fake.plan_calls[1]
    assert repair_call["rejected_plan"]["group_by"] == ["speciez"]
    assert any("speciez" in e for e in repair_call["errors"])


def test_repairs_exhausted_returns_structured_failure(registry, iris_id):
    fake = FakePlanner(plans=[BAD_IRIS_PLAN, BAD_IRIS_PLAN, BAD_IRIS_PLAN, BAD_IRIS_PLAN])
    agent = AgentService(planner=fake, registry=registry)
    out = agent.run("average sepal length by species", dataset_id=iris_id)
    assert out["status"] == "failed"
    chart = out["charts"][0]
    assert chart["status"] == "error"
    assert chart["attempts"] == 3  # 1 initial + MAX_PLAN_ATTEMPTS repairs
    assert any("speciez" in e for e in chart["errors"])


def test_multi_chart_fan_out(registry, titanic_id):
    fare_task = "average fare by class"
    age_task = "age distribution"
    decision = IntentDecision(intent="analysis", tasks=[fare_task, age_task])
    plans = {
        fare_task: {
            "intent": "comparison",
            "group_by": ["class"],
            "aggregations": [{"column": "fare", "fn": "mean", "as": "avg_fare"}],
        },
        age_task: {"intent": "distribution", "select": ["age"]},
    }
    agent = AgentService(planner=FakePlanner(decisions=[decision], plans=plans), registry=registry)
    out = agent.run("average fare by class and the age distribution", dataset_id=titanic_id)
    assert out["status"] == "completed", out
    assert len(out["charts"]) == 2
    assert all(c["status"] == "ok" for c in out["charts"])
    types = {c["chart_spec"]["type"] for c in out["charts"]}
    assert types == {"bar", "histogram"}


def test_clarification_interrupt_round_trip(registry, weather_id):
    ask = IntentDecision(
        intent="clarification",
        clarification=Clarification(
            question="Which measure?", options=["precipitation", "temp_max"]
        ),
    )
    proceed = IntentDecision(intent="analysis", tasks=["total precipitation by month"])
    plan = {
        "intent": "trend",
        "derive": [{"name": "month", "from": "date", "fn": "month"}],
        "group_by": ["month"],
        "aggregations": [{"column": "precipitation", "fn": "sum", "as": "total_precip"}],
    }
    fake = FakePlanner(decisions=[ask, proceed], plans=[plan])
    agent = AgentService(planner=fake, registry=registry)

    out = agent.run("show me the monthly weather", dataset_id=weather_id)
    assert out["status"] == "waiting_for_user", out
    assert out["question"] == "Which measure?"
    assert out["options"] == ["precipitation", "temp_max"]

    resumed = agent.resume(out["thread_id"], "precipitation")
    assert resumed["status"] == "completed", resumed
    assert resumed["charts"][0]["result"]["row_count"] == 12
    # The second classify call saw the user's answer.
    assert fake.classify_calls[-1]["clarification_answer"] == "precipitation"


def test_resume_without_paused_run_is_structured_error(registry):
    agent = AgentService(planner=FakePlanner(), registry=registry)
    out = agent.resume("th_nonexistent", "whatever")
    assert out["status"] == "failed"
    assert any("th_nonexistent" in e for e in out["errors"])


def test_refinement_receives_prior_plan(registry, iris_id):
    first = IntentDecision(intent="analysis", tasks=["avg sepal length by species"])
    second = IntentDecision(intent="refinement", tasks=["same as a pie chart"])
    refined = {
        **GOOD_IRIS_PLAN,
        "chart": {"type": "pie", "x": "species", "y": "avg_sepal_length"},
    }
    fake = FakePlanner(decisions=[first, second], plans=[GOOD_IRIS_PLAN, refined])
    agent = AgentService(planner=fake, registry=registry)

    out1 = agent.run("avg sepal length by species", dataset_id=iris_id)
    assert out1["status"] == "completed"
    out2 = agent.run("same as a pie chart", dataset_id=iris_id, thread_id=out1["thread_id"])
    assert out2["status"] == "completed", out2
    assert out2["charts"][0]["chart_spec"]["type"] == "pie"
    # The refinement planner call was grounded in the previous run's plan.
    assert fake.plan_calls[1]["prior_plan"]["group_by"] == ["species"]
    # And the fresh run replaced (not appended to) the previous chart_results.
    assert len(out2["charts"]) == 1


def test_chart_failure_keeps_partial_result(registry, iris_id):
    # Text-only result: recommend_chart_type fails (no numeric measure) and the
    # bar fallback has no numeric y either -> partial result, no chart, data kept.
    plan = {"intent": "distribution", "select": ["species"]}
    agent = AgentService(planner=FakePlanner(plans=[plan]), registry=registry)
    out = agent.run("list the species", dataset_id=iris_id)
    assert out["status"] == "completed", out
    chart = out["charts"][0]
    assert chart["status"] == "partial"
    assert chart["result"]["row_count"] == 150  # all iris rows (no limit -> full column)
    assert chart.get("vega_lite_spec") is None
    assert any("recommend_chart_type" in e for e in chart["errors"])


def test_unknown_dataset_fails_before_planning(registry):
    fake = FakePlanner(plans=[GOOD_IRIS_PLAN])
    agent = AgentService(planner=fake, registry=registry)
    out = agent.run("anything", dataset_id="ds_nope")
    assert out["status"] == "failed"
    assert any("ds_nope" in e for e in out["errors"])
    assert fake.plan_calls == []
