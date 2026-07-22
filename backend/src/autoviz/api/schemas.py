"""Pydantic request/response models for the HTTP API (Week 3 — not yet implemented).

The plan grammar itself is NOT redefined here — `schema.analysis_plan.AnalysisPlan`
is the single source of truth and is reused directly in request bodies.

Planned models (thin wrappers matching the MCP tool signatures):
- RegisterDatasetRequest{file_ref}          — plus a separate multipart upload route
- PlanRequest{dataset_id, analysis_plan}    — for validate / execute / pipeline
- ChartRequest{result_table, chart_spec}
- ExportRequest{vega_lite_spec, filename?}
- AnalyzeRequest{request, dataset_id?, file_ref?, thread_id?}
- ClarificationRequest{thread_id, answer}

Responses stay the same dicts the services already return (structured errors,
never raised), so the frontend and MCP hosts see identical shapes.
"""
