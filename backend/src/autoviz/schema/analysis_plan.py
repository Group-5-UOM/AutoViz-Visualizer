"""Canonical analysis-plan schema — single source of truth for the plan shape.

Pydantic v2 models implementing Docs/06-MCP-Server-Plan.md §2. Allow-lists are
enforced structurally via Literal types at parse time; semantic checks against
a dataset's profiled schema live in services/validation.py.
"""

import hashlib
import json
from typing import Annotated, Any, ClassVar, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from autoviz.schema.allowlists import (
    MAX_CATEGORY_MAPPING,
    MAX_PREPROCESSING_COLUMNS,
    MAX_PREPROCESSING_STEPS,
    MAX_TOP_CATEGORIES,
    Risk,
)

FilterOp = Literal[
    "eq", "neq", "gt", "gte", "lt", "lte", "in", "between", "contains", "is_null", "is_not_null"
]
AggFn = Literal["sum", "mean", "min", "max", "count", "median", "count_distinct"]
DeriveFn = Literal[
    # Extraction: datetime -> number (a bare 1-12, 1-31, ...). For seasonality.
    "month", "year", "day", "weekday",
    # Truncation: datetime -> datetime, flattened to the start of the period. For
    # trends — see DATETIME_DERIVE_FNS in schema/allowlists.py for why the two are
    # not interchangeable.
    "month_start", "quarter_start", "week_start", "year_start",
    "lower", "upper", "trim", "round", "abs",
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
# Only widening repairs a CSV reader gets wrong: text that is really a number or a
# date. Casting to string is never a repair, so it is not offered.
CastTarget = Literal["number", "datetime"]


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


class _PreprocessOpBase(_StrictModel):
    """Base for every cleaning op — each declares its own behaviour.

    ``removes_rows`` and ``risk`` are read off the model wherever the pipeline
    needs them, never re-derived from the op *name* at the call site. That
    matters because the consequences of getting it wrong all fail open: an op
    that is not recognised as row-dropping skips the confirmation gate, survives
    "Skip cleaning", and is dropped from the validator's column checks. Declaring
    the behaviour once, next to the fields it describes, is what makes adding an
    op a local change instead of a five-site change with silent failure modes.

    The two flags are orthogonal on purpose: ``drop_empty_rows`` is SAFE (a row
    of all-nulls carries no meaning) yet removes rows, so it is auto-appliable
    while still tripping the >30% backstop.
    """

    # No defaults: a subclass that omits either is a definition-time error, so
    # the mistake surfaces at import rather than as a silently ungated op.
    removes_rows: ClassVar[bool]
    risk: ClassVar[Risk]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        missing = [a for a in ("removes_rows", "risk") if a not in cls.__dict__]
        if missing:
            raise TypeError(
                f"{cls.__name__} must declare {' and '.join(missing)}: preprocessing "
                "ops state their own risk and row behaviour so no call site has to "
                "infer it from the op name."
            )

    def columns_touched(self) -> set[str]:
        """Real dataset columns this op reads or rewrites.

        Drives the validator's existence/type checks and the quality scan's
        scoping, so an op that names columns must report them here or they go
        unchecked.
        """
        raise NotImplementedError

    def apply_schema(self, schema: dict[str, str]) -> dict[str, str]:
        """This op's effect on the column set, as ``{name: logical type}``.

        Most ops change values and not the shape, so the default is "no change".
        Ops that retype a column (``cast_column``), add one (``split_column``) or
        replace several with others (``pivot_longer``) override this.

        It exists because everything downstream — validation, the chart encoder —
        needs to know what the table looks like *after* cleaning, and asking each
        of them to special-case each op is how the two drift apart. Declaring the
        effect next to the op is the same rule ``risk`` and ``removes_rows``
        already follow.
        """
        return schema


class DropNulls(_PreprocessOpBase):
    op: Literal["drop_nulls"]
    columns: list[str] = Field(min_length=1, max_length=MAX_PREPROCESSING_COLUMNS)
    # "any": drop a row if ANY listed column is null; "all": only if ALL are null.
    how: DropNullsHow = "any"

    removes_rows: ClassVar[bool] = True
    risk: ClassVar[Risk] = Risk.VALUE_CHANGING

    def columns_touched(self) -> set[str]:
        return set(self.columns)


class FillNulls(_PreprocessOpBase):
    op: Literal["fill_nulls"]
    column: str
    strategy: FillStrategy
    # Required for strategy="constant" (a JSON scalar); ignored/omitted for
    # median/mode, which compute the fill value from the data. Arity and
    # type-compatibility are enforced in services/validation.py.
    value: Any = None

    # Imputation keeps every row but substitutes values, so it never trips the
    # row-removal gate — which is exactly why it needs the VALUE_CHANGING tier to
    # get consent on its own terms.
    removes_rows: ClassVar[bool] = False
    risk: ClassVar[Risk] = Risk.VALUE_CHANGING

    def columns_touched(self) -> set[str]:
        return {self.column}


class DropExactDuplicates(_PreprocessOpBase):
    op: Literal["drop_exact_duplicates"]

    removes_rows: ClassVar[bool] = True
    risk: ClassVar[Risk] = Risk.VALUE_CHANGING

    def columns_touched(self) -> set[str]:
        return set()  # compares whole rows, names no columns


# --- SAFE tier: semantics-preserving repairs ---------------------------------
# These correct how a value is *written*, never what it means, so they are applied
# without asking and reported in provenance. The line is deliberate: anything that
# could make two genuinely different records look the same, or change a number,
# belongs in VALUE_CHANGING above.


class TrimWhitespace(_PreprocessOpBase):
    op: Literal["trim_whitespace"]
    columns: list[str] = Field(min_length=1, max_length=MAX_PREPROCESSING_COLUMNS)

    removes_rows: ClassVar[bool] = False
    risk: ClassVar[Risk] = Risk.SAFE

    def columns_touched(self) -> set[str]:
        return set(self.columns)


class EmptyStringToNull(_PreprocessOpBase):
    """`""` and `"   "` are absent values written as text; make them absent.

    Safe because it does not invent data — it lets the null-handling everything
    else already does (aggregates skipping nulls, null counts in the profile)
    see values that were only ever missing.
    """

    op: Literal["empty_string_to_null"]
    columns: list[str] = Field(min_length=1, max_length=MAX_PREPROCESSING_COLUMNS)

    removes_rows: ClassVar[bool] = False
    risk: ClassVar[Risk] = Risk.SAFE

    def columns_touched(self) -> set[str]:
        return set(self.columns)


class NormalizeCase(_PreprocessOpBase):
    """Fold `Male`/`male`/`MALE` into one category.

    Case folding can only ever merge values that differ by nothing but case, which
    is why it is SAFE rather than a category merge. Deciding it is *worth* doing
    is a separate question and belongs to the recommender, which only proposes it
    when it actually collapses variants (services/quality.py).

    The surviving spelling is the column's **commonest**, not ``lower()``. Both
    merge identically, but the choice is also what every chart then displays, and
    an axis reading "usa" and "canada" is a presentation defect introduced by a
    repair the user never asked for. Ties break towards the spelling that reads
    as a label ("Male" over "MALE"), then on value order, so the result never
    depends on scan order.
    """

    op: Literal["normalize_case"]
    column: str

    removes_rows: ClassVar[bool] = False
    risk: ClassVar[Risk] = Risk.SAFE

    def columns_touched(self) -> set[str]:
        return {self.column}


class DropEmptyRows(_PreprocessOpBase):
    """Remove rows that are null in every column.

    SAFE and row-removing at once — the two flags are independent. A row with no
    values carries no information, so dropping it preserves meaning; it still
    counts toward the >30% backstop, which is what would catch a file that is
    mostly blank lines.
    """

    op: Literal["drop_empty_rows"]

    removes_rows: ClassVar[bool] = True
    risk: ClassVar[Risk] = Risk.SAFE

    def columns_touched(self) -> set[str]:
        return set()  # spans every column


class ParseNumber(_PreprocessOpBase):
    """Read a money/formatted column as the number it already is.

    ``cast_column`` cannot: ``TRY_CAST('$1,234.50' AS DOUBLE)`` is null, so the
    op refuses, and the column stays text that no aggregation will accept. That
    left the commonest financial CSV in existence unanalysable.

    SAFE because the decoration removed is exactly that — a currency symbol, a
    thousands separator, surrounding whitespace — none of which carries meaning
    the number does not. What keeps it safe in practice is that stripping is
    *not* a filter over arbitrary characters: only the listed decoration is
    removed, and whatever remains must convert in full. ``'12 apples'`` becomes
    ``'12apples'``, fails to convert, and the op is refused rather than silently
    yielding 12.

    A ``%`` is deliberately not decoration: ``45%`` is either 45 or 0.45 and the
    column cannot say which, so it fails the conversion and the user is told.
    """

    op: Literal["parse_number"]
    columns: list[str] = Field(min_length=1, max_length=MAX_PREPROCESSING_COLUMNS)
    # Which character is the decimal point in this column's notation, and which
    # groups the thousands. Defaults are the anglophone convention; the ingest
    # probe reports the file's own when it differs (services/ingest.py).
    decimal: Literal[".", ","] = "."
    thousands: Literal[",", ".", " ", "'"] | None = None

    removes_rows: ClassVar[bool] = False
    risk: ClassVar[Risk] = Risk.SAFE

    def columns_touched(self) -> set[str]:
        return set(self.columns)

    def apply_schema(self, schema: dict[str, str]) -> dict[str, str]:
        return {**schema, **{c: "number" for c in self.columns}}


class CastColumn(_PreprocessOpBase):
    """Read a text column as the type it already contains.

    Admitted only when every non-null value parses (checked against the frame in
    validation), which is what keeps it SAFE: a column where some values would
    become null is a lossy conversion, not a repair, and is rejected rather than
    silently coerced.
    """

    op: Literal["cast_column"]
    column: str
    to: CastTarget

    removes_rows: ClassVar[bool] = False
    risk: ClassVar[Risk] = Risk.SAFE

    def columns_touched(self) -> set[str]:
        return {self.column}

    def apply_schema(self, schema: dict[str, str]) -> dict[str, str]:
        return {**schema, self.column: self.to}


# --- Category cleaning -------------------------------------------------------
# VALUE_CHANGING, not SAFE: both of these merge categories that were distinct, so
# two rows that meant different things can end up in the same bar. That the merge
# is usually *right* is not the same as it being semantics-preserving.


class CleanCategories(_PreprocessOpBase):
    """Relabel category values through an explicit mapping.

    Only ever explicit. The recommender never infers a mapping by fuzzy
    similarity — "UK"/"U.K."/"United Kingdom" is obvious to a person and a guess
    to a program, and a wrong guess silently merges two real categories. Exact
    whitespace and case equivalence is handled by the SAFE ops instead, which is
    why nothing auto-proposes this one.
    """

    op: Literal["clean_categories"]
    column: str
    # {existing value -> replacement}. Values not named are left alone.
    mapping: dict[str, str] = Field(min_length=1, max_length=MAX_CATEGORY_MAPPING)

    removes_rows: ClassVar[bool] = False
    risk: ClassVar[Risk] = Risk.VALUE_CHANGING

    def columns_touched(self) -> set[str]:
        return {self.column}


class RankBy(_StrictModel):
    """The measure that decides which categories `top_n` keeps.

    Same shape as an ``Aggregation`` minus the output name, because it is the
    same quantity: the point is to rank categories by what the chart plots.
    """

    column: str
    fn: AggFn


class GroupRareCategories(_PreprocessOpBase):
    """Fold infrequent categories into one bucket so the chart stays readable.

    Exactly one of ``top_n`` (keep the N best) or ``min_frequency`` (keep
    anything appearing at least N times) — they are two ways to draw the same
    line and accepting both at once would leave the precedence undefined.

    Nulls are never bucketed: missing is not the same as rare, and folding them
    into "Other" would turn an absence into a category.
    """

    op: Literal["group_rare_categories"]
    column: str
    top_n: int | None = Field(default=None, ge=1, le=MAX_TOP_CATEGORIES)
    min_frequency: int | None = Field(default=None, ge=1)
    other_label: str = "Other"
    # Which quantity decides who survives. None = row frequency, which is right
    # for a count chart and wrong for every other one: ranking sales reps by how
    # many orders they logged, then plotting their revenue, buries the top earner
    # in "Other" whenever volume and value disagree. Set this to the plan's own
    # measure so the categories kept are the ones the chart is actually about.
    rank_by: RankBy | None = None

    removes_rows: ClassVar[bool] = False
    risk: ClassVar[Risk] = Risk.VALUE_CHANGING

    def columns_touched(self) -> set[str]:
        return {self.column}


# --- Reshape -------------------------------------------------------------------
# SAFE, and worth saying why, because both of these change the table's shape and
# that instinctively reads as drastic. The tier is about *meaning*: neither op
# alters, invents or discards a value — the same facts come out in a different
# arrangement. What they cannot be is *automatic*: nothing proposes them, because
# whether a set of columns is really one repeated measurement is a question about
# what the data means, which the data cannot answer. They appear only when a user
# or planner asked for them.


class PivotLonger(_PreprocessOpBase):
    """Fold repeated columns into rows: `Jan, Feb, Mar` -> `month, value`.

    The single commonest shape of real spreadsheet data, and the one shape the
    plan grammar could not express at all. A file with one column per month is
    not analysable by a grammar whose group_by takes column *names*: "revenue by
    month" needs month to be a value, and in a wide file it is a header.

    ``columns`` are the folded ones; every other column is carried down and
    repeated, which is what makes this row-multiplying rather than row-dropping.
    """

    op: Literal["pivot_longer"]
    # Two is the minimum that means anything: folding one column is a rename.
    columns: list[str] = Field(min_length=2, max_length=MAX_PREPROCESSING_COLUMNS)
    # New column holding the old column names, and the one holding their values.
    names_to: str
    values_to: str

    # It multiplies rows rather than removing them, so the row-removal gate does
    # not apply — there is no data loss to consent to.
    removes_rows: ClassVar[bool] = False
    risk: ClassVar[Risk] = Risk.SAFE

    def columns_touched(self) -> set[str]:
        return set(self.columns)

    def apply_schema(self, schema: dict[str, str]) -> dict[str, str]:
        """The folded columns are gone; two new ones take their place.

        ``values_to`` is numeric only when every folded column was — one text
        column among twelve numeric ones makes the whole stacked column text,
        which is exactly what SQL will do and what the validator must expect.
        """
        folded = {schema.get(c) for c in self.columns}
        out = {k: v for k, v in schema.items() if k not in set(self.columns)}
        out[self.names_to] = "string"
        out[self.values_to] = "number" if folded == {"number"} else "string"
        return out


class SplitColumn(_PreprocessOpBase):
    """Split one text column on a separator into several: `"2026-Q3"` -> year, quarter.

    Additive — the source column is kept. A split is a reading of a column, not a
    correction to it, and the original is often still the one the user wants to
    filter on.

    Parts beyond ``into`` are discarded and missing parts become null, both of
    which are properties of the separator rather than defects, so neither is a
    refusal. The counts are reported instead.
    """

    op: Literal["split_column"]
    column: str
    separator: str = Field(min_length=1, max_length=8)
    into: list[str] = Field(min_length=2, max_length=8)

    removes_rows: ClassVar[bool] = False
    risk: ClassVar[Risk] = Risk.SAFE

    def columns_touched(self) -> set[str]:
        return {self.column}

    def apply_schema(self, schema: dict[str, str]) -> dict[str, str]:
        # Always text: a part that looks numeric still needs an explicit
        # parse_number/cast_column, so the split cannot quietly retype anything.
        return {**schema, **{name: "string" for name in self.into}}


PreprocessOp = Annotated[
    Union[
        DropNulls,
        FillNulls,
        DropExactDuplicates,
        TrimWhitespace,
        EmptyStringToNull,
        NormalizeCase,
        DropEmptyRows,
        CastColumn,
        ParseNumber,
        CleanCategories,
        GroupRareCategories,
        PivotLonger,
        SplitColumn,
    ],
    Field(discriminator="op"),
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
        return any(op.removes_rows for op in self.preprocessing)

    def preprocessing_columns(self) -> set[str]:
        """Every real column the preprocessing block reads or rewrites."""
        cols: set[str] = set()
        for op in self.preprocessing:
            cols |= op.columns_touched()
        return cols

    def referenced_columns(self) -> set[str]:
        """Every real dataset column this plan touches, at any stage.

        Includes derived *source* columns but not derived names, so the result is
        always a set of columns that exist in the dataset. This is what scopes the
        quality scan: a problem in a column the analysis never reads is not a
        reason to interrupt the user.
        """
        return (
            self.preprocessing_columns()
            | set(self.select)
            | set(self.group_by)
            | {f.column for f in self.filters}
            | {a.column for a in self.aggregations}
            | {d.from_ for d in self.derive}
        )

    def preprocessing_schema(self, base: dict[str, str]) -> dict[str, str]:
        """The table's shape after cleaning: ``{column: logical type}``.

        Preprocessing runs before everything else, so by the time a filter or an
        aggregation sees a cast column it *is* the new type — and after a pivot
        the folded columns are simply gone. Validation and the chart encoder both
        have to start from here, or a plan that casts a text column to a number
        and then averages it is rejected as a type error against a schema that no
        longer applies at that point in the query.

        Applied in list order, so a later op sees the earlier one's output — the
        same rule the CTE chain follows.
        """
        schema = dict(base)
        for op in self.preprocessing:
            schema = op.apply_schema(schema)
        return schema

    def _canonical_preprocessing(self) -> list[dict[str, Any]]:
        """The preprocessing block in a form where equal semantics give equal bytes.

        Order-insensitive *fields* are normalised: ``drop_nulls.columns`` becomes a
        sorted, de-duplicated list because the compiled predicate ANDs/ORs them
        together, so ``["a","b"]`` and ``["b","a"]`` are the same filter and must
        not re-prompt the user after a replan reorders them.

        The op *list* order is deliberately left alone — it is genuinely semantic.
        ``fill_nulls`` then ``drop_exact_duplicates`` can collapse rows that the
        reverse order would keep.
        """
        canonical: list[dict[str, Any]] = []
        for op in self.preprocessing:
            dumped = op.model_dump(by_alias=True)
            if isinstance(dumped.get("columns"), list):
                dumped["columns"] = sorted(set(dumped["columns"]))
            canonical.append(dumped)
        return canonical

    def preprocessing_version(self, dataset_id: str) -> str:
        """Stable id for "this cleaning block, applied to this dataset".

        Serves two jobs that must not diverge:

        * **Consent token.** Approval of a large row removal is bound to this
          value rather than to a boolean, so a repaired plan re-gates. It includes
          ``dataset_id`` because consent was given for a *measured impact* — the
          same block against a different frame may remove a wildly different
          share of rows, and a token that omitted the dataset would authorise it.
        * **Logical version id.** The frame this block produces is fully
          determined by (source, ops), and the source is immutable, so this
          identifies the cleaned view without materialising it.
        """
        canonical = json.dumps(
            {"dataset_id": dataset_id, "preprocessing": self._canonical_preprocessing()},
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return "pp_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
