"""POST /charts/style — the one endpoint behind both editing surfaces.

The style panel sends `style` and never reaches a model; the natural-language
editor sends `request` too. Both must end at the same applied spec, which is
what stops the two surfaces drifting apart.
"""

from fastapi.testclient import TestClient

from autoviz.api.deps import get_planner
from autoviz.api.main import create_app
from autoviz.llm.client import PlannerError
from autoviz.services.charts import generate_chart, primary_layer

CREDS = {"email": "style@example.com", "password": "hunter2pw", "username": "styleuser"}

_ROWS = [{"species": "setosa", "avg": 5.0}, {"species": "versicolor", "avg": 5.9}]


class StylePlanner:
    """Scripted style_patch. `raises` wins over `patch` when set."""

    def __init__(self, patch=None, raises=None):
        self.patch = patch if patch is not None else {}
        self.raises = raises
        self.calls = []

    def style_patch(self, request, current_style, chart_context):
        self.calls.append({"request": request, "style": current_style, "chart": chart_context})
        if self.raises:
            raise self.raises
        return self.patch


def _spec():
    return generate_chart(_ROWS, {"type": "bar", "x": "species", "y": "avg"})["vega_lite_spec"]


def _client(planner=None):
    app = create_app()
    app.dependency_overrides[get_planner] = lambda: planner or StylePlanner()
    client = TestClient(app)
    client.post("/auth/register", json=CREDS)
    token = client.post("/auth/login", json=CREDS).json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def test_style_only_applies_without_calling_the_model(api_db):
    planner = StylePlanner()
    client = _client(planner)

    r = client.post(
        "/charts/style",
        json={"vega_lite_spec": _spec(), "style": {"mark_color": "#eb6834", "title": "Mine"}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert primary_layer(body["vega_lite_spec"])["mark"]["color"] == "#eb6834"
    assert body["vega_lite_spec"]["title"]["text"] == "Mine"
    assert body["style"]["mark_color"] == "#eb6834"
    # The panel path costs nothing.
    assert planner.calls == []


def test_request_merges_a_patch_over_the_existing_block(api_db):
    planner = StylePlanner(patch={"mark_color": "#ff0000"})
    client = _client(planner)

    r = client.post(
        "/charts/style",
        json={
            "vega_lite_spec": _spec(),
            "style": {"title": "Set earlier"},
            "request": "make the bars red",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # The earlier title survives an edit that never mentioned it.
    assert body["style"]["title"] == "Set earlier"
    assert body["style"]["mark_color"] == "#ff0000"
    # And the planner was told what it was editing.
    assert planner.calls[0]["chart"]["mark"] == "bar"


def test_both_surfaces_reach_the_same_spec(api_db):
    """The natural-language path is only a second way to author the block."""
    patch = {"mark_color": "#123456", "legend": False}
    spec = _spec()

    by_words = _client(StylePlanner(patch=patch)).post(
        "/charts/style", json={"vega_lite_spec": spec, "request": "make it #123456, no legend"}
    )
    by_panel = _client(StylePlanner()).post(
        "/charts/style", json={"vega_lite_spec": spec, "style": patch}
    )
    assert by_words.json()["vega_lite_spec"] == by_panel.json()["vega_lite_spec"]


def test_out_of_grammar_patch_leaves_the_chart_alone(api_db):
    """A model answering with a colour that is not a colour must not render."""
    client = _client(StylePlanner(patch={"mark_color": "burnt sienna"}))
    r = client.post(
        "/charts/style", json={"vega_lite_spec": _spec(), "request": "burnt sienna please"}
    )
    assert r.status_code == 422
    assert r.json()["valid"] is False
    assert "vega_lite_spec" not in r.json()


def test_invented_field_is_rejected(api_db):
    client = _client(StylePlanner(patch={"drop_outliers": True}))
    r = client.post("/charts/style", json={"vega_lite_spec": _spec(), "request": "clean it up"})
    assert r.status_code == 422
    assert r.json()["valid"] is False


def test_planner_failure_is_structured_not_a_500(api_db):
    client = _client(StylePlanner(raises=PlannerError("no JSON object")))
    r = client.post("/charts/style", json={"vega_lite_spec": _spec(), "request": "???"})
    assert r.status_code == 422
    assert r.json()["valid"] is False


def test_style_requires_auth(api_db):
    app = create_app()
    app.dependency_overrides[get_planner] = lambda: StylePlanner()
    r = TestClient(app).post("/charts/style", json={"vega_lite_spec": _spec()})
    assert r.status_code == 401
