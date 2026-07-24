"""Chart routes.

Stateless (MCP tools 9, 10, 12):
    POST /charts/recommend   recommend_chart_type(result_schema, intent)
    POST /charts/generate    generate_chart(result_table, chart_spec)
    POST /charts/export      export_chart(vega_lite_spec, filename?)
"""

from fastapi import APIRouter

from autoviz.api.errors import respond
from autoviz.api.schemas import (
    ExportChartRequest,
    GenerateChartRequest,
    RecommendChartRequest,
)
from autoviz.services.charts import generate_chart, recommend_chart_type
from autoviz.services.export import export_chart

router = APIRouter()


@router.post("/recommend")
def recommend(body: RecommendChartRequest):
    return respond(recommend_chart_type(body.result_schema, body.intent))


@router.post("/generate")
def generate(body: GenerateChartRequest):
    return respond(generate_chart(body.result_table, body.chart_spec))


@router.post("/export")
def export(body: ExportChartRequest):
    return respond(export_chart(body.vega_lite_spec, body.filename))
