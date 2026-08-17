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
a validated palette, and `tests/test_palette_accessibility.py` is what validates
them — CIEDE2000 distances, Machado (2009) colour-blindness simulation, and WCAG
contrast, all computed rather than asserted. On this app's `#ffffff` surface:

* adjacent-pair separation under protanopia / deuteranopia / tritanopia,
  worst ΔE **8.4** (yellow against magenta, under tritanopia), floor 8;
* any pair that can co-occur, under ordinary vision, worst ΔE **13.3** (orange
  against red — reachable only on a chart using seven or more series), floor 13.

The slot *ordering* is the CVD-safety mechanism, not decoration. Reordering is
what the test above exists to catch: moving green next to orange takes
protanopia separation from 14.6 down to 4.8, and the two series become one hue
for roughly 1 in 12 men in the room.

*(An earlier version of this note claimed ΔE 9.1 and a normal-vision floor of 15
with a worst case of 19.6. Neither reproduces on a standard CIEDE2000 +
Machado implementation, on either reading of "which pairs" — the method behind
them was never recorded. The figures above are the ones the test computes.)*

Three slots (aqua, yellow, magenta) sit below 3:1 contrast against white. That is
a known property of this palette and carries a standing obligation: those series
need a visible label, not colour alone. Tooltips and the legend are not
sufficient relief — direct labels are, and they need the layered-spec refactor
tracked with A6 in Docs/13 §4. Recorded there as outstanding.

The chrome (ink, gridlines, baselines) is taken from the app's own CSS custom
properties rather than the palette reference, so charts read as native rather
than as embedded images.
"""

import copy
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

# The closed set a ChartStyle may choose from, for the same reason colours are
# closed hex: a free-text family is a place for a planner to ask for a font that
# is not there, and a chart silently falling back to Times is worse than a
# rejected patch. Every stack here resolves without a webfont, because an
# exported HTML file and an MCP consumer load none.
FONT_STACKS: dict[str, str] = {
    "sans": FONT,
    "system": "system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif",
    "serif": "Georgia, Cambria, 'Times New Roman', Times, serif",
    "mono": "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Courier New', monospace",
}


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


# --- typography ---------------------------------------------------------------

# What a user-chosen text size is measured against: the size of a tick label in
# the theme above. Read from THEME rather than repeated, so the two cannot drift.
BASE_FONT_SIZE: int = THEME["axis"]["labelFontSize"]

# The chart title has no THEME entry — it renders at Vega-Lite's own default, and
# baking one in would change every existing chart. It gets a size only once the
# user asks for one, which is why this is an offset and not a THEME key.
TITLE_SIZE_OFFSET = 3


def scaled_text(base: int) -> dict[str, dict[str, int]]:
    """THEME's text sizes shifted to sit around `base`.

    Offsets rather than absolutes: the theme puts axis titles one step above tick
    labels, and that hierarchy is the thing worth preserving when someone asks
    for bigger text. Returned as config fragments, ready to merge.
    """
    delta = base - BASE_FONT_SIZE
    return {
        "axis": {
            "labelFontSize": THEME["axis"]["labelFontSize"] + delta,
            "titleFontSize": THEME["axis"]["titleFontSize"] + delta,
        },
        "legend": {
            "labelFontSize": THEME["legend"]["labelFontSize"] + delta,
            "titleFontSize": THEME["legend"]["titleFontSize"] + delta,
        },
        "title": {"fontSize": BASE_FONT_SIZE + TITLE_SIZE_OFFSET + delta},
    }


def attach(spec: dict[str, Any]) -> dict[str, Any]:
    """Merge the theme into a spec's config, in place.

    A config the caller already set wins — a host-supplied spec that themes
    itself is not overridden.

    The values are copied in. THEME's nested dicts are module state, and handing
    a live reference to a spec means anything later writing `config.axis` — which
    is exactly what a font-size override does — would edit the theme itself for
    the rest of the process.
    """
    config = spec.setdefault("config", {})
    for key, value in THEME.items():
        config.setdefault(key, copy.deepcopy(value))
    return spec
