"""Allow-lists for the analysis-plan closed grammar (Docs/06-MCP-Server-Plan.md §2).

Anything outside these lists is a validation failure, not a warning — the LLM
never gets a fallback to raw expressions. These are the full-scope lists; the
MVP subsets were widened once date-range/set filters and distribution charts
were needed.
"""

FILTER_OPS = frozenset(
    {"eq", "neq", "gt", "gte", "lt", "lte", "in", "between", "contains", "is_null", "is_not_null"}
)

# Value-less predicates: a null check takes no `value` and works on any column type.
NULL_OPS = frozenset({"is_null", "is_not_null"})

AGG_FNS = frozenset({"sum", "mean", "min", "max", "count", "median", "count_distinct"})

DERIVE_FNS = frozenset({"month", "year", "day", "weekday", "lower", "upper", "trim", "round", "abs"})

# Any validated Vega-Lite mark; histogram is a binned bar over one numeric column.
CHART_TYPES = frozenset({"bar", "line", "scatter", "pie", "area", "histogram"})

MAX_GROUP_BY = 2
MAX_LIMIT = 1000

# Hard ceiling on rows returned by execution, regardless of what the plan requests.
HARD_ROW_CEILING = 1000

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
# The closed set of cleaning operations. drop_nulls / drop_exact_duplicates remove
# rows (and so can trip the confirmation gate); fill_nulls imputes and never does.
PREPROCESS_OPS = frozenset({"drop_nulls", "fill_nulls", "drop_exact_duplicates"})

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

# Missing-value heuristic thresholds (fractions of input rows). Configurable
# heuristics, not fixed statistical rules — see execution.py / plan_guide.py.
ROW_DROP_CONFIRM_FRACTION = 0.30  # above this, removing rows needs confirmation
ROW_DROP_NOTICE_FRACTION = 0.05   # below this, exclude-and-report without asking
