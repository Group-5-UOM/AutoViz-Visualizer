"""Dashboard routes — persisted layouts of saved-chart widgets, owned by the caller.

    POST   /dashboards            create {name}
    GET    /dashboards            list the caller's dashboards
    GET    /dashboards/{id}       fetch one with its widgets (owner only)
    PUT    /dashboards/{id}       update name and/or widgets (owner only)
    DELETE /dashboards/{id}       delete (owner only)

A widget references a SavedChart the caller owns ({chart_id, x, y, w, h, order});
setting a widget whose chart isn't owned is rejected.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from autoviz.api.deps import get_current_user, get_db
from autoviz.models import Dashboard, User
from autoviz.storage import repository

router = APIRouter()


class CreateDashboardRequest(BaseModel):
    name: str


class WidgetSpec(BaseModel):
    chart_id: str
    x: int = 0
    y: int = 0
    w: int = 6
    h: int = 4
    order: int = 0


class UpdateDashboardRequest(BaseModel):
    name: str | None = None
    widgets: list[WidgetSpec] | None = None
    is_public: bool | None = None


def _dashboard_dict(d: Dashboard) -> dict[str, Any]:
    return {
        "id": d.id,
        "name": d.name,
        "is_public": d.is_public,
        "created_at": d.created_at.isoformat(),
        "updated_at": d.updated_at.isoformat(),
        "widgets": [
            {"id": w.id, "chart_id": w.chart_id, "x": w.x, "y": w.y, "w": w.w, "h": w.h, "order": w.order}
            for w in d.widgets
        ],
    }


def _owned_dashboard(db: Session, dashboard_id: str, user: User) -> Dashboard:
    dashboard = repository.get_dashboard(db, dashboard_id)
    if dashboard is None:
        raise HTTPException(status_code=404, detail=f"Unknown dashboard id: {dashboard_id}")
    if dashboard.user_id != user.id:
        raise HTTPException(status_code=403, detail="You do not own this dashboard")
    return dashboard


@router.post("", status_code=201)
def create(
    body: CreateDashboardRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    dashboard = repository.create_dashboard(db, user_id=user.id, name=body.name)
    return _dashboard_dict(dashboard)


@router.get("")
def list_all(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"dashboards": [_dashboard_dict(d) for d in repository.list_dashboards(db, user.id)]}


@router.get("/{dashboard_id}")
def get_one(dashboard_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _dashboard_dict(_owned_dashboard(db, dashboard_id, user))


@router.put("/{dashboard_id}")
def update(
    dashboard_id: str,
    body: UpdateDashboardRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    dashboard = _owned_dashboard(db, dashboard_id, user)
    if body.name is not None:
        dashboard.name = body.name
    if body.is_public is not None:
        dashboard.is_public = body.is_public
    if body.widgets is not None:
        for w in body.widgets:
            chart = repository.get_chart(db, w.chart_id)
            if chart is None or chart.user_id != user.id:
                raise HTTPException(status_code=400, detail=f"Unknown or unowned chart_id: {w.chart_id}")
        repository.set_dashboard_widgets(db, dashboard, [w.model_dump() for w in body.widgets])
    db.commit()
    db.refresh(dashboard)
    return _dashboard_dict(dashboard)


@router.delete("/{dashboard_id}")
def delete(dashboard_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    repository.delete_dashboard(db, _owned_dashboard(db, dashboard_id, user))
    return {"removed": True, "id": dashboard_id}


@router.get("/shared/{dashboard_id}")
def get_shared(dashboard_id: str, db: Session = Depends(get_db)):
    dashboard = repository.get_dashboard(db, dashboard_id)
    if dashboard is None or not dashboard.is_public:
        raise HTTPException(status_code=404, detail="Dashboard not found or not public")
    
    charts = {}
    for w in dashboard.widgets:
        chart = repository.get_chart(db, w.chart_id)
        if chart:
            charts[w.chart_id] = {
                "id": chart.id,
                "name": chart.name,
                "dataset_id": chart.dataset_id,
                "spec": chart.vega_lite_spec,
            }
            
    res = _dashboard_dict(dashboard)
    res["charts"] = charts
    return res
