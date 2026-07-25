"""Brush-to-select on dense charts (Docs/13 §4, A6).

The brush exists to answer "which rows are those?" — the frontend reads its
signal and narrows the widget's table view to the selection.
"""

from autoviz.services.chart_interaction import (
    BRUSH_PARAM,
    DIM_OPACITY,
    HOVER_PARAM,
    SERIES_PARAM,
    ZOOM_PARAM,
)
from autoviz.services.charts import generate_chart, primary_layer

_POINTS = [{"a": float(i), "b": float(i % 5), "g": f"g{i % 2}"} for i in range(8)]
_NUMS = [{"price": float(p)} for p in (100, 150, 200, 260, 300, 380)]


def _spec(table, chart_spec):
    out = generate_chart(table, chart_spec)
    assert out["valid"], out["warnings"]
    return out["vega_lite_spec"]


def _params(spec):
    return {p["name"]: p for p in primary_layer(spec).get("params", [])}


def test_scatter_gets_a_brush_over_both_axes():
    spec = _spec(_POINTS, {"type": "scatter", "x": "a", "y": "b"})
    brush = _params(spec)[BRUSH_PARAM]
    assert brush["select"]["type"] == "interval"
    assert brush["select"]["encodings"] == ["x", "y"]
    assert "bind" not in brush  # not scale-bound: it selects, it does not zoom


def test_histogram_brushes_only_x():
    # Its y is a derived count, so brushing it would select on a value that is
    # not present in any row.
    spec = _spec(_NUMS, {"type": "histogram", "x": "price"})
    assert _params(spec)[BRUSH_PARAM]["select"]["encodings"] == ["x"]


def test_a_brushed_chart_gets_no_zoom():
    # Both consume the drag gesture.
    spec = _spec(_POINTS, {"type": "scatter", "x": "a", "y": "b"})
    assert ZOOM_PARAM not in _params(spec)


def test_brush_replaces_hover_on_brushable_types():
    spec = _spec(_NUMS, {"type": "histogram", "x": "price"})
    assert HOVER_PARAM not in _params(spec)


def test_brush_drives_opacity():
    spec = _spec(_POINTS, {"type": "scatter", "x": "a", "y": "b"})
    assert primary_layer(spec)["encoding"]["opacity"] == {
        "condition": {"param": BRUSH_PARAM, "value": 1},
        "value": DIM_OPACITY,
    }


def test_a_series_chart_keeps_legend_filtering_over_brushing():
    # Both would drive opacity; isolating a series is the more valuable of the
    # two on a multi-series chart.
    spec = _spec(_POINTS, {"type": "scatter", "x": "a", "y": "b", "color": "g"})
    assert SERIES_PARAM in _params(spec)
    assert BRUSH_PARAM not in _params(spec)


def test_time_series_keeps_zoom_rather_than_a_brush():
    # Panning a range is the natural gesture on a time axis.
    table = [{"d": "2024-01-01", "v": 1.0}, {"d": "2024-02-01", "v": 2.0}]
    spec = _spec(
        table,
        {"type": "line", "x": "d", "y": "v", "column_types": {"d": "datetime", "v": "number"}},
    )
    assert ZOOM_PARAM in _params(spec)
    assert BRUSH_PARAM not in _params(spec)


def test_categorical_charts_are_not_brushable():
    spec = _spec([{"c": "a", "v": 1.0}, {"c": "b", "v": 2.0}], {"type": "bar", "x": "c", "y": "v"})
    assert BRUSH_PARAM not in _params(spec)


def test_brushed_fields_are_real_columns_the_table_can_index():
    # The frontend keys row lookups off the brush signal's field names.
    spec = _spec(_POINTS, {"type": "scatter", "x": "a", "y": "b"})
    enc = primary_layer(spec)["encoding"]
    assert {enc["x"]["field"], enc["y"]["field"]} <= set(_POINTS[0])
