"""Chart routes.

Stateless (MCP tools 9, 10, 12):
    POST /charts/recommend   recommend_chart_type(result_schema, intent)
    POST /charts/generate    generate_chart(result_table, chart_spec)
    POST /charts/export      export_chart(vega_lite_spec, filename?)

Persisted, owned by the caller:
    POST   /charts/save      persist a Vega-Lite spec + provenance
    GET    /charts           list the caller's saved charts
    GET    /charts/{id}      fetch one (owner only)
    DELETE /charts/{id}      delete one (owner only)
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from autoviz.api.deps import get_current_user, get_db
from autoviz.api.errors import respond
from autoviz.api.schemas import (
    ExportChartRequest,
    GenerateChartRequest,
    RecommendChartRequest,
)
from autoviz.models import SavedChart, User
from autoviz.services.charts import generate_chart, recommend_chart_type
from autoviz.services.export import export_chart
from autoviz.storage import repository

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


# --- persisted charts --------------------------------------------------------


class SaveChartRequest(BaseModel):
    name: str
    vega_lite_spec: dict[str, Any]
    dataset_id: str | None = None
    chart_spec: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None


def _chart_dict(c: SavedChart) -> dict[str, Any]:
    return {
        "id": c.id,
        "name": c.name,
        "dataset_id": c.dataset_id,
        "vega_lite_spec": c.vega_lite_spec,
        "chart_spec": c.chart_spec,
        "provenance": c.provenance,
        "created_at": c.created_at.isoformat(),
    }


def _owned_chart(db: Session, chart_id: str, user: User) -> SavedChart:
    chart = repository.get_chart(db, chart_id)
    if chart is None:
        raise HTTPException(status_code=404, detail=f"Unknown chart id: {chart_id}")
    if chart.user_id != user.id:
        raise HTTPException(status_code=403, detail="You do not own this chart")
    return chart


@router.post("/save", status_code=201)
def save(
    body: SaveChartRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    chart = repository.create_chart(
        db,
        user_id=user.id,
        name=body.name,
        dataset_id=body.dataset_id,
        vega_lite_spec=body.vega_lite_spec,
        chart_spec=body.chart_spec,
        provenance=body.provenance,
    )
    return respond(_chart_dict(chart), ok_status=201)


@router.get("")
def list_saved(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"charts": [_chart_dict(c) for c in repository.list_charts(db, user.id)]}


@router.get("/{chart_id}")
def get_saved(chart_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _chart_dict(_owned_chart(db, chart_id, user))


@router.delete("/{chart_id}")
def delete_saved(chart_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    repository.delete_chart(db, _owned_chart(db, chart_id, user))
    return {"removed": True, "id": chart_id}
