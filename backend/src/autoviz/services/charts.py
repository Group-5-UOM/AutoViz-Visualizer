"""Chart services: rule-based type recommendation + Vega-Lite spec generation.

recommend_chart_type scores intent x column types x cardinality (the hybrid
recommender's rule layer, Proposal §4.6); generate_chart builds and
structurally validates the Vega-Lite spec.
"""

from typing import Any

from autoviz.errors import NO_CHART_FIT, make_error
from autoviz.schema.allowlists import (
    CHART_TYPES,
    MAX_SERIES_ADJACENT,
    MAX_SERIES_ALL_PAIRS,
)
from autoviz.services import skew
from autoviz.services.chart_interaction import attach as attach_interaction
from autoviz.services.chart_labels import build_label_layer
from autoviz.services.chart_theme import attach as attach_theme
from autoviz.services.notices import Notice
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


def _split_columns(result_schema: list[dict[str, str]]):
    numeric = [c["name"] for c in result_schema if c["type"] == "number"]
    temporal = [c["name"] for c in result_schema if c["type"] == "datetime"]
    categorical = [
        c["name"] for c in result_schema if c["type"] not in ("number", "datetime")
    ]
    return numeric, temporal, categorical


def recommend_chart_type(
    result_schema: list[dict[str, str]], intent: str
) -> dict[str, Any]:
    numeric, temporal, categorical = _split_columns(result_schema)

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
        chart_type, x = "line", categorical[0]
        rationale = f"Trend intent over ordered category '{x}' — line chart."
        if len(categorical) > 1:
            color = categorical[1]
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
    else:
        chart_type, x = "scatter", numeric[0]
        y = numeric[1] if len(numeric) > 1 else numeric[0]
        rationale = "Only numeric columns available — scatter plot."

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


def _encoding_type(values: list[Any], column_schema: dict[str, str] | None, name: str) -> str:
    if column_schema and name in column_schema:
        return {"number": "quantitative", "datetime": "temporal"}.get(
            column_schema[name], "nominal"
        )
    non_null = [v for v in values if v is not None]
    if non_null and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in non_null):
        return "quantitative"
    return "nominal"


def primary_layer(spec: dict[str, Any]) -> dict[str, Any]:
    """The data layer of a generated spec — its `mark` and `encoding`.

    A spec that carries direct labels is layered, so `mark` and `encoding` sit
    one level down. Anything reading a generated spec's encoding should go
    through here rather than assuming a unit spec.
    """
    layers = spec.get("layer")
    return layers[0] if layers else spec


def _mark_def(chart_type: str) -> Any:
    """The Vega-Lite mark, as a bare name or a mark definition object."""
    if chart_type == "donut":
        # Derived from the view, not an absolute pixel count: charts size from
        # their container, so a literal innerRadius inverts at small widths.
        return {"type": "arc", "innerRadius": {"expr": "min(width, height) / 5"}}
    if chart_type == "boxplot":
        # Vega-Lite rejects selection params on composite marks, so the mark's
        # own tooltip is the only way to surface the quartiles it computes.
        return {"type": "boxplot", "extent": 1.5, "tooltip": True}
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

    columns = set(result_table[0].keys()) if result_table else set()
    warnings: list[str] = []
    channels = {k: chart_spec.get(k) for k in ("x", "y", "color") if chart_spec.get(k)}
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

    schema_hint = chart_spec.get("column_types")  # optional {name: logical_type}

    def enc(col: str) -> dict[str, Any]:
        values = [row.get(col) for row in result_table]
        return {"field": col, "type": _encoding_type(values, schema_hint, col)}

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
        # A ranking is only a ranking once it is ordered. recommend_chart_type
        # already promises "sorted bar chart"; this is what keeps that true.
        # Scoped to a discrete axis — sorting a time axis by value destroys it.
        if (
            chart_spec.get("intent") == "ranking"
            and chart_type == "bar"
            and encoding["x"]["type"] == "nominal"
        ):
            encoding["x"]["sort"] = "-y"
        if "color" in channels:
            encoding["color"] = enc(channels["color"])
            if chart_type == "grouped_bar":
                # What separates grouped from stacked: without xOffset a bar with
                # a colour channel stacks.
                encoding["xOffset"] = enc(channels["color"])
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

    # One extreme value flattens every other mark against the baseline. Judged on
    # the values actually being plotted, because aggregation both creates and
    # destroys skew — see services/skew.py for why the scale is only changed for
    # position-encoded marks.
    axis_notices: list[Notice] = []
    for channel in ("x", "y"):
        enc_def = encoding.get(channel)
        # A channel with no field is derived (a binned count), so there is no
        # column of values to judge.
        if not enc_def or enc_def.get("type") != "quantitative" or "field" not in enc_def:
            continue
        field = enc_def["field"]
        scale, notice = skew.assess(
            [row.get(field) for row in result_table], field, chart_type
        )
        if scale:
            enc_def["scale"] = {**enc_def.get("scale", {}), **scale}
        if notice:
            axis_notices.append(notice)

    data_layer: dict[str, Any] = {"mark": _mark_def(chart_type), "encoding": encoding}
    label_layer = build_label_layer(chart_type, encoding, result_table)

    spec: dict[str, Any] = {
        "$schema": VEGA_LITE_SCHEMA,
        "data": {"values": result_table},
    }
    if label_layer is None:
        spec.update(data_layer)
    else:
        # Labels force a layered spec. Consumers that assume a top-level `mark`
        # have to accept `layer` too — see export.py's spec check.
        spec["layer"] = [data_layer, label_layer]

    attach_theme(spec)
    attach_interaction(spec, chart_type)
    # Size from the container rather than Vega's 200px default, so a chart
    # reflows when the dashboard widget is resized instead of being re-embedded.
    # Belongs to the spec as a whole, so it is set after any layering.
    spec["width"] = "container"
    spec["height"] = "container"
    # The caveat rides on the spec as well as the reply. A saved dashboard has no
    # chat behind it, so an explanation that lives only in the conversation is one
    # a reader will not have tomorrow — and a log axis nobody mentions misleads.
    if axis_notices:
        spec["title"] = {
            "text": "",
            "subtitle": [n.note for n in axis_notices],
            "anchor": "start",
        }
    return {
        "vega_lite_spec": spec,
        "valid": True,
        "warnings": warnings,
        "notices": [n.to_wire() for n in axis_notices],
    }
