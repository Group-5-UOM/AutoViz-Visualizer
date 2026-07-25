"""Direct labels and the layered specs they force (Docs/13 §5, §6)."""

from autoviz.services.chart_interaction import SERIES_PARAM
from autoviz.services.chart_labels import (
    MAX_LABELLED_BARS,
    MAX_LABELLED_CELLS,
    MAX_LABELLED_SERIES,
    MAX_LABELLED_SLICES,
)
from autoviz.services.chart_theme import SECONDARY_INK
from autoviz.services.charts import generate_chart, primary_layer
from autoviz.services.export import export_chart

_BARS = [{"c": "a", "v": 3.0}, {"c": "b", "v": 7.0}, {"c": "c", "v": 5.0}]
_GRID = [
    {"c": c, "g": g, "n": float(i + 1)}
    for i, (c, g) in enumerate((c, g) for c in "ab" for g in "xy")
]
_SERIES = [
    {"m": m, "v": float(m * 2), "s": s}
    for s in ("web", "store")
    for m in range(1, 5)
]


def _spec(table, chart_spec):
    out = generate_chart(table, chart_spec)
    assert out["valid"], out["warnings"]
    return out["vega_lite_spec"]


def _labels(spec):
    """The text layer, or None when the chart carries no labels."""
    layers = spec.get("layer")
    return layers[1] if layers and len(layers) > 1 else None


# --- layering ----------------------------------------------------------------


def test_a_labelled_chart_is_layered_and_an_unlabelled_one_is_not():
    labelled = _spec(_BARS, {"type": "bar", "x": "c", "y": "v"})
    plain = _spec(_BARS, {"type": "scatter", "x": "v", "y": "v"})
    assert "layer" in labelled and "mark" not in labelled
    assert "mark" in plain and "layer" not in plain


def test_primary_layer_reaches_the_data_mark_either_way():
    labelled = _spec(_BARS, {"type": "bar", "x": "c", "y": "v"})
    plain = _spec(_BARS, {"type": "scatter", "x": "v", "y": "v"})
    assert primary_layer(labelled)["mark"] == "bar"
    assert primary_layer(plain)["mark"] == "point"


def test_sizing_stays_at_the_top_level_of_a_layered_spec():
    spec = _spec(_BARS, {"type": "bar", "x": "c", "y": "v"})
    assert spec["width"] == "container"
    assert "width" not in primary_layer(spec)


def test_params_sit_on_the_data_layer_not_the_top_level():
    # A top-level param on a layered spec is pushed into every child unit and
    # fails to parse with "Duplicate signal name" — even if only one layer uses
    # it. A sibling layer can still reference it by name.
    spec = _spec(_SERIES, {"type": "line", "x": "m", "y": "v", "color": "s"})
    assert "params" not in spec
    assert SERIES_PARAM in {p["name"] for p in primary_layer(spec)["params"]}


def test_labels_dim_with_their_series_under_legend_filtering():
    # Otherwise filtering to one series leaves the other series' labels behind.
    spec = _spec(_SERIES, {"type": "line", "x": "m", "y": "v", "color": "s"})
    assert _labels(spec)["encoding"]["opacity"] == primary_layer(spec)["encoding"]["opacity"]


def test_export_accepts_a_layered_spec():
    spec = _spec(_BARS, {"type": "bar", "x": "c", "y": "v"})
    out = export_chart(spec, "layered-export-test")
    assert "error" not in out, out


# --- what gets labelled ------------------------------------------------------


def test_single_series_bar_labels_its_values():
    spec = _spec(_BARS, {"type": "bar", "x": "c", "y": "v"})
    labels = _labels(spec)
    assert labels["mark"]["type"] == "text"
    assert labels["encoding"]["text"]["field"] == "v"


def test_bar_labels_stop_past_the_cap():
    table = [{"c": f"c{i}", "v": float(i)} for i in range(MAX_LABELLED_BARS + 1)]
    assert _labels(_spec(table, {"type": "bar", "x": "c", "y": "v"})) is None


def test_stacked_bar_is_not_labelled():
    # Labels inside stacked segments collide at realistic sizes.
    spec = _spec(_GRID, {"type": "bar", "x": "c", "y": "n", "color": "g"})
    assert _labels(spec) is None


def test_grouped_bar_labels_carry_the_same_offset_as_their_bar():
    spec = _spec(_GRID, {"type": "grouped_bar", "x": "c", "y": "n", "color": "g"})
    labels = _labels(spec)
    assert labels["encoding"]["xOffset"] == primary_layer(spec)["encoding"]["xOffset"]


def test_heatmap_labels_each_cell_and_flips_text_over_dark_cells():
    spec = _spec(_GRID, {"type": "heatmap", "x": "c", "y": "g", "color": "n"})
    color = _labels(spec)["encoding"]["color"]
    assert color["value"] == SECONDARY_INK
    assert "test" in color["condition"]  # white over the dark end of the ramp


def test_heatmap_labels_stop_past_the_cell_cap():
    table = [{"c": str(i), "g": str(j), "n": 1.0}
             for i in range(9) for j in range(9)]
    assert len(table) > MAX_LABELLED_CELLS
    assert _labels(_spec(table, {"type": "heatmap", "x": "c", "y": "g", "color": "n"})) is None


def test_line_labels_the_series_at_its_last_point():
    spec = _spec(_SERIES, {"type": "line", "x": "m", "y": "v", "color": "s"})
    enc = _labels(spec)["encoding"]
    assert enc["text"]["field"] == "s"
    assert enc["x"]["aggregate"] == "max"
    assert enc["y"]["aggregate"] == {"argmax": "m"}


def test_line_without_series_gets_no_label():
    spec = _spec([{"m": 1, "v": 2.0}, {"m": 2, "v": 4.0}], {"type": "line", "x": "m", "y": "v"})
    assert _labels(spec) is None


def test_series_labels_stop_past_the_series_cap():
    table = [{"m": m, "v": float(m), "s": f"s{i}"}
             for i in range(MAX_LABELLED_SERIES + 1) for m in range(1, 4)]
    assert _labels(_spec(table, {"type": "line", "x": "m", "y": "v", "color": "s"})) is None


def test_donut_labels_its_slices():
    spec = _spec(_BARS, {"type": "donut", "x": "c", "y": "v"})
    assert _labels(spec)["encoding"]["text"]["field"] == "c"


def test_slice_labels_stop_past_the_slice_cap():
    table = [{"c": f"c{i}", "v": 1.0} for i in range(MAX_LABELLED_SLICES + 1)]
    assert _labels(_spec(table, {"type": "donut", "x": "c", "y": "v"})) is None


def test_dense_forms_are_never_labelled():
    # One label per point/bin is unreadable, and boxplot is a composite mark.
    scatter = _spec([{"a": float(i), "b": float(i)} for i in range(5)],
                    {"type": "scatter", "x": "a", "y": "b"})
    histogram = _spec([{"p": float(i)} for i in range(5)], {"type": "histogram", "x": "p"})
    boxplot = _spec([{"c": "a", "v": float(i)} for i in range(10)],
                    {"type": "boxplot", "x": "c", "y": "v"})
    for spec in (scatter, histogram, boxplot):
        assert "layer" not in spec


def test_labels_never_wear_the_series_colour():
    # Tinting labels by series would re-introduce the colour-alone dependency
    # they exist to remove.
    spec = _spec(_SERIES, {"type": "line", "x": "m", "y": "v", "color": "s"})
    labels = _labels(spec)
    assert labels["mark"]["color"] == SECONDARY_INK
    assert "color" not in labels["encoding"]
