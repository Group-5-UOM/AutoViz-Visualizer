"""Applying a user's style block to a finished Vega-Lite spec (FR-15).

The counterpart to `schema/chart_style.ChartStyle`: that says what a user may
override, this puts it on the chart. Nothing here re-runs a query — a style edit
changes how the same numbers are drawn, so the data stays exactly as executed.

**Where the overrides land.** `chart_theme.attach` merges the theme with
`config.setdefault`, so anything already set wins. That means a style override
does not have to fight the theme; it only has to be written *somewhere the theme
did not already lose to*. Two consequences worth knowing:

* Colour goes on the mark definition or the colour scale, not into `config` —
  a `config.mark.color` would also repaint the direct-label layer.
* Reverting deletes only the keys this module wrote. `services/skew.py` writes a
  log `scale` onto the very same encodings, and dropping that to reset a colour
  would quietly un-disclose a log axis.

**Total, not incremental.** The caller holds the whole style block and re-applies
it after every edit, so `apply(apply(spec, s), s) == apply(spec, s)`. Every branch
below therefore has an else: a field the block does not set must be actively
restored to the theme's default, not merely left alone.
"""

import copy
from typing import Any

from autoviz.schema.chart_style import ChartStyle
from autoviz.services.chart_theme import CATEGORICAL
from autoviz.services.charts import primary_layer


def _rows(spec: dict[str, Any]) -> list[dict[str, Any]]:
    data = spec.get("data")
    values = data.get("values") if isinstance(data, dict) else None
    return values if isinstance(values, list) else []


def _series_domain(spec: dict[str, Any], field: str) -> list[Any]:
    """Distinct values on the colour channel, in the order they appear.

    Order matters: a Vega-Lite `domain`/`range` pair is positional, so this has to
    be the same walk that decided which series got slot 1.
    """
    seen: list[Any] = []
    for row in _rows(spec):
        value = row.get(field)
        if value not in seen:
            seen.append(value)
    return seen


def _apply_title(spec: dict[str, Any], style: ChartStyle) -> None:
    """Set or clear the chart title without touching the subtitle.

    The subtitle is not decoration — `generate_chart` parks the log-axis and
    skew disclosures there precisely so they survive into a saved dashboard,
    where no chat exists to carry them. Renaming a chart must not erase them.
    """
    title = spec.get("title")
    if not isinstance(title, dict):
        # A plain-string title is not something this codebase generates, but a
        # host-supplied spec may carry one; keep it as the text to overwrite.
        title = {"text": title} if isinstance(title, str) else {}

    title["text"] = style.title or ""
    title.setdefault("anchor", "start")

    if title.get("text") or title.get("subtitle"):
        spec["title"] = title
    else:
        spec.pop("title", None)


def _apply_axis_titles(layer: dict[str, Any], style: ChartStyle) -> None:
    encoding = layer.get("encoding") or {}
    for channel, override in (("x", style.x_title), ("y", style.y_title)):
        # Arc charts encode on theta/color and have no x or y to label.
        enc = encoding.get(channel)
        if not isinstance(enc, dict):
            continue
        if override:
            enc["title"] = override
        else:
            # Removing it returns the axis to Vega-Lite's field-name default,
            # which is what it showed before anyone renamed it.
            enc.pop("title", None)


def _apply_mark_color(layer: dict[str, Any], style: ChartStyle) -> None:
    """Colour for a chart with no colour scale — one series, one colour.

    Set on this layer's own mark rather than `config.mark.color`, which would
    also repaint the direct-label text drawn in the layer above.
    """
    mark = layer.get("mark")
    if isinstance(mark, str):
        mark = {"type": mark}
    elif isinstance(mark, dict):
        mark = dict(mark)
    else:
        return

    if style.mark_color:
        mark["color"] = style.mark_color
    else:
        # Falls back through to the theme's `config.mark.color`.
        mark.pop("color", None)
    layer["mark"] = mark


def _apply_colors(spec: dict[str, Any], layer: dict[str, Any], style: ChartStyle) -> None:
    """Recolour the series, or put the theme's palette back.

    Only `domain` and `range` are written or removed. The rest of the scale
    belongs to whoever else set it — `services/skew.py` puts a log scale on this
    exact encoding for a skewed heatmap, and clearing that here would drop a
    disclosure the user is owed.
    """
    encoding = layer.get("encoding") or {}
    color = encoding.get("color")
    if not isinstance(color, dict):
        return
    scale = color.get("scale")
    scale = dict(scale) if isinstance(scale, dict) else {}

    field = color.get("field")
    quantitative = color.get("type") == "quantitative"

    if style.series_colors and field and not quantitative:
        # Every series needs an entry: a domain that names only the recoloured
        # ones drops the rest off the scale and renders them as "undefined".
        # Unnamed series keep the slot they already had.
        domain = _series_domain(spec, field)
        scale["domain"] = domain
        scale["range"] = [
            style.series_colors.get(str(value), CATEGORICAL[i % len(CATEGORICAL)])
            for i, value in enumerate(domain)
        ]
    elif style.color_scheme:
        # A palette rather than a per-series assignment: leave the domain to
        # Vega-Lite, which is also what makes this work for a quantitative ramp.
        scale.pop("domain", None)
        scale["range"] = list(style.color_scheme)
    else:
        scale.pop("domain", None)
        scale.pop("range", None)

    if scale:
        color["scale"] = scale
    else:
        color.pop("scale", None)


def _apply_legend(layer: dict[str, Any], style: ChartStyle) -> None:
    encoding = layer.get("encoding") or {}
    color = encoding.get("color")
    if not isinstance(color, dict):
        return
    if style.legend is False:
        color["legend"] = None
    else:
        color.pop("legend", None)


def apply(spec: dict[str, Any], style: ChartStyle) -> dict[str, Any]:
    """A copy of `spec` with the user's overrides on it.

    The input is left alone so a caller can keep the un-styled spec around; the
    block is the thing that is stateful, not the render.
    """
    styled = copy.deepcopy(spec)
    layer = primary_layer(styled)

    _apply_title(styled, style)
    _apply_axis_titles(layer, style)
    _apply_mark_color(layer, style)
    _apply_colors(styled, layer, style)
    _apply_legend(layer, style)
    return styled


def context_for(spec: dict[str, Any]) -> dict[str, Any]:
    """What the chart currently looks like, for the planner writing a patch.

    Kept here rather than asked of the client: the series values a user can name
    ("make Setosa red") are in the spec's own data, and a client-supplied list
    would be one more thing that could disagree with what is on screen.
    """
    layer = primary_layer(spec)
    encoding = layer.get("encoding") or {}
    mark = layer.get("mark")
    color = encoding.get("color") if isinstance(encoding.get("color"), dict) else {}
    field = color.get("field")

    title = spec.get("title")
    return {
        "mark": mark.get("type") if isinstance(mark, dict) else mark,
        "title": title.get("text") if isinstance(title, dict) else title,
        "x_field": (encoding.get("x") or {}).get("field"),
        "y_field": (encoding.get("y") or {}).get("field"),
        "color_field": field,
        # Bounded: a high-cardinality colour channel would otherwise put the
        # whole column in the prompt.
        "series": [str(v) for v in _series_domain(spec, field)[:20]] if field else [],
        "has_color_scale": bool(field) and color.get("type") != "quantitative",
    }
