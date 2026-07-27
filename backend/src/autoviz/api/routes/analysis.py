"""Analysis routes — thin adapters over the validation / execution / orchestrator
services (identical behaviour to the matching MCP tools).

    POST /analysis/validate   -> {valid, errors, repaired_plan?}
    POST /analysis/execute    -> {result_table, row_count, provenance, ...}
    POST /analysis/pipeline   -> {status, result, chart_spec, vega_lite_spec, ...}  (preferred)
    POST /analysis/quality    -> {issues, auto_apply, proposals}          (read-only)
    POST /analysis/preview-preprocessing -> {input_rows, output_rows, dropped, ...}
"""

from fastapi import APIRouter, Depends

from autoviz.api.deps import get_registry
from autoviz.api.errors import respond
from autoviz.api.schemas import PlanRequest, QualityRequest
from autoviz.errors import INVALID_PLAN, UNKNOWN_DATASET, make_error
from autoviz.services import quality
from autoviz.services.execution import (
    GovernedFailure,
    PreprocessError,
    execute_analysis,
    preprocessing_impact,
)
from autoviz.services.orchestrator import run_pipeline
from autoviz.services.registry import DatasetRegistry
from autoviz.services.validation import validate_analysis_plan

router = APIRouter()


@router.post("/validate")
def validate(body: PlanRequest, registry: DatasetRegistry = Depends(get_registry)):
    return respond(validate_analysis_plan(body.dataset_id, body.analysis_plan, registry))


@router.post("/execute")
def execute(body: PlanRequest, registry: DatasetRegistry = Depends(get_registry)):
    return respond(
        execute_analysis(
            body.dataset_id,
            body.analysis_plan,
            registry,
            approved_preprocessing_hash=body.approved_preprocessing_hash,
        )
    )


@router.post("/quality")
def data_quality(body: QualityRequest, registry: DatasetRegistry = Depends(get_registry)):
    """Read-only quality report, scoped to the columns the caller names."""
    record = registry.get(body.dataset_id)
    if record is None:
        return respond(make_error(UNKNOWN_DATASET, f"Unknown dataset_id: {body.dataset_id}"))
    scope = set(body.columns) if body.columns else None
    return respond(quality.analyze_data_quality(record, scope))


@router.post("/preview-preprocessing")
def preview_preprocessing(
    body: PlanRequest, registry: DatasetRegistry = Depends(get_registry)
):
    """What a cleaning block would cost, in rows, without running the analysis."""
    record = registry.get(body.dataset_id)
    if record is None:
        return respond(make_error(UNKNOWN_DATASET, f"Unknown dataset_id: {body.dataset_id}"))
    verdict = validate_analysis_plan(body.dataset_id, body.analysis_plan, registry)
    if not verdict["valid"]:
        return respond(verdict)
    try:
        return respond(preprocessing_impact(record, body.analysis_plan))
    except PreprocessError as exc:
        return respond(make_error(INVALID_PLAN, str(exc)))
    except GovernedFailure as exc:
        return respond(make_error(exc.code, str(exc)))


@router.post("/pipeline")
def pipeline(body: PlanRequest, registry: DatasetRegistry = Depends(get_registry)):
    return respond(
        run_pipeline(
            body.dataset_id,
            body.analysis_plan,
            registry,
            approved_preprocessing_hash=body.approved_preprocessing_hash,
        )
    )
