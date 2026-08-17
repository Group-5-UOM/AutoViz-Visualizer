"""Sub-types: the modifier layer over the ten chart families (Docs/13 §11).

Each of the ten `ChartType` values is a *family*, and every family has
recognised sub-types — a bar is vertical or horizontal, plain or stacked or
100% stacked; an area is plain, stacked or a streamgraph; a distribution over
groups is a box, a violin or a strip. This module is where a family plus its
modifiers becomes one specific Vega-Lite spec.

**Why modifiers rather than more type names.** Naming the sub-types needs a
literal per combination — `horizontal_stacked_bar_100` is a real shape someone
will ask for — and the enum passes twenty entries before it covers what
Vega-Lite already says in three properties. Docs/05 records that a wider
decision space measurably degrades plan quality, so the grammar composes
instead: `{"type": "bar", "orientation": "horizontal", "stack": "normalize"}`.

**Everything here defaults to off.** `Form.of()` over a spec with no modifiers
reproduces exactly the chart this pipeline drew before this module existed,
which is what lets it sit under a stored plan without changing its meaning.

**Three sub-types replace the mark outright** — a density histogram is an area,
a binned scatter is a rect grid, a violin is a stacked density — so `Form`
exposes the derived facts (`is_composite`, `is_pathlike`, `draws_labels`) that
the label and interaction layers have to branch on, rather than making each of
them re-derive the sub-type from the modifier fields.
"""

from dataclasses import dataclass
from typing import Any

from autoviz.schema.allowlists import (
    CHART_MODIFIERS,
    DEFAULT_FACET_COLUMNS,
    FACET_PANEL_HEIGHT,
    FACET_PANEL_WIDTH,
    MAX_FACETS,
)

# Vega-Lite composite marks. They expand into layered primitives, and the
# compiler refuses a selection param against them ("Unrecognized signal name"),
# so anything attaching interaction has to know which layer is safe to hang it
# on. See chart_interaction.attach.
COMPOSITE_MARKS = frozenset({"boxplot", "errorbar", "errorband"})

# Bubble size range, in square pixels. The floor is big enough to stay visible
# against the theme's 64px default point; the ceiling is where one bubble starts
# swallowing its neighbours at a realistic widget size.
BUBBLE_SIZE_RANGE = (30, 900)

# Overlapping bubbles have to show what is underneath them, and a bubble chart
# is nothing but overlaps. Also the resting opacity the interaction layer
# restores to, the way area does.
BUBBLE_OPACITY = 0.7
AREA_DENSITY_OPACITY = 0.7

# Bins per axis for a binned scatter. 30x30 is 900 cells — fine on a 400px
# panel, and enough resolution that a real cluster does not smear into one cell.
DENSITY_BINS = 30

# Jitter spread for points overlaid on a box, in pixels either side of centre.
JITTER_SPREAD = 14

# A violin panel is one distribution stood on end, so it wants to be tall and
# narrow — the facet grid's squarer panels squash the shape that is the point.
VIOLIN_PANEL_WIDTH = 90
VIOLIN_PANEL_HEIGHT = 300
# Namespaced like the interaction params, so a calculate transform we add can
# never collide with a column the dataset actually has.
JITTER_FIELD = "autoviz_jitter"
DENSITY_FIELD = "autoviz_density"
CUMULATIVE_FIELD = "autoviz_cumulative"


@dataclass(frozen=True)
class Form:
    """One resolved sub-type: a chart family plus every modifier decision.

    Built once in `generate_chart` and passed to the label and interaction
    layers, so "is this a violin?" is answered in one place rather than by three
    modules each re-reading `chart_spec`.
    """

    chart_type: str
    orientation: str = "vertical"
    stack: str | None = None
    interpolate: str | None = None
    points: bool = False
    size: str | None = None
    binned: bool = False
    density: bool = False
    cumulative: bool = False
    error: str | None = None
    distribution: str = "box"
    facet: str | None = None
    facet_columns: int = DEFAULT_FACET_COLUMNS
    time_unit: dict[str, str] | None = None

    @classmethod
    def of(cls, chart_spec: dict[str, Any]) -> "Form":
        """Read the modifiers off a chart spec, defaulting everything absent."""
        return cls(
            chart_type=chart_spec["type"],
            orientation=chart_spec.get("orientation") or "vertical",
            stack=chart_spec.get("stack"),
            interpolate=chart_spec.get("interpolate"),
            points=bool(chart_spec.get("points")),
            size=chart_spec.get("size"),
            binned=bool(chart_spec.get("bin")),
            density=bool(chart_spec.get("density")),
            cumulative=bool(chart_spec.get("cumulative")),
            error=chart_spec.get("error"),
            distribution=chart_spec.get("form") or "box",
            facet=chart_spec.get("facet"),
            facet_columns=chart_spec.get("facet_columns") or DEFAULT_FACET_COLUMNS,
            time_unit=chart_spec.get("time_unit") or None,
        )

    # --- channel roles --------------------------------------------------------
    # Orientation decides which axis is the measure, and almost every other
    # decision downstream (where a stack accumulates, which way a label sits,
    # which channel a ranking sorts) is really a question about that.

    @property
    def measure_channel(self) -> str:
        return "x" if self.orientation == "horizontal" else "y"

    @property
    def category_channel(self) -> str:
        return "y" if self.orientation == "horizontal" else "x"

    @property
    def offset_channel(self) -> str:
        """Where grouped bars sit side by side — across the category axis."""
        return "yOffset" if self.orientation == "horizontal" else "xOffset"

    # --- derived shape --------------------------------------------------------

    @property
    def is_violin(self) -> bool:
        return self.chart_type == "boxplot" and self.distribution == "violin"

    @property
    def is_strip(self) -> bool:
        return self.chart_type == "boxplot" and self.distribution == "strip"

    @property
    def is_box(self) -> bool:
        return self.chart_type == "boxplot" and self.distribution == "box"

    @property
    def is_composite(self) -> bool:
        """True when the *primary* mark is one Vega-Lite refuses params on."""
        return self.is_box

    @property
    def is_pathlike(self) -> bool:
        """True when the mark is a continuous path, so per-datum opacity splits it.

        A conditional opacity is evaluated per row; on a line, an area or a
        density curve that means the mark renders in differently-opaque
        segments rather than dimming as one thing. The density and cumulative
        histograms are here because they *become* areas, which is exactly the
        kind of fact a caller should not have to re-derive.
        """
        return (
            self.chart_type in ("line", "area")
            or (self.chart_type == "histogram" and (self.density or self.cumulative))
            or self.is_violin
        )

    @property
    def is_faceted(self) -> bool:
        """True when the top level is a facet rather than a single frame.

        A violin is faceted whether or not the caller asked: the standard
        Vega-Lite violin puts one density per column with the panels butted
        together, and there is no unfaceted spelling of it.
        """
        return self.facet is not None or self.is_violin

    @property
    def replaces_mark(self) -> bool:
        """True when a modifier substitutes a different mark for the family's own."""
        return self.binned or self.density or self.cumulative or self.is_violin or self.is_strip

    @property
    def draws_labels(self) -> bool:
        """Whether direct labels are worth drawing on this sub-type at all.

        Four sub-types close the door that their family left open:

        * **stacked anything** — labels inside segments collide at realistic
          widths, which is why plain `bar` + colour already carried none.
        * **error marks** — the mark aggregates in Vega, so a label bound to the
          raw column would print a different number from the one drawn.
        * **faceted** — a panel is `FACET_PANEL_WIDTH` wide; values on bars that
          narrow overlap their neighbours before the second panel.
        * **mark-replacing sub-types** — a density curve, a binned grid and a
          strip of ticks have nothing a per-row value label would name.

        The table view is the accessibility relief in each case, the same way it
        already is for scatter and stacked bar (Docs/13 §6.2).
        """
        return not (
            self.stack
            or self.error
            or self.is_faceted
            or self.replaces_mark
            or self.size
        )


_MODIFIER_FIELDS = frozenset(
    {
        "size", "facet", "orientation", "stack", "interpolate", "points",
        "time_unit", "bin", "density", "cumulative", "error", "form",
    }
)

# facet_columns is not a modifier in its own right — it is how wide `facet`
# wraps — so it is checked and dropped alongside facet rather than needing its
# own entry against all ten types.
_TRAVELS_WITH = {"facet_columns": "facet"}


def unsupported_modifiers(chart_spec: dict[str, Any]) -> list[str]:
    """Modifiers set on a chart type that has no use for them.

    Returned rather than raised because `generate_chart` reports through a
    warnings list, and because the caller wants all of them at once instead of
    discovering them one re-plan at a time.
    """
    allowed = CHART_MODIFIERS.get(chart_spec.get("type"), frozenset())
    offenders = set()
    for name in _MODIFIER_FIELDS | set(_TRAVELS_WITH):
        if chart_spec.get(name) is None:
            continue
        if _TRAVELS_WITH.get(name, name) not in allowed:
            offenders.add(name)
    return sorted(offenders)


def strip_unsupported(chart_spec: dict[str, Any], chart_type: str) -> dict[str, Any]:
    """`chart_spec` with the modifiers the new type cannot carry removed.

    Retyping a chart keeps everything it can (`retype_chart_spec`), and a
    modifier is part of "everything" — turning a horizontal bar into a
    horizontal box plot should keep it on its side. But carrying `stack` onto a
    scatter would produce a plan the validator rejects, from a change the user
    made in one click and never typed.
    """
    allowed = CHART_MODIFIERS.get(chart_type, frozenset())
    dropped = _MODIFIER_FIELDS - allowed
    if "facet" in dropped:
        dropped = dropped | {"facet_columns"}
    return {k: v for k, v in chart_spec.items() if k not in dropped}


# --- applying the modifiers ---------------------------------------------------


def _apply_time_units(form: Form, encoding: dict[str, Any]) -> None:
    """Bucket a temporal channel in the chart rather than in SQL.

    The pipeline normally buckets dates in the query (`month_start` and friends),
    and that stays the better route for a trend. This exists for the shape SQL
    cannot express in one pass: a calendar heatmap needs the *same* date column
    on both axes at two different granularities — week down one, weekday across
    — and a GROUP BY produces one column per expression, not one column read two
    ways.
    """
    if not form.time_unit:
        return
    for channel, unit in form.time_unit.items():
        field_def = encoding.get(channel)
        if not isinstance(field_def, dict) or "field" not in field_def:
            continue
        field_def["timeUnit"] = unit
        if form.chart_type == "heatmap":
            # A heatmap axis is a row of cells, not a continuous time line: the
            # unit's buckets *are* the categories. Left temporal, Vega draws a
            # date axis and the grid stops being a grid.
            field_def["type"] = "ordinal"
        elif field_def.get("type") == "nominal":
            field_def["type"] = "temporal"


def _apply_orientation(form: Form, encoding: dict[str, Any]) -> dict[str, Any]:
    """Turn the chart on its side by swapping the positional channels.

    A horizontal bar is not a different chart — it is the same encoding read
    down the page instead of across it, which is the fix for category labels
    long or numerous enough that the vertical form truncates them.
    """
    if form.orientation != "horizontal":
        return encoding
    swapped = dict(encoding)
    x, y = encoding.get("x"), encoding.get("y")
    if x is not None:
        swapped["y"] = x
    else:
        swapped.pop("y", None)
    if y is not None:
        swapped["x"] = y
    else:
        swapped.pop("x", None)
    if "xOffset" in swapped:
        swapped["yOffset"] = swapped.pop("xOffset")
    return swapped


def _apply_ranking_sort(form: Form, encoding: dict[str, Any], intent: str | None) -> None:
    """Order a ranking bar by its measure.

    Lives here rather than in `generate_chart` because which channel to sort and
    what to sort it by are both orientation questions, and getting them from the
    wrong axis silently produces an unsorted chart whose rationale claims it is
    sorted.
    """
    if intent != "ranking" or form.chart_type != "bar":
        return
    category = encoding.get(form.category_channel)
    if not isinstance(category, dict) or category.get("type") != "nominal":
        # Sorting a time axis by value destroys the axis.
        return
    category["sort"] = f"-{form.measure_channel}"


def _apply_stack(form: Form, encoding: dict[str, Any]) -> None:
    """Plain stack, 100%-normalised, streamgraph, or overlaid.

    Only the measure channel carries a stack, and which channel that is depends
    on orientation — which is the whole reason this runs after the swap.
    """
    if form.stack is None:
        return
    measure = encoding.get(form.measure_channel)
    if not isinstance(measure, dict):
        return
    # Vega-Lite spells "do not stack" as null, not as a mode name.
    measure["stack"] = None if form.stack == "none" else form.stack
    if form.stack == "normalize":
        # Every column now sums to 1. An axis still reading 0.0-1.0 invites the
        # reader to take the values as absolute, which is the one thing a 100%
        # stack has stopped showing.
        measure["axis"] = {**(measure.get("axis") or {}), "format": ".0%"}
        measure["title"] = "share"
    elif form.stack == "center":
        # A streamgraph's baseline wanders, so the axis measures nothing a
        # reader can use — the shape is the message. Vega-Lite's own streamgraph
        # example drops it for the same reason.
        measure["axis"] = None


def _apply_interpolate(form: Form, mark: Any) -> Any:
    """Path shape: straight, stepped, or smoothed."""
    if form.interpolate is None or form.interpolate == "linear":
        return mark
    base = mark if isinstance(mark, dict) else {"type": mark}
    return {**base, "interpolate": form.interpolate}


def _apply_points(form: Form, mark: Any) -> Any:
    """Mark every datum on a path.

    `generate_chart` already does this for a one-row line, where the alternative
    is a blank panel. Asking for it explicitly is the same property for the case
    where the reader wants to know where the readings actually are, as opposed
    to where the line interpolates between them.
    """
    if not form.points or form.chart_type not in ("line", "area"):
        return mark
    base = mark if isinstance(mark, dict) else {"type": mark}
    return {**base, "point": True}


def _apply_bubble(form: Form, encoding: dict[str, Any], mark: Any) -> Any:
    """Scatter + magnitude.

    Area, not radius: Vega-Lite's `size` is the mark's area in square pixels,
    which is the perceptually honest mapping — sizing by radius squares the
    quantity and overstates the big values by exactly that much.
    """
    if not form.size:
        return mark
    encoding["size"] = {
        "field": form.size,
        "type": "quantitative",
        "scale": {"range": list(BUBBLE_SIZE_RANGE)},
    }
    base = mark if isinstance(mark, dict) else {"type": mark}
    # A bubble chart is nothing but overlaps, so the marks have to be see-through
    # or the biggest one simply deletes whatever it covers.
    return {**base, "filled": True, "opacity": BUBBLE_OPACITY}


def _apply_binned_density(form: Form, encoding: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    """Overplotted scatter -> a grid of counts.

    Past a few thousand points a scatter is a solid block: the marks are all
    there and the density is unreadable, which is the one thing the chart was
    drawn to show. Binning both axes and counting per cell recovers it.

    This is a rect grid, so it is a heatmap in everything but name — and it
    picks up the heatmap's blue ramp from the theme for free, because
    `config.range.heatmap` drives any rect colour scale.

    True hexbin is deliberately not what this does. Vega-Lite has no hexbin
    transform; the published recipe fakes it with calculate transforms and a
    hardcoded hexagon path whose size has to track the plot dimensions, and it
    breaks the moment a chart is container-sized — which ours all are.
    """
    x, y = encoding["x"], encoding["y"]
    binned = {
        "x": {**x, "type": "quantitative", "bin": {"maxbins": DENSITY_BINS}},
        "y": {**y, "type": "quantitative", "bin": {"maxbins": DENSITY_BINS}},
        "color": {"aggregate": "count", "type": "quantitative", "title": "points"},
    }
    return "rect", binned


def _apply_density_curve(
    form: Form, encoding: dict[str, Any]
) -> tuple[Any, dict[str, Any], list[dict[str, Any]]]:
    """Histogram -> kernel density estimate.

    A histogram's shape depends on where the bin edges happen to fall; a density
    curve does not, which is why it is the better read of a distribution whose
    modes matter. It is a curve rather than bars, so it carries no labels and
    dims as one mark.
    """
    field = encoding["x"]["field"]
    series = encoding.get("color")
    transform: dict[str, Any] = {"density": field, "as": [field, DENSITY_FIELD]}
    if isinstance(series, dict) and "field" in series:
        # Without this every series is smoothed into one curve, which answers a
        # question nobody asked.
        transform["groupby"] = [series["field"]]
    new_encoding: dict[str, Any] = {
        "x": {"field": field, "type": "quantitative"},
        "y": {"field": DENSITY_FIELD, "type": "quantitative", "title": "density"},
    }
    if isinstance(series, dict):
        new_encoding["color"] = series
    return {"type": "area", "opacity": AREA_DENSITY_OPACITY}, new_encoding, [transform]


def _apply_cumulative(
    form: Form, encoding: dict[str, Any]
) -> tuple[Any, dict[str, Any], list[dict[str, Any]]]:
    """Histogram -> cumulative distribution.

    Answers "how much is below this value" directly, instead of asking the
    reader to add bars up by eye. A running count over the sorted column, which
    is a window frame from the start of the partition to the current row.
    """
    field = encoding["x"]["field"]
    series = encoding.get("color")
    window: dict[str, Any] = {
        "sort": [{"field": field}],
        "window": [{"op": "count", "field": field, "as": CUMULATIVE_FIELD}],
        "frame": [None, 0],
    }
    if isinstance(series, dict) and "field" in series:
        window["groupby"] = [series["field"]]
    new_encoding: dict[str, Any] = {
        "x": {"field": field, "type": "quantitative"},
        "y": {
            "field": CUMULATIVE_FIELD,
            "type": "quantitative",
            "title": f"cumulative count of {field}",
        },
    }
    if isinstance(series, dict):
        new_encoding["color"] = series
    return {"type": "area", "interpolate": "step-after"}, new_encoding, [window]


def _apply_violin(form: Form, encoding: dict[str, Any]) -> tuple[Any, dict[str, Any], list]:
    """Box plot -> violin.

    A box states five numbers; a violin states the whole distribution, which is
    the difference between seeing that two groups have the same median and
    seeing that one of them is bimodal.

    Faceted by construction. Vega-Lite has no unfaceted violin: the density runs
    along the value axis and is mirrored about its own centre, so each group
    needs its own frame with the panels butted together. That is what
    `column` + zero spacing does here, and it is why `facet` and `form: violin`
    cannot both be asked for.
    """
    category = encoding["x"]["field"]
    value = encoding["y"]["field"]
    transform = {
        "density": value,
        "groupby": [category],
        "as": [value, DENSITY_FIELD],
    }
    new_encoding: dict[str, Any] = {
        "y": {"field": value, "type": "quantitative"},
        "x": {
            "field": DENSITY_FIELD,
            "type": "quantitative",
            # Mirrored about the centre — the half either side is what makes it
            # read as one shape rather than two curves.
            "stack": "center",
            "impute": None,
            "title": None,
            "axis": {"labels": False, "ticks": False, "grid": False},
        },
        "column": {
            "field": category,
            "type": "nominal",
            "header": {"titleOrient": "bottom", "labelOrient": "bottom"},
            "spacing": 0,
        },
    }
    return "area", new_encoding, [transform]


def _apply_strip(form: Form, encoding: dict[str, Any]) -> Any:
    """Box plot -> strip plot.

    Every value as its own tick. At small n this is the honest chart and a box
    is not: quartiles over five points draw a confident-looking summary of a
    sample that cannot support one, and the box hides that there were five.
    """
    return {"type": "tick", "thickness": 2, "size": 22, "opacity": 0.7}


def _jitter_layer(form: Form, encoding: dict[str, Any]) -> dict[str, Any]:
    """Raw points scattered across the band, to overlay on a box.

    A box tells you the quartiles and nothing about how many rows produced them.
    The jitter is across the *category* band only — displacing a point along the
    value axis would move it to a value it does not have.
    """
    return {
        "transform": [{"calculate": "random()", "as": JITTER_FIELD}],
        "mark": {"type": "point", "filled": True, "size": 18, "opacity": 0.45},
        "encoding": {
            form.category_channel: encoding[form.category_channel],
            form.measure_channel: encoding[form.measure_channel],
            form.offset_channel: {
                "field": JITTER_FIELD,
                "type": "quantitative",
                "scale": {"range": [-JITTER_SPREAD, JITTER_SPREAD]},
            },
        },
    }


def _error_layer(form: Form, encoding: dict[str, Any]) -> dict[str, Any]:
    """A composite uncertainty mark reading the same raw rows as the primary.

    `extent: "ci"` is a bootstrapped 95% confidence interval on the mean, which
    is the interval that matches what the primary mark now draws — see
    `apply`, where the measure channel picks up `aggregate: "mean"` for exactly
    this reason.
    """
    composite_encoding = {
        form.category_channel: encoding[form.category_channel],
        # The raw column, deliberately without the mean the primary mark takes:
        # the composite computes its own interval from the individual values.
        form.measure_channel: {
            k: v
            for k, v in encoding[form.measure_channel].items()
            if k not in ("aggregate", "stack", "axis", "title")
        },
    }
    if isinstance(encoding.get("color"), dict):
        composite_encoding["color"] = encoding["color"]
    mark = "errorband" if form.error == "band" else "errorbar"
    return {"mark": {"type": mark, "extent": "ci"}, "encoding": composite_encoding}


def apply(
    form: Form,
    encoding: dict[str, Any],
    mark: Any,
    intent: str | None,
) -> tuple[Any, dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], int]:
    """Fold every modifier into one mark + encoding.

    Returns ``(mark, encoding, transforms, extra_layers, data_index)``.
    ``extra_layers`` are siblings the sub-type needs (an error band, a jitter
    overlay) and ``data_index`` is where the primary mark ends up once they are
    interleaved — the interaction layer needs it because a composite sibling
    cannot carry a selection param and the primary is not always first.

    Order matters and is not arbitrary: mark-replacing sub-types run before the
    orientation swap so they swap too, and `stack`/`sort` run after it because
    both name a channel that the swap has just moved.
    """
    transforms: list[dict[str, Any]] = []
    extra_layers: list[dict[str, Any]] = []
    data_index = 0

    # 1. Sub-types that substitute a different mark for the family's own. Each
    #    rebuilds the encoding from scratch, so nothing below can assume the
    #    channels it started with.
    if form.binned:
        mark, encoding = _apply_binned_density(form, encoding)
    elif form.density:
        mark, encoding, transforms = _apply_density_curve(form, encoding)
    elif form.cumulative:
        mark, encoding, transforms = _apply_cumulative(form, encoding)
    elif form.is_violin:
        mark, encoding, transforms = _apply_violin(form, encoding)
    elif form.is_strip:
        mark = _apply_strip(form, encoding)

    # 2. Channels that only make sense on the family's own mark.
    mark = _apply_bubble(form, encoding, mark)
    mark = _apply_interpolate(form, mark)
    mark = _apply_points(form, mark)
    _apply_time_units(form, encoding)

    # 3. Turn it on its side. A violin is already laid out along its own axes
    #    and has no vertical/horizontal reading to swap.
    if not form.is_violin:
        encoding = _apply_orientation(form, encoding)

    # 4. Everything that names a positional channel, now that the swap has
    #    decided which channel that is.
    _apply_ranking_sort(form, encoding, intent)
    _apply_stack(form, encoding)

    # 5. Sibling layers.
    if form.error:
        # The composite computes an interval over the raw rows, so the primary
        # mark has to draw the matching centre — the mean of those same rows,
        # aggregated here rather than in SQL because the SQL result is raw by
        # the time an error mark is legal at all (validation refuses it over an
        # aggregating plan, for the reason boxplot does).
        measure = encoding.get(form.measure_channel)
        if isinstance(measure, dict):
            measure["aggregate"] = "mean"
        composite = _error_layer(form, encoding)
        if form.error == "band":
            # Under the line, or it paints over the thing it is qualifying.
            extra_layers.append(composite)
            data_index = 1
        else:
            extra_layers.append(composite)
    elif form.points and form.is_box:
        extra_layers.append(_jitter_layer(form, encoding))

    return mark, encoding, transforms, extra_layers, data_index


def facet_wrapper(form: Form, inner: dict[str, Any]) -> dict[str, Any]:
    """Wrap a built chart as small multiples.

    The principled answer to "too many series": it separates them in space
    rather than asking the palette for a ninth hue it does not have (Docs/13
    §10). Scales are shared across panels by Vega-Lite's default, which is the
    entire point — panels on independent scales are not comparable, and
    comparison is what a reader opens a facet grid to do.

    Container sizing does not survive here. Vega-Lite ignores `"container"` on a
    faceted top level, so each panel takes a real size and the grid does not
    reflow with the widget. Recorded rather than worked around: the alternative
    is measuring the widget on the backend, which has no widget.
    """
    return {
        "facet": {"field": form.facet, "type": "nominal", "title": form.facet},
        "columns": form.facet_columns,
        "spec": {**inner, "width": FACET_PANEL_WIDTH, "height": FACET_PANEL_HEIGHT},
    }


def apply_sizing(form: Form, spec: dict[str, Any]) -> None:
    """Size the chart from its container, or from its panels where it must.

    Charts normally take `"container"` so they reflow when the widget is
    resized. Vega-Lite ignores that on any spec with a facet at the top, so
    faceted sub-types take a real per-panel size instead and do not reflow.
    """
    if form.is_violin:
        spec["width"] = VIOLIN_PANEL_WIDTH
        spec["height"] = VIOLIN_PANEL_HEIGHT
    elif form.facet is not None:
        return  # facet_wrapper already sized each panel
    else:
        spec["width"] = "container"
        spec["height"] = "container"


def modifier_conflicts(chart_spec: dict[str, Any]) -> list[str]:
    """Modifier pairs that are each legal alone and contradict each other together.

    Separate from `unsupported_modifiers`, which asks whether a modifier belongs
    on this *type*. These are combinations within one type, and every one of
    them would otherwise render something — just not the thing that was asked
    for, which is the failure mode this whole grammar exists to avoid.
    """
    form = Form.of(chart_spec)
    problems: list[str] = []

    if form.density and form.cumulative:
        problems.append(
            "chart: density and cumulative are two different readings of the same "
            "column — a smoothed distribution or a running total. Ask for one."
        )
    if form.binned and chart_spec.get("color"):
        problems.append(
            "chart: a binned scatter puts the count of points on colour, so it has "
            "no colour channel left for a series. Drop color, or drop bin and cap "
            "the series instead."
        )
    if form.stack and not chart_spec.get("color"):
        problems.append(
            f"chart: stack '{form.stack}' needs a color column — there is nothing to "
            "stack without a series to divide each mark into."
        )
    if form.facet and form.is_violin:
        problems.append(
            "chart: a violin is already one panel per category, so it cannot also be "
            "faceted. Drop facet, or use form 'box' with the facet."
        )
    if form.points and form.chart_type == "boxplot" and not form.is_box:
        problems.append(
            f"chart: points overlays the raw values on a box, and form '{form.distribution}' "
            "already draws every value. Drop points."
        )
    if form.error and form.stack:
        problems.append(
            "chart: an error interval is computed about a mean, and a stacked mark has "
            "no single mean to put one on. Drop the stack."
        )
    if form.facet and chart_spec.get("facet") == chart_spec.get("color"):
        problems.append(
            f"chart: faceting and colouring by the same column ('{form.facet}') says the "
            "same thing twice — every panel would hold exactly one colour."
        )
    return problems


def facet_warning(form: Form, panels: int) -> str | None:
    """Whether this many panels is still a chart anyone can read."""
    if form.facet is None or panels <= MAX_FACETS:
        return None
    return (
        f"facet on '{form.facet}' produces {panels} panels (> {MAX_FACETS}) — each one "
        "is too small to read. Cap the categories with group_rare_categories or a "
        "filter, or drop the facet and use colour."
    )
