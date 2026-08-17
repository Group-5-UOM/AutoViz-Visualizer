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

Every gate below reads a `chart_modifiers.Form` rather than a chart-type string,
because the sub-type can overturn the family's answer: a density histogram is an
area and stops being hover-safe, a binned scatter is a rect grid and stops being
brushable, a strip plot is ticks and starts being both.
"""

from typing import Any

from autoviz.services.chart_modifiers import COMPOSITE_MARKS

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


def _brush_encodings(form: Any) -> list[str]:
    """Which axes the brush spans.

    A scatter brushes both. A histogram brushes only the binned axis — its other
    axis is a derived count, so a selection there would name a value that is in
    no row and the table view would have nothing to filter on. Which axis that
    is follows the orientation, so a horizontal histogram brushes down the page.
    """
    if form.chart_type == "scatter":
        return ["x", "y"]
    return [form.category_channel]

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
    seen: set[str] = set()
    for channel in _TOOLTIP_CHANNELS:
        field_def = encoding.get(channel)
        if not isinstance(field_def, dict):
            continue
        # The same column can legitimately land on two channels (e.g. x and
        # color); showing it twice in the tooltip is noise.
        #
        # Rendered to a string rather than tupled, because `bin` is a dict once a
        # sub-type sets `maxbins` and an unhashable key here took the whole
        # binned scatter down.
        key = repr([field_def.get(k) for k in _TOOLTIP_KEYS])
        if key in seen:
            continue
        seen.add(key)
        entries.append(_tooltip_entry(field_def))
    return entries


def _is_zoomable(form: Any, encoding: dict[str, Any]) -> bool:
    if form.chart_type not in _ZOOMABLE_TYPES or form.replaces_mark:
        return False
    x = encoding.get("x") or {}
    y = encoding.get("y") or {}
    if "bin" in x or "aggregate" in x:
        return False
    return x.get("type") in _CONTINUOUS and y.get("type") == "quantitative"


def _hover_safe(form: Any) -> bool:
    """Whether a per-datum opacity condition is safe on this sub-type's mark.

    The family answers this for eight of the ten types, but three sub-types
    overturn their family's answer, all in the same direction — they turn a
    discrete mark into a continuous one:

    * a **density** or **cumulative** histogram is an area, not bars;
    * a **violin** is an area;
    * a **binned scatter** is a rect grid, which stays discrete and safe.

    A strip plot is ticks, one per row, so it is discrete and hovers fine.
    """
    if form.is_pathlike:
        return False
    if form.chart_type == "boxplot":
        return form.is_strip
    return form.chart_type in _HOVER_SAFE_TYPES


def _brushable(form: Any) -> bool:
    """Whether a drag should select rows here.

    Narrower than the family: a density or cumulative histogram is an area, and
    dragging a per-datum opacity across an area splits it into differently
    opaque segments rather than dimming what falls outside. A binned scatter
    falls out too — it is a grid of aggregated cells, so a brush extent would
    name bin edges rather than the rows the table view has to index.
    """
    return form.chart_type in _BRUSHABLE_TYPES and not form.replaces_mark


def build_params(form: Any, encoding: dict[str, Any]) -> list[dict[str, Any]]:
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
    elif _brushable(form):
        # Only without a series: legend filtering and brushing would both want to
        # drive opacity, and on a multi-series chart isolating a series is the
        # more valuable of the two.
        params.append(
            {
                "name": BRUSH_PARAM,
                "select": {"type": "interval", "encodings": _brush_encodings(form)},
            }
        )
    elif _hover_safe(form):
        params.append(
            {
                "name": HOVER_PARAM,
                "select": {"type": "point", "on": "pointerover", "clear": "pointerout"},
            }
        )

    # A brush and a scale-bound zoom both consume the drag gesture, so a brushed
    # chart gets no zoom.
    if _is_zoomable(form, encoding) and not _has(params, BRUSH_PARAM):
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


def _resting_opacity(mark: Any, chart_type: str) -> float:
    """The opacity a mark returns to when nothing is selected.

    An opacity *encoding* overrides the mark's own opacity outright, so any
    sub-type that is translucent by design — a bubble, a density curve, a strip
    of ticks — would be forced opaque the moment interaction is attached, and
    the overlaps it was drawn to show would disappear. Reading the value back
    off the mark keeps the two in step without listing the sub-types here.
    """
    if isinstance(mark, dict) and isinstance(mark.get("opacity"), (int, float)):
        return float(mark["opacity"])
    # Area has no explicit mark opacity — it inherits Vega-Lite's own 0.7, which
    # an opacity encoding would otherwise silently discard.
    return AREA_FULL_OPACITY if chart_type == "area" else FULL_OPACITY


def build_opacity(
    params: list[dict[str, Any]], chart_type: str, full: float | None = None
) -> dict[str, Any] | None:
    """Dim everything the active param does not match.

    An *empty* selection matches all data (Vega-Lite's `empty: true` default), so
    the resting state is the chart's normal appearance — the dimming only appears
    once the user actually hovers or picks a series.
    """
    names = {p["name"] for p in params}
    if full is None:
        full = AREA_FULL_OPACITY if chart_type == "area" else FULL_OPACITY
    # At most one param drives opacity — a condition list resolves first-match,
    # so combining two would silently make the second one dead.
    for name in (BRUSH_PARAM, SERIES_PARAM, HOVER_PARAM):
        if name in names:
            return {"condition": {"param": name, "value": full}, "value": DIM_OPACITY}
    return None


def _mark_type(mark: Any) -> str:
    return str(mark.get("type", "")) if isinstance(mark, dict) else str(mark or "")


def attach(spec: dict[str, Any], form: Any) -> dict[str, Any]:
    """Attach the interaction layer to a freshly built spec, in place.

    Handles a unit spec, a layered one, and a faceted one. Params are declared on
    the *data layer*, never at the top level: Vega-Lite pushes a top-level param
    down into every child unit of a layered spec, which instantiates its signal
    more than once and fails to parse with "Duplicate signal name" — even when
    only one layer references it. A sibling layer can still refer to the param by
    name, which is what lets the labels dim along with their series. Without
    that, a legend filter would dim one series' marks and leave its labels
    behind.

    Two things the sub-types changed here:

    * **The data layer is not always first.** An error *band* draws under its
      line, so layer 0 is the composite — and a param on a composite is the
      compile error this gating has always existed to avoid.
    * **Only text siblings inherit the opacity condition.** Labels must dim with
      their series; a composite sibling must be left alone, because its
      encoding is not a unit encoding and Vega-Lite validates it against a
      narrower schema.
    """
    if form.is_composite:
        return spec

    root = spec.get("spec") if isinstance(spec.get("spec"), dict) else spec
    layers = root.get("layer")
    if layers:
        data_layer = next(
            (lyr for lyr in layers if _mark_type(lyr.get("mark")) not in COMPOSITE_MARKS),
            None,
        )
        if data_layer is None:
            return spec
    else:
        data_layer = root
    encoding = data_layer["encoding"]

    encoding["tooltip"] = build_tooltip(encoding)

    params = build_params(form, encoding)
    if params:
        data_layer["params"] = params
        opacity = build_opacity(
            params, form.chart_type, _resting_opacity(data_layer.get("mark"), form.chart_type)
        )
        if opacity:
            encoding["opacity"] = opacity
            for sibling in layers or []:
                if sibling is data_layer or _mark_type(sibling.get("mark")) != "text":
                    continue
                sibling["encoding"]["opacity"] = opacity
    return spec
