"""Workflow nodes. Each does one thing; LLM nodes degrade gracefully.

Deterministic nodes call the shared services unchanged — run_pipeline() stays
the single source of truth for validate -> execute -> chart.
"""

import time
import uuid
from typing import Any

from langgraph.types import interrupt
from pydantic import ValidationError

from autoviz import observability
from autoviz.agent.ambiguity import detect_ambiguities
from autoviz.agent.state import (
    MAX_CLEANING_PROMPTS,
    MAX_TASKS,
    AutoVizState,
    ChartResult,
    WorkerState,
)
from autoviz.errors import PLAN_REPAIRABLE, RETRYABLE
from autoviz.llm.client import IntentDecision, PlannerError, PlannerLLM
from autoviz.schema.analysis_plan import AnalysisPlan
from autoviz.schema.clarification import Ambiguity, bind_answer
from autoviz.services import charts, dataset, fidelity, notices as notices_svc, quality
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
        # pause_kind lets an MCP host tell a clarification apart from a preprocessing
        # confirmation — both surface as status "waiting_for_user".
        answer = interrupt(  # pause; resumes here with the user's answer
            {**amb.to_wire(), "pause_kind": "clarification"}
        )
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
    answer = interrupt({**payload, "pause_kind": "clarification"})
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


def _normalize_note(text: str) -> str:
    """Fold the differences a re-typed sentence picks up but a reader ignores.

    Case, run-together whitespace, and the dash family — the composer rewrites an
    em dash as a hyphen often enough that an exact match is not a usable test of
    "has this already been said".
    """
    folded = text.casefold()
    for dash in ("—", "–", "−"):
        folded = folded.replace(dash, "-")
    return " ".join(folded.split())


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
    # Disclosures are owed regardless of who wrote the sentence. The composer is
    # asked to weave them in, but "the LLM was told to" is not a guarantee — and a
    # caveat that disappears because a model was terse or the call failed is the
    # one failure mode this channel exists to prevent. Appended only when the
    # answer does not already carry the wording, so the normal path stays clean.
    # Matched on a normalized form, not raw text. An exact substring test fails
    # the moment the composer reproduces a caveat with a hyphen where the notice
    # had an em dash, or across a line break — and the failure mode is the user
    # reading the same sentence twice, which reads like a bug in the analysis
    # rather than in the prose. The `seen` set covers the other source of a
    # double: two workers whose results carry the same disclosure.
    spoken = _normalize_note(answer)
    seen: set[str] = set()
    owed = []
    for r in results:
        for n in r.get("notices") or []:
            if n.get("severity") not in (notices_svc.DISCLOSED, notices_svc.ADVISORY):
                continue
            if not n.get("note"):
                continue
            key = _normalize_note(n["note"])
            if key in seen or key in spoken:
                continue
            seen.add(key)
            owed.append(n)
    if owed:
        answer = " ".join([answer, *(n["note"] for n in owed)]).strip()
    final = {"status": status, "answer": answer, "charts": results}
    # `charts` pairs each plan with the chart it produced, so the next refinement
    # can carry the identity forward as well as the plan. `plans` is kept in step
    # with it because routing still reads that key from older history entries —
    # threads outlive a deploy under the Postgres checkpointer.
    produced = [
        {"chart_id": r.get("chart_id"), "plan": r["plan"]} for r in results if r.get("plan")
    ]
    entry = {
        "request": state["user_request"],
        "plans": [c["plan"] for c in produced],
        "charts": produced,
    }
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


def assess_quality(
    state: WorkerState, *, registry: DatasetRegistry = REGISTRY
) -> dict[str, Any]:
    """Clean what is safe to clean; ask about anything that would change a number.

    This is the node a user who has never heard of imputation depends on. It runs
    between planning and execution, so the scan is scoped to the columns the plan
    actually reads — a messy column nobody asked about produces no findings and no
    interruption.

    One question per invocation, then routing sends us back for the next, matching
    how `clarify` handles ambiguities. Answered slots accumulate in state, so the
    queue shrinks toward empty and a slot is never asked twice.
    """
    record = registry.get(state["dataset_id"])
    plan = dict(state.get("analysis_plan") or {})
    if record is None or not plan:
        return {"cleaning_done": True}
    try:
        model = AnalysisPlan.model_validate(plan)
    except ValidationError:
        # Let the normal validation path report it — assessing an unparseable plan
        # would mean guessing which columns it meant.
        return {"cleaning_done": True}

    existing = list(plan.get("preprocessing") or [])
    scope = {c for c in model.referenced_columns() if c in record.schema}
    issues = quality.scan(record, scope)
    auto_ops, proposals = quality.recommend(
        issues, len(record.df), quality.plan_measure(model)
    )

    resolved: dict[str, Any] = dict(state.get("cleaning_resolutions") or {})
    # An explicit instruction in the plan already answers its slot.
    answered = set(resolved) | quality.suppressed_slots(existing)
    dimensions = quality.dimension_columns(model)
    pending = [
        p
        for p in proposals
        if p.slot not in answered and quality.is_worth_asking(p, dimensions)
    ]

    # Safe repairs first — they need no permission and must be in place before the
    # value-changing ops (a user's chosen op included) decide which rows survive.
    merged, dropped = quality.merge_auto_ops(existing, auto_ops)
    chosen = [op for op in resolved.values() if op]
    if chosen:
        merged = merged + chosen
    if merged != existing:
        plan["preprocessing"] = merged

    # Repairs the step budget had no room for. Owed on every exit from this node,
    # including the one that asks a question, because the budget was already
    # spent by the time we got here.
    owed = notices_svc.from_dropped_repairs(dropped)
    # Findings with no repair to offer — malformed emails and the like. They
    # produce no proposal, so without this they would be detected and then
    # silently discarded, which is worse than not looking.
    owed += notices_svc.from_quality_issues([i.to_wire() for i in issues])

    if not pending or state.get("cleaning_prompts", 0) >= MAX_CLEANING_PROMPTS:
        # Anything still pending here is a decision nobody will ever be asked
        # about: either the queue outran the prompt budget, or we are on the exit
        # path. It resolves to "leave it alone", which is the safe default and
        # still a choice made on the user's behalf.
        owed += notices_svc.from_unasked_proposals([p.question for p in pending])
        return {
            "analysis_plan": plan,
            "applied_cleaning": [op for op in auto_ops],
            "cleaning_notices": notices_svc.to_wire(owed),
            "cleaning_done": True,
        }

    proposal = pending[0]
    answer = interrupt(  # pause; resumes here with the user's choice
        {
            "question": proposal.question,
            # Structured, unlike a clarification's plain strings: each option
            # carries what it costs in real rows plus its technique, so a host can
            # preselect the recommendation and hide the jargon behind a disclosure.
            "options": [o.to_wire() for o in proposal.options],
            "pause_kind": "cleaning_choice",
            "slot": proposal.slot,
            "issue": proposal.issue.to_wire(),
        }
    )
    option = quality.bind_cleaning_answer(proposal, str(answer))
    observability.log_event(
        "cleaning_choice",
        slot=proposal.slot,
        kind=proposal.issue.kind,
        column=proposal.issue.column,
        affected=proposal.issue.affected,
        chose=option.technique,
        applied=option.op is not None,
        recommended=option.recommended,
    )
    return {
        "analysis_plan": plan,
        "cleaning_resolutions": {**resolved, proposal.slot: option.op},
        "cleaning_prompts": state.get("cleaning_prompts", 0) + 1,
        "applied_cleaning": [op for op in auto_ops],
        "cleaning_notices": notices_svc.to_wire(owed),
    }


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
            preferred_chart_type=state.get("preferred_chart_type"),
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
    # preprocessing_hash travels with the pause so a host can show what it is
    # approving; pause_kind distinguishes this from a clarification question.
    answer = interrupt(
        {
            "question": conf.get("question"),
            "options": conf.get("options", []),
            "pause_kind": "confirmation",
            "preprocessing_hash": conf.get("preprocessing_hash"),
            "impact": conf.get("impact"),
        }
    )
    norm = str(answer).strip().casefold()
    proceed = "proceed" in norm or norm in ("y", "yes", "ok", "confirm")

    observability.log_event(
        "preprocessing_confirmation",
        proceed=proceed,
        dropped=(conf.get("impact") or {}).get("dropped"),
        input_rows=(conf.get("impact") or {}).get("input_rows"),
    )

    spent = state.get("confirmation_count", 0) + 1
    if proceed:
        return {
            "approved_preprocessing_hash": conf.get("preprocessing_hash"),
            "confirmation_count": spent,
        }

    # Skip: strip only the row-dropping ops, keep fill_nulls (R3). The trimmed plan
    # has no row-dropping preprocessing, so it will not gate again.
    #
    # Which ops those are is read off the models, not matched against a name list:
    # a row-dropping op missing from a hardcoded tuple here would survive the very
    # "Skip cleaning" the user just chose, and still drop their rows.
    plan = dict(state["analysis_plan"] or {})
    try:
        model = AnalysisPlan.model_validate(plan)
    except ValidationError:
        # Unreachable in the normal flow — the plan validated before the gate could
        # fire. Fail closed: an unparseable plan gets no preprocessing at all rather
        # than keeping steps we cannot classify.
        plan["preprocessing"] = []
        return {
            "analysis_plan": plan,
            "approved_preprocessing_hash": None,
            "confirmation_count": spent,
        }
    plan["preprocessing"] = [
        op.model_dump(by_alias=True) for op in model.preprocessing if not op.removes_rows
    ]
    return {
        "analysis_plan": plan,
        "approved_preprocessing_hash": None,
        "confirmation_count": spent,
    }


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
                        "notices": built.get("notices", []),
                    }
                }
    return {"fallback_chart": None}


def _notices_of(executed: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Disclosures from an execution result, if it got far enough to have any.

    Lifted to the top level of the ChartResult because the composer's condensed
    payload does not carry provenance — a disclosure left buried in there is a
    disclosure the user never hears.
    """
    return ((executed or {}).get("provenance") or {}).get("notices") or []


def finalize_worker(state: WorkerState) -> dict[str, Any]:
    out = state.get("pipeline_output")
    # Disclosures about cleaning that did *not* happen. They belong to the run
    # whatever became of it — a plan that failed at the chart step still skipped
    # those repairs — so they are attached on every branch below rather than only
    # the successful one.
    skipped = list(state.get("cleaning_notices") or [])
    result: ChartResult = {
        "task": state["task"],
        # A refinement is the same chart, changed — so it keeps its id and the
        # host replaces what it already has. Everything else is a new chart.
        "chart_id": state.get("refines_chart_id") or f"ch_{uuid.uuid4().hex[:12]}",
        "plan": state.get("analysis_plan"),
        "attempts": state.get("plan_attempts", 0),
    }
    if out is None:  # planner never produced a parseable plan
        result.update(
            {
                "status": "error",
                "result": None,
                "notices": skipped,
                "errors": state.get("validation_errors") or [],
            }
        )
    elif out["status"] == "ok":
        chart_notices = [*skipped, *(out.get("notices") or _notices_of(out.get("result")))]
        # Anything the request named and the run did not deliver. A refusal the
        # chart grammar forced, a substituted chart type, an ordering that never
        # happened — all of them otherwise come back as a finished chart with
        # nothing to distinguish "considered and declined" from "dropped".
        chart_notices.extend(
            n.to_wire()
            for n in fidelity.unmet_requests(
                state.get("task") or "",
                fidelity.ChartOutcome(
                    chart_type=(out.get("chart_spec") or {}).get("type", ""),
                    vega_lite_spec=out.get("vega_lite_spec") or {},
                    plan=state.get("analysis_plan") or {},
                ),
            )
        )
        result.update(
            {
                "status": "ok",
                "result": out["result"],
                "chart_spec": out["chart_spec"],
                "vega_lite_spec": out["vega_lite_spec"],
                "warnings": out.get("warnings", []),
                # The pipeline merges cleaning and chart disclosures; fall back to
                # the execution half for callers that never ran the chart step.
                "notices": chart_notices,
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
                # A run that failed at the chart step still cleaned data and still
                # returned numbers, so the disclosure is owed either way.
                "notices": [*skipped, *_notices_of(executed)],
                "errors": [f"{out.get('failed_step')}: {e}" for e in out.get("errors", [])],
            }
        )
        if fallback:
            result.update(
                {
                    "chart_spec": fallback["chart_spec"],
                    "vega_lite_spec": fallback["vega_lite_spec"],
                    "warnings": fallback["warnings"],
                    # The substitute chart is still a chart, and can still be the
                    # one whose axis needs explaining.
                    "notices": [*result["notices"], *fallback.get("notices", [])],
                }
            )
    return {"chart_results": [result]}
