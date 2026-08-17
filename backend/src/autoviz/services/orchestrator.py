"""Tool Orchestrator: validate -> execute -> recommend -> generate as one flow.

Partial failure is this layer's responsibility (Docs/06 §1): every failure is
returned as structured error content naming the step that failed, never a
thrown exception, so the caller can reason about retry vs. escalation.
"""

import threading
from typing import Any, Callable

from autoviz.errors import (
    CHART_ERROR,
    CONFIRMATION_REQUIRED,
    EXECUTION_ERROR,
    INVALID_PLAN,
    UNKNOWN_DATASET,
)
from autoviz.schema.allowlists import (
    DATE_PART_DERIVE_FNS,
    DATETIME_DERIVE_FNS,
    NUMERIC_DERIVE_FNS,
)
from autoviz.schema.analysis_plan import AnalysisPlan
from autoviz.services.charts import (
    ORDINAL,
    discrete_channel_columns,
    generate_chart,
    recommend_chart_type,
    retype_chart_spec,
)
from autoviz.services.execution import execute_analysis
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
    preferred_chart_type: str | None = None,
) -> dict[str, Any]:
    """Validate, execute, pick a chart, and build it — as one call.

    ``on_progress(step, total, message)`` is invoked at each stage boundary so a
    caller can show real progress instead of an opaque spinner; the MCP layer
    forwards it to the host as a progress notification. ``cancel_event`` aborts
    a running DuckDB query. Both are optional and default to today's behaviour,
    so the FastAPI callers are unaffected.

    ``preferred_chart_type`` is a type the caller chose outright rather than
    described — the UI's chart-type buttons. It is applied here, after execution,
    because this is the first point at which the columns the chart would have to
    carry are known; before that, whether a pie or a histogram is even drawable
    is a guess. A type these columns cannot carry leaves the recommendation
    standing rather than failing the run.
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

    # The row-removal gate is enforced inside execute_analysis, next to the only
    # code that can actually run the cleaning stage — so the MCP execute_analysis
    # tool and POST /analysis/execute are covered by the same check, not just the
    # callers that happen to come through here. This layer only translates the
    # refusal into the pipeline's own vocabulary.
    progress(2, "Checking data-cleaning impact")
    progress(3, "Executing query")
    executed = execute_analysis(
        dataset_id,
        effective_plan,
        registry,
        cancel_event=cancel_event,
        approved_preprocessing_hash=approved_preprocessing_hash,
    )
    if executed.get("error_code") == CONFIRMATION_REQUIRED:
        return {
            "status": "confirmation_required",
            "confirmation": executed["confirmation"],
        }
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
    # Effective type of every column the query produces — the labels the whole
    # chart layer reasons from. A numeric-coded category (pclass, survived) is
    # demoted to "categorical" where it is acting as a dimension, so it renders
    # as discrete classes rather than a continuous scale; elsewhere it stays a
    # number, because the same column can still be a measure.
    coded = set(record.categorical_numeric)
    # Where a coded category is acting as a class rather than as a quantity.
    #
    # Scoped to `group_by` plus `chart.color` alone, this missed the two commonest
    # cases outright. An explicit `chart.x = pclass` left three passenger classes
    # on a continuous 1-3 axis, and a plan that merely *selected* a coded column
    # gave the recommender nothing discrete to work with, so it fell through to a
    # scatter. Both were silent.
    if plan.chart is not None:
        # The chart itself says which of its channels hold classes — and it has
        # to, because the answer is not a property of the column: pclass is three
        # classes on a bar's x axis and a genuine number on a scatter's.
        dimension_cols = set(plan.group_by) | discrete_channel_columns(
            plan.chart.model_dump(exclude_none=True)
        )
    else:
        # No chart yet, so there are no channels to ask. The recommender is about
        # to choose one and cannot choose a chart that treats pclass as three
        # classes unless it is told that is what pclass is. Aggregating over the
        # column is the one use that makes it a measure again.
        dimension_cols = set(plan.group_by) | (
            coded - {a.column for a in plan.aggregations}
        )
    # Start from the cleaned types: a column cast to a number in preprocessing must
    # reach the chart encoder as a number, or it would be plotted as a text axis.
    effective_types = plan.preprocessing_schema(record.schema)
    for d in plan.derive:
        # Same split as services/validation.py, and it has to stay in step with
        # it. Three outcomes, not two:
        #   truncation  -> a timestamp; typing it as a number puts 2026-01-01 on a
        #                  linear axis, the mis-rendering these fns exist to prevent
        #   extraction  -> an ORDERED DISCRETE position (month 1-12), not a
        #                  quantity. Typed "number" it emptied both the temporal
        #                  and categorical buckets, and a trend over it came back
        #                  as a scatter.
        #   round/abs   -> genuinely a number
        if d.fn in DATETIME_DERIVE_FNS:
            effective_types[d.name] = "datetime"
        elif d.fn in DATE_PART_DERIVE_FNS:
            effective_types[d.name] = ORDINAL
        elif d.fn in NUMERIC_DERIVE_FNS:
            effective_types[d.name] = "number"
        else:
            effective_types[d.name] = "string"
    for a in plan.aggregations:
        effective_types[a.as_] = "number"

    # Demote last, once every other column's type is settled, because whether a
    # demotion is safe depends on what else the result holds.
    #
    # The guard is not hypothetical: `categorical_numeric` detection keys off how
    # few distinct values a column has, so on a narrow result the *measure* is
    # often flagged too — a lone `fare` column comes back coded. Demoting it left
    # the result with no numeric column at all, and "nothing to plot as a measure"
    # is a worse answer than a continuous axis on a column that has an order.
    demote = coded & dimension_cols
    if not {
        c for c in result_columns
        if effective_types.get(c) == "number" and c not in demote
    }:
        demote = set()
    for c in demote:
        # Nominal, not ordinal: a coded category may or may not have an order
        # (pclass does, survived does not), and only a nominal colour scale picks
        # up the theme's palette. See charts.series_enc.
        effective_types[c] = "categorical"

    progress(4, "Selecting chart type")
    result_schema = [
        {"name": c, "type": effective_types.get(c, "string")} for c in result_columns
    ]
    if plan.chart is not None:
        chart_spec: dict[str, Any] = plan.chart.model_dump(exclude_none=True)
        recommendation = None
    else:
        # The row count is what separates a column of values from a single total,
        # which the schema alone cannot say — see recommend_chart_type.
        recommendation = recommend_chart_type(
            result_schema, plan.intent, row_count=len(result_table)
        )
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

    # A type the caller picked outright overrides the one chosen for them, but
    # only where these columns can carry it. A boxplot is refused over aggregated
    # results whatever the columns look like: quartiles need the raw values, and
    # drawing one from a column of means would be a chart that lies.
    declined_spec: dict[str, Any] | None = None
    if preferred_chart_type and chart_spec.get("type") != preferred_chart_type:
        retyped = (
            None
            if preferred_chart_type == "boxplot" and plan.aggregations
            else retype_chart_spec(chart_spec, preferred_chart_type, result_schema)
        )
        if retyped is not None:
            declined_spec, chart_spec = chart_spec, retyped

    def annotate(spec: dict[str, Any]) -> dict[str, Any]:
        # Encoding hint so each channel renders with the right Vega-Lite type — in
        # particular coded categories go nominal (discrete legend/axis), not a
        # continuous quantitative scale. Applies to host-supplied charts too.
        spec["column_types"] = {c: effective_types.get(c, "string") for c in result_columns}
        # Same pattern: plan metadata the renderer needs but the chart grammar does
        # not carry. Intent is what tells a bar chart it is a ranking and must sort.
        spec["intent"] = plan.intent
        return spec

    chart_spec = annotate(chart_spec)
    progress(5, "Building visualization")
    chart = generate_chart(result_table, chart_spec)
    if not chart["valid"] and declined_spec is not None:
        # The forced type survived the role check and still could not be drawn.
        # Falling back to the chart that can be beats returning none at all — the
        # numbers are already computed, and the substitution is disclosed.
        chart_spec = annotate(declined_spec)
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
        # Both halves of the disclosure in one list: what cleaning did to the
        # numbers, and what the chart had to do to make them legible. They reach
        # the user through the same channel and neither is worth more than the
        # other, so nothing downstream should have to know they had two sources.
        "notices": [
            *((executed.get("provenance") or {}).get("notices") or []),
            *chart.get("notices", []),
        ],
    }
