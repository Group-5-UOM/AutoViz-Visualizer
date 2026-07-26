"""Direct labels: a `text` layer over the data marks (Docs/13 §5, §6).

**Why this exists.** Three slots of the categorical palette (aqua, yellow,
magenta) sit below 3:1 contrast on the app's white surface. That is a documented
property of the palette, and it carries a standing obligation: those series must
be readable by something other than their colour. A legend does not discharge it
and a tooltip does not either — both require the reader to already be able to
pick the mark out. A visible label does.

Labels are also the readability half of the "visually rich" goal in their own
right, independently of the accessibility rule.

**They are selective, never universal.** A number on every mark is noise, and on
a dense chart it is unreadable noise — so each strategy carries a ceiling and
returns nothing above it. Types with no good labelling story (scatter, histogram,
boxplot, stacked bar) get none at all; see `_STRATEGIES` for the reasoning per
type.

**Text wears text tokens, not the series colour.** A label is identified by
*where it sits* — at the end of its own line, inside its own cell — not by being
tinted. Colouring labels by series would re-introduce exactly the colour-alone
dependency this module exists to remove. The one exception is heatmap, where the
label sits on top of a filled cell and has to flip to white over the dark end of
the ramp to stay legible at all.
"""

from typing import Any

from autoviz.services.chart_theme import SECONDARY_INK, SURFACE

# Ceilings, past which labels collide into noise rather than clarifying.
MAX_LABELLED_BARS = 15
MAX_LABELLED_GROUPED_BARS = 24
MAX_LABELLED_CELLS = 60
MAX_LABELLED_SLICES = 6
# The direct-label ceiling for series: past four, the legend carries identity.
MAX_LABELLED_SERIES = 4

LABEL_FONT_SIZE = 10
# Shorter than the tooltip's format: a label has to fit beside a mark.
LABEL_NUMBER_FORMAT = ",.3~f"


def _text_mark(**overrides: Any) -> dict[str, Any]:
    return {
        "type": "text",
        "fontSize": LABEL_FONT_SIZE,
        "color": SECONDARY_INK,
        **overrides,
    }


def _value_text(field: str) -> dict[str, Any]:
    return {"field": field, "type": "quantitative", "format": LABEL_NUMBER_FORMAT}


def _bar_values(encoding, table, *, offset_by=None, cap):
    """Value above each bar."""
    if len(table) > cap:
        return None
    enc: dict[str, Any] = {
        "x": encoding["x"],
        "y": encoding["y"],
        "text": _value_text(encoding["y"]["field"]),
    }
    if offset_by is not None:
        # Without the same offset the labels sit over the group's centre rather
        # than over their own bar.
        enc["xOffset"] = offset_by
    return {"mark": _text_mark(dy=-5, baseline="bottom"), "encoding": enc}


def _heatmap_values(encoding, table):
    """Value inside each cell, flipped to white over the dark end of the ramp."""
    if len(table) > MAX_LABELLED_CELLS:
        return None
    measure = encoding["color"]["field"]
    values = [row.get(measure) for row in table]
    numbers = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not numbers:
        return None
    # Past the ramp's midpoint the cell is dark enough that ink text disappears.
    midpoint = (min(numbers) + max(numbers)) / 2
    return {
        "mark": _text_mark(),
        "encoding": {
            "x": encoding["x"],
            "y": encoding["y"],
            "text": _value_text(measure),
            "color": {
                "condition": {"test": f"datum['{measure}'] > {midpoint}", "value": SURFACE},
                "value": SECONDARY_INK,
            },
        },
    }


def _series_at_line_end(encoding, table):
    """Series name beside the last point of its own line."""
    color = encoding.get("color")
    if not isinstance(color, dict) or "field" not in color:
        return None
    series_field = color["field"]
    n_series = len({row.get(series_field) for row in table})
    if n_series > MAX_LABELLED_SERIES:
        return None
    x_field = encoding["x"]["field"]
    return {
        "mark": _text_mark(align="left", dx=6),
        "encoding": {
            "x": {"field": x_field, "type": encoding["x"]["type"], "aggregate": "max"},
            "y": {
                "field": encoding["y"]["field"],
                "type": "quantitative",
                "aggregate": {"argmax": x_field},
            },
            # detail groups the text per series without tinting it.
            "detail": {"field": series_field, "type": "nominal"},
            "text": {"field": series_field, "type": "nominal"},
        },
    }


def _slice_categories(encoding, table):
    """Category name outside its own arc."""
    category = encoding["color"]["field"]
    if len({row.get(category) for row in table}) > MAX_LABELLED_SLICES:
        return None
    return {
        "mark": _text_mark(radius={"expr": "min(width, height) / 2.1"}),
        "encoding": {
            "theta": {**encoding["theta"], "stack": True},
            "text": {"field": category, "type": "nominal"},
        },
    }


# Per-type strategy. Absent means no labels, deliberately:
#   scatter   — one label per point is unreadable at any useful point count
#   histogram — bins are counts; the y axis already says what a label would
#   boxplot   — composite mark; its own tooltip carries the quartiles
#   bar+color — stacked segments; labels inside them collide at realistic sizes
_STRATEGIES = {
    "bar": lambda e, t: (
        None if "color" in e else _bar_values(e, t, cap=MAX_LABELLED_BARS)
    ),
    "grouped_bar": lambda e, t: _bar_values(
        e, t, offset_by=e.get("xOffset"), cap=MAX_LABELLED_GROUPED_BARS
    ),
    "heatmap": _heatmap_values,
    "line": _series_at_line_end,
    "area": _series_at_line_end,
    "pie": _slice_categories,
    "donut": _slice_categories,
}


def build_label_layer(
    chart_type: str, encoding: dict[str, Any], result_table: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """The text layer for this chart, or None if it should carry no labels."""
    strategy = _STRATEGIES.get(chart_type)
    if strategy is None or not result_table:
        return None
    return strategy(encoding, result_table)
