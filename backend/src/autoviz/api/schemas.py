"""Pydantic request models for the HTTP API — thin wrappers over the MCP tool
signatures.

The plan grammar is NOT redefined here: `analysis_plan` is accepted as a raw
object and validated by `services.validation` against
`schema.analysis_plan.AnalysisPlan` (the single source of truth), so the caller
gets AutoViz's structured, message-rich validation errors instead of a generic
422 from a Pydantic body coercion. Responses stay the exact dicts the services
already return.
"""

from typing import Any

from pydantic import BaseModel


class PlanRequest(BaseModel):
    dataset_id: str
    analysis_plan: dict[str, Any]
    # Echo back the preprocessing_hash from a prior {status: "confirmation_required"}
    # response to approve a large row-removal. Honoured by /execute and /pipeline
    # alike — the gate lives in execution, so both need the token. Ignored by
    # /validate, which never runs anything.
    approved_preprocessing_hash: str | None = None


class QualityRequest(BaseModel):
    dataset_id: str
    # Scope the scan to the columns an analysis actually needs. Omit for the whole
    # frame — but a scoped scan is what keeps an unrelated messy column from
    # interrupting a question that never touches it.
    columns: list[str] | None = None


class RecommendChartRequest(BaseModel):
    result_schema: list[dict[str, str]]
    intent: str


class GenerateChartRequest(BaseModel):
    result_table: list[dict[str, Any]]
    chart_spec: dict[str, Any]


class ExportChartRequest(BaseModel):
    vega_lite_spec: dict[str, Any]
    filename: str | None = None


class AnalyzeRequest(BaseModel):
    request: str
    dataset_id: str | None = None
    file_ref: str | None = None
    thread_id: str | None = None


class ClarificationRequest(BaseModel):
    thread_id: str
    answer: str
