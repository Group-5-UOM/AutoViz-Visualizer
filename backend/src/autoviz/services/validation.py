"""Semantic validation of an analysis plan against a dataset's profiled schema.

This is the safety layer: every column must exist with a type compatible with
the op/fn applied to it, all ops/fns must sit inside the closed allow-lists,
and the chart may only reference columns the query actually produces. Failures
are errors, never warnings — there is no raw-expression fallback.
"""

import math
import re
from typing import Any

from pydantic import ValidationError

from autoviz.schema.allowlists import (
    AGG_FNS,
    CATEGORICAL_FILL_STRATEGIES,
    DATE_DERIVE_FNS,
    FILTER_OPS,
    LIST_VALUE_OPS,
    MAX_FILL_STRING_LEN,
    MAX_IN_VALUES,
    MAX_LIMIT,
    MAX_PREPROCESSING_COLUMNS,
    NULL_OPS,
    NUMERIC_DERIVE_FNS,
    NUMERIC_FILL_STRATEGIES,
    NUMERIC_ONLY_AGGS,
    ORDERED_OPS,
    STRING_DERIVE_FNS,
    STRING_ONLY_OPS,
)
from autoviz.errors import INVALID_PLAN, TYPE_MISMATCH, UNKNOWN_DATASET
from autoviz.schema.analysis_plan import AnalysisPlan
from autoviz.services.registry import REGISTRY, DatasetRecord, DatasetRegistry

# Substrings unique to type-compatibility failures (op/fn on the wrong column
# type). If *every* error is one of these the failure is a pure TYPE_MISMATCH;
# any structural error (missing column, bad arity, ...) makes it INVALID_PLAN.
# Both are plan-repairable, so this only sharpens the reported code.
_TYPE_MARKERS = (
    "requires a numeric column",
    "requires a string column",
    "requires a datetime column",
    "requires a numeric or datetime",
)


def _plan_error_code(errors: list[str]) -> str:
    if errors and all(any(m in e for m in _TYPE_MARKERS) for e in errors):
        return TYPE_MISMATCH
    return INVALID_PLAN


# Values resembling code/SQL/shell are rejected outright (Proposal §4.7).
_INJECTION_PATTERN = re.compile(
    r"(;|--|/\*|\bdrop\b|\bdelete\b|\binsert\b|\bupdate\b|\bexec\b|\bimport\b|__|\$\(|`)",
    re.IGNORECASE,
)


def _looks_like_code(value: Any) -> bool:
    return isinstance(value, str) and bool(_INJECTION_PATTERN.search(value))


def _fully_null_columns(record: DatasetRecord, columns: set[str]) -> set[str]:
    """Which of `columns` are entirely null (unusable) — computed from the frame.

    Only the referenced columns are inspected (bounded work). An empty frame is
    rejected at registration, so a non-empty column that is all-null is genuinely
    unusable, not merely empty.
    """
    df = record.df
    if len(df) == 0:
        return set()
    return {c for c in columns if c in df.columns and bool(df[c].isna().all())}


def _fill_value_errors(value: Any, col_type: str, column: str) -> list[str]:
    """Type/shape checks for a fill_nulls constant (R7): bound as a param, so a
    code-looking string is ordinary data — we validate scalarity, finiteness,
    length, and destination-column compatibility instead of pattern-matching."""
    errs: list[str] = []
    if value is None:
        return [f"preprocessing fill_nulls on '{column}': strategy 'constant' requires a value"]
    if isinstance(value, (list, dict)):
        return [f"preprocessing fill_nulls on '{column}': constant value must be a scalar"]
    if isinstance(value, float) and not math.isfinite(value):
        errs.append(f"preprocessing fill_nulls on '{column}': constant value must be finite")
    if isinstance(value, str) and len(value) > MAX_FILL_STRING_LEN:
        errs.append(
            f"preprocessing fill_nulls on '{column}': constant string exceeds "
            f"{MAX_FILL_STRING_LEN} characters"
        )
    # Destination-column type compatibility (bool is a subclass of int — treat it
    # as boolean, never as a numeric fill).
    is_bool = isinstance(value, bool)
    is_number = isinstance(value, (int, float)) and not is_bool
    if col_type == "number" and not is_number:
        errs.append(
            f"preprocessing fill_nulls on '{column}': numeric column needs a numeric constant"
        )
    elif col_type == "boolean" and not is_bool:
        errs.append(
            f"preprocessing fill_nulls on '{column}': boolean column needs a boolean constant"
        )
    elif col_type in ("string", "datetime") and not isinstance(value, str):
        errs.append(
            f"preprocessing fill_nulls on '{column}': {col_type} column needs a string constant"
        )
    return errs


def _validate_preprocessing(
    plan: AnalysisPlan, schema: dict[str, str], fully_null: set[str], errors: list[str]
) -> None:
    """Validate the preprocessing block against the raw (pre-derive) schema.

    Preprocessing runs first on real dataset columns, so it is checked against
    `schema`, never derived names. Enforces column existence, strategy/type
    compatibility, constant-value shape, resource ceilings, and op conflicts.
    """
    touched: set[str] = set()
    drop_cols: set[str] = set()
    fill_cols: set[str] = set()

    for op in plan.preprocessing:
        if op.op == "drop_nulls":
            for col in op.columns:
                touched.add(col)
                if col not in schema:
                    errors.append(f"preprocessing drop_nulls: column '{col}' does not exist")
                elif col in fully_null:
                    errors.append(
                        f"preprocessing drop_nulls: column '{col}' is entirely null (unusable)"
                    )
                if col in fill_cols:
                    errors.append(
                        f"preprocessing: conflicting drop_nulls and fill_nulls on column '{col}'"
                    )
                drop_cols.add(col)
        elif op.op == "fill_nulls":
            col = op.column
            touched.add(col)
            col_type = schema.get(col)
            if col_type is None:
                errors.append(f"preprocessing fill_nulls: column '{col}' does not exist")
            elif col in fully_null:
                errors.append(
                    f"preprocessing fill_nulls: column '{col}' is entirely null "
                    f"(cannot compute a fill value)"
                )
            if col in fill_cols:
                errors.append(f"preprocessing: multiple fill_nulls on column '{col}'")
            if col in drop_cols:
                errors.append(
                    f"preprocessing: conflicting fill_nulls and drop_nulls on column '{col}'"
                )
            fill_cols.add(col)
            if col_type is not None:
                if op.strategy in NUMERIC_FILL_STRATEGIES and col_type != "number":
                    errors.append(
                        f"preprocessing fill_nulls on '{col}': strategy '{op.strategy}' "
                        f"requires a numeric column ({col_type} given)"
                    )
                elif op.strategy in CATEGORICAL_FILL_STRATEGIES and col_type not in (
                    "string",
                    "boolean",
                ):
                    errors.append(
                        f"preprocessing fill_nulls on '{col}': strategy '{op.strategy}' "
                        f"requires a categorical (string/boolean) column ({col_type} given)"
                    )
                elif op.strategy == "constant":
                    errors.extend(_fill_value_errors(op.value, col_type, col))
        # drop_exact_duplicates takes no params — nothing to check.

    if len(touched) > MAX_PREPROCESSING_COLUMNS:
        errors.append(
            f"preprocessing references {len(touched)} columns; the limit is "
            f"{MAX_PREPROCESSING_COLUMNS}"
        )


def validate_analysis_plan(
    dataset_id: str,
    analysis_plan: dict[str, Any],
    registry: DatasetRegistry = REGISTRY,
) -> dict[str, Any]:
    record = registry.get(dataset_id)
    if record is None:
        return {
            "valid": False,
            "errors": [f"Unknown dataset_id: {dataset_id}"],
            "error_code": UNKNOWN_DATASET,
        }

    try:
        plan = AnalysisPlan.model_validate(analysis_plan)
    except ValidationError as exc:
        errors = [
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        ]
        return {"valid": False, "errors": errors, "error_code": INVALID_PLAN}

    errors: list[str] = []
    repaired: dict[str, Any] | None = None
    schema = record.schema

    # Columns this plan touches directly on the raw schema; used to flag fully-null
    # (unusable) columns cheaply, without scanning the whole frame.
    pp_cols: set[str] = set()
    for op in plan.preprocessing:
        if op.op == "drop_nulls":
            pp_cols.update(op.columns)
        elif op.op == "fill_nulls":
            pp_cols.add(op.column)
    referenced = (
        pp_cols
        | set(plan.select)
        | set(plan.group_by)
        | {f.column for f in plan.filters}
        | {a.column for a in plan.aggregations}
        | {d.from_ for d in plan.derive}
    )
    fully_null = _fully_null_columns(record, {c for c in referenced if c in schema})

    # Preprocessing runs first, on real columns — validate it against the raw schema.
    _validate_preprocessing(plan, schema, fully_null, errors)

    # Derived columns become referenceable with a known logical type.
    effective: dict[str, str] = dict(schema)
    for d in plan.derive:
        src_type = schema.get(d.from_)
        if src_type is None:
            errors.append(f"derive '{d.name}': source column '{d.from_}' does not exist")
            continue
        if d.fn in DATE_DERIVE_FNS and src_type != "datetime":
            errors.append(
                f"derive '{d.name}': fn '{d.fn}' requires a datetime column, "
                f"'{d.from_}' is {src_type}"
            )
        elif d.fn in STRING_DERIVE_FNS and src_type != "string":
            errors.append(
                f"derive '{d.name}': fn '{d.fn}' requires a string column, "
                f"'{d.from_}' is {src_type}"
            )
        elif d.fn in NUMERIC_DERIVE_FNS and src_type != "number":
            errors.append(
                f"derive '{d.name}': fn '{d.fn}' requires a numeric column, "
                f"'{d.from_}' is {src_type}"
            )
        effective[d.name] = "number" if d.fn in (DATE_DERIVE_FNS | NUMERIC_DERIVE_FNS) else "string"

    for name in (d.name for d in plan.derive):
        if _looks_like_code(name):
            errors.append(f"derive name '{name}' resembles code and is rejected")

    for col in plan.select:
        if col not in effective:
            errors.append(f"select: column '{col}' does not exist")
        elif col in fully_null:
            errors.append(f"select: column '{col}' is entirely null (unusable)")

    for f in plan.filters:
        if f.op not in FILTER_OPS:
            errors.append(f"filter on '{f.column}': op '{f.op}' is not in the allow-list")
            continue
        col_type = effective.get(f.column)
        if col_type is None:
            errors.append(f"filter: column '{f.column}' does not exist")
            continue
        # Null predicates take no value and work on any column type; they skip the
        # scalar/list value checks below.
        if f.op in NULL_OPS:
            if f.value is not None:
                errors.append(f"filter on '{f.column}': op '{f.op}' takes no value")
            continue
        # Every other op needs a value (the model now defaults it to None).
        if f.value is None:
            errors.append(f"filter on '{f.column}': op '{f.op}' requires a value")
            continue
        if f.op in STRING_ONLY_OPS and col_type != "string":
            errors.append(
                f"filter on '{f.column}': op '{f.op}' requires a string column ({col_type} given)"
            )
        if f.op in ORDERED_OPS and col_type not in ("number", "datetime"):
            errors.append(
                f"filter on '{f.column}': op '{f.op}' requires a numeric or datetime "
                f"column ({col_type} given)"
            )
        # Value shape: "in"/"between" take a list of scalars, everything else a scalar.
        if f.op in LIST_VALUE_OPS:
            if not isinstance(f.value, list) or any(isinstance(v, (list, dict)) for v in f.value):
                errors.append(
                    f"filter on '{f.column}': op '{f.op}' requires a list of scalar values"
                )
                continue
            if f.op == "between" and len(f.value) != 2:
                errors.append(
                    f"filter on '{f.column}': op 'between' requires exactly 2 values "
                    f"[low, high] ({len(f.value)} given)"
                )
            if f.op == "in" and not (1 <= len(f.value) <= MAX_IN_VALUES):
                errors.append(
                    f"filter on '{f.column}': op 'in' requires 1-{MAX_IN_VALUES} values "
                    f"({len(f.value)} given)"
                )
            for v in f.value:
                if _looks_like_code(v):
                    errors.append(
                        f"filter on '{f.column}': a value resembles code and is rejected"
                    )
        else:
            if isinstance(f.value, (list, dict)):
                errors.append(
                    f"filter on '{f.column}': op '{f.op}' requires a scalar value, not a list"
                )
            if _looks_like_code(f.value):
                errors.append(f"filter on '{f.column}': value resembles code and is rejected")

    for col in plan.group_by:
        if col not in effective:
            errors.append(f"group_by: column '{col}' does not exist")
        elif col in fully_null:
            errors.append(f"group_by: column '{col}' is entirely null (unusable)")

    for a in plan.aggregations:
        if a.fn not in AGG_FNS:
            errors.append(f"aggregation '{a.as_}': fn '{a.fn}' is not in the allow-list")
            continue
        col_type = effective.get(a.column)
        if col_type is None:
            errors.append(f"aggregation '{a.as_}': column '{a.column}' does not exist")
            continue
        if a.column in fully_null:
            errors.append(f"aggregation '{a.as_}': column '{a.column}' is entirely null (unusable)")
        if a.fn in NUMERIC_ONLY_AGGS and col_type != "number":
            errors.append(
                f"aggregation '{a.as_}': fn '{a.fn}' requires a numeric column, "
                f"'{a.column}' is {col_type}"
            )
        if _looks_like_code(a.as_):
            errors.append(f"aggregation alias '{a.as_}' resembles code and is rejected")

    produced = plan.produced_columns() or set(effective)
    for s in plan.sort:
        if s.by not in produced:
            errors.append(f"sort: column '{s.by}' is not produced by the query")

    if plan.limit is not None and plan.limit > MAX_LIMIT:
        # The only deterministic repair attempted at this layer: clamp the limit.
        repaired = plan.model_dump(by_alias=True, exclude_none=True)
        repaired["limit"] = MAX_LIMIT

    if plan.chart is not None:
        for channel, col in (("x", plan.chart.x), ("y", plan.chart.y), ("color", plan.chart.color)):
            if col is not None and col not in produced:
                errors.append(
                    f"chart.{channel}: column '{col}' is not produced by the query "
                    f"(must come from select, group_by, derive, or an aggregation alias)"
                )
        if plan.chart.type == "histogram":
            # Histogram bins one numeric column; y is a count, not a column.
            if plan.chart.y is not None:
                errors.append("chart.y: histogram takes no y column (y is the binned count)")
            agg_aliases = {a.as_ for a in plan.aggregations}  # always numeric
            x_type = "number" if plan.chart.x in agg_aliases else effective.get(plan.chart.x)
            if plan.chart.x in produced and x_type != "number":
                errors.append(
                    f"chart.x: histogram requires a numeric column, '{plan.chart.x}' is {x_type}"
                )
        elif plan.chart.y is None:
            errors.append(f"chart.y: required for chart type '{plan.chart.type}'")

    result: dict[str, Any] = {"valid": not errors, "errors": errors}
    if errors:
        result["error_code"] = _plan_error_code(errors)
    if repaired is not None and not errors:
        result["repaired_plan"] = repaired
    return result
