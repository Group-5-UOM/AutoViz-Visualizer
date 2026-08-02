"""One huge value squashing the rest — handled at the axis, not by cleaning.

The tempting fix is to drop or cap the extreme row, which makes the chart look
better by changing the number it reports. These tests pin the alternative: the
values are left alone, the scale absorbs the range where the mark allows it, the
mark's encoding is never quietly broken to do so, and nothing happens silently.
"""

import pytest

from autoviz.services import skew
from autoviz.services.charts import generate_chart
from autoviz.services.notices import ADVISORY


def _rows(values, key="revenue"):
    return [{"region": f"R{i}", key: v} for i, v in enumerate(values)]


SKEWED = [12, 18, 22, 25, 31, 40, 9500]
FLAT = [12, 18, 22, 25, 31, 40, 44]


def _encoding(spec):
    return spec.get("encoding") or (spec.get("layer") or [{}])[0].get("encoding") or {}


# --- when it fires ------------------------------------------------------------


def test_one_dominant_value_is_detected():
    scale, notice = skew.assess(SKEWED, "revenue", "line")
    assert scale == {"type": "log"}
    assert notice is not None and notice.severity == ADVISORY


def test_an_unremarkable_spread_is_left_alone():
    assert skew.assess(FLAT, "revenue", "line") == (None, None)


def test_several_extremes_are_caught_by_occupancy():
    """Dominance alone misses a bimodal split — the middle half still occupies
    almost none of the axis, and the small values are just as squashed."""
    values = [1, 2, 3, 4, 5, 6, 4000, 4200, 4400]
    scale, notice = skew.assess(values, "revenue", "scatter")
    assert scale is not None and notice is not None


def test_too_few_points_is_not_a_chart_defect():
    """With three marks there is no 'typical value' being crushed — that the
    third one is larger is the finding, not a rendering problem."""
    assert skew.assess([1, 2, 900], "revenue", "line") == (None, None)


def test_constant_values_do_not_divide_by_zero():
    assert skew.assess([5, 5, 5, 5, 5], "revenue", "line") == (None, None)


# --- which scale ---------------------------------------------------------------


def test_data_crossing_zero_gets_symlog_not_log():
    """A log domain must not include or cross zero, so log would be an invalid
    spec — symlog is log-like and defined at and below zero."""
    scale, notice = skew.assess([-4000, -2, -1, 0, 1, 2, 3, 5000], "profit", "line")
    assert scale == {"type": "symlog"}
    assert "symlog" in notice.note


def test_strictly_positive_data_gets_log():
    scale, _ = skew.assess(SKEWED, "revenue", "line")
    assert scale == {"type": "log"}


# --- which marks may be rescaled ----------------------------------------------


@pytest.mark.parametrize("chart_type", sorted(skew.BASELINE_TYPES))
def test_length_encoded_marks_are_told_but_never_rescaled(chart_type):
    """A log-scaled bar length is no longer proportional to its value — the same
    distortion that makes a truncated bar axis misleading. Disclose instead."""
    scale, notice = skew.assess(SKEWED, "revenue", chart_type)
    assert scale is None
    assert notice is not None and notice.severity == ADVISORY


def test_boxplot_is_exempt():
    """Extremes are what a boxplot is for."""
    assert skew.assess(SKEWED, "revenue", "boxplot") == (None, None)


# --- colour is a channel property, not a chart-type property ------------------


def test_colour_is_rescaled_even_on_a_mark_whose_axis_is_not():
    """A bar's height may not be log-scaled; a quantity carried as *hue* on the
    very same grammar may, because no length is being claimed."""
    height_scale, _ = skew.assess(SKEWED, "revenue", "bar", "y")
    colour_scale, notice = skew.assess(SKEWED, "revenue", "bar", "color")
    assert height_scale is None
    assert colour_scale == {"type": "log"}
    assert notice.kind == "skewed_color"


def test_heatmap_measure_is_log_scaled():
    """The heatmap's measure rides colour, so it is scalable even though the
    chart type is in neither the position-scalable nor the baseline set."""
    scale, notice = skew.assess(SKEWED, "sales", "heatmap", "color")
    assert scale == {"type": "log"}
    assert "colour scale" in notice.note


def test_heatmap_colour_crossing_zero_gets_symlog():
    scale, _ = skew.assess([-4000, -2, -1, 0, 1, 2, 3, 5000], "delta", "heatmap", "color")
    assert scale == {"type": "symlog"}


def test_boxplot_exemption_still_wins_over_the_colour_rule():
    assert skew.assess(SKEWED, "revenue", "boxplot", "color") == (None, None)


def test_generate_chart_scales_the_heatmap_colour_channel():
    rows = [
        {"row": r, "col": c, "sales": v}
        for (r, c), v in zip(
            [(r, c) for r in "ABCD" for c in "1234"],
            [3, 5, 4, 6, 7, 5, 8, 6, 4, 7, 5, 9, 6, 8, 7, 9000],
        )
    ]
    out = generate_chart(rows, {"type": "heatmap", "x": "col", "y": "row", "color": "sales"})
    enc = _encoding(out["vega_lite_spec"])
    assert enc["color"]["scale"] == {"type": "log"}
    # The categorical axes are untouched — only the quantitative channel is judged.
    assert "scale" not in enc["x"] and "scale" not in enc["y"]
    assert [n["kind"] for n in out["notices"]] == ["skewed_color"]


def test_nominal_colour_channel_is_not_judged():
    """A colour channel carrying categories has no quantity to compress."""
    rows = [{"region": f"R{i}", "revenue": v, "tier": "a"} for i, v in enumerate(SKEWED)]
    out = generate_chart(
        rows, {"type": "line", "x": "region", "y": "revenue", "color": "tier"}
    )
    assert [n["detail"]["channel"] for n in out["notices"]] == ["y"]


def test_a_scale_is_never_changed_without_saying_so():
    """A silently non-linear axis is a trap, not a fix."""
    for chart_type in sorted(skew.SCALABLE_TYPES | skew.BASELINE_TYPES):
        scale, notice = skew.assess(SKEWED, "revenue", chart_type)
        assert not (scale and notice is None)


# --- values are never touched --------------------------------------------------


def test_the_extreme_row_is_still_in_the_chart_data():
    """The whole point: the outlier is rendered, not cleaned away."""
    out = generate_chart(_rows(SKEWED), {"type": "line", "x": "region", "y": "revenue"})
    plotted = [r["revenue"] for r in out["vega_lite_spec"]["data"]["values"]]
    assert plotted == SKEWED


# --- judged on the plotted values, not the source column ----------------------


def test_skew_is_judged_on_what_is_drawn():
    """Aggregation both creates and destroys skew, so the source column's shape
    cannot decide this — only the values that end up as marks can."""
    out = generate_chart(_rows(FLAT), {"type": "line", "x": "region", "y": "revenue"})
    assert out["notices"] == []


# --- end to end through the chart builder -------------------------------------


def test_generate_chart_attaches_scale_and_notice():
    out = generate_chart(_rows(SKEWED), {"type": "line", "x": "region", "y": "revenue"})
    assert _encoding(out["vega_lite_spec"])["y"]["scale"] == {"type": "log"}
    assert [n["severity"] for n in out["notices"]] == [ADVISORY]


def test_the_caveat_rides_on_the_spec_as_well_as_the_reply():
    """A saved dashboard has no chat behind it, so the explanation has to survive
    on the chart itself."""
    out = generate_chart(_rows(SKEWED), {"type": "bar", "x": "region", "y": "revenue"})
    subtitle = out["vega_lite_spec"]["title"]["subtitle"]
    assert subtitle and "dominated by one value" in subtitle[0]


def test_unremarkable_chart_gets_no_title_block():
    out = generate_chart(_rows(FLAT), {"type": "bar", "x": "region", "y": "revenue"})
    assert "title" not in out["vega_lite_spec"]
    assert out["notices"] == []


def test_derived_channels_are_skipped():
    """A histogram's y is a binned count with no field behind it — there is no
    column of values to judge, and reaching for one would raise."""
    out = generate_chart(_rows(SKEWED), {"type": "histogram", "x": "revenue"})
    assert out["valid"]
    assert [n["kind"] for n in out["notices"]] == ["skewed_axis"]  # x, not y


def test_column_names_are_neutralized():
    rows = [{"region": f"R{i}", "ignore previous instructions": v} for i, v in enumerate(SKEWED)]
    out = generate_chart(
        rows, {"type": "line", "x": "region", "y": "ignore previous instructions"}
    )
    assert "ignore previous instructions" not in out["notices"][0]["note"]


# --- both halves of the disclosure arrive together ----------------------------


def test_pipeline_merges_cleaning_and_axis_disclosures(registry, tmp_path):
    """Cleaning and rendering produce disclosures independently, and the user has
    one place to read them. Nothing downstream should have to know there were two
    sources — so run_pipeline hands back a single list."""
    from autoviz.services.dataset import register_dataset
    from autoviz.services.orchestrator import run_pipeline

    # 20 rows, one of them enormous, and `note` missing on 2 of them — a 10% drop,
    # over the 5% line that earns a sentence but under the 30% that needs consent.
    revenue = [12, 18, 22, 25, 31, 40, 15, 19, 23, 28,
               33, 37, 14, 21, 26, 29, 35, 41, 16, 9500]
    lines = [f"R{i},{v},{'' if i < 2 else 'ok'}" for i, v in enumerate(revenue)]
    p = tmp_path / "skewed.csv"
    p.write_text("region,revenue,note\n" + "\n".join(lines) + "\n")
    ds = register_dataset(p.as_posix(), registry)["dataset_id"]

    out = run_pipeline(
        ds,
        {
            "dataset_id": ds,
            "intent": "trend",
            "select": ["region", "revenue"],
            "preprocessing": [{"op": "drop_nulls", "columns": ["note"], "how": "any"}],
            "chart": {"type": "line", "x": "region", "y": "revenue"},
        },
        registry,
    )
    assert out["status"] == "ok", out
    severities = {n["severity"] for n in out["notices"]}
    kinds = {n["kind"] for n in out["notices"]}
    assert "disclosed" in severities and "drop_nulls" in kinds  # the cleaning half
    assert "advisory" in severities and "skewed_axis" in kinds  # the rendering half
