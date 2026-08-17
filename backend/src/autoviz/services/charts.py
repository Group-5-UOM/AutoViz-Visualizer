"""Chart services: rule-based type recommendation + Vega-Lite spec generation.

recommend_chart_type scores intent x column types x cardinality (the hybrid
recommender's rule layer, Proposal §4.6); generate_chart builds and
structurally validates the Vega-Lite spec.
"""

from typing import Any

from autoviz.errors import NO_CHART_FIT, make_error
from autoviz.schema.allowlists import (
    CHART_MODIFIERS,
    CHART_TYPES,
    MAX_SERIES_ADJACENT,
    MAX_SERIES_ALL_PAIRS,
)
from autoviz.services import chart_modifiers, skew
from autoviz.services.chart_interaction import attach as attach_interaction
from autoviz.services.chart_labels import build_label_layer
from autoviz.services.chart_modifiers import COMPOSITE_MARKS, Form
from autoviz.services.chart_theme import attach as attach_theme
from autoviz.services.notices import ADVISORY, Notice
from autoviz.vega import VEGA_LITE_SCHEMA

_VEGA_MARK = {
    "bar": "bar",
    "line": "line",
    "scatter": "point",
    "pie": "arc",
    "area": "area",
    "histogram": "bar",  # binned bar over one numeric column
    "heatmap": "rect",  # grid of categories; colour carries the measure
    "boxplot": "boxplot",  # composite mark — Vega-Lite computes the quartiles
    "grouped_bar": "bar",  # bar + xOffset; a plain bar + colour stacks instead
    "donut": "arc",
}

_PIE_MAX_CATEGORIES = 6

# Arc charts: category on colour, measure on theta.
_ARC_TYPES = frozenset({"pie", "donut"})

# Forms where any two series can end up adjacent, so the colour ceiling is the
# stricter all-pairs one.
_ALL_PAIRS_TYPES = frozenset({"scatter"})

# Channels each type needs beyond the default x+y.
_REQUIRED_CHANNELS: dict[str, tuple[str, ...]] = {
    "histogram": ("x",),
    "heatmap": ("x", "y", "color"),
    "grouped_bar": ("x", "y", "color"),
}


# A discrete dimension whose values have a meaningful order: month 1-12, a
# weekday, a year. Sorted with the categoricals — every rule that wants "a
# category to put on an axis" should see one — but tracked separately, because a
# trend belongs on the *ordered* one and Vega-Lite must not sort it as text.
ORDINAL = "ordinal"

# Channels that carry a discrete class rather than a measure, per chart type.
#
# Exists so the orchestrator can decide whether a numeric-coded category
# (pclass, survived) is acting as a class on *this* chart. It cannot be answered
# per column — pclass is three classes on a bar's x axis and a genuine number on
# a scatter's — so it is answered per channel, here, next to the types it
# describes.
_DISCRETE_CHANNELS: dict[str, frozenset[str]] = {
    "bar": frozenset({"x", "color"}),
    "grouped_bar": frozenset({"x", "color"}),
    "line": frozenset({"x", "color"}),
    "area": frozenset({"x", "color"}),
    "pie": frozenset({"x", "color"}),
    "donut": frozenset({"x", "color"}),
    "boxplot": frozenset({"x", "color"}),
    "heatmap": frozenset({"x", "y"}),  # colour is the measure on a heatmap
    "scatter": frozenset({"color"}),   # both axes are measures
    "histogram": frozenset({"color"}), # x is binned, y is a derived count
}


def discrete_channel_columns(chart_spec: dict[str, Any]) -> set[str]:
    """Columns this chart puts on a discrete channel.

    `facet` is always discrete — one panel per value is the definition of a
    class. Orientation moves which *axis* holds the category, so the answer
    follows the swap rather than assuming the vertical layout.
    """
    channels = _DISCRETE_CHANNELS.get(chart_spec.get("type"))
    if channels is None:
        return set()
    if chart_spec.get("orientation") == "horizontal":
        flip = {"x": "y", "y": "x"}
        channels = frozenset(flip.get(c, c) for c in channels)
    cols = {chart_spec[c] for c in channels if chart_spec.get(c)}
    if chart_spec.get("facet"):
        cols.add(chart_spec["facet"])
    return cols


def _split_columns(result_schema: list[dict[str, str]]):
    """Sort the result's columns into the buckets the rules are written against.

    Returns ``(numeric, temporal, categorical, ordered)``. ``ordered`` is the
    subset of ``categorical`` whose values have a sequence — it is deliberately
    *in* both, so an ordinal satisfies every existing "is there a category?"
    rule while still being identifiable as the right x for a trend.
    """
    numeric = [c["name"] for c in result_schema if c["type"] == "number"]
    temporal = [c["name"] for c in result_schema if c["type"] == "datetime"]
    categorical = [
        c["name"] for c in result_schema if c["type"] not in ("number", "datetime")
    ]
    ordered = [c["name"] for c in result_schema if c["type"] == ORDINAL]
    return numeric, temporal, categorical, ordered


def recommend_chart_type(
    result_schema: list[dict[str, str]], intent: str, row_count: int | None = None
) -> dict[str, Any]:
    """Pick a chart for this result shape and this question.

    ``row_count`` separates the two shapes a schema alone cannot tell apart: one
    measure over many rows (a column of fares — its distribution is the chart)
    from one measure over one row (a single total — not a chart at all). Optional
    so existing callers keep working; without it the first reading is assumed,
    because it is the one whose wrong answer is merely odd rather than false.

    **Intent is the question; the column types only decide how to answer it.**
    Every branch below is guarded on the types, and for a long time the terminal
    fallback was not guarded on anything — so whenever the temporal and
    categorical buckets both came up empty, a *trend* request was answered with
    a scatter whose rationale did not even mention that a trend was asked for.
    The fix is in two halves and both matter:

    * upstream, the buckets are filled correctly — an extracted month is an
      ordinal, not a number, and a numeric-coded category is a class (see
      `ORDINAL` and `discrete_channel_columns`);
    * here, the terminal case reads `intent` like every other branch, because
      something will always slip past the bucketing and a scatter is not a
      neutral default. It is the answer to one specific question.
    """
    numeric, temporal, categorical, ordered = _split_columns(result_schema)

    if not numeric:
        return make_error(
            NO_CHART_FIT, "No numeric column in the result to plot as a measure"
        )

    y = numeric[0]
    color = None

    if intent == "trend" and temporal:
        chart_type, x = "line", temporal[0]
        rationale = f"Trend intent with temporal column '{x}' — line chart shows change over time."
        if categorical:
            color = categorical[0]
    elif intent == "trend" and categorical:
        # An ordered dimension is the x axis a trend wants — a month or a year
        # runs along the axis, where an unordered category merely sits on it.
        # Taking categorical[0] regardless put the series column on x whenever
        # it happened to come back first.
        x = ordered[0] if ordered else categorical[0]
        chart_type = "line"
        kind = "ordered" if ordered else "sequential"
        rationale = f"Trend intent over {kind} dimension '{x}' — line chart."
        others = [c for c in categorical if c != x]
        if others:
            color = others[0]
    elif intent == "relationship" and len(numeric) >= 2:
        chart_type, x, y = "scatter", numeric[0], numeric[1]
        rationale = "Relationship intent with two numeric columns — scatter shows correlation."
        if categorical:
            color = categorical[0]
    elif intent == "composition" and categorical:
        # Donut over pie: the centre hole removes the wedge-area comparison that
        # makes pies hard to read. `pie` stays available if asked for by name.
        chart_type, x = "donut", categorical[0]
        rationale = f"Composition intent over '{x}' — donut shows part-to-whole shares."
    elif intent == "ranking" and categorical:
        chart_type, x = "bar", categorical[0]
        rationale = f"Ranking intent — sorted bar chart over '{x}'."
    elif intent in ("distribution", "relationship") and len(categorical) >= 2:
        # Two categories crossed with a measure is a grid, and a grid is a
        # heatmap — the shape MAX_GROUP_BY = 2 already produces.
        chart_type, x, y, color = "heatmap", categorical[0], categorical[1], numeric[0]
        rationale = (
            f"Two categorical columns crossed with '{color}' — heatmap grid of "
            f"'{x}' by '{y}', colour carrying the measure."
        )
    elif intent == "distribution" and not categorical:
        chart_type, x = "histogram", numeric[0]
        rationale = f"Distribution intent over numeric '{x}' — histogram of binned counts."
    elif intent == "distribution":
        chart_type = "bar"
        x = categorical[0]
        rationale = f"Distribution intent — bar chart of counts over '{x}'."
    elif len(categorical) >= 2:
        # Side by side, not stacked: a plain bar with a colour channel stacks,
        # which answers part-to-whole rather than "compare these series".
        chart_type, x = "grouped_bar", categorical[0]
        color = categorical[1]
        rationale = (
            f"Comparison across '{x}' split by '{color}' — grouped bars sit side "
            f"by side so the series can be compared directly."
        )
    elif categorical:
        chart_type, x = "bar", categorical[0]
        rationale = f"Comparison across categories of '{x}' — bar chart."
    elif temporal:
        chart_type, x = "line", temporal[0]
        rationale = f"Temporal column '{x}' available — line chart."
    elif intent == "trend" and len(numeric) >= 2:
        # Nothing discrete and nothing temporal, but a trend was still asked for:
        # the sequence must be one of the measures (a raw year column, a period
        # index). A line over it answers the question; a scatter does not.
        chart_type, x, y = "line", numeric[0], numeric[1]
        rationale = (
            f"Trend intent with no date or category — line over numeric '{x}', "
            "which is the only column that can carry a sequence here."
        )
    elif len(numeric) >= 2:
        chart_type, x, y = "scatter", numeric[0], numeric[1]
        rationale = (
            "Only measures available and no dimension to break them down by — "
            "scatter shows how the two relate."
        )
    elif row_count == 1:
        # One measure, one row: a single number. The old fallback plotted it
        # against itself — a scatter of one point at (x, x) — which is a picture
        # of nothing. Refusing is the honest answer and costs the caller nothing:
        # a chart failure downgrades the run to "partial" with the result table
        # intact, so the number still reaches the user.
        return make_error(
            NO_CHART_FIT,
            f"'{numeric[0]}' is a single value with nothing to plot it against — "
            "the number is the whole answer. Group by a column to chart it.",
        )
    else:
        # One measure over many rows: its distribution is the only thing there is
        # to show. Reached when `row_count` is unknown too, because a histogram of
        # one value is a single bar — wrong-looking, but not a lie the way a
        # scatter of a column against itself is.
        chart_type, x = "histogram", numeric[0]
        rationale = (
            f"One measure and nothing to break it down by — histogram of '{x}'."
        )

    result: dict[str, Any] = {
        "chart_type": chart_type,
        "x": x,
        "rationale": rationale,
    }
    if chart_type != "histogram":  # histogram's y is the binned count, not a column
        result["y"] = y
    if color:
        result["color"] = color
    return result


# The column role each chart type needs on (x, y, color). "num" is a measure,
# "cat" a discrete class, "dim" either a time axis or a category; None means the
# type does not use that channel. This is the same knowledge
# `recommend_chart_type` applies when it is choosing — stated as a table because
# retyping has to run it backwards, from a wanted type to the columns for it.
_TYPE_ROLES: dict[str, tuple[str, str | None, str | None]] = {
    "bar": ("dim", "num", None),
    "line": ("dim", "num", None),
    "area": ("dim", "num", None),
    "pie": ("cat", "num", None),
    "donut": ("cat", "num", None),
    "scatter": ("num", "num", None),
    "histogram": ("num", None, None),  # y is the binned count, not a column
    "boxplot": ("dim", "num", None),
    "grouped_bar": ("cat", "num", "cat"),
    "heatmap": ("cat", "cat", "num"),
}


def _role_pool(
    role: str, numeric: list[str], temporal: list[str], categorical: list[str]
) -> list[str]:
    if role == "num":
        return numeric
    if role == "cat":
        return categorical
    return [*temporal, *categorical]  # "dim": a time axis first, else a category


def retype_chart_spec(
    chart_spec: dict[str, Any], chart_type: str, result_schema: list[dict[str, str]]
) -> dict[str, Any] | None:
    """`chart_spec` redrawn as `chart_type`, or None if these columns cannot carry it.

    Exists for the case where the user picked a type outright instead of letting
    the recommendation stand. A type is not just a mark swap — a histogram has no
    y, a heatmap needs a measure on colour — so the channels are reassigned by
    role rather than carried over blindly.

    Returning None is the honest answer, not a failure: asking for a scatter of
    one numeric column, or a pie with nothing to slice by, describes a chart that
    does not exist. The caller keeps the recommendation and the substitution is
    disclosed to the user.
    """
    roles = _TYPE_ROLES.get(chart_type)
    if roles is None:
        return None
    if chart_spec.get("type") == chart_type:
        return dict(chart_spec)

    # `ordered` is unused here: an ordinal is already in `categorical`, which is
    # the pool a "dim" or "cat" role draws from.
    numeric, temporal, categorical, _ordered = _split_columns(result_schema)
    # Modifiers survive a retype wherever the new type can carry them — turning a
    # horizontal bar into a horizontal box plot should stay on its side — and are
    # dropped where it cannot, because a `stack` left on a scatter is a plan the
    # validator rejects from a change the user made in one click.
    kept = chart_modifiers.strip_unsupported(chart_spec, chart_type)
    retyped = {k: v for k, v in kept.items() if k not in ("x", "y", "color")}
    retyped["type"] = chart_type
    used: set[str] = set()
    for channel, role in zip(("x", "y", "color"), roles):
        if role is None:
            continue
        # Each channel needs its own column: a scatter of one number against
        # itself, or a heatmap gridded on one category twice, is not the chart
        # that was asked for.
        pool = [c for c in _role_pool(role, numeric, temporal, categorical) if c not in used]
        if not pool:
            return None
        # Keep what the spec already had wherever it still suits the role, so a
        # swap moves as little as possible and the axes stay recognisable.
        current = chart_spec.get(channel)
        pick = current if current in pool else pool[0]
        retyped[channel] = pick
        used.add(pick)
    return retyped


def _encoding_type(values: list[Any], column_schema: dict[str, str] | None, name: str) -> str:
    if column_schema and name in column_schema:
        # ORDINAL rather than nominal for an ordered dimension: a month axis
        # sorted as text puts 10, 11, 12 before 2, and a nominal scale is exactly
        # what would do that.
        return {"number": "quantitative", "datetime": "temporal", ORDINAL: "ordinal"}.get(
            column_schema[name], "nominal"
        )
    non_null = [v for v in values if v is not None]
    if non_null and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in non_null):
        return "quantitative"
    return "nominal"


def _mark_type(mark: Any) -> str:
    if isinstance(mark, dict):
        return str(mark.get("type", ""))
    return str(mark or "")


def chart_root(spec: dict[str, Any]) -> dict[str, Any]:
    """The frame a generated spec actually draws in.

    Faceted specs put the chart one level down under `spec`, so the top level
    carries the facet definition and nothing else a reader of the encoding
    wants. Everything looking for marks has to come through here first.
    """
    inner = spec.get("spec")
    return inner if isinstance(inner, dict) else spec


def primary_layer(spec: dict[str, Any]) -> dict[str, Any]:
    """The data layer of a generated spec — its `mark` and `encoding`.

    A spec that carries direct labels is layered, so `mark` and `encoding` sit
    one level down; a faceted one puts them lower still. Anything reading a
    generated spec's encoding should go through here rather than assuming a unit
    spec.

    Composite layers are skipped rather than counted. An error band is drawn
    *under* its line, so with `error: "band"` the first layer is the composite —
    and returning it would hand the caller the mark Vega-Lite refuses to attach
    a selection param to, which is the one thing this accessor exists to find.
    """
    root = chart_root(spec)
    layers = root.get("layer")
    if not layers:
        return root
    for layer in layers:
        if _mark_type(layer.get("mark")) not in COMPOSITE_MARKS:
            return layer
    return layers[0]


def _mark_def(chart_type: str, row_count: int = 2) -> Any:
    """The Vega-Lite mark, as a bare name or a mark definition object."""
    if chart_type in ("line", "area") and row_count < 2:
        # A line through one point is a zero-length path: the panel renders with
        # axes and nothing in it, and nothing anywhere says why. Marking the
        # datum is the difference between "no data" and "one data point", which
        # are very different answers to have got.
        return {"type": chart_type, "point": True}
    if chart_type == "donut":
        # Derived from the view, not an absolute pixel count: charts size from
        # their container, so a literal innerRadius inverts at small widths.
        return {"type": "arc", "innerRadius": {"expr": "min(width, height) / 5"}}
    if chart_type == "boxplot":
        # Vega-Lite rejects selection params on composite marks, so a mark
        # tooltip is the only way to surface the quartiles it computes.
        #
        # It has to go on the *sub-parts*, not on the composite mark: `BoxPlotDef`
        # sets additionalProperties:false and has no `tooltip`, so a top-level
        # `tooltip: true` made every boxplot spec non-conformant against the
        # Vega-Lite v6 schema — and bought no tooltip for it. `box` carries the
        # quartiles and `outliers` the individual points, which are the two parts
        # a reader hovers. Caught by bench/chart_quality.py.
        return {
            "type": "boxplot",
            "extent": 1.5,
            "box": {"tooltip": True},
            "outliers": {"tooltip": True},
        }
    return _VEGA_MARK[chart_type]


def generate_chart(
    result_table: list[dict[str, Any]], chart_spec: dict[str, Any]
) -> dict[str, Any]:
    chart_type = chart_spec.get("type")
    if chart_type not in CHART_TYPES:
        return {
            "vega_lite_spec": None,
            "valid": False,
            "warnings": [f"chart type '{chart_type}' is not in the allow-list {sorted(CHART_TYPES)}"],
        }

    # Sub-type modifiers are checked here as well as in plan validation, because
    # generate_chart is reachable directly over MCP with a hand-written chart
    # spec that no plan validator ever saw.
    misapplied = chart_modifiers.unsupported_modifiers(chart_spec)
    if misapplied:
        return {
            "vega_lite_spec": None,
            "valid": False,
            "warnings": [
                f"chart type '{chart_type}' does not take modifier(s): "
                f"{', '.join(misapplied)} (it accepts "
                f"{', '.join(sorted(CHART_MODIFIERS[chart_type])) or 'none'})"
            ],
        }
    conflicts = chart_modifiers.modifier_conflicts(chart_spec)
    if conflicts:
        return {"vega_lite_spec": None, "valid": False, "warnings": conflicts}

    form = Form.of(chart_spec)
    columns = set(result_table[0].keys()) if result_table else set()
    warnings: list[str] = []
    # An empty result is not a chart error — the query ran and matched nothing,
    # which is a real answer. But it is also not a chart anybody can read, and
    # until this notice existed the axes rendered as usual and the emptiness was
    # left for the user to infer from a blank panel. Say it instead.
    empty_notices: list[Notice] = []
    if not result_table:
        empty_notices.append(
            Notice(
                kind="empty_result",
                severity=ADVISORY,
                note=(
                    "This query matched no rows, so the chart is empty. The filters "
                    "are the usual cause — a value spelled differently from the data, "
                    "or a date range outside it."
                ),
                detail={"row_count": 0},
            )
        )
    # `size` and `facet` name columns too, so they are checked for existence and
    # for nulls alongside the positional channels — a facet on a column with
    # missing values would otherwise draw a silent "null" panel.
    channels = {
        k: chart_spec.get(k)
        for k in ("x", "y", "color", "size", "facet")
        if chart_spec.get(k)
    }
    missing = [f"{ch} -> '{col}'" for ch, col in channels.items() if columns and col not in columns]
    if missing:
        return {
            "vega_lite_spec": None,
            "valid": False,
            "warnings": [f"chart channel references absent column(s): {', '.join(missing)}"],
        }

    required = _REQUIRED_CHANNELS.get(chart_type, ("x", "y"))
    absent = [ch for ch in required if ch not in channels]
    if absent:
        return {
            "vega_lite_spec": None,
            "valid": False,
            "warnings": [f"chart type '{chart_type}' requires channel(s): {', '.join(absent)}"],
        }

    # A row missing a value in a column this chart draws cannot be plotted, and
    # Vega-Lite drops it without a word — which is how a category disappears from
    # a chart with nothing on screen to say it was ever there. Worse, when *every*
    # value is missing the bars are drawn at full plot height, so an empty result
    # looks like several large equal ones. Drop them here instead, and say so.
    #
    # Only the charted columns count. A result often carries extra columns, and
    # dropping a row for a null in one the chart never touches would delete data
    # it was perfectly able to show.
    plotted = [
        row for row in result_table
        if all(row.get(col) is not None for col in channels.values())
    ]
    dropped = len(result_table) - len(plotted)
    if dropped:
        result_table = plotted
        empty_notices.append(
            Notice(
                kind="unplottable_rows",
                severity=ADVISORY,
                note=(
                    f"{dropped} row(s) had no value in the columns this chart draws, "
                    "so they are not on it. The chart shows the rest."
                ),
                detail={"dropped_rows": dropped, "columns": sorted(channels.values())},
            )
        )

    schema_hint = chart_spec.get("column_types")  # optional {name: logical_type}

    def enc(col: str) -> dict[str, Any]:
        values = [row.get(col) for row in result_table]
        return {"field": col, "type": _encoding_type(values, schema_hint, col)}

    def series_enc(col: str) -> dict[str, Any]:
        """A colour or offset channel — a series, never a position.

        Ordinal is right on an axis and wrong here: the theme's palette is
        registered as `config.range.category`, which Vega-Lite applies to a
        *nominal* colour scale only. An ordinal one falls through to Vega's own
        ordered scheme, and the chart quietly stops using the app's colours —
        the exact defect Docs/13 §5 already records for single-series charts.
        """
        field_def = enc(col)
        if field_def["type"] == "ordinal":
            return {**field_def, "type": "nominal"}
        return field_def

    if chart_type == "histogram":
        if "y" in channels:
            return {
                "vega_lite_spec": None,
                "valid": False,
                "warnings": ["histogram takes no y column — y is the binned count"],
            }
        encoding = {
            "x": {"field": channels["x"], "type": "quantitative", "bin": True},
            "y": {"aggregate": "count", "type": "quantitative"},
        }
    elif chart_type in _ARC_TYPES:
        # An arc chart says "these are the parts of one whole", and the geometry
        # takes that literally: each slice's angle is its share of the total.
        # Two kinds of data make that meaningless, and Vega draws them anyway
        # rather than complaining — so these are refusals, not warnings.
        measures = [row.get(channels["y"]) for row in result_table]
        numeric = [v for v in measures if isinstance(v, (int, float))]
        if any(v < 0 for v in numeric):
            # Vega sweeps a negative theta *backwards*: the slice runs the wrong
            # way round and overlaps its neighbours. There is also no honest
            # reading of "share of a whole" when a part is below zero.
            return {
                "vega_lite_spec": None,
                "valid": False,
                "warnings": [
                    f"'{channels['y']}' has negative values, which a {chart_type} chart "
                    "cannot show — a slice has no meaning below zero. Use a bar chart, "
                    "which has a baseline to go below."
                ],
            }
        if numeric and sum(numeric) == 0:
            # Every slice is a share of the total, so a total of zero gives every
            # slice an angle of zero and the chart renders completely blank.
            return {
                "vega_lite_spec": None,
                "valid": False,
                "warnings": [
                    f"'{channels['y']}' adds up to zero, so a {chart_type} chart has no "
                    "slices to draw. Use a bar chart to show the values themselves."
                ],
            }
        encoding: dict[str, Any] = {
            "theta": {**enc(channels["y"]), "type": "quantitative"},
            "color": {**enc(channels["x"]), "type": "nominal"},
        }
        n_cats = len({row.get(channels["x"]) for row in result_table})
        if n_cats > _PIE_MAX_CATEGORIES:
            warnings.append(
                f"{chart_type} has {n_cats} categories (> {_PIE_MAX_CATEGORIES}) "
                "— consider a bar chart"
            )
    elif chart_type == "heatmap":
        # Both axes are categories; the measure rides the colour channel, which
        # is why heatmap is the one type whose colour is quantitative.
        encoding = {
            "x": enc(channels["x"]),
            "y": enc(channels["y"]),
            "color": {**enc(channels["color"]), "type": "quantitative"},
        }
    elif chart_type == "boxplot":
        # Vega-Lite derives the quartiles from raw rows; y must be the values
        # themselves, not a per-group aggregate.
        encoding = {
            "x": enc(channels["x"]),
            "y": {**enc(channels["y"]), "type": "quantitative"},
        }
    else:
        encoding = {"x": enc(channels["x"]), "y": enc(channels["y"])}
        # The ranking sort moved into chart_modifiers: which channel to sort, and
        # what to sort it by, are both questions about orientation, and a
        # horizontal ranking bar sorted on the wrong axis comes back unsorted
        # while still claiming to be sorted.
        if "color" in channels:
            encoding["color"] = series_enc(channels["color"])
            if chart_type == "grouped_bar":
                # What separates grouped from stacked: without xOffset a bar with
                # a colour channel stacks.
                encoding["xOffset"] = series_enc(channels["color"])
            n_colors = len({row.get(channels["color"]) for row in result_table})
            cap = (
                MAX_SERIES_ALL_PAIRS
                if chart_type in _ALL_PAIRS_TYPES
                else MAX_SERIES_ADJACENT
            )
            if n_colors > cap:
                warnings.append(
                    f"color channel has {n_colors} distinct values (> {cap} for "
                    f"'{chart_type}') — series will not be reliably distinguishable"
                )

    # Fold in the sub-type. Everything below sees the *final* channels, which is
    # why this runs before the skew pass and the labels: a horizontal bar's
    # measure is on x, and a skew notice naming the y axis of a chart whose y is
    # the category would be describing a different chart.
    mark, encoding, transforms, extra_layers, data_index = chart_modifiers.apply(
        form, encoding, _mark_def(chart_type, len(result_table)), chart_spec.get("intent")
    )
    if form.facet:
        panels = len({row.get(form.facet) for row in result_table})
        facet_note = chart_modifiers.facet_warning(form, panels)
        if facet_note:
            warnings.append(facet_note)

    # One extreme value flattens every other mark against the baseline. Judged on
    # the values actually being plotted, because aggregation both creates and
    # destroys skew — see services/skew.py for why the scale is only changed for
    # position-encoded marks.
    # `color` is in the list for the heatmap, whose measure rides the colour
    # channel rather than an axis — and where a linear ramp fails hardest, since
    # one dominant cell leaves every other on the same shade.
    axis_notices: list[Notice] = []
    for channel in ("x", "y", "color"):
        enc_def = encoding.get(channel)
        # A channel with no field is derived (a binned count), so there is no
        # column of values to judge.
        if not enc_def or enc_def.get("type") != "quantitative" or "field" not in enc_def:
            continue
        field = enc_def["field"]
        scale, notice = skew.assess(
            [row.get(field) for row in result_table], field, chart_type, channel
        )
        if scale:
            enc_def["scale"] = {**enc_def.get("scale", {}), **scale}
        if notice:
            axis_notices.append(notice)

    data_layer: dict[str, Any] = {"mark": mark, "encoding": encoding}
    if transforms:
        data_layer["transform"] = transforms
    label_layer = build_label_layer(form, encoding, result_table)

    # Assemble the frame. A unit spec stays a unit spec — only a sub-type that
    # needs a sibling (an error band, a jitter overlay) or a chart carrying
    # direct labels becomes layered. `data_index` is where the primary mark
    # landed: an error *band* draws under its line, so it goes first and the
    # data layer is second.
    layers: list[dict[str, Any]] = []
    if extra_layers:
        layers = (
            [extra_layers[0], data_layer, *extra_layers[1:]]
            if data_index == 1
            else [data_layer, *extra_layers]
        )
    if label_layer is not None:
        layers = (layers or [data_layer]) + [label_layer]

    inner: dict[str, Any] = {"layer": layers} if layers else data_layer

    spec: dict[str, Any] = {
        "$schema": VEGA_LITE_SCHEMA,
        "data": {"values": result_table},
    }
    if form.facet:
        # Small multiples put the chart under `spec`, so the top level carries no
        # `mark` and no `layer`. Consumers checking for a renderable top level
        # have to accept `facet` as a third shape — see export.py.
        spec.update(chart_modifiers.facet_wrapper(form, inner))
    else:
        spec.update(inner)

    attach_theme(spec)
    attach_interaction(spec, form)
    # Size from the container rather than Vega's 200px default, so a chart
    # reflows when the dashboard widget is resized instead of being re-embedded.
    # Faceted sub-types cannot — Vega-Lite ignores container sizing on them — and
    # take a per-panel size instead.
    chart_modifiers.apply_sizing(form, spec)
    # The caveat rides on the spec as well as the reply. A saved dashboard has no
    # chat behind it, so an explanation that lives only in the conversation is one
    # a reader will not have tomorrow — and a log axis nobody mentions misleads.
    chart_notices = empty_notices + axis_notices
    if chart_notices:
        spec["title"] = {
            "text": "",
            "subtitle": [n.note for n in chart_notices],
            "anchor": "start",
        }
    return {
        "vega_lite_spec": spec,
        "valid": True,
        "warnings": warnings,
        "notices": [n.to_wire() for n in chart_notices],
    }
