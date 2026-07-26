"""Workflow nodes. Each does one thing; LLM nodes degrade gracefully.

Deterministic nodes call the shared services unchanged — run_pipeline() stays
the single source of truth for validate -> execute -> chart.
"""

import time
from typing import Any

from langgraph.types import interrupt

from autoviz import observability
from autoviz.agent.ambiguity import detect_ambiguities
from autoviz.agent.state import (
    MAX_TASKS,
    AutoVizState,
    ChartResult,
    WorkerState,
)
from autoviz.errors import PLAN_REPAIRABLE, RETRYABLE
from autoviz.llm.client import IntentDecision, PlannerError, PlannerLLM
from autoviz.schema.clarification import Ambiguity, bind_answer
from autoviz.services import charts, dataset
from autoviz.services.orchestrator import run_pipeline
from autoviz.services.registry import REGISTRY, DatasetRegistry

# failed_step values after a successful execution -> deterministic chart fallback.
CHART_FALLBACK_STEPS = {"recommend_chart_type", "generate_chart"}

# Bounded retry for infrastructure faults (EXECUTION_ERROR / TIMEOUT). The plan
# is already validated, so replanning would be wrong; a short backoff instead.
MAX_EXEC_RETRIES = 1
EXEC_RETRY_BACKOFF_S = 0.25


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


def detect_ambiguity(state: AutoVizState) -> dict[str, Any]:
    """Deterministic pre-check: queue the request's ambiguities (minus resolved ones).

    Runs before the planner LLM so 'should we ask?' is a computed signal, not a
    prompt guess. Re-runs after each answer (via the clarify loop) so answered
    slots drop out and the queue shrinks toward empty.
    """
    ambs = detect_ambiguities(
        state["user_request"],
        state.get("schema") or [],
        state.get("profile") or {},
        resolved=state.get("resolved_slots") or {},
    )
    return {"pending_ambiguities": [a.model_dump() for a in ambs]}


def clarify(state: AutoVizState) -> dict[str, Any]:
    """Ask one clarifying question and bind the answer.

    Prefers a deterministic ambiguity (grounded options, answer bound to its slot);
    falls back to an LLM-authored clarification when the detectors found nothing.
    """
    pending = state.get("pending_ambiguities") or []
    if pending:
        amb = Ambiguity.model_validate(pending[0])
        answer = interrupt(amb.to_wire())  # pause; resumes here with the user's answer
        resolution = bind_answer(amb, str(answer))
        observability.log_event(
            "clarification", source="detector", amb_type=amb.type, slot=amb.slot,
            n_options=len(amb.options), resolution=resolution.source,
            round=state.get("clarification_count", 0) + 1,
        )
        return {
            "resolved_slots": {**(state.get("resolved_slots") or {}), resolution.slot: resolution.value},
            "clarification_count": state.get("clarification_count", 0) + 1,
            "clarify_source": "detector",
            "clarification_answer": str(answer),
        }

    # LLM-authored clarification (detectors found nothing structural).
    payload = state.get("clarification") or {"question": "Could you clarify your request?", "options": []}
    answer = interrupt(payload)
    observability.log_event(
        "clarification", source="llm", n_options=len(payload.get("options", [])),
        round=state.get("clarification_count", 0) + 1,
    )
    return {
        "clarification_answer": str(answer),
        "clarification_count": state.get("clarification_count", 0) + 1,
        "clarify_source": "llm",
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
    # Retry transient infrastructure faults in place with backoff; only a
    # plan-repairable code sends us back to the planner (handled in routing).
    attempts = 0
    while True:
        out = run_pipeline(
            state["dataset_id"],
            state["analysis_plan"],
            registry,
            approved_preprocessing_hash=state.get("approved_preprocessing_hash"),
        )
        if (
            out["status"] == "ok"
            or out.get("error_code") not in RETRYABLE
            or attempts >= MAX_EXEC_RETRIES
        ):
            break
        attempts += 1
        time.sleep(EXEC_RETRY_BACKOFF_S * attempts)

    update: dict[str, Any] = {"pipeline_output": out}
    if out["status"] == "error" and out.get("error_code") in PLAN_REPAIRABLE:
        update["rejected_plan"] = state["analysis_plan"]
        update["validation_errors"] = [str(e) for e in out.get("errors", [])]
    return update


def confirm_preprocessing(state: WorkerState) -> dict[str, Any]:
    """Present the shared pipeline's large-row-removal gate and bind the answer.

    run_pipeline (the single enforcer) returned status "confirmation_required". We
    surface its question, then deterministically map the answer: "proceed" approves
    this exact preprocessing block (by hash) and re-executes; anything else skips the
    row-dropping steps (keeping any fill_nulls) and runs on the full data.
    """
    out = state.get("pipeline_output") or {}
    conf = out.get("confirmation") or {}
    answer = interrupt({"question": conf.get("question"), "options": conf.get("options", [])})
    norm = str(answer).strip().casefold()
    proceed = "proceed" in norm or norm in ("y", "yes", "ok", "confirm")

    observability.log_event(
        "preprocessing_confirmation",
        proceed=proceed,
        dropped=(conf.get("impact") or {}).get("dropped"),
        input_rows=(conf.get("impact") or {}).get("input_rows"),
    )

    if proceed:
        return {"approved_preprocessing_hash": conf.get("preprocessing_hash")}

    # Skip: strip only the row-dropping ops, keep fill_nulls (R3). The trimmed plan
    # has no row-dropping preprocessing, so it will not gate again.
    plan = dict(state["analysis_plan"] or {})
    plan["preprocessing"] = [
        op
        for op in plan.get("preprocessing", [])
        if op.get("op") not in ("drop_nulls", "drop_exact_duplicates")
    ]
    return {"analysis_plan": plan, "approved_preprocessing_hash": None}


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
