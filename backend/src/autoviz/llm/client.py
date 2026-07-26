"""Planner LLM client for the internal agentic workflow.

The graph never talks to a provider directly — it talks to the PlannerLLM
protocol, so tests inject a scripted fake and the provider stays swappable via
AUTOVIZ_PLANNER_MODEL (any init_chat_model id, default Google Gemini).

The planner only *plans*: it emits IntentDecision / analysis_plan JSON that the
deterministic services validate and execute. All outputs are parsed here and
failures surface as PlannerError, never as provider exceptions.
"""

import json
import os
import re
from pathlib import Path
from typing import Any, Literal, Protocol

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from autoviz.schema.plan_guide import PLAN_GUIDE

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

DEFAULT_MODEL = "google_genai:gemini-3.5-flash"

_FENCE = re.compile(r"^```[a-zA-Z]*\n|\n?```$")


class Clarification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    options: list[str] = Field(default_factory=list)


class IntentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Literal["analysis", "refinement", "clarification"]
    tasks: list[str] = Field(default_factory=list)
    clarification: Clarification | None = None


class PlannerError(Exception):
    """The planner LLM failed to produce usable output."""


class PlannerLLM(Protocol):
    def classify(
        self,
        request: str,
        schema: list[dict[str, str]],
        profile: dict[str, Any],
        history: list[dict[str, Any]],
        clarification_answer: str | None = None,
    ) -> IntentDecision: ...

    def generate_plan(
        self,
        task: str,
        dataset_id: str,
        schema: list[dict[str, str]],
        profile: dict[str, Any],
        prior_plan: dict[str, Any] | None = None,
        rejected_plan: dict[str, Any] | None = None,
        errors: list[str] | None = None,
    ) -> dict[str, Any]: ...

    def compose(self, request: str, results: list[dict[str, Any]]) -> str: ...


def _strip_fences(text: str) -> str:
    return _FENCE.sub("", text.strip()).strip()


def _json_object(text: str) -> dict[str, Any]:
    """Extract the outermost JSON object from LLM text output."""
    cleaned = _strip_fences(text)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise PlannerError(f"planner returned no JSON object: {cleaned[:200]!r}")
    try:
        parsed = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise PlannerError(f"planner returned invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise PlannerError("planner returned JSON that is not an object")
    return parsed


_CLASSIFY_SYSTEM = """You route requests for AutoViz, a tool that answers data questions with
validated charts computed from a registered CSV dataset.

Given the user's request, the dataset schema/profile, and the conversation history, output ONLY
a JSON object:
{"intent": "analysis" | "refinement" | "clarification",
 "tasks": ["one self-contained analysis request", ...],
 "clarification": {"question": "...", "options": ["...", ...]} | null}

Rules:
- Split multi-part requests into at most 3 independent tasks, each answerable with one chart.
  Rewrite each task so it stands alone (carry shared filters/context into every task).
- "refinement" only when the request modifies a previous chart from the history (e.g. "make it
  a line chart", "same but only 2015"); still emit the full rewritten task(s).
- "clarification" ONLY when the request is materially ambiguous against this schema (e.g. two
  plausible date columns, an undefined metric like "best"). Then set clarification and leave
  tasks empty. If a clarification answer is provided in the input, do NOT ask again.
- Column references in tasks must use real column names from the schema."""


_PLAN_SYSTEM = (
    """You translate ONE analysis task into an AutoViz analysis_plan. Output ONLY the JSON
object for the plan — no prose, no code fences.

"""
    + PLAN_GUIDE
    + """
Additional rules:
- Use the exact dataset_id you are given.
- Only reference columns from the provided schema (types matter — check them).
- Omit "chart" unless the task asks for a specific chart type.
- If a rejected plan and validation errors are provided, return a corrected version of THAT
  plan: change only what the errors require."""
)


_COMPOSE_SYSTEM = """You summarize AutoViz analysis results for the user in 2-5 sentences.
Ground every number strictly in the provided result tables — never estimate, extrapolate, or
invent values. Mention each chart produced (its type and what it shows). If a task failed,
say so plainly and include the reason. Plain text only."""


class GeminiPlanner:
    """PlannerLLM backed by init_chat_model (default: Google Gemini free tier).

    The chat model is created lazily so importing the server never requires an
    API key — only actually calling the agent does.
    """

    def __init__(self, model: str | None = None):
        self._model_id = model or os.environ.get("AUTOVIZ_PLANNER_MODEL", DEFAULT_MODEL)
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from langchain.chat_models import init_chat_model

            self._model = init_chat_model(self._model_id, temperature=0)
        return self._model

    def _invoke_text(self, system: str, user: str) -> str:
        try:
            response = self.model.invoke([("system", system), ("user", user)])
        except Exception as exc:
            raise PlannerError(f"planner LLM call failed: {exc}") from exc
        content = response.content
        if isinstance(content, list):  # some providers return content blocks
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        return str(content)

    def classify(
        self,
        request: str,
        schema: list[dict[str, str]],
        profile: dict[str, Any],
        history: list[dict[str, Any]],
        clarification_answer: str | None = None,
    ) -> IntentDecision:
        payload = {
            "request": request,
            "schema": schema,
            "column_cardinality": profile.get("cardinality", {}),
            "history": history[-3:],
        }
        if clarification_answer is not None:
            payload["clarification_answer"] = clarification_answer
        raw = _json_object(self._invoke_text(_CLASSIFY_SYSTEM, json.dumps(payload)))
        try:
            return IntentDecision.model_validate(raw)
        except ValidationError as exc:
            raise PlannerError(f"planner returned an invalid IntentDecision: {exc}") from exc

    def generate_plan(
        self,
        task: str,
        dataset_id: str,
        schema: list[dict[str, str]],
        profile: dict[str, Any],
        prior_plan: dict[str, Any] | None = None,
        rejected_plan: dict[str, Any] | None = None,
        errors: list[str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "task": task,
            "dataset_id": dataset_id,
            "schema": schema,
            "column_cardinality": profile.get("cardinality", {}),
            # Numeric columns that are really coded categories (pclass, survived) —
            # group and colour by these, do not treat them as continuous measures.
            "categorical_numeric_columns": profile.get("categorical_numeric", []),
        }
        if prior_plan:
            payload["previous_plan_to_refine"] = prior_plan
        if rejected_plan:
            payload["rejected_plan"] = rejected_plan
            payload["validation_errors"] = errors or []
        return _json_object(self._invoke_text(_PLAN_SYSTEM, json.dumps(payload)))

    def compose(self, request: str, results: list[dict[str, Any]]) -> str:
        condensed = []
        for r in results:
            result = r.get("result") or {}
            condensed.append(
                {
                    "task": r.get("task"),
                    "status": r.get("status"),
                    "chart_type": (r.get("chart_spec") or {}).get("type"),
                    "rows": (result.get("result_table") or [])[:25],
                    "row_count": result.get("row_count"),
                    "sql": (result.get("provenance") or {}).get("sql"),
                    "errors": r.get("errors") or [],
                }
            )
        return self._invoke_text(
            _COMPOSE_SYSTEM, json.dumps({"request": request, "results": condensed})
        ).strip()
