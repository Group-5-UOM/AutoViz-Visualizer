"""Conditional-edge routing: the failure policy lives here, not in the nodes."""

from langgraph.types import Send

from autoviz.agent.nodes import CHART_FALLBACK_STEPS, PLAN_REPAIR_STEPS
from autoviz.agent.state import (
    MAX_CLARIFICATIONS,
    MAX_PLAN_ATTEMPTS,
    AutoVizState,
    WorkerState,
)


def route_after_context(state: AutoVizState) -> str:
    return "record_failure" if state.get("status") == "failed" else "classify_intent"


def route_after_classify(state: AutoVizState) -> str | list[Send]:
    wants_clarification = state.get("intent") == "clarification" or state.get("clarification")
    if wants_clarification and state.get("clarification_count", 0) < MAX_CLARIFICATIONS:
        return "clarify"
    tasks = state.get("tasks") or [state["user_request"]]
    prior_plan = None
    if state.get("intent") == "refinement":
        for entry in reversed(state.get("history", [])):
            if entry.get("plans"):
                prior_plan = entry["plans"][-1]
                break
    return [
        Send(
            "analysis_worker",
            {
                "task": task,
                "dataset_id": state["dataset_id"],
                "schema": state["schema"],
                "profile": state["profile"],
                "prior_plan": prior_plan,
                "plan_attempts": 0,
            },
        )
        for task in tasks
    ]


def _can_replan(state: WorkerState) -> bool:
    return state.get("plan_attempts", 0) < 1 + MAX_PLAN_ATTEMPTS


def route_after_plan(state: WorkerState) -> str:
    if state.get("analysis_plan") is None:  # planner output unusable
        return "plan" if _can_replan(state) else "finalize"
    return "execute"


def route_after_execute(state: WorkerState) -> str:
    out = state["pipeline_output"]
    if out["status"] == "ok":
        return "finalize"
    step = out.get("failed_step")
    if step in PLAN_REPAIR_STEPS and _can_replan(state):
        return "plan"
    if step in CHART_FALLBACK_STEPS:
        return "chart_fallback"
    return "finalize"
