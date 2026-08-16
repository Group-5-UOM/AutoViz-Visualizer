"""Tier 1 chart types: heatmap, boxplot, grouped_bar, donut (Docs/13 §6)."""

import pytest

from autoviz.schema.allowlists import MAX_SERIES_ADJACENT, MAX_SERIES_ALL_PAIRS
from autoviz.services.chart_interaction import HOVER_PARAM, SERIES_PARAM
from autoviz.services.charts import generate_chart, primary_layer, recommend_chart_type
from autoviz.services.validation import validate_analysis_plan

_GRID = [
    {"cls": "a", "grp": "x", "n": 3.0},
    {"cls": "a", "grp": "y", "n": 5.0},
    {"cls": "b", "grp": "x", "n": 1.0},
    {"cls": "b", "grp": "y", "n": 9.0},
]
_RAW = [{"cls": c, "v": float(i)} for c in ("a", "b") for i in range(10)]
_PARTS = [{"region": "north", "revenue": 300.0}, {"region": "south", "revenue": 1200.0}]


def _spec(table, chart_spec):
    out = generate_chart(table, chart_spec)
    assert out["valid"], out["warnings"]
    return out["vega_lite_spec"]


def _names(spec):
    # Params live on the data layer, not the top level.
    return {p["name"] for p in primary_layer(spec).get("params", [])}


# --- heatmap -----------------------------------------------------------------


def test_heatmap_is_a_rect_grid_with_the_measure_on_colour():
    spec = _spec(_GRID, {"type": "heatmap", "x": "cls", "y": "grp", "color": "n"})
    assert primary_layer(spec)["mark"] == "rect"
    enc = primary_layer(spec)["encoding"]
    assert enc["x"]["type"] == "nominal"
    assert enc["y"]["type"] == "nominal"
    assert enc["color"] == {"field": "n", "type": "quantitative"}


def test_heatmap_requires_a_colour_channel():
    out = generate_chart(_GRID, {"type": "heatmap", "x": "cls", "y": "grp"})
    assert not out["valid"]
    assert "color" in out["warnings"][0]


def test_heatmap_gets_hover_not_legend_filtering():
    # Its legend is a continuous gradient — there are no discrete entries to click.
    spec = _spec(_GRID, {"type": "heatmap", "x": "cls", "y": "grp", "color": "n"})
    assert HOVER_PARAM in _names(spec)
    assert SERIES_PARAM not in _names(spec)


def test_heatmap_tooltip_covers_both_axes_and_the_measure():
    spec = _spec(_GRID, {"type": "heatmap", "x": "cls", "y": "grp", "color": "n"})
    assert [t["field"] for t in primary_layer(spec)["encoding"]["tooltip"]] == ["cls", "grp", "n"]


def test_recommender_picks_heatmap_for_two_categories_crossed():
    schema = [
        {"name": "cls", "type": "string"},
        {"name": "grp", "type": "string"},
        {"name": "n", "type": "number"},
    ]
    for intent in ("distribution", "relationship"):
        rec = recommend_chart_type(schema, intent)
        assert rec["chart_type"] == "heatmap", intent
        assert rec["color"] == "n"
        assert {rec["x"], rec["y"]} == {"cls", "grp"}


# --- boxplot -----------------------------------------------------------------


def test_boxplot_is_a_composite_mark_with_its_own_tooltip():
    """The tooltip belongs on the sub-parts, not on the composite mark.

    `BoxPlotDef` sets additionalProperties:false and has no `tooltip`, so the
    top-level form this used to assert made every boxplot spec fail the
    Vega-Lite v6 schema — and produced no tooltip either.
    """
    spec = _spec(_RAW, {"type": "boxplot", "x": "cls", "y": "v"})
    mark = primary_layer(spec)["mark"]
    assert mark["type"] == "boxplot"
    assert mark["extent"] == 1.5
    assert "tooltip" not in mark
    assert mark["box"]["tooltip"] is True
    assert mark["outliers"]["tooltip"] is True


def test_boxplot_gets_no_selection_params():
    # Vega-Lite throws "Unrecognized signal name" on a param over a composite mark.
    spec = _spec(_RAW, {"type": "boxplot", "x": "cls", "y": "v"})
    assert "params" not in primary_layer(spec)
    assert "opacity" not in primary_layer(spec)["encoding"]
    assert "tooltip" not in primary_layer(spec)["encoding"]


def test_boxplot_still_sizes_from_its_container():
    spec = _spec(_RAW, {"type": "boxplot", "x": "cls", "y": "v"})
    assert spec["width"] == "container"


def test_boxplot_y_is_quantitative():
    spec = _spec(_RAW, {"type": "boxplot", "x": "cls", "y": "v"})
    assert primary_layer(spec)["encoding"]["y"]["type"] == "quantitative"


# --- grouped_bar -------------------------------------------------------------


def test_grouped_bar_adds_xoffset_so_it_groups_instead_of_stacking():
    spec = _spec(_GRID, {"type": "grouped_bar", "x": "cls", "y": "n", "color": "grp"})
    assert primary_layer(spec)["mark"] == "bar"
    assert primary_layer(spec)["encoding"]["xOffset"] == {"field": "grp", "type": "nominal"}


def test_plain_bar_with_colour_has_no_xoffset_and_therefore_stacks():
    spec = _spec(_GRID, {"type": "bar", "x": "cls", "y": "n", "color": "grp"})
    assert "xOffset" not in primary_layer(spec)["encoding"]


def test_grouped_bar_requires_colour():
    out = generate_chart(_GRID, {"type": "grouped_bar", "x": "cls", "y": "n"})
    assert not out["valid"]


def test_recommender_groups_rather_than_stacks_for_comparison():
    schema = [
        {"name": "cls", "type": "string"},
        {"name": "grp", "type": "string"},
        {"name": "n", "type": "number"},
    ]
    rec = recommend_chart_type(schema, "comparison")
    assert rec["chart_type"] == "grouped_bar"
    assert rec["color"] == "grp"


def test_single_category_comparison_stays_a_plain_bar():
    schema = [{"name": "region", "type": "string"}, {"name": "revenue", "type": "number"}]
    assert recommend_chart_type(schema, "comparison")["chart_type"] == "bar"


# --- donut -------------------------------------------------------------------


def test_donut_inner_radius_is_derived_from_the_view():
    # A literal pixel radius inverts once the chart sizes from its container.
    spec = _spec(_PARTS, {"type": "donut", "x": "region", "y": "revenue"})
    assert primary_layer(spec)["mark"]["type"] == "arc"
    assert "expr" in primary_layer(spec)["mark"]["innerRadius"]
    assert "width" in primary_layer(spec)["mark"]["innerRadius"]["expr"]


def test_donut_encodes_like_a_pie():
    spec = _spec(_PARTS, {"type": "donut", "x": "region", "y": "revenue"})
    assert primary_layer(spec)["encoding"]["theta"]["field"] == "revenue"
    assert primary_layer(spec)["encoding"]["color"]["field"] == "region"


def test_donut_gets_legend_filtering():
    spec = _spec(_PARTS, {"type": "donut", "x": "region", "y": "revenue"})
    assert SERIES_PARAM in _names(spec)


def test_donut_warns_past_the_category_cap():
    table = [{"c": f"c{i}", "v": float(i)} for i in range(9)]
    out = generate_chart(table, {"type": "donut", "x": "c", "y": "v"})
    assert out["valid"]
    assert any("categories" in w for w in out["warnings"])


def test_recommender_prefers_donut_for_composition():
    schema = [{"name": "region", "type": "string"}, {"name": "revenue", "type": "number"}]
    rec = recommend_chart_type(schema, "composition")
    assert rec["chart_type"] == "donut"


def test_pie_remains_available_when_asked_for_by_name():
    spec = _spec(_PARTS, {"type": "pie", "x": "region", "y": "revenue"})
    assert primary_layer(spec)["mark"] == "arc"
    assert "innerRadius" not in str(primary_layer(spec)["mark"])


# --- colour cardinality caps (§2.2) ------------------------------------------


def test_scatter_warns_at_the_stricter_all_pairs_cap():
    table = [{"a": float(i), "b": float(i), "g": f"g{i}"} for i in range(MAX_SERIES_ALL_PAIRS + 2)]
    out = generate_chart(table, {"type": "scatter", "x": "a", "y": "b", "color": "g"})
    assert out["valid"]
    assert any(str(MAX_SERIES_ALL_PAIRS) in w for w in out["warnings"])


def test_bar_tolerates_more_series_than_scatter():
    n = MAX_SERIES_ALL_PAIRS + 2
    table = [{"a": f"a{i}", "b": float(i), "g": f"g{i}"} for i in range(n)]
    out = generate_chart(table, {"type": "bar", "x": "a", "y": "b", "color": "g"})
    assert out["valid"]
    assert not out["warnings"], out["warnings"]


def test_bar_warns_past_the_adjacent_cap():
    table = [{"a": f"a{i}", "b": float(i), "g": f"g{i}"} for i in range(MAX_SERIES_ADJACENT + 2)]
    out = generate_chart(table, {"type": "bar", "x": "a", "y": "b", "color": "g"})
    assert any(str(MAX_SERIES_ADJACENT) in w for w in out["warnings"])


# --- plan validation ---------------------------------------------------------


def _plan(registry, titanic_id, chart, **extra):
    return validate_analysis_plan(
        titanic_id,
        {"dataset_id": titanic_id, "intent": "comparison", "chart": chart, **extra},
        registry,
    )


def test_boxplot_over_an_aggregated_plan_is_rejected(registry, titanic_id):
    verdict = _plan(
        registry,
        titanic_id,
        {"type": "boxplot", "x": "pclass", "y": "avg_fare"},
        group_by=["pclass"],
        aggregations=[{"column": "fare", "fn": "mean", "as": "avg_fare"}],
    )
    assert not verdict["valid"]
    assert any("quartiles" in e for e in verdict["errors"])


def test_boxplot_over_raw_rows_validates(registry, titanic_id):
    verdict = _plan(
        registry,
        titanic_id,
        {"type": "boxplot", "x": "pclass", "y": "fare"},
        select=["pclass", "fare"],
    )
    assert verdict["valid"], verdict["errors"]


def test_heatmap_without_colour_is_rejected(registry, titanic_id):
    verdict = _plan(
        registry,
        titanic_id,
        {"type": "heatmap", "x": "pclass", "y": "sex"},
        group_by=["pclass", "sex"],
        aggregations=[{"column": "fare", "fn": "mean", "as": "avg_fare"}],
    )
    assert not verdict["valid"]
    assert any("chart.color" in e for e in verdict["errors"])


def test_heatmap_with_a_categorical_colour_is_rejected(registry, titanic_id):
    verdict = _plan(
        registry,
        titanic_id,
        {"type": "heatmap", "x": "pclass", "y": "sex", "color": "sex"},
        group_by=["pclass", "sex"],
        aggregations=[{"column": "fare", "fn": "mean", "as": "avg_fare"}],
    )
    assert not verdict["valid"]
    assert any("numeric measure" in e for e in verdict["errors"])


def test_heatmap_with_a_measure_on_colour_validates(registry, titanic_id):
    verdict = _plan(
        registry,
        titanic_id,
        {"type": "heatmap", "x": "pclass", "y": "sex", "color": "avg_fare"},
        group_by=["pclass", "sex"],
        aggregations=[{"column": "fare", "fn": "mean", "as": "avg_fare"}],
    )
    assert verdict["valid"], verdict["errors"]


@pytest.mark.parametrize("chart_type", ["heatmap", "boxplot", "grouped_bar", "donut"])
def test_new_types_are_accepted_by_the_plan_grammar(registry, titanic_id, chart_type):
    # A bad plan must fail on its own merits, never on "unknown chart type".
    verdict = _plan(registry, titanic_id, {"type": chart_type, "x": "pclass", "y": "fare"},
                    select=["pclass", "fare"])
    assert not any("type" in e and "literal" in e.lower() for e in verdict["errors"])
