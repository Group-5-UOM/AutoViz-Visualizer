"""Visual theme baked into every generated Vega-Lite spec (Docs/13 §5).

Without this, charts render in Vega's stock defaults — tableau10, 10px sans, a
box around the plot — which look nothing like the app they sit in.

**Why the theme is baked in on the backend rather than applied at embed time.**
AutoViz is MCP-first: a spec handed to Claude Desktop or written into an exported
HTML file has no frontend to theme it. Baking it in means every consumer gets the
same chart. The cost is that a saved chart freezes the theme it was generated
with — acceptable, since a saved chart is a saved *render*. When dark mode
arrives it should be a frontend override at embed time (`vegaEmbed(el, spec,
{config: DARK})` merges over the spec's own config), so no stored spec has to be
regenerated.

**Colour choices.** The eight categorical slots and the blue sequential ramp are
a validated palette: on this app's `#ffffff` chart surface they clear the
lightness band, the chroma floor, adjacent-pair CVD separation (worst ΔE 9.1,
target ≥ 8) and the normal-vision floor (worst ΔE 19.6, floor ≥ 15). The slot
*ordering* is the CVD-safety mechanism, not decoration — do not reorder these
without re-running the check.

Three slots (aqua, yellow, magenta) sit below 3:1 contrast against white. That is
a known property of this palette and carries a standing obligation: those series
need a visible label, not colour alone. Tooltips and the legend are not
sufficient relief — direct labels are, and they need the layered-spec refactor
tracked with A6 in Docs/13 §4. Recorded there as outstanding.

The chrome (ink, gridlines, baselines) is taken from the app's own CSS custom
properties rather than the palette reference, so charts read as native rather
than as embedded images.
"""

from typing import Any

# --- series colour -----------------------------------------------------------

# Fixed slot order. Assigned in sequence, never cycled; a 9th series is not a
# generated hue — it folds into "Other" or facets.
CATEGORICAL = [
    "#2a78d6",  # blue
    "#eb6834",  # orange
    "#1baf7a",  # aqua
    "#eda100",  # yellow
    "#e87ba4",  # magenta
    "#008300",  # green
    "#4a3aa7",  # violet
    "#e34948",  # red
]

# One hue, light -> dark, for continuous magnitude (heatmaps, ramps).
SEQUENTIAL_BLUE = [
    "#cde2fb",
    "#9ec5f4",
    "#6da7ec",
    "#3987e5",
    "#256abf",
    "#184f95",
    "#0d366b",
]

# --- chrome, matched to the app's CSS custom properties ----------------------

SURFACE = "#ffffff"        # --bg-surface; the ring colour that separates marks
SECONDARY_INK = "#60636c"  # --text-secondary; axis and legend titles
MUTED_INK = "#8b909a"      # --text-muted; tick labels
GRIDLINE = "#e6e9ee"       # --border-subtle; hairline grid
BASELINE = "#d9dde3"       # --border; axis domain and ticks

# The app loads DM Sans; the fallbacks cover exported HTML and MCP consumers,
# where that webfont is not present.
FONT = "'DM Sans', system-ui, -apple-system, 'Segoe UI', sans-serif"


THEME: dict[str, Any] = {
    # Let the widget surface show through instead of painting Vega's white box.
    "background": "transparent",
    "font": FONT,
    "axis": {
        "labelColor": MUTED_INK,
        "labelFontSize": 11,
        "labelPadding": 4,
        "titleColor": SECONDARY_INK,
        "titleFontSize": 12,
        "titleFontWeight": 500,
        "titlePadding": 8,
        "gridColor": GRIDLINE,
        "domainColor": BASELINE,
        "tickColor": BASELINE,
        "tickSize": 4,
    },
    "legend": {
        "labelColor": SECONDARY_INK,
        "labelFontSize": 11,
        "titleColor": SECONDARY_INK,
        "titleFontSize": 11,
        "titleFontWeight": 500,
        "symbolType": "circle",
        "symbolSize": 80,
        "offset": 12,
    },
    # No box around the plot area; the widget already has a border.
    "view": {"stroke": None},
    "range": {
        "category": CATEGORICAL,
        "heatmap": SEQUENTIAL_BLUE,
        "ramp": SEQUENTIAL_BLUE,
    },
    # range.category only feeds a *colour scale*, which exists only when a chart
    # has a colour encoding. Single-series charts have none and would otherwise
    # fall through to Vega's stock tableau blue, so the default mark colour has
    # to be set separately to slot 1.
    "mark": {"color": CATEGORICAL[0]},
    # Rounded data-end only — the baseline end stays square so bars still read
    # as anchored to zero.
    "bar": {"cornerRadiusEnd": 4},
    "line": {"strokeWidth": 2},
    # Filled markers with a surface-coloured ring, so overlapping points in a
    # dense scatter stay countable.
    "point": {"size": 64, "filled": True, "stroke": SURFACE, "strokeWidth": 1.5},
    # Same idea for pie: a 2px surface gap between adjacent slices.
    "arc": {"stroke": SURFACE, "strokeWidth": 2},
}


def attach(spec: dict[str, Any]) -> dict[str, Any]:
    """Merge the theme into a spec's config, in place.

    A config the caller already set wins — a host-supplied spec that themes
    itself is not overridden.
    """
    config = spec.setdefault("config", {})
    for key, value in THEME.items():
        config.setdefault(key, value)
    return spec
