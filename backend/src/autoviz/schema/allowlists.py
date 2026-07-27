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

DERIVE_FNS = frozenset({"month", "year", "day", "weekday", "lower", "upper", "trim", "round", "abs"})

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
DATE_DERIVE_FNS = frozenset({"month", "year", "day", "weekday"})
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
# Ceiling on `group_rare_categories.top_n`. Past this the chart is unreadable
# anyway, which is the problem the op exists to solve.
MAX_TOP_CATEGORIES = 50

# Missing-value heuristic thresholds (fractions of input rows). Configurable
# heuristics, not fixed statistical rules — see execution.py / plan_guide.py.
ROW_DROP_CONFIRM_FRACTION = 0.30  # above this, removing rows needs confirmation
ROW_DROP_NOTICE_FRACTION = 0.05   # below this, exclude-and-report without asking
