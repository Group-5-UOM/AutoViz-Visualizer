"""Analysis routes (Week 3 — not yet implemented).

Thin adapters over `services.validation` / `services.execution` /
`services.orchestrator`, identical behavior to MCP tools 7, 8, 11:

    POST /analysis/validate   validate_plan()      -> {valid, errors, repaired_plan?}
    POST /analysis/execute    execute_plan()       -> {result_table, row_count, provenance, ...}
    POST /analysis/pipeline   run_pipeline()       -> {status, result, chart_spec,
                                                       vega_lite_spec, ...} (preferred)

Request body: `{dataset_id, analysis_plan}` where `analysis_plan` validates
against `schema.analysis_plan.AnalysisPlan` (closed grammar, Docs/07).
"""
