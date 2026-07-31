"""Chart routes.

Stateless (MCP tools 9, 10, 12):
    POST /charts/recommend   recommend_chart_type(result_schema, intent)
    POST /charts/generate    generate_chart(result_table, chart_spec)
    POST /charts/export      export_chart(vega_lite_spec, filename?)
    POST /charts/style       restyle a finished spec (authenticated: spends tokens)

Persisted, owned by the caller:
    POST   /charts/save      persist a Vega-Lite spec + provenance
    GET    /charts           list the caller's saved charts
    GET    /charts/{id}      fetch one (owner only)
    PUT    /charts/{id}      overwrite an edited chart in place (owner only)
    DELETE /charts/{id}      delete one (owner only)
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from autoviz.api.deps import get_current_user, get_db, get_planner
from autoviz.api.errors import respond
from autoviz.api.schemas import (
    ExportChartRequest,
    GenerateChartRequest,
    RecommendChartRequest,
)
from autoviz.llm.client import PlannerError
from autoviz.models import SavedChart, User
from autoviz.schema.chart_style import ChartStyle
from autoviz.services import chart_style
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


class StyleChartRequest(BaseModel):
    """Restyle a chart the user is already looking at.

    Two authors, one block. The style panel sends `style` alone and never reaches
    a model; the natural-language editor sends `request` too and the planner
    turns it into a patch over that block. Both end at the same `apply`, so the
    panel and the chat can never drift apart.
    """

    vega_lite_spec: dict[str, Any]
    # The widget's whole current style, not a diff — see schema/chart_style.py.
    style: dict[str, Any] | None = None
    # "make the bars orange". Omit for a direct, LLM-free application of `style`.
    request: str | None = None


@router.post("/style")
def style_chart(
    body: StyleChartRequest,
    user: User = Depends(get_current_user),
    planner=Depends(get_planner),
):
    """Apply presentation overrides to a finished spec. Never re-runs a query."""
    # `error` carries the sentence the user reads; `warnings` keeps the shape the
    # other chart routes return. Both are set on every refusal, and the spec is
    # never partially styled — the chart on screen stays exactly as it was.
    def refuse(message: str):
        return respond({"valid": False, "error": message, "warnings": [message]})

    try:
        current = ChartStyle.model_validate(body.style or {})
    except ValidationError:
        return refuse("That chart's saved styling could not be read.")

    if body.request:
        try:
            raw = planner.style_patch(
                body.request,
                current.model_dump(exclude_none=True),
                chart_style.context_for(body.vega_lite_spec),
            )
            current = current.merged_with(ChartStyle.model_validate(raw))
        except PlannerError:
            return refuse("I could not read that request. Try rephrasing it.")
        except ValidationError:
            # The model answered with something outside the grammar — a colour
            # that is not a colour, or a field that does not exist. Rendering it
            # would be worse than saying so: the chart stays as it is.
            return refuse(
                "I can only change how this chart looks — try naming a colour, a "
                "title, an axis label, or the legend."
            )

    return respond(
        {
            "vega_lite_spec": chart_style.apply(body.vega_lite_spec, current),
            "style": current.model_dump(exclude_none=True),
            "valid": True,
            "warnings": [],
        }
    )


# --- persisted charts --------------------------------------------------------


class SaveChartRequest(BaseModel):
    name: str
    vega_lite_spec: dict[str, Any]
    dataset_id: str | None = None
    chart_spec: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None


class UpdateChartRequest(BaseModel):
    """A partial overwrite: only the fields sent are written.

    Every field is optional *and* nullable, so `exclude_unset` is what separates
    "leave the name alone" from "clear the name" — a plain None check would
    conflate them.
    """

    name: str | None = None
    vega_lite_spec: dict[str, Any] | None = None
    chart_spec: dict[str, Any] | None = None


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


@router.put("/{chart_id}")
def update_saved(
    chart_id: str,
    body: UpdateChartRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Overwrite an edited chart rather than saving a second copy of it.

    Without this, editing a chart on the canvas could only ever append a new row,
    and a dashboard reopened tomorrow would show the chart as it was first
    generated — see the widget-update branch in the frontend's `ensureCharts`.
    """
    chart = _owned_chart(db, chart_id, user)
    fields = body.model_dump(exclude_unset=True)
    if fields:
        repository.update_chart(db, chart, **fields)
    return _chart_dict(chart)


@router.delete("/{chart_id}")
def delete_saved(chart_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    repository.delete_chart(db, _owned_chart(db, chart_id, user))
    return {"removed": True, "id": chart_id}
