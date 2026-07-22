"""Allow-lists for the analysis-plan closed grammar (Docs/06-MCP-Server-Plan.md §2).

Anything outside these lists is a validation failure, not a warning — the LLM
never gets a fallback to raw expressions. These are the full-scope lists; the
MVP subsets were widened once date-range/set filters and distribution charts
were needed.
"""

FILTER_OPS = frozenset({"eq", "neq", "gt", "gte", "lt", "lte", "in", "between", "contains"})

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
