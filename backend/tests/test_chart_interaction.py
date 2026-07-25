"""Interaction layer on generated specs (Docs/13 §4, A1-A5)."""

from autoviz.services.chart_interaction import (
    DIM_OPACITY,
    HOVER_PARAM,
    SERIES_PARAM,
    ZOOM_PARAM,
)
from autoviz.services.charts import generate_chart, primary_layer

_BAR = [{"region": "north", "revenue": 1200.5}, {"region": "south", "revenue": 980.0}]
_SERIES = [
    {"month": 1, "sales": 10.0, "channel": "web"},
    {"month": 2, "sales": 14.0, "channel": "store"},
]


def _spec(table, chart_spec):
    out = generate_chart(table, chart_spec)
    assert out["valid"], out["warnings"]
    return out["vega_lite_spec"]


def _param_names(spec):
    # Params live on the data layer, not the top level — see chart_interaction.attach.
    return {p["name"] for p in primary_layer(spec).get("params", [])}


# --- A1 tooltips -------------------------------------------------------------


def test_tooltip_covers_encoded_channels_with_titles():
    spec = _spec(_BAR, {"type": "bar", "x": "region", "y": "revenue"})
    tooltip = primary_layer(spec)["encoding"]["tooltip"]
    assert [t["field"] for t in tooltip] == ["region", "revenue"]
    assert [t["title"] for t in tooltip] == ["region", "revenue"]


def test_tooltip_formats_quantitative_and_leaves_nominal_alone():
    spec = _spec(_BAR, {"type": "bar", "x": "region", "y": "revenue"})
    by_field = {t["field"]: t for t in primary_layer(spec)["encoding"]["tooltip"]}
    assert "format" in by_field["revenue"]
    assert "format" not in by_field["region"]


def test_tooltip_formats_temporal_with_a_date_pattern():
    table = [{"d": "2024-01-01", "v": 1.0}]
    spec = _spec(
        table,
        {"type": "line", "x": "d", "y": "v", "column_types": {"d": "datetime", "v": "number"}},
    )
    by_field = {t["field"]: t for t in primary_layer(spec)["encoding"]["tooltip"]}
    assert by_field["d"]["format"].startswith("%")


def test_tooltip_carries_histogram_bin_and_count():
    spec = _spec([{"price": 100}, {"price": 250}], {"type": "histogram", "x": "price"})
    tooltip = primary_layer(spec)["encoding"]["tooltip"]
    assert tooltip[0] == {
        "field": "price",
        "type": "quantitative",
        "bin": True,
        "title": "price",
        "format": ",.4~f",
    }
    # The count channel has no field of its own, so it titles itself.
    assert tooltip[1]["aggregate"] == "count"
    assert tooltip[1]["title"] == "Count"


def test_tooltip_does_not_repeat_a_column_encoded_twice():
    spec = _spec(_BAR, {"type": "bar", "x": "region", "y": "revenue", "color": "region"})
    fields = [t["field"] for t in primary_layer(spec)["encoding"]["tooltip"]]
    assert fields == ["region", "revenue"]


def test_pie_tooltip_uses_theta_and_color():
    spec = _spec(_BAR, {"type": "pie", "x": "region", "y": "revenue"})
    fields = [t["field"] for t in primary_layer(spec)["encoding"]["tooltip"]]
    assert set(fields) == {"region", "revenue"}


# --- A2 legend filtering -----------------------------------------------------


def test_color_channel_binds_a_series_param_to_the_legend():
    spec = _spec(_SERIES, {"type": "bar", "x": "month", "y": "sales", "color": "channel"})
    series = next(p for p in primary_layer(spec)["params"] if p["name"] == SERIES_PARAM)
    assert series["bind"] == "legend"
    assert series["select"] == {"type": "point", "fields": ["channel"]}


def test_series_param_drives_opacity():
    spec = _spec(_SERIES, {"type": "bar", "x": "month", "y": "sales", "color": "channel"})
    assert primary_layer(spec)["encoding"]["opacity"] == {
        "condition": {"param": SERIES_PARAM, "value": 1},
        "value": DIM_OPACITY,
    }


# --- A3 hover highlight ------------------------------------------------------


def test_discrete_mark_without_color_gets_hover_highlight():
    spec = _spec(_BAR, {"type": "bar", "x": "region", "y": "revenue"})
    hover = next(p for p in primary_layer(spec)["params"] if p["name"] == HOVER_PARAM)
    assert hover["select"]["on"] == "pointerover"
    assert primary_layer(spec)["encoding"]["opacity"]["condition"]["param"] == HOVER_PARAM


def test_hover_and_legend_never_both_drive_opacity():
    spec = _spec(_SERIES, {"type": "bar", "x": "month", "y": "sales", "color": "channel"})
    assert HOVER_PARAM not in _param_names(spec)


def test_line_never_gets_a_per_datum_hover_condition():
    # A per-point opacity condition splits a line mark into segments.
    spec = _spec(_SERIES, {"type": "line", "x": "month", "y": "sales"})
    assert HOVER_PARAM not in _param_names(spec)
    assert "opacity" not in primary_layer(spec)["encoding"]


def test_line_with_color_still_gets_legend_filtering():
    # Series-level opacity is constant within each line, so it stays safe.
    spec = _spec(_SERIES, {"type": "line", "x": "month", "y": "sales", "color": "channel"})
    assert SERIES_PARAM in _param_names(spec)
    assert primary_layer(spec)["encoding"]["opacity"]["condition"]["param"] == SERIES_PARAM


# --- A4 pan / zoom -----------------------------------------------------------


def test_line_on_continuous_axes_binds_zoom_to_scales():
    table = [{"d": "2024-01-01", "v": 1.0}, {"d": "2024-02-01", "v": 3.0}]
    spec = _spec(
        table,
        {"type": "line", "x": "d", "y": "v", "column_types": {"d": "datetime", "v": "number"}},
    )
    zoom = next(p for p in primary_layer(spec)["params"] if p["name"] == ZOOM_PARAM)
    assert zoom["bind"] == "scales"
    assert zoom["select"]["type"] == "interval"


def test_line_over_time_is_zoomable():
    table = [{"d": "2024-01-01", "v": 1.0}]
    spec = _spec(
        table,
        {"type": "line", "x": "d", "y": "v", "column_types": {"d": "datetime", "v": "number"}},
    )
    assert ZOOM_PARAM in _param_names(spec)


def test_nominal_axis_is_not_zoomable():
    spec = _spec(_BAR, {"type": "bar", "x": "region", "y": "revenue"})
    assert ZOOM_PARAM not in _param_names(spec)


def test_line_over_a_nominal_x_is_not_zoomable():
    table = [{"stage": "a", "v": 1.0}, {"stage": "b", "v": 2.0}]
    spec = _spec(table, {"type": "line", "x": "stage", "y": "v"})
    assert ZOOM_PARAM not in _param_names(spec)


def test_histogram_binned_axis_is_not_zoomable():
    spec = _spec([{"price": 100}, {"price": 250}], {"type": "histogram", "x": "price"})
    assert ZOOM_PARAM not in _param_names(spec)


# --- A5 container sizing -----------------------------------------------------


def test_spec_sizes_from_its_container():
    spec = _spec(_BAR, {"type": "bar", "x": "region", "y": "revenue"})
    assert spec["width"] == "container"
    assert spec["height"] == "container"


# --- the layer stays additive ------------------------------------------------


def test_interaction_layer_leaves_positional_encodings_untouched():
    spec = _spec(_BAR, {"type": "bar", "x": "region", "y": "revenue"})
    assert primary_layer(spec)["encoding"]["x"] == {"field": "region", "type": "nominal"}
    assert primary_layer(spec)["encoding"]["y"] == {"field": "revenue", "type": "quantitative"}


def test_invalid_spec_gets_no_interaction_layer():
    out = generate_chart([{"a": 1}], {"type": "bar", "x": "a", "y": "missing"})
    assert not out["valid"]
    assert out["vega_lite_spec"] is None
