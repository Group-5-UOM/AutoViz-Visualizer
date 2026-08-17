"""Sub-types: the modifier layer over the ten chart families (Docs/13 §11).

These are structural assertions. What they *cannot* see is whether a modifier
actually changed the picture — a `stack` that never reached the encoding still
produces a perfectly valid spec — so every sub-type here also has a scenegraph
case in `scripts/emit_reference_specs.py`, checked by `npm run verify:specs`.
The division is the one Docs/13 §6 draws: structure here, geometry there.
"""

import pytest

from autoviz.schema.allowlists import (
    CHART_MODIFIERS,
    DEFAULT_FACET_COLUMNS,
    FACET_PANEL_WIDTH,
    MAX_FACETS,
)
from autoviz.services.chart_modifiers import COMPOSITE_MARKS, Form
from autoviz.services.charts import chart_root, generate_chart, primary_layer, retype_chart_spec
from autoviz.services.export import export_chart
from autoviz.services.orchestrator import run_pipeline
from autoviz.services.validation import validate_analysis_plan

_PARTS = [
    {"region": "north", "revenue": 300.0},
    {"region": "south", "revenue": 1200.0},
    {"region": "east", "revenue": 700.0},
]
_GRID = [
    {"cls": c, "grp": g, "n": float(i + 1)}
    for i, (c, g) in enumerate((c, g) for c in "ab" for g in "xy")
]
_RAW = [{"cls": c, "v": float(i * 3 % 7)} for c in ("a", "b", "c") for i in range(9)]
_XY = [{"a": float(i), "b": float(i * i % 7)} for i in range(20)]
_NUM = [{"price": float(p)} for p in (100, 120, 130, 250, 260, 270, 350, 355, 500)]
_TIME = [{"d": f"2024-{m:02d}-01", "v": float(m)} for m in range(1, 7)]


def _spec(table, chart_spec):
    out = generate_chart(table, chart_spec)
    assert out["valid"], out["warnings"]
    return out["vega_lite_spec"]


def _enc(spec):
    return primary_layer(spec)["encoding"]


def _mark_type(mark):
    return mark.get("type") if isinstance(mark, dict) else mark


# --- the defaults are the chart that existed before modifiers did -------------


def test_a_spec_with_no_modifiers_is_untouched():
    """The compatibility guarantee: every modifier defaults to off, and off has
    to mean *exactly* what the pipeline drew before any of this existed."""
    spec = _spec(_PARTS, {"type": "bar", "x": "region", "y": "revenue"})
    assert primary_layer(spec)["mark"] == "bar"
    assert _enc(spec)["x"] == {"field": "region", "type": "nominal"}
    assert _enc(spec)["y"]["field"] == "revenue"
    assert "stack" not in _enc(spec)["y"]
    assert spec["width"] == "container"
    assert "facet" not in spec


def test_form_defaults_match_the_plain_chart():
    form = Form.of({"type": "bar", "x": "a", "y": "b"})
    assert form.orientation == "vertical"
    assert form.distribution == "box"
    assert not form.replaces_mark
    assert form.draws_labels
    assert not form.is_faceted


# --- a modifier only exists on the types that can use it ----------------------


@pytest.mark.parametrize(
    "chart_spec, offender",
    [
        ({"type": "scatter", "x": "a", "y": "b", "stack": "zero"}, "stack"),
        ({"type": "pie", "x": "region", "y": "revenue", "orientation": "horizontal"}, "orientation"),
        ({"type": "heatmap", "x": "cls", "y": "grp", "color": "n", "interpolate": "step"}, "interpolate"),
        ({"type": "bar", "x": "region", "y": "revenue", "form": "violin"}, "form"),
        ({"type": "line", "x": "d", "y": "v", "bin": True}, "bin"),
    ],
)
def test_a_modifier_on_the_wrong_type_is_refused(chart_spec, offender):
    """`extra="forbid"` catches a misspelled modifier; only this catches a
    well-formed one aimed at a type with no use for it."""
    out = generate_chart(_PARTS, chart_spec)
    assert not out["valid"]
    assert offender in out["warnings"][0]


def test_the_refusal_names_what_the_type_does_accept():
    out = generate_chart(_XY, {"type": "scatter", "x": "a", "y": "b", "stack": "zero"})
    assert "size" in out["warnings"][0] and "facet" in out["warnings"][0]


def test_every_type_has_a_modifier_entry():
    """A type absent from CHART_MODIFIERS accepts nothing, silently — so a new
    type would arrive with its whole sub-type layer switched off and no error."""
    from autoviz.schema.allowlists import CHART_TYPES

    assert set(CHART_MODIFIERS) == set(CHART_TYPES)


# --- contradictory pairs ------------------------------------------------------


@pytest.mark.parametrize(
    "table, chart_spec, phrase",
    [
        (_NUM, {"type": "histogram", "x": "price", "density": True, "cumulative": True}, "one"),
        (_XY, {"type": "scatter", "x": "a", "y": "b", "bin": True, "color": "a"}, "colour"),
        (_PARTS, {"type": "bar", "x": "region", "y": "revenue", "stack": "normalize"}, "color column"),
        (_RAW, {"type": "boxplot", "x": "cls", "y": "v", "form": "violin", "facet": "cls"}, "violin"),
        (_RAW, {"type": "boxplot", "x": "cls", "y": "v", "form": "strip", "points": True}, "points"),
        (_GRID, {"type": "bar", "x": "cls", "y": "n", "color": "grp", "stack": "zero", "error": "bar"}, "stack"),
        (_GRID, {"type": "bar", "x": "cls", "y": "n", "color": "grp", "facet": "grp"}, "twice"),
    ],
)
def test_contradictory_modifiers_are_refused(table, chart_spec, phrase):
    out = generate_chart(table, chart_spec)
    assert not out["valid"]
    assert phrase in " ".join(out["warnings"])


# --- orientation --------------------------------------------------------------


def test_horizontal_swaps_the_positional_channels():
    spec = _spec(_PARTS, {"type": "bar", "x": "region", "y": "revenue", "orientation": "horizontal"})
    enc = _enc(spec)
    assert enc["x"]["field"] == "revenue"  # the measure
    assert enc["y"]["field"] == "region"   # the category


def test_a_horizontal_ranking_bar_sorts_on_the_axis_the_measure_moved_to():
    """The bug this guards: the sort is written before the swap in the vertical
    build, so a horizontal ranking chart came back claiming to be sorted while
    sorting the category axis by a channel that no longer held the measure."""
    spec = _spec(
        _PARTS,
        {"type": "bar", "x": "region", "y": "revenue", "intent": "ranking",
         "orientation": "horizontal"},
    )
    assert _enc(spec)["y"]["sort"] == "-x"


def test_a_vertical_ranking_bar_still_sorts_on_y():
    spec = _spec(_PARTS, {"type": "bar", "x": "region", "y": "revenue", "intent": "ranking"})
    assert _enc(spec)["x"]["sort"] == "-y"


def test_horizontal_grouped_bars_offset_across_the_category_axis():
    spec = _spec(
        _GRID,
        {"type": "grouped_bar", "x": "cls", "y": "n", "color": "grp",
         "orientation": "horizontal"},
    )
    enc = _enc(spec)
    assert "yOffset" in enc and "xOffset" not in enc


def test_a_horizontal_histogram_bins_down_the_page():
    spec = _spec(_NUM, {"type": "histogram", "x": "price", "orientation": "horizontal"})
    enc = _enc(spec)
    assert enc["y"]["bin"] is True
    assert enc["x"]["aggregate"] == "count"


def test_a_horizontal_histogram_brushes_the_binned_axis():
    """Brushing the count axis would select on a derived value that is in no
    row, leaving the table view nothing to filter by."""
    spec = _spec(_NUM, {"type": "histogram", "x": "price", "orientation": "horizontal"})
    brush = next(p for p in primary_layer(spec)["params"] if p["name"] == "autoviz_brush")
    assert brush["select"]["encodings"] == ["y"]


# --- stack --------------------------------------------------------------------


@pytest.mark.parametrize(
    "mode, expected", [("zero", "zero"), ("normalize", "normalize"), ("center", "center"), ("none", None)]
)
def test_stack_modes_reach_the_measure_channel(mode, expected):
    spec = _spec(_GRID, {"type": "bar", "x": "cls", "y": "n", "color": "grp", "stack": mode})
    assert _enc(spec)["y"]["stack"] == expected


def test_normalising_relabels_the_axis_as_a_share():
    """0.0-1.0 on an axis invites the reader to take the values as absolute,
    which is the one thing a 100% stack has stopped showing."""
    spec = _spec(_GRID, {"type": "bar", "x": "cls", "y": "n", "color": "grp", "stack": "normalize"})
    assert _enc(spec)["y"]["axis"]["format"] == ".0%"


def test_a_streamgraph_drops_the_wandering_axis():
    spec = _spec(_GRID, {"type": "area", "x": "cls", "y": "n", "color": "grp", "stack": "center"})
    assert _enc(spec)["y"]["axis"] is None


def test_horizontal_stacking_accumulates_along_x():
    spec = _spec(
        _GRID,
        {"type": "bar", "x": "cls", "y": "n", "color": "grp", "stack": "normalize",
         "orientation": "horizontal"},
    )
    enc = _enc(spec)
    assert enc["x"]["stack"] == "normalize"
    assert "stack" not in enc["y"]


# --- line and area shape ------------------------------------------------------


def test_interpolate_reaches_the_mark():
    spec = _spec(_TIME, {"type": "line", "x": "d", "y": "v", "interpolate": "step"})
    assert primary_layer(spec)["mark"]["interpolate"] == "step"


def test_linear_interpolation_leaves_the_mark_a_bare_name():
    spec = _spec(_TIME, {"type": "line", "x": "d", "y": "v", "interpolate": "linear"})
    assert primary_layer(spec)["mark"] == "line"


def test_points_marks_every_reading():
    spec = _spec(_TIME, {"type": "line", "x": "d", "y": "v", "points": True})
    assert primary_layer(spec)["mark"]["point"] is True


# --- scatter sub-types --------------------------------------------------------


def test_size_makes_a_bubble_chart():
    spec = _spec(_XY, {"type": "scatter", "x": "a", "y": "b", "size": "b"})
    assert _enc(spec)["size"]["field"] == "b"
    assert _enc(spec)["size"]["type"] == "quantitative"
    assert primary_layer(spec)["mark"]["filled"] is True


def test_a_bubble_stays_translucent_once_interaction_is_attached():
    """An opacity encoding overrides the mark's own opacity outright, so a
    bubble chart would be forced opaque the moment a brush was attached — and a
    bubble chart is nothing but overlaps."""
    spec = _spec(_XY, {"type": "scatter", "x": "a", "y": "b", "size": "b"})
    opacity = _enc(spec)["opacity"]
    assert opacity["condition"]["value"] == pytest.approx(0.7)


def test_bin_replaces_the_points_with_a_counted_grid():
    spec = _spec(_XY, {"type": "scatter", "x": "a", "y": "b", "bin": True})
    assert primary_layer(spec)["mark"] == "rect"
    enc = _enc(spec)
    assert enc["x"]["bin"]["maxbins"] > 1
    assert enc["y"]["bin"]["maxbins"] > 1
    assert enc["color"]["aggregate"] == "count"


def test_a_binned_scatter_is_not_brushable():
    """Its cells are aggregates, so a brush extent would name bin edges rather
    than the rows the table view has to index."""
    spec = _spec(_XY, {"type": "scatter", "x": "a", "y": "b", "bin": True})
    assert not any(
        p["name"] == "autoviz_brush" for p in primary_layer(spec).get("params", [])
    )


# --- histogram sub-types ------------------------------------------------------


def test_density_replaces_the_bars_with_a_curve():
    spec = _spec(_NUM, {"type": "histogram", "x": "price", "density": True})
    layer = primary_layer(spec)
    assert _mark_type(layer["mark"]) == "area"
    assert layer["transform"][0]["density"] == "price"


def test_cumulative_runs_a_window_count_over_the_sorted_column():
    spec = _spec(_NUM, {"type": "histogram", "x": "price", "cumulative": True})
    transform = primary_layer(spec)["transform"][0]
    assert transform["window"][0]["op"] == "count"
    assert transform["frame"] == [None, 0]


def test_a_density_curve_carries_no_hover_param():
    """A per-datum opacity condition on an area splits it into differently
    opaque segments rather than dimming it as one mark."""
    spec = _spec(_NUM, {"type": "histogram", "x": "price", "density": True})
    assert not primary_layer(spec).get("params")


# --- distribution forms -------------------------------------------------------


def test_violin_is_a_density_faceted_per_category():
    spec = _spec(_RAW, {"type": "boxplot", "x": "cls", "y": "v", "form": "violin"})
    root = chart_root(spec)
    assert root["mark"] == "area"
    assert root["encoding"]["column"]["field"] == "cls"
    assert root["encoding"]["x"]["stack"] == "center"
    assert root["transform"][0]["groupby"] == ["cls"]


def test_a_violin_is_sized_per_panel_not_by_its_container():
    """Vega-Lite ignores container sizing on anything faceted, so a violin that
    kept it would render at Vega's 200px default and never say why."""
    spec = _spec(_RAW, {"type": "boxplot", "x": "cls", "y": "v", "form": "violin"})
    assert isinstance(spec["width"], int)


def test_strip_draws_every_value_as_a_tick():
    spec = _spec(_RAW, {"type": "boxplot", "x": "cls", "y": "v", "form": "strip"})
    assert _mark_type(primary_layer(spec)["mark"]) == "tick"


def test_a_strip_is_hover_safe_where_a_box_is_not():
    """A box is a composite mark and Vega-Lite refuses params on it; ticks are
    ordinary discrete marks, so the family's blanket skip would cost a strip an
    interaction it can perfectly well have."""
    strip = _spec(_RAW, {"type": "boxplot", "x": "cls", "y": "v", "form": "strip"})
    box = _spec(_RAW, {"type": "boxplot", "x": "cls", "y": "v"})
    assert primary_layer(strip).get("params")
    assert not primary_layer(box).get("params")


def test_points_overlays_jittered_raw_values_on_a_box():
    spec = _spec(_RAW, {"type": "boxplot", "x": "cls", "y": "v", "points": True})
    overlay = spec["layer"][1]
    assert _mark_type(overlay["mark"]) == "point"
    assert overlay["transform"][0]["calculate"] == "random()"
    # Across the band only: displacing a point along the value axis would move
    # it to a value it does not have.
    assert "xOffset" in overlay["encoding"]
    assert overlay["encoding"]["y"]["field"] == "v"


# --- error intervals ----------------------------------------------------------


def test_an_error_band_is_layered_under_its_line():
    spec = _spec(_RAW, {"type": "line", "x": "cls", "y": "v", "error": "band"})
    assert _mark_type(spec["layer"][0]["mark"]) == "errorband"
    assert _mark_type(spec["layer"][1]["mark"]) == "line"


def test_error_bars_are_layered_over_their_bars():
    spec = _spec(_RAW, {"type": "bar", "x": "cls", "y": "v", "error": "bar"})
    assert _mark_type(spec["layer"][0]["mark"]) == "bar"
    assert _mark_type(spec["layer"][1]["mark"]) == "errorbar"


def test_the_primary_mark_takes_the_mean_the_interval_is_about():
    """The composite computes an interval around the mean of the raw rows, so a
    primary mark drawing anything else would put the interval somewhere the
    centre is not."""
    spec = _spec(_RAW, {"type": "line", "x": "cls", "y": "v", "error": "band"})
    assert primary_layer(spec)["encoding"]["y"]["aggregate"] == "mean"
    band = spec["layer"][0]
    assert "aggregate" not in band["encoding"]["y"]


def test_params_go_on_the_line_not_the_composite_beneath_it():
    """Vega-Lite refuses a selection param on a composite mark — and with a band
    the composite is layer 0, so anything assuming "the data layer is first"
    produces a spec that will not compile."""
    spec = _spec(_RAW, {"type": "line", "x": "cls", "y": "v", "error": "band"})
    assert "params" not in spec["layer"][0]
    assert _mark_type(primary_layer(spec)["mark"]) not in COMPOSITE_MARKS


# --- small multiples ----------------------------------------------------------


def test_facet_wraps_the_chart_under_a_facet_definition():
    spec = _spec(_GRID, {"type": "bar", "x": "cls", "y": "n", "facet": "grp"})
    assert spec["facet"]["field"] == "grp"
    assert spec["columns"] == DEFAULT_FACET_COLUMNS
    assert spec["spec"]["mark"] == "bar"
    assert spec["data"]["values"], "rows must stay at the top level for the table view"


def test_a_faceted_chart_sizes_its_panels_instead_of_its_container():
    spec = _spec(_GRID, {"type": "bar", "x": "cls", "y": "n", "facet": "grp"})
    assert "width" not in spec
    assert spec["spec"]["width"] == FACET_PANEL_WIDTH


def test_facet_columns_is_honoured():
    spec = _spec(_GRID, {"type": "bar", "x": "cls", "y": "n", "facet": "grp", "facet_columns": 2})
    assert spec["columns"] == 2


def test_too_many_panels_warns_but_still_renders():
    """Consistent with the pie and colour-cap ceilings: the chart is drawn and
    the problem is said out loud, rather than the request being refused."""
    rows = [{"k": f"k{i}", "v": float(i)} for i in range(MAX_FACETS + 4)]
    out = generate_chart(rows, {"type": "bar", "x": "k", "y": "v", "facet": "k"})
    assert out["valid"]
    assert any("panels" in w for w in out["warnings"])


def test_a_faceted_chart_carries_no_direct_labels():
    """A panel is 180px wide; values on bars that narrow overlap their
    neighbours before the second panel starts."""
    spec = _spec(_GRID, {"type": "bar", "x": "cls", "y": "n", "facet": "grp"})
    assert "layer" not in spec["spec"]


def test_export_accepts_a_faceted_spec():
    """Small multiples put the chart under `spec`, so the top level has neither
    `mark` nor `layer` — the two keys export.py used to require."""
    spec = _spec(_GRID, {"type": "bar", "x": "cls", "y": "n", "facet": "grp"})
    assert "error_code" not in export_chart(spec, "faceted")


# --- time units ---------------------------------------------------------------


def test_a_time_unit_buckets_a_heatmap_axis_as_an_ordinal():
    """Left temporal, Vega draws a date axis and the grid stops being a grid."""
    rows = [{"d": f"2024-0{m}-0{d}", "v": float(m * d)} for m in (1, 2) for d in (1, 2)]
    spec = _spec(
        rows,
        {"type": "heatmap", "x": "d", "y": "d", "color": "v",
         "time_unit": {"x": "yearmonth", "y": "date"},
         "column_types": {"d": "datetime", "v": "number"}},
    )
    enc = _enc(spec)
    assert enc["x"]["timeUnit"] == "yearmonth"
    assert enc["y"]["timeUnit"] == "date"
    assert enc["x"]["type"] == "ordinal"


# --- labels the sub-type must not draw ----------------------------------------


@pytest.mark.parametrize(
    "table, chart_spec",
    [
        (_GRID, {"type": "bar", "x": "cls", "y": "n", "color": "grp", "stack": "normalize"}),
        (_RAW, {"type": "bar", "x": "cls", "y": "v", "error": "bar"}),
        (_GRID, {"type": "bar", "x": "cls", "y": "n", "facet": "grp"}),
        (_XY, {"type": "scatter", "x": "a", "y": "b", "size": "b"}),
    ],
)
def test_sub_types_that_must_not_label_do_not(table, chart_spec):
    spec = _spec(table, chart_spec)
    root = chart_root(spec)
    labels = [
        layer for layer in root.get("layer", []) if _mark_type(layer.get("mark")) == "text"
    ]
    assert not labels


def test_a_plain_bar_still_labels():
    spec = _spec(_PARTS, {"type": "bar", "x": "region", "y": "revenue"})
    assert _mark_type(spec["layer"][1]["mark"]) == "text"


def test_a_horizontal_bar_labels_off_the_end_of_the_bar():
    """Reusing the vertical placement would park every value above its bar's own
    row, beside the wrong category."""
    spec = _spec(_PARTS, {"type": "bar", "x": "region", "y": "revenue", "orientation": "horizontal"})
    label = spec["layer"][1]
    assert label["mark"]["align"] == "left"
    assert "dy" not in label["mark"]


# --- retyping -----------------------------------------------------------------


def test_retyping_keeps_a_modifier_the_new_type_can_carry():
    schema = [{"name": "cls", "type": "string"}, {"name": "v", "type": "number"}]
    out = retype_chart_spec(
        {"type": "bar", "x": "cls", "y": "v", "orientation": "horizontal"}, "boxplot", schema
    )
    assert out["orientation"] == "horizontal"


def test_retyping_drops_a_modifier_the_new_type_cannot():
    """A `stack` left on a scatter is a plan the validator rejects, produced by
    a change the user made in one click and never typed."""
    schema = [{"name": "a", "type": "number"}, {"name": "b", "type": "number"}]
    out = retype_chart_spec(
        {"type": "bar", "x": "a", "y": "b", "color": "a", "stack": "normalize"}, "scatter", schema
    )
    assert "stack" not in out


# --- plan validation ----------------------------------------------------------
# generate_chart and the plan validator both police the modifiers, deliberately:
# a plan is checked before any SQL runs, and generate_chart is reachable directly
# over MCP with a hand-written chart spec that no plan validator ever saw.


def _plan(registry, dataset_id, chart, **extra):
    return validate_analysis_plan(
        dataset_id,
        {"dataset_id": dataset_id, "intent": "comparison", "chart": chart, **extra},
        registry,
    )


def test_an_unknown_modifier_is_rejected_at_parse_time(registry, titanic_id):
    """`extra="forbid"` on ChartSpec — a misspelling never reaches the semantic
    layer, so the error names the field rather than the data."""
    verdict = _plan(
        registry, titanic_id,
        {"type": "bar", "x": "pclass", "y": "fare", "orientaton": "horizontal"},
        select=["pclass", "fare"],
    )
    assert not verdict["valid"]


def test_a_misapplied_modifier_is_rejected_by_the_plan_validator(registry, titanic_id):
    verdict = _plan(
        registry, titanic_id,
        {"type": "scatter", "x": "age", "y": "fare", "stack": "normalize"},
        select=["age", "fare"],
    )
    assert not verdict["valid"]
    assert any("does not take stack" in e for e in verdict["errors"])


def test_a_horizontal_bar_validates(registry, titanic_id):
    verdict = _plan(
        registry, titanic_id,
        {"type": "bar", "x": "pclass", "y": "avg_fare", "orientation": "horizontal"},
        group_by=["pclass"],
        aggregations=[{"column": "fare", "fn": "mean", "as": "avg_fare"}],
    )
    assert verdict["valid"], verdict["errors"]


def test_error_over_an_aggregating_plan_is_rejected(registry, titanic_id):
    """Same trap as boxplot: one value per group gives an interval of zero
    width, and Vega-Lite draws it rather than complaining."""
    verdict = _plan(
        registry, titanic_id,
        {"type": "bar", "x": "pclass", "y": "avg_fare", "error": "bar"},
        group_by=["pclass"],
        aggregations=[{"column": "fare", "fn": "mean", "as": "avg_fare"}],
    )
    assert not verdict["valid"]
    assert any("zero width" in e for e in verdict["errors"])


def test_a_bubble_needs_a_numeric_size_column(registry, titanic_id):
    verdict = _plan(
        registry, titanic_id,
        {"type": "scatter", "x": "age", "y": "fare", "size": "sex"},
        select=["age", "fare", "sex"],
    )
    assert not verdict["valid"]
    assert any("chart.size" in e for e in verdict["errors"])


def test_a_facet_column_must_be_produced_by_the_query(registry, titanic_id):
    verdict = _plan(
        registry, titanic_id,
        {"type": "bar", "x": "pclass", "y": "fare", "facet": "embarked"},
        select=["pclass", "fare"],
    )
    assert not verdict["valid"]
    assert any("chart.facet" in e for e in verdict["errors"])


def test_a_modifier_survives_the_whole_pipeline(registry, titanic_id):
    """End to end, on a real dataset. The unit tests all call generate_chart
    directly; this is the one that would catch a modifier being dropped between
    the plan and the encoder — `plan.chart.model_dump` is what carries it, and
    nothing else asserts that it does."""
    piped = run_pipeline(
        titanic_id,
        {
            "dataset_id": titanic_id,
            "intent": "ranking",
            "group_by": ["class"],
            "aggregations": [{"column": "fare", "fn": "mean", "as": "avg_fare"}],
            "chart": {
                "type": "bar", "x": "class", "y": "avg_fare",
                "orientation": "horizontal",
            },
        },
        registry,
    )
    assert piped["status"] == "ok", piped
    enc = primary_layer(piped["vega_lite_spec"])["encoding"]
    assert enc["x"]["field"] == "avg_fare"
    assert enc["y"]["field"] == "class"
    assert enc["y"]["sort"] == "-x"


def test_forcing_a_type_drops_a_modifier_the_new_type_cannot_carry(registry, titanic_id):
    """The Setup panel's type buttons go through retype_chart_spec. A `stack`
    left behind on a scatter would be a chart the encoder refuses, from a change
    the user made in one click."""
    piped = run_pipeline(
        titanic_id,
        {
            "dataset_id": titanic_id,
            "intent": "comparison",
            "select": ["age", "fare"],
            "chart": {"type": "bar", "x": "age", "y": "fare", "orientation": "horizontal"},
        },
        registry,
        preferred_chart_type="scatter",
    )
    assert piped["status"] == "ok", piped
    assert piped["chart_spec"]["type"] == "scatter"
    assert "orientation" not in piped["chart_spec"]


def test_a_time_unit_on_a_non_date_channel_is_rejected(registry, titanic_id):
    """A timeUnit on a string column silently does nothing, which is exactly the
    class of failure this grammar exists to turn into an error."""
    verdict = _plan(
        registry, titanic_id,
        {"type": "bar", "x": "pclass", "y": "fare", "time_unit": {"x": "yearmonth"}},
        select=["pclass", "fare"],
    )
    assert not verdict["valid"]
    assert any("time_unit" in e for e in verdict["errors"])
