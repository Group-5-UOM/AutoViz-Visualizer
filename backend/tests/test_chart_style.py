"""Applying user style overrides to a generated spec (FR-15)."""

import pytest
from pydantic import ValidationError

from autoviz.schema.chart_style import ChartStyle
from autoviz.services.chart_style import apply, context_for
from autoviz.services.chart_theme import (
    BASE_FONT_SIZE,
    CATEGORICAL,
    FONT,
    FONT_STACKS,
    THEME,
)
from autoviz.services.charts import generate_chart, primary_layer

_ROWS = [
    {"species": "setosa", "avg": 5.0},
    {"species": "versicolor", "avg": 5.9},
    {"species": "virginica", "avg": 6.6},
]


def _bar():
    out = generate_chart(_ROWS, {"type": "bar", "x": "species", "y": "avg"})
    assert out["valid"], out
    return out["vega_lite_spec"]


def _coloured_bar():
    out = generate_chart(
        _ROWS, {"type": "bar", "x": "species", "y": "avg", "color": "species"}
    )
    assert out["valid"], out
    return out["vega_lite_spec"]


def test_hex_syntax_is_validated_but_nothing_else_is():
    """Any colour is allowed — the check is that it is a colour, not that it is
    a good one against the chart's white surface."""
    ChartStyle(mark_color="#ffff00")  # unreadable on white, and permitted
    ChartStyle(mark_color="#fff")
    with pytest.raises(ValidationError):
        ChartStyle(mark_color="orange")
    with pytest.raises(ValidationError):
        ChartStyle(mark_color="#12345")
    with pytest.raises(ValidationError):
        ChartStyle(nonsense="x")


def test_mark_colour_goes_on_the_layer_not_the_config():
    """config.mark.color would repaint the direct-label layer too."""
    styled = apply(_bar(), ChartStyle(mark_color="#eb6834"))
    assert primary_layer(styled)["mark"]["color"] == "#eb6834"
    assert styled["config"]["mark"]["color"] == CATEGORICAL[0]


def test_title_preserves_the_disclosure_subtitle():
    """The log-axis/skew caveat lives in title.subtitle so it survives into a
    saved dashboard. Renaming the chart must not erase it."""
    spec = _bar()
    spec["title"] = {"text": "", "subtitle": ["Plotted on a log scale."], "anchor": "start"}

    styled = apply(spec, ChartStyle(title="Sepal length by species"))
    assert styled["title"]["text"] == "Sepal length by species"
    assert styled["title"]["subtitle"] == ["Plotted on a log scale."]

    # And clearing the title leaves the caveat standing on its own.
    cleared = apply(styled, ChartStyle(title=None))
    assert cleared["title"]["subtitle"] == ["Plotted on a log scale."]


def test_title_is_dropped_entirely_when_there_is_nothing_to_say():
    styled = apply(_bar(), ChartStyle(title="Named"))
    assert apply(styled, ChartStyle()).get("title") is None


def test_axis_titles_set_and_revert():
    styled = apply(_bar(), ChartStyle(x_title="Species", y_title="Mean sepal length"))
    enc = primary_layer(styled)["encoding"]
    assert enc["x"]["title"] == "Species"
    assert enc["y"]["title"] == "Mean sepal length"

    reverted = apply(styled, ChartStyle())
    assert "title" not in primary_layer(reverted)["encoding"]["x"]


def test_series_colours_cover_every_series():
    """Naming one series must not drop the others off the scale."""
    styled = apply(_coloured_bar(), ChartStyle(series_colors={"setosa": "#ff0000"}))
    scale = primary_layer(styled)["encoding"]["color"]["scale"]
    assert scale["domain"] == ["setosa", "versicolor", "virginica"]
    assert scale["range"] == ["#ff0000", CATEGORICAL[1], CATEGORICAL[2]]


def test_series_colour_for_an_absent_series_is_ignored():
    """A block carried across a refinement may name series the new query does
    not produce; those entries simply do not apply."""
    styled = apply(
        _coloured_bar(), ChartStyle(series_colors={"setosa": "#ff0000", "gone": "#00ff00"})
    )
    scale = primary_layer(styled)["encoding"]["color"]["scale"]
    assert "gone" not in scale["domain"]
    assert "#00ff00" not in scale["range"]


def test_colour_scheme_replaces_the_palette_without_a_domain():
    styled = apply(_coloured_bar(), ChartStyle(color_scheme=["#111111", "#222222"]))
    scale = primary_layer(styled)["encoding"]["color"]["scale"]
    assert scale["range"] == ["#111111", "#222222"]
    assert "domain" not in scale


def test_reverting_colour_keeps_a_log_scale_someone_else_set():
    """services/skew.py writes a log scale onto this same encoding. Clearing a
    colour override must not quietly un-disclose the axis."""
    spec = _coloured_bar()
    primary_layer(spec)["encoding"]["color"]["scale"] = {"type": "log"}

    styled = apply(spec, ChartStyle(series_colors={"setosa": "#ff0000"}))
    reverted = apply(styled, ChartStyle())
    scale = primary_layer(reverted)["encoding"]["color"]["scale"]
    assert scale == {"type": "log"}


def test_legend_hidden_and_restored():
    styled = apply(_coloured_bar(), ChartStyle(legend=False))
    assert primary_layer(styled)["encoding"]["color"]["legend"] is None
    assert "legend" not in primary_layer(apply(styled, ChartStyle()))["encoding"]["color"]


def test_apply_is_idempotent_and_leaves_the_input_alone():
    """The block is the state, not the render — so re-applying it after every
    edit has to converge rather than compound."""
    spec = _coloured_bar()
    before = str(spec)
    style = ChartStyle(
        title="Chart", x_title="X", legend=False, series_colors={"setosa": "#ff0000"}
    )

    once = apply(spec, style)
    twice = apply(once, style)
    assert once == twice
    assert str(spec) == before


def test_apply_to_a_layered_spec_targets_the_data_layer():
    """Direct labels make the spec layered; the label layer must not be recoloured."""
    out = generate_chart(_ROWS, {"type": "pie", "x": "species", "y": "avg"})
    spec = out["vega_lite_spec"]
    if "layer" not in spec:
        pytest.skip("pie is not label-layered in this configuration")

    styled = apply(spec, ChartStyle(series_colors={"setosa": "#ff0000"}))
    assert styled["layer"][0]["encoding"]["color"]["scale"]["range"][0] == "#ff0000"
    assert "scale" not in styled["layer"][1]["encoding"].get("color", {})


def test_font_family_is_a_closed_set_resolved_to_a_stack():
    """A free-text family is a place for a planner to name a font nobody has."""
    styled = apply(_bar(), ChartStyle(font="mono"))
    assert styled["config"]["font"] == FONT_STACKS["mono"]

    with pytest.raises(ValidationError):
        ChartStyle(font="Helvetica")


def test_font_size_moves_every_text_size_by_the_same_step():
    """One number, because the theme's hierarchy — axis titles a step above tick
    labels — is a designed relationship and not something to set piecemeal."""
    styled = apply(_coloured_bar(), ChartStyle(font_size=16))
    config = styled["config"]
    delta = 16 - BASE_FONT_SIZE

    assert config["axis"]["labelFontSize"] == THEME["axis"]["labelFontSize"] + delta
    assert config["axis"]["titleFontSize"] == THEME["axis"]["titleFontSize"] + delta
    assert config["legend"]["labelFontSize"] == THEME["legend"]["labelFontSize"] + delta
    # The gap the theme set between tick labels and axis titles is preserved.
    assert (
        config["axis"]["titleFontSize"] - config["axis"]["labelFontSize"]
        == THEME["axis"]["titleFontSize"] - THEME["axis"]["labelFontSize"]
    )


def test_font_size_is_bounded():
    ChartStyle(font_size=8)
    ChartStyle(font_size=28)
    with pytest.raises(ValidationError):
        ChartStyle(font_size=7)
    with pytest.raises(ValidationError):
        ChartStyle(font_size=29)


def test_typography_reverts_to_the_theme_rather_than_being_deleted():
    """config already carries the theme by the time a block is applied, so an
    unset field has to write the theme's value back — dropping the key would
    leave the last override in place."""
    styled = apply(_bar(), ChartStyle(font="serif", font_size=20))
    reverted = apply(styled, ChartStyle())

    assert reverted["config"]["font"] == FONT
    assert reverted["config"]["axis"]["labelFontSize"] == THEME["axis"]["labelFontSize"]
    assert reverted["config"]["legend"]["titleFontSize"] == THEME["legend"]["titleFontSize"]
    # The theme sets no title size, so reverting removes the key entirely rather
    # than freezing whatever Vega-Lite's default happens to be.
    assert "fontSize" not in reverted["config"].get("title", {})


def test_typography_is_idempotent():
    spec = _coloured_bar()
    style = ChartStyle(font="mono", font_size=18)
    once = apply(spec, style)
    assert once == apply(once, style)


def test_applying_a_font_size_does_not_mutate_the_shared_theme():
    """attach() used to hand specs a live reference to THEME's nested dicts, so
    writing config.axis here would have resized every chart in the process."""
    before = dict(THEME["axis"])
    apply(_bar(), ChartStyle(font_size=24))
    assert THEME["axis"] == before


def test_merged_with_keeps_unmentioned_fields():
    base = ChartStyle(title="Kept", mark_color="#111111")
    merged = base.merged_with(ChartStyle.model_validate({"mark_color": "#222222"}))
    assert merged.title == "Kept"
    assert merged.mark_color == "#222222"

    # An explicit null is a revert, not an omission.
    cleared = base.merged_with(ChartStyle.model_validate({"title": None}))
    assert cleared.title is None
    assert cleared.mark_color == "#111111"


def test_context_for_names_the_series_a_user_can_talk_about():
    ctx = context_for(_coloured_bar())
    assert ctx["mark"] == "bar"
    assert ctx["color_field"] == "species"
    assert ctx["series"] == ["setosa", "versicolor", "virginica"]
    assert ctx["has_color_scale"] is True

    plain = context_for(_bar())
    assert plain["has_color_scale"] is False
