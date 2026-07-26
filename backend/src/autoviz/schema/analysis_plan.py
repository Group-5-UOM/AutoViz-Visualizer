"""Canonical analysis-plan schema — single source of truth for the plan shape.

Pydantic v2 models implementing Docs/06-MCP-Server-Plan.md §2. Allow-lists are
enforced structurally via Literal types at parse time; semantic checks against
a dataset's profiled schema live in services/validation.py.
"""

import hashlib
import json
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from autoviz.schema.allowlists import MAX_PREPROCESSING_COLUMNS, MAX_PREPROCESSING_STEPS

FilterOp = Literal[
    "eq", "neq", "gt", "gte", "lt", "lte", "in", "between", "contains", "is_null", "is_not_null"
]
AggFn = Literal["sum", "mean", "min", "max", "count", "median", "count_distinct"]
DeriveFn = Literal[
    "month", "year", "day", "weekday", "lower", "upper", "trim", "round", "abs"
]
ChartType = Literal[
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
]
Intent = Literal[
    "comparison", "trend", "distribution", "relationship", "composition", "ranking"
]
SortDir = Literal["asc", "desc"]
DropNullsHow = Literal["any", "all"]
FillStrategy = Literal["constant", "median", "mode"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Filter(_StrictModel):
    column: str
    op: FilterOp
    # Scalar for most ops; a list of scalars for "in" (any length) and
    # "between" ([low, high]); omitted for is_null/is_not_null. Presence and
    # arity are checked in services/validation.py.
    value: Any = None


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


# --- Preprocessing (explicit, provenance-tracked cleaning) --------------------
# A discriminated union on `op`: each op is a distinct, typed cleaning step that
# runs as a read-only working view *before* filters/derive/aggregation. The source
# data is never mutated. drop_* remove rows; fill_nulls imputes.


class DropNulls(_StrictModel):
    op: Literal["drop_nulls"]
    columns: list[str] = Field(min_length=1, max_length=MAX_PREPROCESSING_COLUMNS)
    # "any": drop a row if ANY listed column is null; "all": only if ALL are null.
    how: DropNullsHow = "any"


class FillNulls(_StrictModel):
    op: Literal["fill_nulls"]
    column: str
    strategy: FillStrategy
    # Required for strategy="constant" (a JSON scalar); ignored/omitted for
    # median/mode, which compute the fill value from the data. Arity and
    # type-compatibility are enforced in services/validation.py.
    value: Any = None


class DropExactDuplicates(_StrictModel):
    op: Literal["drop_exact_duplicates"]


PreprocessOp = Annotated[
    Union[DropNulls, FillNulls, DropExactDuplicates], Field(discriminator="op")
]


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
    # Explicit cleaning steps applied to a read-only working view before anything
    # else. Empty = no preprocessing (the default, immutable-source behaviour).
    preprocessing: list[PreprocessOp] = Field(
        default_factory=list, max_length=MAX_PREPROCESSING_STEPS
    )
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

    def has_row_dropping_preprocessing(self) -> bool:
        """True if any preprocessing step removes rows (so the confirmation gate applies)."""
        return any(
            op.op in ("drop_nulls", "drop_exact_duplicates") for op in self.preprocessing
        )

    def preprocessing_hash(self) -> str:
        """Stable content hash of the preprocessing block.

        Approval of a large row-removal is bound to this hash (not a boolean), so a
        repaired plan whose preprocessing differs re-triggers the confirmation gate.
        """
        canonical = json.dumps(
            [op.model_dump(by_alias=True) for op in self.preprocessing],
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
