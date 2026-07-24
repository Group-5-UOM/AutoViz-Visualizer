"""Tool Orchestrator: validate -> execute -> recommend -> generate as one flow.

Partial failure is this layer's responsibility (Docs/06 §1): every failure is
returned as structured error content naming the step that failed, never a
thrown exception, so the caller can reason about retry vs. escalation.
"""

from typing import Any

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
from autoviz.services.execution import execute_analysis, preprocessing_impact
from autoviz.services.registry import REGISTRY, DatasetRegistry
from autoviz.services.validation import validate_analysis_plan


def run_pipeline(
    dataset_id: str,
    analysis_plan: dict[str, Any],
    registry: DatasetRegistry = REGISTRY,
    approved_preprocessing_hash: str | None = None,
) -> dict[str, Any]:
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
            impact = preprocessing_impact(record, effective_plan)
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

    executed = execute_analysis(dataset_id, effective_plan, registry)
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

    if plan.chart is not None:
        chart_spec: dict[str, Any] = plan.chart.model_dump(exclude_none=True)
        recommendation = None
    else:
        result_columns = list(result_table[0].keys()) if result_table else []
        effective_types = dict(record.schema)
        for d in plan.derive:
            effective_types[d.name] = (
                "number" if d.fn in (DATE_DERIVE_FNS | NUMERIC_DERIVE_FNS) else "string"
            )
        for a in plan.aggregations:
            effective_types[a.as_] = "number"
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
