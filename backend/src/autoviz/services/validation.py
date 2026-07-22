"""Semantic validation of an analysis plan against a dataset's profiled schema.

This is the safety layer: every column must exist with a type compatible with
the op/fn applied to it, all ops/fns must sit inside the closed allow-lists,
and the chart may only reference columns the query actually produces. Failures
are errors, never warnings — there is no raw-expression fallback.
"""

import re
from typing import Any

from pydantic import ValidationError

from autoviz.schema.allowlists import (
    AGG_FNS,
    DATE_DERIVE_FNS,
    FILTER_OPS,
    LIST_VALUE_OPS,
    MAX_IN_VALUES,
    MAX_LIMIT,
    NUMERIC_DERIVE_FNS,
    NUMERIC_ONLY_AGGS,
    ORDERED_OPS,
    STRING_DERIVE_FNS,
    STRING_ONLY_OPS,
)
from autoviz.schema.analysis_plan import AnalysisPlan
from autoviz.services.registry import REGISTRY, DatasetRegistry

# Values resembling code/SQL/shell are rejected outright (Proposal §4.7).
_INJECTION_PATTERN = re.compile(
    r"(;|--|/\*|\bdrop\b|\bdelete\b|\binsert\b|\bupdate\b|\bexec\b|\bimport\b|__|\$\(|`)",
    re.IGNORECASE,
)


def _looks_like_code(value: Any) -> bool:
    return isinstance(value, str) and bool(_INJECTION_PATTERN.search(value))


def validate_analysis_plan(
    dataset_id: str,
    analysis_plan: dict[str, Any],
    registry: DatasetRegistry = REGISTRY,
) -> dict[str, Any]:
    record = registry.get(dataset_id)
    if record is None:
        return {"valid": False, "errors": [f"Unknown dataset_id: {dataset_id}"]}

    try:
        plan = AnalysisPlan.model_validate(analysis_plan)
    except ValidationError as exc:
        errors = [
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        ]
        return {"valid": False, "errors": errors}

    errors: list[str] = []
    repaired: dict[str, Any] | None = None
    schema = record.schema

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

    for f in plan.filters:
        if f.op not in FILTER_OPS:
            errors.append(f"filter on '{f.column}': op '{f.op}' is not in the allow-list")
            continue
        col_type = effective.get(f.column)
        if col_type is None:
            errors.append(f"filter: column '{f.column}' does not exist")
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

    for a in plan.aggregations:
        if a.fn not in AGG_FNS:
            errors.append(f"aggregation '{a.as_}': fn '{a.fn}' is not in the allow-list")
            continue
        col_type = effective.get(a.column)
        if col_type is None:
            errors.append(f"aggregation '{a.as_}': column '{a.column}' does not exist")
            continue
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

    if plan.limit > MAX_LIMIT:
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
    if repaired is not None and not errors:
        result["repaired_plan"] = repaired
    return result
