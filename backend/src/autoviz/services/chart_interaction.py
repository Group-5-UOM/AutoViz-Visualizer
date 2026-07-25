"""Interaction layer for generated Vega-Lite specs (Docs/13 §4, items A1-A5).

Everything here is additive and runs *after* generate_chart has built a
structurally valid encoding: it attaches tooltips, selection params and an
opacity condition. Nothing here reads the dataset, and nothing here can turn a
valid spec invalid — it works purely off the encoding just built. Container
sizing lives in generate_chart, since it belongs to the spec as a whole rather
than to any one layer.

Two Vega-Lite constraints shape the gating below, and both are the reason this
is not a blanket "add params to everything":

  * A conditional opacity is evaluated **per datum**. On a `line`/`area` mark a
    per-point hover condition therefore splits the line into differently-opaque
    segments. Hover dimming is restricted to discrete marks; a *series-level*
    (legend) condition is constant within a line and stays safe on every mark.
  * `bind: "scales"` needs continuous scales on both axes, so pan/zoom is only
    attached when x is quantitative/temporal and y is quantitative — never on a
    nominal axis and never over a binned or aggregated channel.
"""

from typing import Any

# Param names are namespaced so a host-supplied spec can never collide with ours.
HOVER_PARAM = "autoviz_hover"
SERIES_PARAM = "autoviz_series"
ZOOM_PARAM = "autoviz_zoom"
BRUSH_PARAM = "autoviz_brush"

# Opacity of the marks that are *not* hovered / not the selected series.
DIM_OPACITY = 0.25

# Opacity of the marks that *are*. An opacity encoding overrides the mark's
# config default outright, so area has to restate its translucency here or
# overlapping bands would occlude each other once a condition is attached.
FULL_OPACITY = 1
AREA_FULL_OPACITY = 0.7

# d3-format: thousands separators, up to 4 decimals, trailing zeros trimmed —
# so counts read "1,234" and means read "5.0063".
NUMBER_FORMAT = ",.4~f"
DATE_FORMAT = "%b %d, %Y"

# Chart types whose marks are discrete enough to carry a per-datum hover
# condition. line/area are deliberately absent — see the module docstring.
_HOVER_SAFE_TYPES = frozenset(
    {"bar", "scatter", "pie", "histogram", "heatmap", "grouped_bar", "donut"}
)

# Composite marks (boxplot, errorbar, errorband) expand into layered primitives,
# and Vega-Lite refuses to compile a selection param against them — it throws
# "Unrecognized signal name". They also compute their own tooltip from the
# quartiles, so the whole interaction layer is skipped for them.
_COMPOSITE_TYPES = frozenset({"boxplot"})

# Chart types whose axes can carry a continuous, zoomable scale.
_ZOOMABLE_TYPES = frozenset({"scatter", "line", "area"})
_CONTINUOUS = frozenset({"quantitative", "temporal"})

# Types where a drag is better spent selecting marks than panning: both draw many
# undifferentiated marks, and the reader's question is "which rows are those?"
# rather than "show me a different range". The frontend reads the brush signal
# and filters the widget's table view to the selection.
#
# Time series are deliberately absent — panning and zooming a range is the
# natural gesture there, and `bind: "scales"` already claims the drag.
_BRUSHABLE_TYPES = frozenset({"scatter", "histogram"})

# Which axes the brush spans. A histogram's y is a derived count, so brushing it
# would select on a value that is not in any row.
_BRUSH_ENCODINGS = {"scatter": ["x", "y"], "histogram": ["x"]}

# Encoding-level keys a tooltip entry inherits; anything else (scale, axis,
# legend, sort) is chrome that means nothing in a tooltip.
_TOOLTIP_KEYS = ("field", "type", "bin", "aggregate")

# Channels worth showing in a tooltip, in reading order. theta covers pie.
_TOOLTIP_CHANNELS = ("x", "y", "theta", "color")


def _tooltip_entry(field_def: dict[str, Any]) -> dict[str, Any]:
    """Project an encoding field-def into a formatted tooltip entry."""
    entry = {k: v for k, v in field_def.items() if k in _TOOLTIP_KEYS}
    # An aggregate channel (histogram's count) has no field to name itself with.
    entry["title"] = field_def.get("field") or str(field_def.get("aggregate", "value")).title()
    if entry.get("type") == "quantitative":
        entry["format"] = NUMBER_FORMAT
    elif entry.get("type") == "temporal":
        entry["format"] = DATE_FORMAT
    return entry


def build_tooltip(encoding: dict[str, Any]) -> list[dict[str, Any]]:
    """One tooltip entry per encoded channel, de-duplicated.

    Replaces vega-embed's default tooltip, which dumps raw field names and
    unformatted values for every column in the row.
    """
    entries: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for channel in _TOOLTIP_CHANNELS:
        field_def = encoding.get(channel)
        if not isinstance(field_def, dict):
            continue
        # The same column can legitimately land on two channels (e.g. x and
        # color); showing it twice in the tooltip is noise.
        key = tuple(field_def.get(k) for k in _TOOLTIP_KEYS)
        if key in seen:
            continue
        seen.add(key)
        entries.append(_tooltip_entry(field_def))
    return entries


def _is_zoomable(chart_type: str, encoding: dict[str, Any]) -> bool:
    if chart_type not in _ZOOMABLE_TYPES:
        return False
    x = encoding.get("x") or {}
    y = encoding.get("y") or {}
    if "bin" in x or "aggregate" in x:
        return False
    return x.get("type") in _CONTINUOUS and y.get("type") == "quantitative"


def build_params(chart_type: str, encoding: dict[str, Any]) -> list[dict[str, Any]]:
    """Selection params for the spec.

    A colour channel earns legend filtering (click a legend entry to isolate a
    series); without one, discrete marks get hover highlighting instead. The two
    are mutually exclusive because they would otherwise both drive opacity.
    """
    params: list[dict[str, Any]] = []
    color = encoding.get("color")
    # Binding a point selection to the legend needs a *discrete* legend to click.
    # A heatmap's colour is the measure, so its legend is a continuous gradient
    # and there is nothing to select — it falls through to hover instead.
    has_series = (
        isinstance(color, dict)
        and "field" in color
        and color.get("type") != "quantitative"
    )

    if has_series:
        params.append(
            {
                "name": SERIES_PARAM,
                "select": {"type": "point", "fields": [color["field"]]},
                "bind": "legend",
            }
        )
    elif chart_type in _BRUSHABLE_TYPES:
        # Only without a series: legend filtering and brushing would both want to
        # drive opacity, and on a multi-series chart isolating a series is the
        # more valuable of the two.
        params.append(
            {
                "name": BRUSH_PARAM,
                "select": {"type": "interval", "encodings": _BRUSH_ENCODINGS[chart_type]},
            }
        )
    elif chart_type in _HOVER_SAFE_TYPES:
        params.append(
            {
                "name": HOVER_PARAM,
                "select": {"type": "point", "on": "pointerover", "clear": "pointerout"},
            }
        )

    # A brush and a scale-bound zoom both consume the drag gesture, so a brushed
    # chart gets no zoom.
    if _is_zoomable(chart_type, encoding) and not _has(params, BRUSH_PARAM):
        params.append(
            {
                "name": ZOOM_PARAM,
                "select": {"type": "interval", "encodings": ["x", "y"]},
                "bind": "scales",
            }
        )
    return params


def _has(params: list[dict[str, Any]], name: str) -> bool:
    return any(p["name"] == name for p in params)


def build_opacity(params: list[dict[str, Any]], chart_type: str) -> dict[str, Any] | None:
    """Dim everything the active param does not match.

    An *empty* selection matches all data (Vega-Lite's `empty: true` default), so
    the resting state is the chart's normal appearance — the dimming only appears
    once the user actually hovers or picks a series.
    """
    names = {p["name"] for p in params}
    full = AREA_FULL_OPACITY if chart_type == "area" else FULL_OPACITY
    # At most one param drives opacity — a condition list resolves first-match,
    # so combining two would silently make the second one dead.
    for name in (BRUSH_PARAM, SERIES_PARAM, HOVER_PARAM):
        if name in names:
            return {"condition": {"param": name, "value": full}, "value": DIM_OPACITY}
    return None


def attach(spec: dict[str, Any], chart_type: str) -> dict[str, Any]:
    """Attach the interaction layer to a freshly built spec, in place.

    Handles both a unit spec and a layered one. Params are declared on the *data
    layer*, never at the top level: Vega-Lite pushes a top-level param down into
    every child unit of a layered spec, which instantiates its signal more than
    once and fails to parse with "Duplicate signal name" — even when only one
    layer references it. A sibling layer can still refer to the param by name,
    which is what lets the labels dim along with their series. Without that, a
    legend filter would dim one series' marks and leave its labels behind.
    """
    if chart_type in _COMPOSITE_TYPES:
        return spec

    layers = spec.get("layer")
    data_layer = layers[0] if layers else spec
    encoding = data_layer["encoding"]

    encoding["tooltip"] = build_tooltip(encoding)

    params = build_params(chart_type, encoding)
    if params:
        data_layer["params"] = params
        opacity = build_opacity(params, chart_type)
        if opacity:
            encoding["opacity"] = opacity
            for label_layer in (layers or [])[1:]:
                label_layer["encoding"]["opacity"] = opacity
    return spec
