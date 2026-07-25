"""Theme baked into generated specs, and ranking sort (Docs/13 §5)."""

from autoviz.services.chart_theme import CATEGORICAL, SEQUENTIAL_BLUE, THEME
from autoviz.services.charts import generate_chart, primary_layer
from autoviz.services.orchestrator import run_pipeline

_BAR = [
    {"region": "north", "revenue": 300.0},
    {"region": "south", "revenue": 1200.0},
    {"region": "east", "revenue": 700.0},
]


def _spec(table, chart_spec):
    out = generate_chart(table, chart_spec)
    assert out["valid"], out["warnings"]
    return out["vega_lite_spec"]


# --- theme -------------------------------------------------------------------


def test_spec_carries_the_theme_config():
    spec = _spec(_BAR, {"type": "bar", "x": "region", "y": "revenue"})
    assert spec["config"]["range"]["category"] == CATEGORICAL
    assert spec["config"]["range"]["heatmap"] == SEQUENTIAL_BLUE
    assert spec["config"]["background"] == "transparent"
    assert spec["config"]["view"]["stroke"] is None


def test_single_series_chart_gets_the_palette_not_vegas_default():
    # range.category only feeds a colour scale, which a single-series chart has
    # none of — without an explicit default mark colour it renders tableau blue.
    spec = _spec(_BAR, {"type": "bar", "x": "region", "y": "revenue"})
    assert "color" not in primary_layer(spec)["encoding"]
    assert spec["config"]["mark"]["color"] == CATEGORICAL[0]


def test_theme_sets_app_fonts_and_ink():
    spec = _spec(_BAR, {"type": "bar", "x": "region", "y": "revenue"})
    config = spec["config"]
    assert "DM Sans" in config["font"]
    assert config["axis"]["labelColor"] == THEME["axis"]["labelColor"]
    assert config["legend"]["symbolType"] == "circle"


def test_theme_does_not_override_a_caller_supplied_config():
    out = generate_chart(
        _BAR,
        {"type": "bar", "x": "region", "y": "revenue"},
    )
    spec = out["vega_lite_spec"]
    spec["config"]["background"] = "#000000"
    # Re-attaching must not clobber what is already there.
    from autoviz.services.chart_theme import attach

    attach(spec)
    assert spec["config"]["background"] == "#000000"


def test_categorical_slot_order_is_stable():
    # The slot ordering is the CVD-safety mechanism, not decoration.
    assert CATEGORICAL[:3] == ["#2a78d6", "#eb6834", "#1baf7a"]
    assert len(CATEGORICAL) == 8
    assert len(set(CATEGORICAL)) == 8


def test_sequential_ramp_is_a_single_hue_light_to_dark():
    assert len(SEQUENTIAL_BLUE) == 7
    # Monotonically darkening: sum of channels strictly decreases.
    weights = [sum(int(h[i : i + 2], 16) for i in (1, 3, 5)) for h in SEQUENTIAL_BLUE]
    assert weights == sorted(weights, reverse=True)


# --- ranking sort ------------------------------------------------------------


def test_ranking_bar_sorts_by_value_descending():
    spec = _spec(_BAR, {"type": "bar", "x": "region", "y": "revenue", "intent": "ranking"})
    assert primary_layer(spec)["encoding"]["x"]["sort"] == "-y"


def test_non_ranking_bar_keeps_natural_order():
    spec = _spec(_BAR, {"type": "bar", "x": "region", "y": "revenue", "intent": "comparison"})
    assert "sort" not in primary_layer(spec)["encoding"]["x"]


def test_ranking_does_not_sort_a_temporal_axis():
    # Ordering a time axis by value would destroy the axis.
    table = [{"d": "2024-01-01", "v": 5.0}, {"d": "2024-02-01", "v": 1.0}]
    spec = _spec(
        table,
        {
            "type": "bar",
            "x": "d",
            "y": "v",
            "intent": "ranking",
            "column_types": {"d": "datetime", "v": "number"},
        },
    )
    assert "sort" not in primary_layer(spec)["encoding"]["x"]


def test_ranking_does_not_sort_a_non_bar_chart():
    table = [{"a": 1.0, "b": 2.0}, {"a": 3.0, "b": 4.0}]
    spec = _spec(table, {"type": "scatter", "x": "a", "y": "b", "intent": "ranking"})
    assert "sort" not in primary_layer(spec)["encoding"]["x"]


def test_pipeline_threads_intent_into_the_chart_spec(registry, titanic_id):
    plan = {
        "dataset_id": titanic_id,
        "intent": "ranking",
        "group_by": ["pclass"],
        "aggregations": [{"column": "fare", "fn": "mean", "as": "avg_fare"}],
    }
    out = run_pipeline(titanic_id, plan, registry)
    assert out["status"] == "ok", out
    assert out["chart_spec"]["intent"] == "ranking"
    assert primary_layer(out["vega_lite_spec"])["encoding"]["x"]["sort"] == "-y"


def test_pipeline_charts_are_themed(registry, iris_id):
    plan = {
        "dataset_id": iris_id,
        "intent": "comparison",
        "group_by": ["species"],
        "aggregations": [{"column": "sepal_length", "fn": "mean", "as": "avg"}],
    }
    out = run_pipeline(iris_id, plan, registry)
    assert out["status"] == "ok", out
    assert out["vega_lite_spec"]["config"]["range"]["category"] == CATEGORICAL


# --- area translucency under a selection condition ---------------------------


def test_area_keeps_its_translucency_when_a_condition_is_attached():
    table = [{"m": 1, "v": 5.0, "g": "a"}, {"m": 2, "v": 3.0, "g": "b"}]
    spec = _spec(table, {"type": "area", "x": "m", "y": "v", "color": "g"})
    # An opacity encoding overrides the mark default outright, so overlapping
    # bands would occlude each other if "selected" meant fully opaque.
    assert primary_layer(spec)["encoding"]["opacity"]["condition"]["value"] == 0.7


def test_bar_selection_is_fully_opaque():
    spec = _spec(_BAR, {"type": "bar", "x": "region", "y": "revenue"})
    assert primary_layer(spec)["encoding"]["opacity"]["condition"]["value"] == 1
