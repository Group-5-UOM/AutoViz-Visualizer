"""Conditional-edge routing: the failure policy lives here, not in the nodes."""

from langgraph.types import Send

from autoviz.agent.ambiguity import apply_resolutions
from autoviz.agent.nodes import CHART_FALLBACK_STEPS
from autoviz.agent.state import (
    MAX_CLARIFICATIONS,
    MAX_CLEANING_PROMPTS,
    MAX_CONFIRMATIONS,
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
    """Every answer goes back through detection, whoever asked the question.

    Both layers now write to the same queue, so both answers deserve the same
    treatment: re-detect against the resolved slots (the queue shrinks, and a
    second distinct ambiguity can surface), then classify with the answer in
    hand. Routing an LLM answer straight to the classifier used to skip the
    detectors entirely on the second round.
    """
    return "detect_ambiguity"


def _chart_in_history(history: list[dict], chart_id: str) -> dict | None:
    """The record of one specific chart, wherever in the thread it was produced.

    Searched across every entry rather than only the newest, because a chart the
    user pointed at may be several requests old — that is the whole reason for
    pointing at it.
    """
    for entry in reversed(history or []):
        for chart in entry.get("charts") or []:
            if chart.get("chart_id") == chart_id:
                return chart
    return None


def _most_recent_chart(history: list[dict]) -> tuple[dict | None, dict | None]:
    """The last plan of the last run, and the chart it produced.

    The fallback when nothing was pointed at: "a refinement refines the chart you
    just saw" is the only guess available, and it is right for the common case of
    one chart on the canvas.
    """
    for entry in reversed(history or []):
        if entry.get("plans"):
            # Entries written before `charts` existed carry plans only; those
            # threads keep the old append-only behaviour rather than breaking.
            last = (entry.get("charts") or [{}])[-1]
            return entry["plans"][-1], last
    return None, None


def route_after_classify(state: AutoVizState) -> str | list[Send]:
    # An ambiguity the classifier proposed only counts once it has survived
    # grounding. "The model said clarification" is not on its own a reason to
    # stop: without an answerable, grounded question there is nothing to ask.
    if state.get("pending_ambiguities") and (
        state.get("clarification_count", 0) < MAX_CLARIFICATIONS
    ):
        return "clarify"
    tasks = state.get("tasks") or [state["user_request"]]
    resolved = state.get("resolved_slots") or {}
    prior_plan = None
    refines_chart_id = None

    target = state.get("target_chart_id")
    targeted = _chart_in_history(state.get("history", []), target) if target else None
    if targeted is not None:
        # Pointing at a chart *is* the statement of intent, so the classifier's
        # reading does not get a vote here. It is also the only way the planner
        # is grounded in the right plan: the fallback below can only reach the
        # newest one, which is the wrong chart whenever the canvas has several.
        prior_plan = targeted.get("plan")
        if len(tasks) == 1:
            refines_chart_id = target
    elif state.get("intent") == "refinement":
        # No target, or one this thread has never heard of — a chart from a
        # dashboard reopened without its conversation. Guess, or append.
        prior_plan, last = _most_recent_chart(state.get("history", []))
        # Only a single-task refinement has one thing to replace. Fanning out to
        # several charts from "make it a line chart" means the planner read it as
        # new analysis, so nothing is superseded.
        if len(tasks) == 1 and last:
            refines_chart_id = last.get("chart_id")

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
                "refines_chart_id": refines_chart_id,
                # Every worker gets the pick: the fan-out splits one request into
                # sub-tasks, and the type the user chose applies to all of them.
                "preferred_chart_type": state.get("preferred_chart_type"),
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
    # A replan has already been through the cleaning pass; its answers are kept in
    # state, so going round again would only re-apply them.
    if state.get("cleaning_done"):
        return "execute"
    return "assess_quality"


def route_after_assess(state: WorkerState) -> str:
    """Keep asking while there are unanswered cleaning questions and budget left.

    `assess_quality` sets `cleaning_done` when it has nothing more to ask; until
    then each pass resolves one slot, exactly like the clarification loop.
    """
    if state.get("cleaning_done"):
        return "execute"
    if state.get("cleaning_prompts", 0) >= MAX_CLEANING_PROMPTS:
        return "execute"
    return "assess_quality"


def route_after_execute(state: WorkerState) -> str:
    out = state["pipeline_output"]
    if out["status"] == "ok":
        return "finalize"
    # Execution refused to run an unapproved large row removal; ask the user.
    # Budgeted like every other loop in the graph: if the answer somehow fails to
    # clear the gate, finalize with the refusal rather than re-prompting forever.
    if out["status"] == "confirmation_required":
        if state.get("confirmation_count", 0) < MAX_CONFIRMATIONS:
            return "confirm_preprocessing"
        return "finalize"
    # Replan only for a genuinely plan-repairable failure — never for an
    # infrastructure fault (those were already retried in execute_node) or a
    # missing dataset, which no amount of replanning can fix.
    if out.get("error_code") in PLAN_REPAIRABLE and _can_replan(state):
        return "plan"
    if out.get("failed_step") in CHART_FALLBACK_STEPS:
        return "chart_fallback"
    return "finalize"
