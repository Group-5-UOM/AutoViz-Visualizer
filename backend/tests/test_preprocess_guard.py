"""Agent-level large-row-removal guard: the worker presents run_pipeline's
confirmation gate as an interrupt and binds the answer (proceed vs skip)."""

from autoviz import observability
from autoviz.agent.service import AgentService

from tests.test_agent import FakePlanner

DROP_PLAN = {
    "intent": "comparison",
    "preprocessing": [{"op": "drop_nulls", "columns": ["cls", "fare"], "how": "any"}],
    "group_by": ["cls"],
    "aggregations": [{"column": "fare", "fn": "mean", "as": "avg_fare"}],
}


def test_guard_interrupts_over_threshold_then_proceeds(registry, nulls_id):
    fake = FakePlanner(plans=[dict(DROP_PLAN)])
    agent = AgentService(planner=fake, registry=registry)

    out = agent.run("avg fare by class dropping missing", dataset_id=nulls_id)
    assert out["status"] == "waiting_for_user"
    assert "remove 4 of 10 rows" in out["question"]

    resumed = agent.resume(out["thread_id"], "Proceed with cleaning")
    assert resumed["status"] == "completed", resumed
    result = resumed["charts"][0]["result"]
    assert result["output_rows"] == 6
    assert result["preprocessing"][0]["operation"] == "drop_nulls"


def test_guard_skip_runs_on_full_data_but_keeps_fill(registry, nulls_id):
    plan = {
        "intent": "comparison",
        "preprocessing": [
            {"op": "fill_nulls", "column": "age", "strategy": "median"},
            {"op": "drop_nulls", "columns": ["cls", "fare"], "how": "any"},
        ],
        "select": ["cls", "age"],
    }
    fake = FakePlanner(plans=[dict(plan)])
    agent = AgentService(planner=fake, registry=registry)

    out = agent.run("clean then show", dataset_id=nulls_id)
    assert out["status"] == "waiting_for_user"

    resumed = agent.resume(out["thread_id"], "Skip cleaning (keep all rows)")
    assert resumed["status"] == "completed", resumed
    result = resumed["charts"][0]["result"]
    # Row-dropping step skipped -> all rows retained; the fill_nulls step is kept.
    assert result["input_rows"] == 10 and result["output_rows"] == 10
    ops = [s["operation"] for s in result["preprocessing"]]
    assert ops == ["fill_nulls"]


def test_guard_does_not_interrupt_under_threshold(registry, nulls_id):
    plan = {
        "intent": "comparison",
        "preprocessing": [{"op": "drop_nulls", "columns": ["fare"], "how": "any"}],  # 30%, not > 30%
        "select": ["fare"],
    }
    fake = FakePlanner(plans=[dict(plan)])
    agent = AgentService(planner=fake, registry=registry)
    out = agent.run("drop missing fares", dataset_id=nulls_id)
    assert out["status"] == "completed", out


def test_guard_emits_observability_event(registry, nulls_id, monkeypatch):
    events: list[dict] = []
    monkeypatch.setattr(
        observability, "log_event", lambda event, **f: events.append({"event": event, **f})
    )
    fake = FakePlanner(plans=[dict(DROP_PLAN)])
    agent = AgentService(planner=fake, registry=registry)
    out = agent.run("avg fare by class dropping missing", dataset_id=nulls_id)
    agent.resume(out["thread_id"], "Proceed with cleaning")

    conf = [e for e in events if e["event"] == "preprocessing_confirmation"]
    assert conf and conf[-1]["proceed"] is True and conf[-1]["dropped"] == 4
