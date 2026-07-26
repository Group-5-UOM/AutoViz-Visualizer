"""Tool Orchestrator: validate -> execute -> recommend -> generate as one flow.

Partial failure is this layer's responsibility (Docs/06 §1): every failure is
returned as structured error content naming the step that failed, never a
thrown exception, so the caller can reason about retry vs. escalation.
"""

import threading
from typing import Any, Callable

from autoviz.errors import (
    CHART_ERROR,
    EXECUTION_ERROR,
    INVALID_PLAN,
    UNKNOWN_DATASET,
)
from autoviz.schema.allowlists import (
    DATE_DERIVE_FNS,
    NUMERIC_DERIVE_FNS,
    ROW_DROP_CONFIRM_FRACTION,
)
from autoviz.schema.analysis_plan import AnalysisPlan
from autoviz.services.charts import generate_chart, recommend_chart_type
from autoviz.services.execution import (
    PreprocessError,
    execute_analysis,
    preprocessing_impact,
)
from autoviz.services.registry import REGISTRY, DatasetRegistry
from autoviz.services.validation import validate_analysis_plan


TOTAL_STEPS = 5


def run_pipeline(
    dataset_id: str,
    analysis_plan: dict[str, Any],
    registry: DatasetRegistry = REGISTRY,
    approved_preprocessing_hash: str | None = None,
    on_progress: Callable[[int, int, str], None] | None = None,
    cancel_event: "threading.Event | None" = None,
) -> dict[str, Any]:
    """Validate, execute, pick a chart, and build it — as one call.

    ``on_progress(step, total, message)`` is invoked at each stage boundary so a
    caller can show real progress instead of an opaque spinner; the MCP layer
    forwards it to the host as a progress notification. ``cancel_event`` aborts
    a running DuckDB query. Both are optional and default to today's behaviour,
    so the FastAPI callers are unaffected.
    """

    def progress(step: int, message: str) -> None:
        if on_progress is not None:
            on_progress(step, TOTAL_STEPS, message)

    progress(1, "Validating analysis plan")
    verdict = validate_analysis_plan(dataset_id, analysis_plan, registry)
    if not verdict["valid"]:
        return {
            "status": "error",
            "failed_step": "validate_analysis_plan",
            "error_code": verdict.get("error_code", INVALID_PLAN),
            "errors": verdict["errors"],
        }
    effective_plan = verdict.get("repaired_plan", analysis_plan)

    # Shared confirmation gate (enforced here, not just in the agent, so no caller —
    # including a bare MCP host — can bypass it). If a cleaning step would remove more
    # than the configured fraction of rows, pause unless this exact preprocessing block
    # was already approved (approval is bound to its content hash, not a boolean).
    progress(2, "Checking data-cleaning impact")
    plan_model = AnalysisPlan.model_validate(effective_plan)
    if plan_model.has_row_dropping_preprocessing():
        record = registry.get(dataset_id)
        if record is None:
            return {
                "status": "error",
                "failed_step": "validate_analysis_plan",
                "error_code": UNKNOWN_DATASET,
                "errors": [f"Unknown dataset_id: {dataset_id}"],
            }
        pp_hash = plan_model.preprocessing_hash()
        if approved_preprocessing_hash != pp_hash:
            # preprocessing_impact runs the cleaning stage to measure it, so it can
            # raise on an unfillable column (all-null median/mode). execute_analysis
            # already converts that to INVALID_PLAN; the gate must too, or the
            # exception escapes run_pipeline as an unstructured crash.
            try:
                impact = preprocessing_impact(record, effective_plan)
            except PreprocessError as exc:
                return {
                    "status": "error",
                    "failed_step": "validate_analysis_plan",
                    "error_code": INVALID_PLAN,
                    "errors": [str(exc)],
                }
            if impact["fraction"] > ROW_DROP_CONFIRM_FRACTION:
                pct = round(impact["fraction"] * 100, 1)
                return {
                    "status": "confirmation_required",
                    "confirmation": {
                        "question": (
                            f"This cleaning step would remove {impact['dropped']} of "
                            f"{impact['input_rows']} rows ({pct}%). Proceed?"
                        ),
                        "options": ["Proceed with cleaning", "Skip cleaning (keep all rows)"],
                        "impact": impact,
                        "preprocessing_hash": pp_hash,
                    },
                }

    progress(3, "Executing query")
    executed = execute_analysis(dataset_id, effective_plan, registry, cancel_event=cancel_event)
    if "error" in executed:
        return {
            "status": "error",
            "failed_step": "execute_analysis",
            "error_code": executed.get("error_code", EXECUTION_ERROR),
            "errors": [executed["error"], *executed.get("validation_errors", [])],
        }

    plan = AnalysisPlan.model_validate(effective_plan)
    record = registry.get(dataset_id)
    if record is None:
        return {
            "status": "error",
            "failed_step": "execute_analysis",
            "error_code": UNKNOWN_DATASET,
            "errors": [f"Unknown dataset_id: {dataset_id}"],
        }
    result_table = executed["result_table"]

    result_columns = list(result_table[0].keys()) if result_table else []
    # Effective type of every column the query produces. A numeric-coded category
    # (pclass, survived) is demoted to "categorical" only where it is used as a
    # dimension — a group_by key or an explicit colour channel — so it renders as
    # discrete classes instead of a continuous scale. Elsewhere it stays a number:
    # the same column can still be a measure when selected or aggregated on.
    coded = set(record.categorical_numeric)
    dimension_cols = set(plan.group_by)
    if plan.chart is not None and plan.chart.color:
        dimension_cols.add(plan.chart.color)
    effective_types = dict(record.schema)
    for c in coded & dimension_cols:
        effective_types[c] = "categorical"
    for d in plan.derive:
        effective_types[d.name] = (
            "number" if d.fn in (DATE_DERIVE_FNS | NUMERIC_DERIVE_FNS) else "string"
        )
    for a in plan.aggregations:
        effective_types[a.as_] = "number"

    progress(4, "Selecting chart type")
    if plan.chart is not None:
        chart_spec: dict[str, Any] = plan.chart.model_dump(exclude_none=True)
        recommendation = None
    else:
        result_schema = [
            {"name": c, "type": effective_types.get(c, "string")} for c in result_columns
        ]
        recommendation = recommend_chart_type(result_schema, plan.intent)
        if "error" in recommendation:
            return {
                "status": "error",
                "failed_step": "recommend_chart_type",
                "error_code": CHART_ERROR,
                "errors": [recommendation["error"]],
                "result": executed,
            }
        chart_spec = {
            "type": recommendation["chart_type"],
            "x": recommendation["x"],
        }
        if recommendation.get("y") is not None:  # histogram has no y column
            chart_spec["y"] = recommendation["y"]
        if recommendation.get("color"):
            chart_spec["color"] = recommendation["color"]

    # Encoding hint so each channel renders with the right Vega-Lite type — in
    # particular coded categories go nominal (discrete legend/axis), not a
    # continuous quantitative scale. Applies to host-supplied charts too.
    chart_spec["column_types"] = {c: effective_types.get(c, "string") for c in result_columns}
    # Same pattern: plan metadata the renderer needs but the chart grammar does
    # not carry. Intent is what tells a bar chart it is a ranking and must sort.
    chart_spec["intent"] = plan.intent
    progress(5, "Building visualization")
    chart = generate_chart(result_table, chart_spec)
    if not chart["valid"]:
        return {
            "status": "error",
            "failed_step": "generate_chart",
            "error_code": CHART_ERROR,
            "errors": chart["warnings"],
            "result": executed,
        }

    return {
        "status": "ok",
        "result": executed,
        "chart_spec": chart_spec,
        "recommendation": recommendation,
        "vega_lite_spec": chart["vega_lite_spec"],
        "warnings": chart["warnings"],
    }
