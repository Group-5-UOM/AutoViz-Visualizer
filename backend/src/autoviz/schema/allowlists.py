"""Allow-lists for the analysis-plan closed grammar (Docs/06-MCP-Server-Plan.md §2).

Anything outside these lists is a validation failure, not a warning — the LLM
never gets a fallback to raw expressions. These are the full-scope lists; the
MVP subsets were widened once date-range/set filters and distribution charts
were needed.
"""

from enum import Enum

FILTER_OPS = frozenset(
    {"eq", "neq", "gt", "gte", "lt", "lte", "in", "between", "contains", "is_null", "is_not_null"}
)

# Value-less predicates: a null check takes no `value` and works on any column type.
NULL_OPS = frozenset({"is_null", "is_not_null"})

AGG_FNS = frozenset({"sum", "mean", "min", "max", "count", "median", "count_distinct"})

DERIVE_FNS = frozenset(
    {
        "month", "year", "day", "weekday",
        "month_start", "quarter_start", "week_start", "year_start",
        "lower", "upper", "trim", "round", "abs",
    }
)

# Any validated Vega-Lite mark. Several are not one-to-one with a Vega mark:
# histogram is a binned bar over one numeric column, grouped_bar is a bar with an
# xOffset (a plain bar + colour stacks instead), donut is an arc with an inner
# radius, and heatmap is a rect grid whose colour carries the measure rather than
# a series. See Docs/13 §6.
CHART_TYPES = frozenset(
    {
        "bar",
        "line",
        "scatter",
        "pie",
        "area",
        "histogram",
        "heatmap",
        "boxplot",
        "grouped_bar",
        "donut",
    }
)

# --- chart modifiers ----------------------------------------------------------
# Sub-types are modifiers on the ten types above, not eleventh and twelfth names.
# A horizontal 100%-stacked bar is `bar` + two modifiers; naming it would need a
# literal per orientation x stack x interpolate combination, and Docs/05 records
# that widening the model's decision space is itself a measurable quality cost.
#
# Every value here maps onto a Vega-Lite property that already exists — these
# widen the *plan* grammar to reach Vega-Lite's, they do not invent geometry.

# Which axis carries the category. Bars, boxes and histograms can turn on their
# side; a horizontal bar is the fix for long or numerous category labels, which
# the vertical form truncates.
ORIENTATIONS = frozenset({"vertical", "horizontal"})

# What a series-bearing bar or area does with its segments. "zero" is the
# Vega-Lite default (a plain stack), "normalize" makes every column sum to 100%,
# "center" is the streamgraph offset, "none" overlays them.
STACK_MODES = frozenset({"zero", "normalize", "center", "none"})

# Path shape between points. "step" is the correct form for a value that holds
# until it changes (a price, a headcount) rather than sliding between readings.
INTERPOLATIONS = frozenset({"linear", "step", "monotone"})

# Distribution forms over a category. All three answer the same question with
# different amounts of summarising: box = quartiles, violin = the whole density,
# strip = every value. Strip is the honest one at small n, where a box invents
# structure out of four points.
DISTRIBUTION_FORMS = frozenset({"box", "violin", "strip"})

# Uncertainty marks layered under a line or bar. Both are Vega-Lite composites
# that compute the interval from the raw rows, so both need an unaggregated plan.
ERROR_FORMS = frozenset({"bar", "band"})

# Vega-Lite timeUnit values worth exposing. Restricted to the ones that bucket a
# date for a chart axis; the full list includes sub-second units that no result
# table of ours carries.
TIME_UNITS = frozenset(
    {
        "year", "quarter", "month", "week", "date", "day", "hours",
        "yearquarter", "yearmonth", "yearmonthdate", "monthdate",
    }
)

# Channels a timeUnit may be applied to.
TIME_UNIT_CHANNELS = frozenset({"x", "y", "color"})

# Which modifiers each chart type accepts. A modifier on a type that has no use
# for it is a rejected plan, not a silently ignored field: `extra="forbid"` on
# ChartSpec catches a *misspelled* modifier, and only this catches a well-formed
# one aimed at the wrong chart. Both failures look identical to the user
# otherwise — a chart that came back not doing what was asked.
CHART_MODIFIERS: dict[str, frozenset[str]] = {
    "bar": frozenset({"orientation", "stack", "facet", "error", "time_unit"}),
    "grouped_bar": frozenset({"orientation", "facet", "time_unit"}),
    "line": frozenset({"interpolate", "points", "facet", "error", "time_unit"}),
    "area": frozenset({"interpolate", "stack", "points", "facet", "time_unit"}),
    "scatter": frozenset({"size", "bin", "facet"}),
    "histogram": frozenset({"orientation", "density", "cumulative", "facet"}),
    "pie": frozenset({"facet"}),
    "donut": frozenset({"facet"}),
    "heatmap": frozenset({"facet", "time_unit"}),
    "boxplot": frozenset({"orientation", "form", "points", "facet"}),
}

# Every modifier name, for the "which types accept this?" half of the error.
ALL_CHART_MODIFIERS = frozenset().union(*CHART_MODIFIERS.values())

# Small multiples: how many panels before the grid is unreadable, and how wide
# the wrap is by default. Nine panels at ~180px is a legible page; past that the
# principled answer is a filter, not a smaller panel.
MAX_FACETS = 12
DEFAULT_FACET_COLUMNS = 3
# Faceted specs cannot use container sizing — Vega-Lite ignores "container" on a
# faceted top level — so each panel gets a real size instead.
FACET_PANEL_WIDTH = 180
FACET_PANEL_HEIGHT = 140

# Legible ceilings for the colour channel. Adjacent forms (bars, lines, stacked
# segments) place series next to each other and can carry the full token set;
# all-pairs forms (scatter) put every series beside every other, so any two hues
# have to be separable and the safe ceiling is far lower.
MAX_SERIES_ADJACENT = 8
MAX_SERIES_ALL_PAIRS = 3

MAX_GROUP_BY = 2
MAX_LIMIT = 100_000

# Hard ceiling on rows returned by execution, regardless of what the plan requests.
HARD_ROW_CEILING = 100_000

# Type-compatibility contracts used by validation.
NUMERIC_ONLY_AGGS = frozenset({"sum", "mean", "min", "max", "median"})

# Truncation, not extraction: these keep the instant and flatten it to the start of
# its month/quarter/week/year, so the result is still a *datetime* and still sorts
# and spaces correctly on a time axis.
#
# The distinction from the extraction fns below is the difference between a correct
# and a wrong chart. `month` yields a bare 1-12, so a monthly trend spanning two
# years collapses both into twelve points with January 2025 and January 2026 added
# together. That is right for a seasonality question ("which month is busiest?")
# and wrong for every trend, which is the commoner request.
DATETIME_DERIVE_FNS = frozenset({"month_start", "quarter_start", "week_start", "year_start"})

# Extraction: datetime -> a bare number (month gives 1-12, weekday 0-6).
#
# Named separately from the truncating fns above because the *result* is a
# different kind of thing, and lumping the two together is what made a trend
# over an extracted month come back as a scatter: a bare 1-12 was typed "number",
# which emptied both the temporal and the categorical bucket and left the
# recommender with nothing but measures. These are ordered discrete positions —
# ORDINAL — not quantities to be summed.
DATE_PART_DERIVE_FNS = frozenset({"month", "year", "day", "weekday"})

# Every fn that reads a datetime column, whatever it returns.
DATE_DERIVE_FNS = DATE_PART_DERIVE_FNS | DATETIME_DERIVE_FNS
STRING_DERIVE_FNS = frozenset({"lower", "upper", "trim"})
NUMERIC_DERIVE_FNS = frozenset({"round", "abs"})
STRING_ONLY_OPS = frozenset({"contains"})
ORDERED_OPS = frozenset({"gt", "gte", "lt", "lte", "between"})

# Ops whose value is a list, and the arity/size limits on those lists.
LIST_VALUE_OPS = frozenset({"in", "between"})
MAX_IN_VALUES = 20

# --- Preprocessing (explicit, provenance-tracked cleaning) --------------------
# The closed set of cleaning operations is the PreprocessOp union in
# schema/analysis_plan.py — the models carry their own row/risk behaviour, so a
# parallel name list here would only be a second thing to forget to update.


class Risk(str, Enum):
    """How far a cleaning op can move the answer — the primary consent axis.

    Percentage is the *secondary* axis: it escalates within a tier (see
    ROW_DROP_CONFIRM_FRACTION) but never demotes one. Changing 1% of a revenue
    column can move a total materially, while trimming whitespace from 80% of
    category labels changes nothing — so "how many rows" cannot decide consent
    on its own.
    """

    # Semantics-preserving. The corrected data means what the original meant, so
    # this is applied automatically and reported, never asked about.
    SAFE = "safe"
    # Alters values or row membership, and so can alter the result. Always
    # confirmed, at any fraction of rows — including below 5%.
    VALUE_CHANGING = "value_changing"
    # Correctness is not determinable from the data alone (e.g. a fuzzily-inferred
    # category merge). Never auto-proposed at any percentage; only ever applied
    # when the user asked for it explicitly.
    AMBIGUOUS = "ambiguous"

# Imputation strategies, split by the column type each is valid on. mean is
# deliberately excluded from the MVP (sensitive to outliers).
FILL_STRATEGIES = frozenset({"constant", "median", "mode"})
NUMERIC_FILL_STRATEGIES = frozenset({"median"})   # numeric columns only
CATEGORICAL_FILL_STRATEGIES = frozenset({"mode"})  # string/boolean columns only
CONSTANT_STRATEGY = "constant"                      # any column type

# Resource ceilings on a single preprocessing block, all env-overridable at the
# call sites that read them. Bound the work and the blast radius of a bad plan.
MAX_PREPROCESSING_STEPS = 10
MAX_PREPROCESSING_COLUMNS = 20
MAX_FILL_STRING_LEN = 256

# Category cleaning. An explicit mapping is one CASE arm per entry, so the cap
# bounds both the generated SQL and how much relabelling can happen in one
# unreviewable step.
MAX_CATEGORY_MAPPING = 50
# How many distinct values one nullify_values op may reclassify as missing. Small
# on purpose: this op says "these codes mean nothing was recorded", and a list
# long enough to need scrolling is a category merge wearing a disguise.
MAX_NULLIFY_VALUES = 20

# Ceiling on `group_rare_categories.top_n`. Past this the chart is unreadable
# anyway, which is the problem the op exists to solve.
MAX_TOP_CATEGORIES = 50

# Missing-value heuristic thresholds (fractions of input rows). Configurable
# heuristics, not fixed statistical rules — see execution.py / plan_guide.py.
ROW_DROP_CONFIRM_FRACTION = 0.30  # above this, removing rows needs confirmation
ROW_DROP_NOTICE_FRACTION = 0.05   # below this, exclude-and-report without asking
