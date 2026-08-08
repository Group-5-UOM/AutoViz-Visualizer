"""Graph state and limits for the agentic workflow.

Only identifiers, metadata, plans, and (bounded) results enter state — never
DataFrames. Checkpoints are per-thread and in-memory, matching the in-memory
dataset registry.
"""

from typing import Annotated, Any, Literal, TypedDict

# Repairs allowed after the first plan generation (so <= 1 + MAX_PLAN_ATTEMPTS
# LLM plan calls per task).
MAX_PLAN_ATTEMPTS = 2
# Cap on parallel analysis tasks a single request may fan out into. Each task is
# an independent worker, so this also caps concurrent planner calls (x1 +
# MAX_PLAN_ATTEMPTS) and concurrent pauses. Keep the classifier prompt's own
# limit (llm/client.py) in step, or the planner never emits this many.
MAX_TASKS = 6
# Bounded clarification rounds per run (deterministic detectors + LLM combined);
# after this we proceed on best effort. Raised from 1 to allow resolving more than
# one distinct ambiguity (e.g. a time column AND an undefined metric).
MAX_CLARIFICATIONS = 2
# Bounded preprocessing-confirmation rounds per worker. Every other loop in the
# graph carries a budget; this one terminates today only because both answers
# happen to defuse the gate ("proceed" approves the hash, "skip" strips the ops).
# That is a property of the current two ops, not a guarantee — a future op whose
# approved hash does not match exactly would spin here forever.
MAX_CONFIRMATIONS = 2
# Bounded cleaning questions per worker. Every proposal is a real decision the user
# should make, but a dirty wide dataset could produce a dozen — and an interrogation
# is its own kind of unusable. Past the budget the remaining issues are left
# untouched (the safe default: no value is changed without an answer).
MAX_CLEANING_PROMPTS = 2


class ChartResult(TypedDict, total=False):
    task: str
    # Stable identity for the chart this result represents, so a consumer can tell
    # "here is a new chart" from "here is that chart again, changed". A refinement
    # inherits the id of the chart it refined; anything else mints a fresh one.
    # Without it a host has no way to update a chart in place and must append.
    chart_id: str
    status: Literal["ok", "partial", "error"]
    plan: dict[str, Any] | None
    attempts: int
    result: dict[str, Any] | None  # {result_table, row_count, execution_time_ms, provenance}
    chart_spec: dict[str, Any] | None
    vega_lite_spec: dict[str, Any] | None
    warnings: list[str]
    # Cleaning disclosures for this chart, lifted out of provenance so the
    # composer sees them without digging. See services/notices.py.
    notices: list[dict[str, Any]]
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
    # A chart the caller pointed at explicitly ("edit this one"). Authoritative
    # where it is set: the alternative is inferring the target from history, which
    # can only ever mean "the most recent chart" and is wrong the moment a canvas
    # holds more than one. Unset for an ordinary request.
    target_chart_id: str | None
    # A chart type the caller chose from a list rather than described in prose.
    # Unlike a type merely mentioned in the request, this one is applied to the
    # plan deterministically wherever the data supports it. Unset for a plain
    # natural-language question.
    preferred_chart_type: str | None
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
    # Set only on a single-task refinement: the chart_id this worker's output
    # supersedes. finalize_worker inherits it instead of minting a new one.
    refines_chart_id: str | None
    # Inherited from the parent state: the caller's explicit chart-type pick.
    preferred_chart_type: str | None
    analysis_plan: dict[str, Any] | None
    rejected_plan: dict[str, Any] | None
    validation_errors: list[str]
    plan_attempts: int
    # Logical version of the preprocessing block the user approved (large
    # row-removal gate). Bound to the block *and* the dataset, not a boolean, so a
    # repaired block — or the same block on different data — re-gates.
    approved_preprocessing_hash: str | None
    # Confirmation rounds spent, against MAX_CONFIRMATIONS.
    confirmation_count: int
    # Automated cleaning (assess_quality): slot -> the op the user chose, or None
    # for "leave it alone". Answered slots are never re-asked, including across a
    # replan, so a repaired plan does not restart the questioning.
    cleaning_resolutions: dict[str, Any]
    cleaning_prompts: int
    # Set once the cleaning pass has nothing left to ask, so a replan loop does not
    # re-enter it forever.
    cleaning_done: bool
    # Safe repairs applied without asking — surfaced so the answer can say so.
    applied_cleaning: list[dict[str, Any]]
    # Disclosures about cleaning the node decided *not* to do: repairs the step
    # budget cut, questions the prompt cap cut. They have no preprocessing report
    # entry to ride on — nothing ran — so they travel here and are merged into the
    # ChartResult in finalize_worker.
    cleaning_notices: list[dict[str, Any]]
    pipeline_output: dict[str, Any] | None
    fallback_chart: dict[str, Any] | None
    chart_results: Annotated[list[ChartResult], add_or_reset]


class WorkerOutput(TypedDict):
    """Only chart_results flows back into the parent graph — worker internals
    (plans, errors, attempts) must not collide across parallel workers."""

    chart_results: Annotated[list[ChartResult], add_or_reset]
