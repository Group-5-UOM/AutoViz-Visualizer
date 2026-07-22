"""MVP allow-lists for the analysis-plan closed grammar (Docs/06-MCP-Server-Plan.md §2).

Anything outside these lists is a validation failure, not a warning — the LLM
never gets a fallback to raw expressions. The full-scope lists are kept here
commented so widening (e.g. gte/lte/between for date-range tasks) is a
one-line change.
"""

# Full: eq, neq, gt, gte, lt, lte, in, between, contains
FILTER_OPS = frozenset({"eq", "neq", "gt", "lt", "contains"})

# Full: sum, mean, count, min, max, median, count_distinct
AGG_FNS = frozenset({"sum", "mean", "min", "max", "count"})

DERIVE_FNS = frozenset({"month", "year", "day", "lower", "round"})

# Full: any validated Vega-Lite mark
CHART_TYPES = frozenset({"bar", "line", "scatter", "pie"})

MAX_GROUP_BY = 2
MAX_LIMIT = 1000

# Hard ceiling on rows returned by execution, regardless of what the plan requests.
HARD_ROW_CEILING = 1000

# Type-compatibility contracts used by validation.
NUMERIC_ONLY_AGGS = frozenset({"sum", "mean", "min", "max"})
DATE_DERIVE_FNS = frozenset({"month", "year", "day"})
STRING_DERIVE_FNS = frozenset({"lower"})
NUMERIC_DERIVE_FNS = frozenset({"round"})
STRING_ONLY_OPS = frozenset({"contains"})
ORDERED_OPS = frozenset({"gt", "lt"})
