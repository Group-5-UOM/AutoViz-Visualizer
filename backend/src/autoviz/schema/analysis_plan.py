"""Canonical analysis-plan schema — single source of truth for the plan shape.

Pydantic v2 models implementing Docs/06-MCP-Server-Plan.md §2. Allow-lists are
enforced structurally via Literal types at parse time; semantic checks against
a dataset's profiled schema live in services/validation.py.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

FilterOp = Literal["eq", "neq", "gt", "gte", "lt", "lte", "in", "between", "contains"]
AggFn = Literal["sum", "mean", "min", "max", "count", "median", "count_distinct"]
DeriveFn = Literal[
    "month", "year", "day", "weekday", "lower", "upper", "trim", "round", "abs"
]
ChartType = Literal["bar", "line", "scatter", "pie", "area", "histogram"]
Intent = Literal[
    "comparison", "trend", "distribution", "relationship", "composition", "ranking"
]
SortDir = Literal["asc", "desc"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Filter(_StrictModel):
    column: str
    op: FilterOp
    # Scalar for most ops; a list of scalars for "in" (any length) and
    # "between" ([low, high]). Arity is checked in services/validation.py.
    value: Any


class Derive(_StrictModel):
    name: str
    from_: str = Field(alias="from")
    fn: DeriveFn


class Aggregation(_StrictModel):
    column: str
    fn: AggFn
    as_: str = Field(alias="as")


class Sort(_StrictModel):
    by: str
    dir: SortDir = "asc"


class ChartSpec(_StrictModel):
    type: ChartType
    x: str
    # Optional only for histogram (count of binned x); every other chart type
    # requires y — enforced in services/validation.py.
    y: str | None = None
    color: str | None = None


class AnalysisPlan(_StrictModel):
    dataset_id: str
    intent: Intent
    select: list[str] = Field(default_factory=list)
    filters: list[Filter] = Field(default_factory=list)
    derive: list[Derive] = Field(default_factory=list)
    group_by: list[str] = Field(default_factory=list, max_length=2)
    aggregations: list[Aggregation] = Field(default_factory=list)
    sort: list[Sort] = Field(default_factory=list)
    # None = "no explicit cap": execution returns the full result up to the hard
    # row ceiling. This matters for non-aggregated distribution/relationship
    # queries whose rows ARE the chart data (histogram bins, scatter points) — a
    # small default here would silently truncate them. Set an explicit limit only
    # to cap ranking/top-N.
    limit: int | None = Field(default=None, ge=1)
    chart: ChartSpec | None = None

    def produced_columns(self) -> set[str]:
        """Columns present in the result table this plan would produce."""
        if self.group_by or self.aggregations:
            return set(self.group_by) | {a.as_ for a in self.aggregations}
        produced = set(self.select) | {d.name for d in self.derive}
        return produced
