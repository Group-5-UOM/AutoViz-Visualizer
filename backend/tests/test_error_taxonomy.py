"""Error-code propagation and the routing/retry policy that depends on it."""

import threading

import pandas as pd

import autoviz.agent.nodes as nodes_mod
import autoviz.services.execution as execution_mod
from autoviz.agent.routing import route_after_execute
from autoviz.errors import (
    CHART_ERROR,
    EXECUTION_ERROR,
    INVALID_PLAN,
    TIMEOUT,
    TYPE_MISMATCH,
    UNKNOWN_DATASET,
)
from autoviz.services.execution import execute_analysis
from autoviz.services.validation import validate_analysis_plan


# --- error_code on the service returns ---------------------------------------


def test_execute_unknown_dataset_is_terminal_code(registry):
    out = execute_analysis("ds_missing", {"dataset_id": "ds_missing", "intent": "comparison"}, registry)
    assert out["error_code"] == UNKNOWN_DATASET
    assert out["retryable"] is False


def test_validation_missing_column_is_invalid_plan(registry, iris_id):
    verdict = validate_analysis_plan(
        iris_id,
        {"dataset_id": iris_id, "intent": "comparison", "select": ["nope"]},
        registry,
    )
    assert verdict["valid"] is False
    assert verdict["error_code"] == INVALID_PLAN


def test_validation_pure_type_error_is_type_mismatch(registry, iris_id):
    # 'contains' on a numeric column: a pure type-compatibility failure.
    verdict = validate_analysis_plan(
        iris_id,
        {
            "dataset_id": iris_id,
            "intent": "distribution",
            "filters": [{"column": "sepal_length", "op": "contains", "value": "x"}],
        },
        registry,
    )
    assert verdict["valid"] is False
    assert verdict["error_code"] == TYPE_MISMATCH


def test_execute_validation_failure_keeps_legacy_message(registry, iris_id):
    out = execute_analysis(
        iris_id,
        {"dataset_id": iris_id, "intent": "comparison", "group_by": ["nope"],
         "aggregations": [{"column": "sepal_length", "fn": "sum", "as": "s"}]},
        registry,
    )
    assert out["error"] == "Plan failed validation"  # unchanged contract
    assert out["error_code"] == INVALID_PLAN
    assert out["validation_errors"]


# --- execution timeout wiring -------------------------------------------------


class _InterruptibleCon:
    """Fake DuckDB connection: the main query blocks until interrupt() fires."""

    def __init__(self):
        self._interrupted = threading.Event()

    def execute(self, sql, params=None):
        if sql.startswith("SET"):
            return self
        # Simulate a long-running, interruptible query.
        if self._interrupted.wait(timeout=5):
            raise RuntimeError("query interrupted")
        return self

    def register(self, *args):
        pass

    def fetchdf(self):
        return pd.DataFrame({"x": [1]})

    def interrupt(self):
        self._interrupted.set()

    def close(self):
        pass


def test_execution_timeout_returns_timeout_code(registry, iris_id, monkeypatch):
    monkeypatch.setattr(execution_mod, "EXECUTION_TIMEOUT_S", 0.05)
    monkeypatch.setattr(execution_mod.duckdb, "connect", lambda *a, **k: _InterruptibleCon())
    out = execute_analysis(
        iris_id, {"dataset_id": iris_id, "intent": "distribution", "select": ["species"]}, registry
    )
    assert out["error_code"] == TIMEOUT
    assert out["retryable"] is True


# --- routing: replan only for plan-repairable codes ---------------------------


def _state(code, failed_step="execute_analysis", status="error", attempts=1):
    return {
        "pipeline_output": {"status": status, "failed_step": failed_step, "error_code": code},
        "plan_attempts": attempts,
    }


def test_routing_replans_on_plan_errors():
    assert route_after_execute(_state(INVALID_PLAN)) == "plan"
    assert route_after_execute(_state(TYPE_MISMATCH)) == "plan"


def test_routing_does_not_replan_on_infrastructure_errors():
    # The core regression: infra faults must not burn the replan budget.
    assert route_after_execute(_state(EXECUTION_ERROR)) == "finalize"
    assert route_after_execute(_state(TIMEOUT)) == "finalize"
    assert route_after_execute(_state(UNKNOWN_DATASET)) == "finalize"


def test_routing_chart_error_falls_back():
    assert route_after_execute(_state(CHART_ERROR, failed_step="generate_chart")) == "chart_fallback"


def test_routing_exhausted_budget_finalizes():
    # attempts at the ceiling (1 + MAX_PLAN_ATTEMPTS) -> no more replans.
    assert route_after_execute(_state(INVALID_PLAN, attempts=3)) == "finalize"


def test_routing_ok_finalizes():
    assert route_after_execute({"pipeline_output": {"status": "ok"}}) == "finalize"


# --- execute_node retry-with-backoff ------------------------------------------


def test_execute_node_retries_infrastructure_faults(monkeypatch):
    calls = {"n": 0}

    def fake_run_pipeline(dataset_id, plan, registry):
        calls["n"] += 1
        return {"status": "error", "failed_step": "execute_analysis",
                "error_code": EXECUTION_ERROR, "errors": ["boom"]}

    monkeypatch.setattr(nodes_mod, "run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(nodes_mod, "EXEC_RETRY_BACKOFF_S", 0.0)  # keep the test fast

    out = nodes_mod.execute_node({"dataset_id": "x", "analysis_plan": {}}, registry=None)
    assert calls["n"] == 1 + nodes_mod.MAX_EXEC_RETRIES
    # An infra fault never feeds the plan-repair loop.
    assert "rejected_plan" not in out


def test_execute_node_does_not_retry_plan_errors(monkeypatch):
    calls = {"n": 0}

    def fake_run_pipeline(dataset_id, plan, registry):
        calls["n"] += 1
        return {"status": "error", "failed_step": "execute_analysis",
                "error_code": INVALID_PLAN, "errors": ["bad column"]}

    monkeypatch.setattr(nodes_mod, "run_pipeline", fake_run_pipeline)

    out = nodes_mod.execute_node({"dataset_id": "x", "analysis_plan": {"k": "v"}}, registry=None)
    assert calls["n"] == 1  # no retry for a plan error
    assert out["rejected_plan"] == {"k": "v"}
    assert out["validation_errors"] == ["bad column"]
