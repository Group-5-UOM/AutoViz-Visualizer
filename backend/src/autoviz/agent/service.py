"""AgentService: the sync facade over the compiled graph.

Used by the MCP `analyze` / `answer_clarification` tools and by the Week-3
FastAPI routes. Same discipline as every service: structured results, never
exceptions. thread_id gives conversation continuity (refinements) and carries
paused clarification runs.

Parallel workers can pause in the same superstep, so a pause is presented as a
*decision* rather than as one worker's interrupt: identical questions raised by
N workers are grouped behind one token, and distinct questions queue up one at a
time. See `_group_key` for what makes two pauses the same decision.
"""

import hashlib
import uuid
from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command

from autoviz.agent.graph import build_graph
from autoviz.llm.client import PlannerLLM
from autoviz.services import dataset as dataset_service
from autoviz.services.registry import REGISTRY, DatasetRegistry


@dataclass(frozen=True)
class _Group:
    """One decision the user has to make, and every interrupt asking for it."""

    token: str  # opaque, client-facing; survives LangGraph id churn
    payload: dict[str, Any]  # representative interrupt value (all members match)
    ids: tuple[str, ...]  # LangGraph Interrupt.id of every member


def _payload_of(intr: Any) -> dict[str, Any]:
    value = getattr(intr, "value", intr)
    if isinstance(value, dict):
        return value
    return {"question": str(value), "options": []}


def _group_key(payload: dict[str, Any]) -> str:
    """Token identifying the decision this pause represents.

    Two fanned-out workers gating on the same column are asking the same
    question, and the same answer is correct for both — asking twice would be a
    bug, not thoroughness. What makes them "the same" differs by pause kind:

    - confirmation:    preprocessing_hash. It hashes {dataset_id, preprocessing}
                       and the impact is a pure function of those, so an equal
                       hash means byte-identical question AND answer semantics.
    - cleaning_choice: slot. Proposals are per-(dataset, column); the plan only
                       decides *whether* a proposal surfaces, not what it says.
    - clarification:   question text. This node runs in the parent graph before
                       the fan-out, so it is structurally never concurrent.

    Synthetic rather than a raw Interrupt.id because a group has N ids, and ids
    re-hash across checkpoints — a token the client echoes back must survive
    that, and must not leak LangGraph internals into the browser.
    """
    kind = payload.get("pause_kind") or "clarification"
    if kind == "confirmation":
        seed = payload.get("preprocessing_hash") or payload.get("question") or ""
    elif kind == "cleaning_choice":
        seed = payload.get("slot") or payload.get("question") or ""
    else:
        seed = payload.get("question") or ""
    return hashlib.sha256(f"{kind}|{seed}".encode()).hexdigest()[:16]


def _group_interrupts(live: list[tuple[str, dict[str, Any]]]) -> list[_Group]:
    """Collapse concurrent interrupts into decisions, in first-seen (Send) order."""
    order: list[str] = []
    seen: dict[str, tuple[dict[str, Any], list[str]]] = {}
    for interrupt_id, payload in live:
        key = _group_key(payload)
        if key not in seen:
            seen[key] = (payload, [])
            order.append(key)
        seen[key][1].append(interrupt_id)
    return [_Group(key, seen[key][0], tuple(seen[key][1])) for key in order]


def _live_from_state(state: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Pending interrupts as returned by invoke() — already live-only."""
    return [(getattr(i, "id", ""), _payload_of(i)) for i in (state.get("__interrupt__") or ())]


def _live_from_snapshot(snapshot: Any) -> list[tuple[str, dict[str, Any]]]:
    """Pending interrupts from a checkpoint, filtered to the ones still live.

    `snapshot.interrupts` cannot be used directly: LangGraph never deletes a
    task's INTERRUPT pending write when that task later succeeds, and the
    snapshot rebuilds its list from those writes — so an answered interrupt
    keeps showing up there forever. A task carries a result only once it has
    written one, which makes `result is None` exactly "still paused".
    """
    return [
        (i.id, _payload_of(i))
        for task in snapshot.tasks
        if task.result is None
        for i in task.interrupts
    ]


def _shape_pending(
    groups: list[_Group], thread_id: str, *, stale_answer: bool = False
) -> dict[str, Any]:
    """Present the head decision. The rest stay paused and follow one by one."""
    head = groups[0]
    payload = head.payload
    shaped: dict[str, Any] = {
        "status": "waiting_for_user",
        "question": payload.get("question"),
        "options": payload.get("options", []),
        # Three different decisions pause here (clarification, cleaning choice,
        # row-removal confirmation); without this a caller cannot tell which one
        # it is making.
        "pause_kind": payload.get("pause_kind", "clarification"),
        "thread_id": thread_id,
        # Pass back with the answer so it reaches the workers that asked this
        # question — and only them.
        "interrupt_id": head.token,
        # Distinct decisions still queued, this one included.
        "pending_count": len(groups),
    }
    # confirmation extras (what is being approved) and cleaning_choice extras
    # (which finding is being decided, so a host can show the counts alongside
    # the options rather than just a question).
    for key in ("preprocessing_hash", "impact", "slot", "issue"):
        if payload.get(key) is not None:
            shaped[key] = payload[key]
    if stale_answer:
        shaped["stale_answer"] = True
    return shaped


class AgentService:
    def __init__(
        self,
        planner: PlannerLLM | None = None,
        registry: DatasetRegistry = REGISTRY,
        checkpointer: BaseCheckpointSaver | None = None,
    ):
        self._registry = registry
        # checkpointer=None -> build_graph defaults to InMemorySaver (unchanged
        # behaviour). Pass a PostgresSaver for durable, cross-restart threads.
        self._graph = build_graph(planner=planner, registry=registry, checkpointer=checkpointer)

    def run(
        self,
        request: str,
        dataset_id: str | None = None,
        file_ref: str | None = None,
        thread_id: str | None = None,
        chart_id: str | None = None,
    ) -> dict[str, Any]:
        """Run one request. ``chart_id`` names a chart from an earlier turn on
        this thread that the request is about ("make *this one* a line chart"),
        so the answer modifies that chart instead of the most recent one."""
        if dataset_id is None and file_ref is not None:
            registered = dataset_service.register_dataset(file_ref, self._registry)
            if "error" in registered:
                return {
                    "status": "failed",
                    "errors": [registered["error"]] + ([registered["hint"]] if "hint" in registered else []),
                }
            dataset_id = registered["dataset_id"]
        if dataset_id is None:
            return {"status": "failed", "errors": ["Provide a dataset_id or a file_ref."]}

        thread_id = thread_id or f"th_{uuid.uuid4().hex[:12]}"
        config = {"configurable": {"thread_id": thread_id}}
        payload = {
            "user_request": request,
            "dataset_id": dataset_id,
            # Reset per-run keys that persist in the thread checkpoint. A target
            # is emphatically one of them: carrying last turn's chart into an
            # unrelated question would silently overwrite it.
            "target_chart_id": chart_id,
            "chart_results": None,
            "clarification_answer": None,
            "clarification_count": 0,
            "clarification": None,
            "pending_ambiguities": [],
            "resolved_slots": {},
            "clarify_source": None,
            "errors": [],
            "final_response": None,
            "status": "running",
        }
        try:
            state = self._graph.invoke(payload, config)
        except Exception as exc:
            return {"status": "failed", "errors": [f"agent error: {exc}"], "thread_id": thread_id}
        return self._shape(state, thread_id)

    def resume(
        self, thread_id: str, answer: str, interrupt_id: str | None = None
    ) -> dict[str, Any]:
        """Answer one paused decision. Omit interrupt_id to answer the head one."""
        config = {"configurable": {"thread_id": thread_id}}
        try:
            snapshot = self._graph.get_state(config)
            groups = _group_interrupts(_live_from_snapshot(snapshot))
            if not groups:
                return {
                    "status": "failed",
                    "errors": [f"No paused run to resume for thread_id '{thread_id}'."],
                    "thread_id": thread_id,
                }
            if interrupt_id is None:
                target = groups[0]
            else:
                target = next(
                    (g for g in groups if g.token == interrupt_id), None
                ) or next(  # defensive: a host that read a raw Interrupt.id elsewhere
                    (g for g in groups if interrupt_id in g.ids), None
                )
                if target is None:
                    # The answer is for a question nobody is asking any more.
                    # Applying it to whatever is pending instead could approve a
                    # row-removal the user never saw, and passing the unknown id
                    # to LangGraph is a silent no-op that would loop the client
                    # on the same question. Re-ask what is actually pending.
                    return _shape_pending(groups, thread_id, stale_answer=True)
            # Always a map, never a bare value. Once any resume-map has been used
            # on this thread the answered tasks' INTERRUPT writes are left
            # hanging, so LangGraph's "multiple pending interrupts" guard trips
            # on a bare resume even when exactly one interrupt is really live.
            state = self._graph.invoke(
                Command(resume={i: answer for i in target.ids}), config
            )
        except Exception as exc:
            return {"status": "failed", "errors": [f"agent error: {exc}"], "thread_id": thread_id}
        return self._shape(state, thread_id)

    def _shape(self, state: dict[str, Any], thread_id: str) -> dict[str, Any]:
        groups = _group_interrupts(_live_from_state(state))
        if groups:
            return _shape_pending(groups, thread_id)
        final = state.get("final_response") or {
            "status": state.get("status", "failed"),
            "errors": state.get("errors", []),
        }
        return {**final, "thread_id": thread_id}
