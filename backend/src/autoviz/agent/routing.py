"""Conditional-edge routing: the failure policy lives here, not in the nodes."""

from langgraph.types import Send

from autoviz.agent.ambiguity import apply_resolutions
from autoviz.agent.nodes import CHART_FALLBACK_STEPS
from autoviz.agent.state import (
    MAX_CLARIFICATIONS,
    MAX_PLAN_ATTEMPTS,
    AutoVizState,
    WorkerState,
)
from autoviz.errors import PLAN_REPAIRABLE


def route_after_context(state: AutoVizState) -> str:
    return "record_failure" if state.get("status") == "failed" else "detect_ambiguity"


def route_after_detect(state: AutoVizState) -> str:
    """Ask about a detected ambiguity if the round budget allows; else plan."""
    pending = state.get("pending_ambiguities") or []
    if pending and state.get("clarification_count", 0) < MAX_CLARIFICATIONS:
        return "clarify"
    return "classify_intent"


def route_after_clarify(state: AutoVizState) -> str:
    """A deterministic answer re-detects (queue may shrink); an LLM answer re-classifies."""
    return "classify_intent" if state.get("clarify_source") == "llm" else "detect_ambiguity"


def route_after_classify(state: AutoVizState) -> str | list[Send]:
    wants_clarification = state.get("intent") == "clarification" or state.get("clarification")
    if wants_clarification and state.get("clarification_count", 0) < MAX_CLARIFICATIONS:
        return "clarify"
    tasks = state.get("tasks") or [state["user_request"]]
    resolved = state.get("resolved_slots") or {}
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
                # Bound clarification answers become explicit task constraints.
                "task": apply_resolutions(task, resolved),
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
    # The shared pipeline paused for large-row-removal confirmation; ask the user.
    if out["status"] == "confirmation_required":
        return "confirm_preprocessing"
    # Replan only for a genuinely plan-repairable failure — never for an
    # infrastructure fault (those were already retried in execute_node) or a
    # missing dataset, which no amount of replanning can fix.
    if out.get("error_code") in PLAN_REPAIRABLE and _can_replan(state):
        return "plan"
    if out.get("failed_step") in CHART_FALLBACK_STEPS:
        return "chart_fallback"
    return "finalize"
