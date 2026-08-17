"""The recommender's buckets, and what happens when nothing lands in them.

Two reported defects — a comparison of two groups drawn as a scatter, and a time
trend drawn as a scatter — turned out to be one cause with two entry points.
`recommend_chart_type` sorts columns into measures / temporal / categorical and
every rule is guarded on those buckets. Two kinds of column were landing in the
wrong one:

  * an EXTRACTED date part (month 1-12) was typed "number", so `temporal` and
    `categorical` were both empty;
  * a numeric-coded category (pclass, survived) was only recognised as a class
    when it was a group_by key or `chart.color`, so a plan that merely selected
    it left `categorical` empty.

With both buckets empty every rule fell through to a terminal branch that did not
read `intent` at all, and answered every question with a scatter.

These tests pin the buckets, the terminal branch, and — just as importantly — the
cases that were already correct, since the fix moves type labels that a lot of
other behaviour reads.
"""

import pytest

from autoviz.services.charts import (
    ORDINAL,
    discrete_channel_columns,
    primary_layer,
    recommend_chart_type,
)
from autoviz.services.dataset import register_dataset
from autoviz.services.orchestrator import run_pipeline
from tests.conftest import data_path


@pytest.fixture()
def titanic(registry):
    """Has `pclass` (1/2/3) and `survived` (0/1) detected as coded categories."""
    return register_dataset(data_path("general-testing", "titanic.csv"), registry)["dataset_id"]


@pytest.fixture()
def weather(registry):
    return register_dataset(data_path("weather-climate", "seattle-weather.csv"), registry)[
        "dataset_id"
    ]


def _run(registry, dataset_id, **plan):
    return run_pipeline(dataset_id, {"dataset_id": dataset_id, **plan}, registry)


def _ok(registry, dataset_id, **plan):
    out = _run(registry, dataset_id, **plan)
    assert out["status"] == "ok", out
    return out


def _x(out):
    return primary_layer(out["vega_lite_spec"])["encoding"]["x"]


# --- the two reported failures ------------------------------------------------


@pytest.mark.parametrize("fn", ["month", "year", "day", "weekday"])
def test_a_trend_over_an_extracted_date_part_is_a_line(registry, weather, fn):
    """Reported as: "Time trend. Agent drew a scatter instead of a line."

    Extracting a date part gives a bare number, which used to empty both the
    temporal and the categorical bucket and drop the plan through every rule.
    """
    out = _ok(
        registry, weather,
        intent="trend",
        derive=[{"name": "p", "from": "date", "fn": fn}],
        group_by=["p"],
        aggregations=[{"column": "precipitation", "fn": "sum", "as": "total"}],
    )
    assert out["chart_spec"]["type"] == "line"
    assert _x(out)["field"] == "p"


def test_an_extracted_date_part_is_ordinal_not_quantitative(registry, weather):
    """Ordinal, so the axis keeps its order. A nominal month axis sorts as text
    and puts 10, 11, 12 before 2."""
    out = _ok(
        registry, weather,
        intent="trend",
        derive=[{"name": "m", "from": "date", "fn": "month"}],
        group_by=["m"],
        aggregations=[{"column": "precipitation", "fn": "sum", "as": "total"}],
    )
    assert _x(out)["type"] == "ordinal"


def test_a_comparison_over_a_coded_category_is_a_bar(registry, titanic):
    """Reported as: "Comparison of two groups. Agent drew a scatter."

    `pclass` is three classes stored as 1/2/3. It is only in `select` here — no
    group_by, no explicit chart — which is exactly the hole the old scoping left.
    """
    out = _ok(registry, titanic, intent="comparison", select=["pclass", "fare"])
    assert out["chart_spec"]["type"] == "bar"
    assert _x(out) == {"field": "pclass", "type": "nominal"}


# --- the same cause, two more symptoms ----------------------------------------


def test_a_coded_category_on_an_explicit_x_axis_is_discrete(registry, titanic):
    """Only `chart.color` was ever demoted, never `chart.x` — so an explicit bar
    of pclass put three passenger classes on a continuous 1-3 scale."""
    out = _ok(
        registry, titanic,
        intent="comparison", select=["pclass", "fare"],
        chart={"type": "bar", "x": "pclass", "y": "fare"},
    )
    assert _x(out)["type"] == "nominal"


def test_a_single_total_is_refused_rather_than_plotted_against_itself(registry, titanic):
    """One number was drawn as a scatter at (x, x) — a picture of nothing."""
    out = _run(
        registry, titanic,
        intent="comparison",
        aggregations=[{"column": "fare", "fn": "mean", "as": "avg_fare"}],
    )
    assert out["status"] == "error"
    assert out["failed_step"] == "recommend_chart_type"
    assert "single value" in out["errors"][0]


def test_a_refused_chart_still_carries_the_numbers(registry, titanic):
    """What makes the refusal safe: the agent turns a chart failure into a
    "partial" result rather than losing the answer, and this is the field it
    reads to do it."""
    out = _run(
        registry, titanic,
        intent="comparison",
        aggregations=[{"column": "fare", "fn": "mean", "as": "avg_fare"}],
    )
    assert out["result"]["result_table"] == [{"avg_fare": pytest.approx(32.2042, rel=1e-4)}]


# --- which channels count as discrete -----------------------------------------


@pytest.mark.parametrize(
    "chart_spec, expected",
    [
        ({"type": "bar", "x": "a", "y": "b"}, {"a"}),
        ({"type": "bar", "x": "a", "y": "b", "color": "c"}, {"a", "c"}),
        # Both axes are measures on a scatter — a coded column there is a number.
        ({"type": "scatter", "x": "a", "y": "b"}, set()),
        ({"type": "scatter", "x": "a", "y": "b", "color": "c"}, {"c"}),
        # A heatmap's colour is the measure, so it must NOT be demoted.
        ({"type": "heatmap", "x": "a", "y": "b", "color": "c"}, {"a", "b"}),
        # x is binned and y is a derived count.
        ({"type": "histogram", "x": "a"}, set()),
        # One panel per value is the definition of a class.
        ({"type": "bar", "x": "a", "y": "b", "facet": "f"}, {"a", "f"}),
        # Orientation moves the category to the other axis.
        ({"type": "bar", "x": "a", "y": "b", "orientation": "horizontal"}, {"b"}),
    ],
)
def test_discrete_channels_follow_the_chart_type(chart_spec, expected):
    assert discrete_channel_columns(chart_spec) == expected


def test_a_coded_category_on_a_scatter_axis_stays_a_measure(registry, titanic):
    """The precision that matters: pclass is three classes on a bar's x and a
    genuine number on a scatter's. Demoting it everywhere would be as wrong as
    demoting it nowhere."""
    out = _ok(
        registry, titanic,
        intent="relationship", select=["pclass", "fare"],
        chart={"type": "scatter", "x": "pclass", "y": "fare"},
    )
    assert _x(out)["type"] == "quantitative"


# --- the guard that keeps a measure ------------------------------------------


def test_a_coded_column_that_is_the_only_measure_stays_a_measure(registry, tmp_path):
    """`categorical_numeric` detection keys off how few distinct values a column
    has, so on a narrow result the *measure* gets flagged too. Demoting it left
    nothing to plot and the run failed with "no numeric column" — a worse answer
    than a continuous axis."""
    csv = tmp_path / "narrow.csv"
    csv.write_text("fare\n" + "\n".join(str(v) for v in (10, 20, 30, 40, 10, 20)))
    ds = register_dataset(str(csv), registry)["dataset_id"]
    assert "fare" in registry.get(ds).categorical_numeric, "fixture must trip the detector"

    out = _ok(registry, ds, intent="comparison", select=["fare"])
    # One measure over many rows: its distribution is the only thing to show.
    assert out["chart_spec"]["type"] == "histogram"


# --- the terminal branch now reads the intent ---------------------------------


def test_trend_with_only_measures_is_a_line_not_a_scatter():
    """Something will always slip past the bucketing; the terminal branch is the
    safety net, and it used to answer every question with a scatter."""
    schema = [{"name": "period", "type": "number"}, {"name": "revenue", "type": "number"}]
    assert recommend_chart_type(schema, "trend")["chart_type"] == "line"


def test_relationship_with_only_measures_is_still_a_scatter():
    schema = [{"name": "age", "type": "number"}, {"name": "fare", "type": "number"}]
    assert recommend_chart_type(schema, "relationship")["chart_type"] == "scatter"


def test_one_measure_over_many_rows_is_a_histogram():
    schema = [{"name": "fare", "type": "number"}]
    assert recommend_chart_type(schema, "comparison", row_count=500)["chart_type"] == "histogram"


def test_one_measure_over_one_row_is_no_chart():
    schema = [{"name": "avg_fare", "type": "number"}]
    assert "error" in recommend_chart_type(schema, "comparison", row_count=1)


def test_an_unknown_row_count_prefers_the_histogram():
    """A histogram of one value is a single bar — odd-looking, but not the lie a
    scatter of a column against itself is."""
    schema = [{"name": "fare", "type": "number"}]
    assert recommend_chart_type(schema, "comparison")["chart_type"] == "histogram"


# --- ordinals in the rules ----------------------------------------------------


def test_a_trend_puts_the_ordered_dimension_on_x():
    """With a series column and a month, the month is the axis. Taking
    categorical[0] regardless put whichever came back first on x."""
    schema = [
        {"name": "region", "type": "string"},
        {"name": "month", "type": ORDINAL},
        {"name": "total", "type": "number"},
    ]
    out = recommend_chart_type(schema, "trend")
    assert (out["chart_type"], out["x"], out["color"]) == ("line", "month", "region")


def test_an_ordinal_satisfies_the_ordinary_categorical_rules():
    """It is deliberately in both buckets: every rule that wants "a category to
    put on an axis" should see one."""
    schema = [{"name": "month", "type": ORDINAL}, {"name": "total", "type": "number"}]
    assert recommend_chart_type(schema, "ranking")["chart_type"] == "bar"
    assert recommend_chart_type(schema, "composition")["chart_type"] == "donut"


def test_an_ordinal_on_the_colour_channel_falls_back_to_nominal(registry, weather):
    """The theme registers its palette as `config.range.category`, which
    Vega-Lite applies to a *nominal* colour scale only. An ordinal one falls
    through to Vega's own scheme and the chart quietly stops using the app's
    colours."""
    out = _ok(
        registry, weather,
        intent="comparison",
        derive=[{"name": "m", "from": "date", "fn": "month"}],
        group_by=["m", "weather"],
        aggregations=[{"column": "precipitation", "fn": "sum", "as": "total"}],
        chart={"type": "bar", "x": "weather", "y": "total", "color": "m"},
    )
    assert primary_layer(out["vega_lite_spec"])["encoding"]["color"]["type"] == "nominal"


# --- what must not have moved -------------------------------------------------


def test_a_truncated_month_is_still_temporal(registry, weather):
    """The truncate/extract line is the whole reason the two derive families
    exist; a fix to one must not swap the other."""
    out = _ok(
        registry, weather,
        intent="trend",
        derive=[{"name": "m", "from": "date", "fn": "month_start"}],
        group_by=["m"],
        aggregations=[{"column": "precipitation", "fn": "sum", "as": "total"}],
    )
    assert out["chart_spec"]["type"] == "line"
    assert _x(out)["type"] == "temporal"


def test_grouping_by_a_coded_category_still_gives_a_bar(registry, titanic):
    out = _ok(
        registry, titanic,
        intent="comparison", group_by=["survived"],
        aggregations=[{"column": "fare", "fn": "mean", "as": "avg_fare"}],
    )
    assert out["chart_spec"]["type"] == "bar"
    assert _x(out)["type"] == "nominal"


def test_two_genuine_measures_still_scatter(registry, titanic):
    out = _ok(registry, titanic, intent="relationship", select=["age", "fare"])
    assert out["chart_spec"]["type"] == "scatter"
    assert _x(out)["type"] == "quantitative"


def test_round_and_abs_are_still_plain_numbers(registry, titanic):
    """Only the *date* extracts became ordinal — the numeric derives share the
    branch they were split out of."""
    out = _ok(
        registry, titanic,
        intent="relationship",
        derive=[{"name": "r", "from": "fare", "fn": "round"}],
        select=["age", "fare"],
        chart={"type": "scatter", "x": "r", "y": "age"},
    )
    assert _x(out)["type"] == "quantitative"
