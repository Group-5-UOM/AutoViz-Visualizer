"""AgentService: the sync facade over the compiled graph.

Used by the MCP `analyze` / `answer_clarification` tools and by the Week-3
FastAPI routes. Same discipline as every service: structured results, never
exceptions. thread_id gives conversation continuity (refinements) and carries
paused clarification runs.
"""

import uuid
from typing import Any

from langgraph.types import Command

from autoviz.agent.graph import build_graph
from autoviz.llm.client import PlannerLLM
from autoviz.services import dataset as dataset_service
from autoviz.services.registry import REGISTRY, DatasetRegistry


def _interrupt_payload(state: dict[str, Any]) -> dict[str, Any] | None:
    interrupts = state.get("__interrupt__") or ()
    for intr in interrupts:
        value = getattr(intr, "value", intr)
        if isinstance(value, dict):
            return value
        return {"question": str(value), "options": []}
    return None


class AgentService:
    def __init__(
        self,
        planner: PlannerLLM | None = None,
        registry: DatasetRegistry = REGISTRY,
    ):
        self._registry = registry
        self._graph = build_graph(planner=planner, registry=registry)

    def run(
        self,
        request: str,
        dataset_id: str | None = None,
        file_ref: str | None = None,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
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
            # Reset per-run keys that persist in the thread checkpoint.
            "chart_results": None,
            "clarification_answer": None,
            "clarification_count": 0,
            "clarification": None,
            "errors": [],
            "final_response": None,
            "status": "running",
        }
        try:
            state = self._graph.invoke(payload, config)
        except Exception as exc:
            return {"status": "failed", "errors": [f"agent error: {exc}"], "thread_id": thread_id}
        return self._shape(state, thread_id)

    def resume(self, thread_id: str, answer: str) -> dict[str, Any]:
        config = {"configurable": {"thread_id": thread_id}}
        try:
            snapshot = self._graph.get_state(config)
            if not snapshot.next:
                return {
                    "status": "failed",
                    "errors": [f"No paused run to resume for thread_id '{thread_id}'."],
                    "thread_id": thread_id,
                }
            state = self._graph.invoke(Command(resume=answer), config)
        except Exception as exc:
            return {"status": "failed", "errors": [f"agent error: {exc}"], "thread_id": thread_id}
        return self._shape(state, thread_id)

    def _shape(self, state: dict[str, Any], thread_id: str) -> dict[str, Any]:
        pending = _interrupt_payload(state)
        if pending is not None:
            return {
                "status": "waiting_for_user",
                "question": pending.get("question"),
                "options": pending.get("options", []),
                "thread_id": thread_id,
            }
        final = state.get("final_response") or {
            "status": state.get("status", "failed"),
            "errors": state.get("errors", []),
        }
        return {**final, "thread_id": thread_id}
