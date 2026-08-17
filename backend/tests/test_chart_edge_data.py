"""Charts built from awkward data — the shapes real results actually arrive in.

Every existing chart test feeds well-formed data: several rows, all populated,
all positive. Real query results are not like that. A filter matches one row. A
measure is null for half the categories. A "net change" column is negative. A
count is zero.

We found four defects by rendering these cases through the real Vega runtime and
looking at what was drawn, and every one of them was **silent** — the spec was
structurally valid, `generate_chart` returned `valid: True`, and no warning was
raised:

* a line with a single point drew an invisible zero-length path;
* a pie with a negative value drew an arc sweeping *backwards*;
* a pie whose values summed to zero drew two arcs of zero width — a blank chart;
* an all-null measure drew **two full-height bars**, which is the worst of the
  four, because it does not look broken. It looks like an answer.

So this module holds the rule those defects share: **a chart must either draw
the data or say it cannot.** Drawing nothing, or drawing something that is not
the data, is the one outcome that is never acceptable — a blank panel gets
retried, but a confident wrong picture gets believed.

The last group is the counterweight. Negative bars, zero bars and identical bars
are all perfectly legitimate, and a guard that refused them would be worse than
the bug it replaced.
"""

import pytest

from autoviz.services.charts import generate_chart, primary_layer

_TWO_ROWS = [{"region": "north", "revenue": 300.0}, {"region": "south", "revenue": 1200.0}]


def _kinds(built: dict) -> set[str]:
    return {n["kind"] for n in built.get("notices", [])}


def _mark_type(spec: dict) -> str:
    mark = primary_layer(spec)["mark"]
    return mark["type"] if isinstance(mark, dict) else mark


# --- charts that would draw nothing at all -----------------------------------


def test_a_single_point_line_is_still_visible():
    """A line through one point is a zero-length path: it renders as a blank
    panel with axes. The datum has to be marked so there is something to see."""
    built = generate_chart(
        [{"month": "2026-01-01T00:00:00", "total": 5.0}],
        {"type": "line", "x": "month", "y": "total",
         "column_types": {"month": "datetime", "total": "number"}},
    )
    assert built["valid"], built["warnings"]
    mark = primary_layer(built["vega_lite_spec"])["mark"]
    assert isinstance(mark, dict) and mark.get("point"), (
        "a one-point line draws nothing without point markers"
    )


def test_a_normal_line_is_left_alone():
    """The fix above must not put dots on every line chart in the product."""
    built = generate_chart(
        [{"month": f"2026-{m:02d}-01T00:00:00", "total": m * 10.0} for m in range(1, 6)],
        {"type": "line", "x": "month", "y": "total",
         "column_types": {"month": "datetime", "total": "number"}},
    )
    mark = primary_layer(built["vega_lite_spec"])["mark"]
    assert mark == "line" or not (isinstance(mark, dict) and mark.get("point"))


@pytest.mark.parametrize("chart_type", ["pie", "donut"])
def test_an_arc_chart_whose_total_is_zero_is_refused(chart_type):
    """Every slice is a share of the total. A total of zero has no shares, and
    Vega draws two arcs of 0.00 radians — nothing at all, with no error."""
    built = generate_chart(
        [{"region": "north", "revenue": 0.0}, {"region": "south", "revenue": 0.0}],
        {"type": chart_type, "x": "region", "y": "revenue"},
    )
    assert not built["valid"]
    assert "zero" in " ".join(built["warnings"]).lower()


def test_a_measure_that_is_null_everywhere_is_not_plotted_as_data():
    """The worst of the four. Vega gave both bars the full plot height, so an
    empty result looked like two large equal values."""
    built = generate_chart(
        [{"region": "north", "revenue": None}, {"region": "south", "revenue": None}],
        {"type": "bar", "x": "region", "y": "revenue"},
    )
    assert built["valid"], built["warnings"]
    assert built["vega_lite_spec"]["data"]["values"] == []
    assert "unplottable_rows" in _kinds(built)


# --- charts that would draw the wrong thing ----------------------------------


@pytest.mark.parametrize("chart_type", ["pie", "donut"])
def test_an_arc_chart_with_a_negative_value_is_refused(chart_type):
    """A negative theta sweeps the arc backwards, and "share of a whole" has no
    meaning when a part is negative. Bars carry negatives correctly; arcs do
    not, so this declines and says which chart does work."""
    built = generate_chart(
        [{"region": "north", "revenue": -500.0}, {"region": "south", "revenue": 1200.0}],
        {"type": chart_type, "x": "region", "y": "revenue"},
    )
    assert not built["valid"]
    warning = " ".join(built["warnings"]).lower()
    assert "negative" in warning
    assert "bar" in warning, "a refusal should name the chart that would work"


def test_rows_with_no_value_are_dropped_and_the_drop_is_disclosed():
    """Vega-Lite drops these silently, which is how a category disappears from a
    chart with nothing on screen to say it ever existed."""
    built = generate_chart(
        [
            {"region": "north", "revenue": 300.0},
            {"region": "south", "revenue": None},
            {"region": "east", "revenue": 900.0},
        ],
        {"type": "bar", "x": "region", "y": "revenue"},
    )
    assert built["valid"], built["warnings"]
    values = built["vega_lite_spec"]["data"]["values"]
    assert [row["region"] for row in values] == ["north", "east"]
    assert "unplottable_rows" in _kinds(built)
    note = next(n for n in built["notices"] if n["kind"] == "unplottable_rows")
    assert "1" in note["note"], "the notice has to say how many rows went"


def test_a_null_in_the_category_also_counts_as_unplottable():
    built = generate_chart(
        [{"region": None, "revenue": 300.0}, {"region": "south", "revenue": 1200.0}],
        {"type": "bar", "x": "region", "y": "revenue"},
    )
    values = built["vega_lite_spec"]["data"]["values"]
    assert [row["region"] for row in values] == ["south"]
    assert "unplottable_rows" in _kinds(built)


def test_a_null_outside_the_charted_columns_is_not_a_reason_to_drop_a_row():
    """Only the columns this chart actually draws matter. A result often carries
    extra columns, and dropping a row for a null in one of those would delete
    data the chart was perfectly able to show."""
    built = generate_chart(
        [
            {"region": "north", "revenue": 300.0, "note": None},
            {"region": "south", "revenue": 1200.0, "note": "x"},
        ],
        {"type": "bar", "x": "region", "y": "revenue"},
    )
    assert len(built["vega_lite_spec"]["data"]["values"]) == 2
    assert "unplottable_rows" not in _kinds(built)


# --- data that is awkward but entirely legitimate ----------------------------
#
# The counterweight. Every guard above is a chance to refuse something real, and
# a chart tool that will not draw a negative number is worse than one that draws
# a bad pie.


def test_negative_values_on_a_bar_are_fine():
    """A bar has a baseline to go below. This is a profit-and-loss chart, not a
    defect, and the arc guard must not have leaked into it."""
    built = generate_chart(
        [{"region": "north", "revenue": -500.0}, {"region": "south", "revenue": 1200.0}],
        {"type": "bar", "x": "region", "y": "revenue"},
    )
    assert built["valid"], built["warnings"]
    assert len(built["vega_lite_spec"]["data"]["values"]) == 2


def test_zero_values_on_a_bar_are_fine():
    built = generate_chart(
        [{"region": "north", "revenue": 0.0}, {"region": "south", "revenue": 1200.0}],
        {"type": "bar", "x": "region", "y": "revenue"},
    )
    assert built["valid"], built["warnings"]
    assert "unplottable_rows" not in _kinds(built), "zero is a value, not a missing one"


def test_identical_values_are_fine():
    """A flat result is a real answer — every region sold the same amount."""
    built = generate_chart(
        [{"region": "north", "revenue": 700.0}, {"region": "south", "revenue": 700.0}],
        {"type": "bar", "x": "region", "y": "revenue"},
    )
    assert built["valid"], built["warnings"]


def test_a_single_row_bar_is_fine():
    built = generate_chart([{"region": "north", "revenue": 300.0}],
                           {"type": "bar", "x": "region", "y": "revenue"})
    assert built["valid"], built["warnings"]


def test_an_ordinary_chart_still_says_nothing():
    """The whole point of the disclosure channel: it stays quiet when there is
    nothing to disclose. A notice on every chart is a notice nobody reads."""
    built = generate_chart(_TWO_ROWS, {"type": "bar", "x": "region", "y": "revenue"})
    assert built["valid"], built["warnings"]
    assert built.get("notices") == []
