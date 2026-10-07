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

# Pie/donut geometry, shared with the arc mark in charts.py so the labels and the
# slices agree on where the edge is. The margin is what the labels sit in.
ARC_LABEL_MARGIN = 26
# Labels go left and right of the pie, so it is the *width* that has to leave room
# for them: a card 260 wide and 200 tall has 30px either side of a full-height pie,
# and a category name is three times that. The pie gives up radius to the labels
# down to a quarter of the view, and below that the labels are truncated instead.
ARC_LABEL_ROOM = 96
ARC_OUTER_RADIUS = (
    f"max(min(width, height) / 4, min(min(width, height) / 2 - {ARC_LABEL_MARGIN}, "
    f"width / 2 - {ARC_LABEL_ROOM}))"
)
# A slice thinner than this has no room for its name beside its neighbours': the
# 2% "Shared room" slice printed straight over "Entire home/apt". The legend
# still names it.
MIN_LABELLED_SLICE_SHARE = 0.04
# Truncated with an ellipsis at whatever room is left beside the pie.
ARC_LABEL_GAP = 6
ARC_LABEL_LIMIT = f"max(30, width / 2 - ({ARC_OUTER_RADIUS}) - {ARC_LABEL_GAP} - 4)"


def _text_mark(**overrides: Any) -> dict[str, Any]:
    return {
        "type": "text",
        "fontSize": LABEL_FONT_SIZE,
        "color": SECONDARY_INK,
        **overrides,
    }


def _number_format(numbers: list[float]) -> str:
    """Decimals by magnitude: as many as can matter beside a mark, and no more.

    A fixed three decimals printed "127.507" in every heatmap cell, and five of
    those across a card ran into each other. A value of a hundred or more reads
    to the unit; below that a decimal or two still carries information.
    """
    biggest = max((abs(n) for n in numbers), default=0)
    if biggest >= 100:
        return ",.0f"
    if biggest >= 10:
        return ",.1~f"
    return ",.2~f"


def _value_text(field: str, numbers: list[float] | None = None) -> dict[str, Any]:
    fmt = _number_format(numbers) if numbers else LABEL_NUMBER_FORMAT
    return {"field": field, "type": "quantitative", "format": fmt}


def _numbers(table: list[dict[str, Any]], field: str) -> list[float]:
    return [
        v
        for v in (row.get(field) for row in table)
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    ]


def _bar_values(form, encoding, table, *, grouped=False, cap):
    """Value at the end of each bar — above it, or beside it when horizontal."""
    if len(table) > cap:
        return None
    measure, category = form.measure_channel, form.category_channel
    if measure not in encoding or category not in encoding:
        return None
    field = encoding[measure]["field"]
    enc: dict[str, Any] = {
        category: encoding[category],
        measure: encoding[measure],
        "text": _value_text(field, _numbers(table, field)),
    }
    if grouped:
        # Without the same offset the labels sit over the group's centre rather
        # than over their own bar.
        offset = encoding.get(form.offset_channel)
        if offset is None:
            return None
        enc[form.offset_channel] = offset
    # A horizontal bar grows rightwards, so its label sits off the end of the
    # bar rather than on top of it. Reusing the vertical placement would park
    # every value above the bar's own row, next to the wrong category.
    mark = (
        _text_mark(dx=5, align="left", baseline="middle")
        if form.orientation == "horizontal"
        else _text_mark(dy=-5, baseline="bottom")
    )
    return {"mark": mark, "encoding": enc}


def _heatmap_values(form, encoding, table):
    """Value inside each cell, flipped to white over the dark end of the ramp."""
    if len(table) > MAX_LABELLED_CELLS:
        return None
    measure = encoding["color"]["field"]
    numbers = _numbers(table, measure)
    if not numbers:
        return None
    # Past the ramp's midpoint the cell is dark enough that ink text disappears.
    midpoint = (min(numbers) + max(numbers)) / 2
    return {
        # Clipped to the cell rather than spilling into the next one.
        "mark": _text_mark(limit={"expr": "bandwidth('x') - 2"}),
        "encoding": {
            "x": encoding["x"],
            "y": encoding["y"],
            "text": _value_text(measure, numbers),
            "color": {
                "condition": {"test": f"datum['{measure}'] > {midpoint}", "value": SURFACE},
                "value": SECONDARY_INK,
            },
        },
    }


def _series_at_line_end(form, encoding, table):
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


def _slice_categories(form, encoding, table):
    """Category name just outside its own arc, anchored away from the pie.

    Centred text at the rim spilled half its width past the edge of the card on
    both sides ("rivate room"), so each label is aligned outward instead —
    left-aligned on the right half, right-aligned on the left — and starts a few
    pixels beyond the slice. Slivers too thin to hold a name are left to the
    legend rather than printed over their neighbours.
    """
    category = encoding["color"]["field"]
    if len({row.get(category) for row in table}) > MAX_LABELLED_SLICES:
        return None
    theta = encoding["theta"]
    measure = theta.get("field")
    numbers = _numbers(table, measure) if measure else []
    total = sum(numbers)
    # Vega-Lite's stack writes <field>_start/_end; the angle at a slice's middle
    # says which side of the pie its label is on.
    mid = (
        f"scale('theta', 0.5 * datum['{measure}_start'] + 0.5 * datum['{measure}_end'])"
    )
    mark = _text_mark(
        radius={"expr": f"({ARC_OUTER_RADIUS}) + {ARC_LABEL_GAP}"},
        align={"expr": f"sin({mid}) >= 0 ? 'left' : 'right'"},
        baseline="middle",
        limit={"expr": ARC_LABEL_LIMIT},
    )
    enc: dict[str, Any] = {
        "theta": {**theta, "stack": True},
        "text": {"field": category, "type": "nominal"},
    }
    if total > 0:
        # Empty text rather than a filter: a filter would re-stack the remaining
        # slices and park every label at the wrong angle.
        enc["text"]["condition"] = {
            "test": f"datum['{measure}'] < {MIN_LABELLED_SLICE_SHARE * total}",
            "value": "",
        }
    return {"mark": mark, "encoding": enc}


# Per-type strategy. Absent means no labels, deliberately:
#   scatter   — one label per point is unreadable at any useful point count
#   histogram — bins are counts; the y axis already says what a label would
#   boxplot   — composite mark; its own tooltip carries the quartiles
#   bar+color — stacked segments; labels inside them collide at realistic sizes
_STRATEGIES = {
    "bar": lambda f, e, t: (
        None if "color" in e else _bar_values(f, e, t, cap=MAX_LABELLED_BARS)
    ),
    "grouped_bar": lambda f, e, t: _bar_values(
        f, e, t, grouped=True, cap=MAX_LABELLED_GROUPED_BARS
    ),
    "heatmap": _heatmap_values,
    "line": _series_at_line_end,
    "area": _series_at_line_end,
    "pie": _slice_categories,
    "donut": _slice_categories,
}


def build_label_layer(
    form: Any, encoding: dict[str, Any], result_table: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """The text layer for this chart, or None if it should carry no labels.

    `form` is a `chart_modifiers.Form`: the sub-type decides this as much as the
    family does. A stacked bar, a faceted anything, a density curve and an error
    chart each have a family that labels and a sub-type that must not — the
    reasoning for each is on `Form.draws_labels`, kept there so this module and
    the interaction layer read the same answer.
    """
    if not result_table or not form.draws_labels:
        return None
    strategy = _STRATEGIES.get(form.chart_type)
    if strategy is None:
        return None
    return strategy(form, encoding, result_table)
