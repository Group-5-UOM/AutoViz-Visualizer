"""Analysis routes — thin adapters over the validation / execution / orchestrator
services (identical behaviour to MCP tools 7, 8, 11).

    POST /analysis/validate   -> {valid, errors, repaired_plan?}
    POST /analysis/execute    -> {result_table, row_count, provenance, ...}
    POST /analysis/pipeline   -> {status, result, chart_spec, vega_lite_spec, ...}  (preferred)
"""

from fastapi import APIRouter, Depends

from autoviz.api.deps import get_registry
from autoviz.api.errors import respond
from autoviz.api.schemas import PlanRequest
from autoviz.services.execution import execute_analysis
from autoviz.services.orchestrator import run_pipeline
from autoviz.services.registry import DatasetRegistry
from autoviz.services.validation import validate_analysis_plan

router = APIRouter()


@router.post("/validate")
def validate(body: PlanRequest, registry: DatasetRegistry = Depends(get_registry)):
    return respond(validate_analysis_plan(body.dataset_id, body.analysis_plan, registry))


@router.post("/execute")
def execute(body: PlanRequest, registry: DatasetRegistry = Depends(get_registry)):
    return respond(execute_analysis(body.dataset_id, body.analysis_plan, registry))


@router.post("/pipeline")
def pipeline(body: PlanRequest, registry: DatasetRegistry = Depends(get_registry)):
    return respond(run_pipeline(body.dataset_id, body.analysis_plan, registry))
