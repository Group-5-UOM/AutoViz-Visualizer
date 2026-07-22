"""Workflow nodes. Each does one thing; LLM nodes degrade gracefully.

Deterministic nodes call the shared services unchanged — run_pipeline() stays
the single source of truth for validate -> execute -> chart.
"""

from typing import Any

from langgraph.types import interrupt

from autoviz.agent.state import (
    MAX_TASKS,
    AutoVizState,
    ChartResult,
    WorkerState,
)
from autoviz.llm.client import IntentDecision, PlannerError, PlannerLLM
from autoviz.services import charts, dataset
from autoviz.services.orchestrator import run_pipeline
from autoviz.services.registry import REGISTRY, DatasetRegistry

# failed_step values that mean "the plan is wrong" -> repairable by the LLM.
PLAN_REPAIR_STEPS = {"validate_analysis_plan", "execute_analysis"}
# failed_step values after a successful execution -> deterministic fallback.
CHART_FALLBACK_STEPS = {"recommend_chart_type", "generate_chart"}


# --- main-graph nodes ---------------------------------------------------------


def load_context(state: AutoVizState, *, registry: DatasetRegistry = REGISTRY) -> dict[str, Any]:
    schema = dataset.get_dataset_schema(state["dataset_id"], registry)
    if "error" in schema:
        return {"status": "failed", "errors": [schema["error"]]}
    profile = dataset.get_dataset_profile(state["dataset_id"], registry)
    return {"schema": schema["columns"], "profile": profile, "status": "running"}


def classify_intent(state: AutoVizState, *, planner: PlannerLLM) -> dict[str, Any]:
    try:
        decision = planner.classify(
            request=state["user_request"],
            schema=state["schema"],
            profile=state["profile"],
            history=state.get("history", []),
            clarification_answer=state.get("clarification_answer"),
        )
    except PlannerError:
        # Degrade: treat the raw request as a single analysis task.
        decision = IntentDecision(intent="analysis", tasks=[state["user_request"]])
    tasks = [t.strip() for t in decision.tasks if t.strip()][:MAX_TASKS]
    if decision.intent != "clarification" and not tasks:
        tasks = [state["user_request"]]
    return {
        "intent": decision.intent,
        "tasks": tasks,
        "clarification": (
            decision.clarification.model_dump() if decision.clarification else None
        ),
    }


def clarify(state: AutoVizState) -> dict[str, Any]:
    payload = state.get("clarification") or {
        "question": "Could you clarify your request?",
        "options": [],
    }
    answer = interrupt(payload)
    return {
        "clarification_answer": str(answer),
        "clarification_count": state.get("clarification_count", 0) + 1,
        "clarification": None,
    }


def compose_response(state: AutoVizState, *, planner: PlannerLLM) -> dict[str, Any]:
    results = state.get("chart_results") or []
    usable = [r for r in results if r.get("status") in ("ok", "partial")]
    status = "completed" if usable else "failed"
    try:
        answer = planner.compose(state["user_request"], list(results))
    except Exception:  # grounded template fallback — composing must never fail
        parts = []
        for r in results:
            if r.get("status") == "error":
                parts.append(f"'{r.get('task')}' failed: {'; '.join(r.get('errors') or [])}")
            else:
                rows = (r.get("result") or {}).get("row_count")
                chart = (r.get("chart_spec") or {}).get("type", "table")
                parts.append(f"'{r.get('task')}': {rows} row(s), {chart} chart.")
        answer = " ".join(parts) or "No results were produced."
    final = {"status": status, "answer": answer, "charts": results}
    plans = [r["plan"] for r in results if r.get("plan")]
    entry = {"request": state["user_request"], "plans": plans}
    return {"status": status, "final_response": final, "history": [entry]}


def record_failure(state: AutoVizState) -> dict[str, Any]:
    errors = state.get("errors") or ["The request could not be processed."]
    return {
        "status": "failed",
        "final_response": {"status": "failed", "answer": None, "errors": errors, "charts": []},
    }


# --- worker-subgraph nodes ----------------------------------------------------


def plan_node(state: WorkerState, *, planner: PlannerLLM) -> dict[str, Any]:
    attempts = state.get("plan_attempts", 0) + 1
    try:
        plan = planner.generate_plan(
            task=state["task"],
            dataset_id=state["dataset_id"],
            schema=state["schema"],
            profile=state["profile"],
            prior_plan=state.get("prior_plan"),
            rejected_plan=state.get("rejected_plan"),
            errors=state.get("validation_errors"),
        )
    except PlannerError as exc:
        return {
            "analysis_plan": None,
            "plan_attempts": attempts,
            "validation_errors": [str(exc)],
        }
    if isinstance(plan, dict):
        plan["dataset_id"] = state["dataset_id"]  # never trust the LLM with ids
    return {"analysis_plan": plan, "plan_attempts": attempts}


def execute_node(state: WorkerState, *, registry: DatasetRegistry = REGISTRY) -> dict[str, Any]:
    out = run_pipeline(state["dataset_id"], state["analysis_plan"], registry)
    update: dict[str, Any] = {"pipeline_output": out}
    if out["status"] == "error" and out.get("failed_step") in PLAN_REPAIR_STEPS:
        update["rejected_plan"] = state["analysis_plan"]
        update["validation_errors"] = [str(e) for e in out.get("errors", [])]
    return update


def chart_fallback(state: WorkerState) -> dict[str, Any]:
    """Chart recommendation/generation failed after a successful execution:
    keep the computed result and try one plain bar chart; else result-only."""
    out = state.get("pipeline_output") or {}
    table = (out.get("result") or {}).get("result_table") or []
    if table:
        cols = list(table[0].keys())
        numeric = [
            c
            for c in cols
            if isinstance(table[0][c], (int, float)) and not isinstance(table[0][c], bool)
        ]
        categorical = [c for c in cols if c not in numeric]
        if numeric:
            spec = {"type": "bar", "x": categorical[0] if categorical else numeric[0], "y": numeric[0]}
            built = charts.generate_chart(table, spec)
            if built["valid"]:
                return {
                    "fallback_chart": {
                        "chart_spec": spec,
                        "vega_lite_spec": built["vega_lite_spec"],
                        "warnings": built["warnings"],
                    }
                }
    return {"fallback_chart": None}


def finalize_worker(state: WorkerState) -> dict[str, Any]:
    out = state.get("pipeline_output")
    result: ChartResult = {
        "task": state["task"],
        "plan": state.get("analysis_plan"),
        "attempts": state.get("plan_attempts", 0),
    }
    if out is None:  # planner never produced a parseable plan
        result.update(
            {"status": "error", "result": None, "errors": state.get("validation_errors") or []}
        )
    elif out["status"] == "ok":
        result.update(
            {
                "status": "ok",
                "result": out["result"],
                "chart_spec": out["chart_spec"],
                "vega_lite_spec": out["vega_lite_spec"],
                "warnings": out.get("warnings", []),
                "errors": [],
            }
        )
    else:
        executed = out.get("result")  # partial results are never discarded
        fallback = state.get("fallback_chart")
        result.update(
            {
                "status": "partial" if executed is not None else "error",
                "result": executed,
                "errors": [f"{out.get('failed_step')}: {e}" for e in out.get("errors", [])],
            }
        )
        if fallback:
            result.update(
                {
                    "chart_spec": fallback["chart_spec"],
                    "vega_lite_spec": fallback["vega_lite_spec"],
                    "warnings": fallback["warnings"],
                }
            )
    return {"chart_results": [result]}
