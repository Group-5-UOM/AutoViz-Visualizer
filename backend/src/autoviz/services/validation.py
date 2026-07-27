"""Semantic validation of an analysis plan against a dataset's profiled schema.

This is the safety layer: every column must exist with a type compatible with
the op/fn applied to it, all ops/fns must sit inside the closed allow-lists,
and the chart may only reference columns the query actually produces. Failures
are errors, never warnings — there is no raw-expression fallback.
"""

import math
import re
from typing import Any

import pandas as pd
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
    elif col_type == "datetime" and pd.isna(pd.to_datetime(value, errors="coerce")):
        # Parse it here or DuckDB raises at execution time, where the failure is
        # caught as a generic EXECUTION_ERROR — which is *retryable*, so the agent
        # would back off and re-run an identical, deterministically-failing plan
        # and never be told to fix the value. A bad literal is a plan defect.
        errs.append(
            f"preprocessing fill_nulls on '{column}': constant "
            f"'{value}' is not a recognisable date/time"
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
    drop_cols: set[str] = set()
    fill_cols: set[str] = set()
    # Every column any op names, read off the ops themselves — an op that adds a
    # new column-bearing field reports it via columns_touched() rather than
    # needing this loop to learn about the field.
    touched: set[str] = plan.preprocessing_columns()

    for op in plan.preprocessing:
        if op.op == "drop_nulls":
            for col in op.columns:
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
        elif op.op in ("trim_whitespace", "empty_string_to_null", "normalize_case"):
            # Text repairs only make sense on text. Applying them to a number
            # would be a no-op at best and a silent string coercion at worst.
            cols = [op.column] if op.op == "normalize_case" else list(op.columns)
            for col in cols:
                col_type = schema.get(col)
                if col_type is None:
                    errors.append(f"preprocessing {op.op}: column '{col}' does not exist")
                elif col_type != "string":
                    errors.append(
                        f"preprocessing {op.op} on '{col}': requires a string column "
                        f"({col_type} given)"
                    )
        elif op.op == "cast_column":
            col_type = schema.get(op.column)
            if col_type is None:
                errors.append(f"preprocessing cast_column: column '{op.column}' does not exist")
            elif col_type != "string":
                errors.append(
                    f"preprocessing cast_column on '{op.column}': only a string column can be "
                    f"converted ({col_type} is already typed)"
                )
            elif op.column in fully_null:
                errors.append(
                    f"preprocessing cast_column on '{op.column}': column is entirely null (unusable)"
                )
            # Whether every value actually converts is checked at execution time,
            # against the working view rather than the raw frame. It has to be:
            # the whole point of casting after empty_string_to_null is that the
            # values blocking the conversion are gone by then, and a raw-frame
            # check would reject exactly the plans that were written correctly.
        elif op.op in ("clean_categories", "group_rare_categories"):
            col_type = schema.get(op.column)
            if col_type is None:
                errors.append(f"preprocessing {op.op}: column '{op.column}' does not exist")
            elif col_type not in ("string", "boolean"):
                errors.append(
                    f"preprocessing {op.op} on '{op.column}': requires a categorical "
                    f"(string/boolean) column ({col_type} given)"
                )
            if op.op == "clean_categories":
                for source, target in op.mapping.items():
                    if len(source) > MAX_FILL_STRING_LEN or len(target) > MAX_FILL_STRING_LEN:
                        errors.append(
                            f"preprocessing clean_categories on '{op.column}': a mapping "
                            f"entry exceeds {MAX_FILL_STRING_LEN} characters"
                        )
                        break
            else:
                # Two ways to draw the same line; accepting both would leave the
                # precedence between them undefined.
                given = [
                    n for n in ("top_n", "min_frequency") if getattr(op, n) is not None
                ]
                if len(given) != 1:
                    errors.append(
                        f"preprocessing group_rare_categories on '{op.column}': give exactly "
                        f"one of top_n or min_frequency ({', '.join(given) or 'neither'} given)"
                    )
                if len(op.other_label) > MAX_FILL_STRING_LEN:
                    errors.append(
                        f"preprocessing group_rare_categories on '{op.column}': other_label "
                        f"exceeds {MAX_FILL_STRING_LEN} characters"
                    )
        elif op.op in ("drop_exact_duplicates", "drop_empty_rows"):
            pass  # span whole rows; no parameters to check
        else:
            # Unreachable through the closed grammar. An op added to PreprocessOp
            # without a branch here would otherwise be accepted with *no* semantic
            # checks at all — no column-existence, no type compatibility — so the
            # default has to be rejection, not silence.
            errors.append(
                f"preprocessing: op '{op.op}' has no validation rule and cannot be applied"
            )

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
    referenced = plan.referenced_columns()
    fully_null = _fully_null_columns(record, {c for c in referenced if c in schema})

    # Preprocessing runs first, on real columns — validate it against the raw schema.
    _validate_preprocessing(plan, schema, fully_null, errors)

    # Everything after the cleaning stage sees the *cleaned* types, so a cast
    # column is its new type from here on. Derived columns then layer on top.
    effective: dict[str, str] = {**schema, **plan.preprocessing_type_overrides()}
    for d in plan.derive:
        src_type = effective.get(d.from_)
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
        agg_aliases = {a.as_ for a in plan.aggregations}  # always numeric

        def _column_type(col: str) -> str | None:
            return "number" if col in agg_aliases else effective.get(col)

        if plan.chart.type == "histogram":
            # Histogram bins one numeric column; y is a count, not a column.
            if plan.chart.y is not None:
                errors.append("chart.y: histogram takes no y column (y is the binned count)")
            x_type = _column_type(plan.chart.x)
            if plan.chart.x in produced and x_type != "number":
                errors.append(
                    f"chart.x: histogram requires a numeric column, '{plan.chart.x}' is {x_type}"
                )
        elif plan.chart.y is None:
            errors.append(f"chart.y: required for chart type '{plan.chart.type}'")
        elif plan.chart.type == "boxplot":
            # A box summarises a distribution, so it needs the raw rows. Over an
            # aggregated result there is one value per group and no box to draw.
            if plan.aggregations:
                errors.append(
                    "chart: boxplot needs the raw values to compute quartiles from, but "
                    "this plan aggregates — drop the aggregations and select the column"
                )
            y_type = _column_type(plan.chart.y)
            if plan.chart.y in produced and y_type != "number":
                errors.append(
                    f"chart.y: boxplot requires a numeric column, '{plan.chart.y}' is {y_type}"
                )
        elif plan.chart.type in ("heatmap", "grouped_bar"):
            if plan.chart.color is None:
                errors.append(
                    f"chart.color: required for chart type '{plan.chart.type}' "
                    f"(it carries the {'measure' if plan.chart.type == 'heatmap' else 'series'})"
                )
            elif plan.chart.type == "heatmap":
                # Heatmap is the one type whose colour is the measure.
                color_type = _column_type(plan.chart.color)
                if plan.chart.color in produced and color_type != "number":
                    errors.append(
                        f"chart.color: heatmap requires a numeric measure on colour, "
                        f"'{plan.chart.color}' is {color_type}"
                    )

    result: dict[str, Any] = {"valid": not errors, "errors": errors}
    if errors:
        result["error_code"] = _plan_error_code(errors)
    if repaired is not None and not errors:
        result["repaired_plan"] = repaired
    return result
