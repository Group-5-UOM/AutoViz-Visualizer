"""Graph state and limits for the agentic workflow.

Only identifiers, metadata, plans, and (bounded) results enter state — never
DataFrames. Checkpoints are per-thread and in-memory, matching the in-memory
dataset registry.
"""

from typing import Annotated, Any, Literal, TypedDict

# Repairs allowed after the first plan generation (so <= 1 + MAX_PLAN_ATTEMPTS
# LLM plan calls per task).
MAX_PLAN_ATTEMPTS = 2
# Cap on parallel analysis tasks a single request may fan out into.
MAX_TASKS = 3
# Bounded clarification rounds per run (deterministic detectors + LLM combined);
# after this we proceed on best effort. Raised from 1 to allow resolving more than
# one distinct ambiguity (e.g. a time column AND an undefined metric).
MAX_CLARIFICATIONS = 2


class ChartResult(TypedDict, total=False):
    task: str
    status: Literal["ok", "partial", "error"]
    plan: dict[str, Any] | None
    attempts: int
    result: dict[str, Any] | None  # {result_table, row_count, execution_time_ms, provenance}
    chart_spec: dict[str, Any] | None
    vega_lite_spec: dict[str, Any] | None
    warnings: list[str]
    errors: list[str]


def add_or_reset(
    existing: list[ChartResult] | None, update: list[ChartResult] | None
) -> list[ChartResult]:
    """Accumulate parallel-worker results; a None update resets for a new run
    on the same thread (checkpointed state persists across invokes)."""
    if update is None:
        return []
    return (existing or []) + update


def append_history(
    existing: list[dict[str, Any]] | None, update: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    return (existing or []) + (update or [])


class AutoVizState(TypedDict, total=False):
    # Request
    user_request: str
    dataset_id: str
    # Context loaded from the registry
    schema: list[dict[str, str]]
    profile: dict[str, Any]
    # Routing
    intent: Literal["analysis", "refinement", "clarification"]
    tasks: list[str]
    clarification: dict[str, Any] | None
    clarification_answer: str | None
    clarification_count: int
    # Ambiguity resolution (Direction B): deterministic detectors queue ambiguities
    # here; each answered slot is bound into resolved_slots and applied to the tasks.
    pending_ambiguities: list[dict[str, Any]]
    resolved_slots: dict[str, Any]
    clarify_source: Literal["detector", "llm"] | None
    # Results (reducer: parallel workers append; None resets per run)
    chart_results: Annotated[list[ChartResult], add_or_reset]
    # Cross-run memory for refinements (accumulates over the thread)
    history: Annotated[list[dict[str, Any]], append_history]
    # Output
    status: Literal["running", "waiting_for_user", "completed", "failed"]
    errors: list[str]
    final_response: dict[str, Any] | None


class WorkerState(TypedDict, total=False):
    """State of one analysis worker (Send payload + loop bookkeeping)."""

    task: str
    dataset_id: str
    schema: list[dict[str, str]]
    profile: dict[str, Any]
    prior_plan: dict[str, Any] | None
    analysis_plan: dict[str, Any] | None
    rejected_plan: dict[str, Any] | None
    validation_errors: list[str]
    plan_attempts: int
    # Content hash of the preprocessing block the user approved (large row-removal
    # gate). Bound to the block, not a boolean, so a repaired plan re-gates.
    approved_preprocessing_hash: str | None
    pipeline_output: dict[str, Any] | None
    fallback_chart: dict[str, Any] | None
    chart_results: Annotated[list[ChartResult], add_or_reset]


class WorkerOutput(TypedDict):
    """Only chart_results flows back into the parent graph — worker internals
    (plans, errors, attempts) must not collide across parallel workers."""

    chart_results: Annotated[list[ChartResult], add_or_reset]
