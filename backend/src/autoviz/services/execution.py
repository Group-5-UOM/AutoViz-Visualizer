"""Deterministic plan execution: analysis_plan -> DuckDB SQL -> result table.

Translation is a pure function over the closed plan grammar — identifiers are
quoted, literals are bound as parameters, and only allow-listed ops/fns can
appear, so injection is structurally impossible. A hard output-row ceiling is
enforced regardless of the requested limit.
"""

import time
from typing import Any

import duckdb
import pandas as pd

from autoviz.schema.allowlists import HARD_ROW_CEILING
from autoviz.schema.analysis_plan import AnalysisPlan
from autoviz.services.dataset import sanitize_records
from autoviz.services.registry import REGISTRY, DatasetRegistry
from autoviz.services.validation import validate_analysis_plan

_DERIVE_SQL = {
    "month": "date_part('month', {col})",
    "year": "date_part('year', {col})",
    "day": "date_part('day', {col})",
    "lower": "lower({col})",
    "round": "round({col})",
}

_FILTER_SQL = {
    "eq": "{col} = ?",
    "neq": "{col} != ?",
    "gt": "{col} > ?",
    "lt": "{col} < ?",
    "contains": "contains(CAST({col} AS VARCHAR), ?)",
}

_AGG_SQL = {
    "sum": "sum({col})",
    "mean": "avg({col})",
    "min": "min({col})",
    "max": "max({col})",
    "count": "count({col})",
}


def _q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def build_sql(plan: AnalysisPlan) -> tuple[str, list[Any]]:
    """Translate a validated plan into (sql, bound_params) over relation 'df'."""
    derive_exprs = [
        _DERIVE_SQL[d.fn].format(col=_q(d.from_)) + f" AS {_q(d.name)}"
        for d in plan.derive
    ]
    base = "SELECT *" + ("".join(f", {e}" for e in derive_exprs)) + " FROM df"

    if plan.group_by or plan.aggregations:
        select_parts = [_q(c) for c in plan.group_by] + [
            _AGG_SQL[a.fn].format(col=_q(a.column)) + f" AS {_q(a.as_)}"
            for a in plan.aggregations
        ]
    elif plan.select or plan.derive:
        select_parts = [_q(c) for c in plan.select] + [_q(d.name) for d in plan.derive]
    else:
        select_parts = ["*"]

    params: list[Any] = []
    where_parts: list[str] = []
    for f in plan.filters:
        where_parts.append(_FILTER_SQL[f.op].format(col=_q(f.column)))
        params.append(f.value)

    sql = f"WITH base AS ({base}) SELECT {', '.join(select_parts)} FROM base"
    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)
    if plan.group_by:
        sql += " GROUP BY " + ", ".join(_q(c) for c in plan.group_by)
    if plan.sort:
        sql += " ORDER BY " + ", ".join(
            f"{_q(s.by)} {'DESC' if s.dir == 'desc' else 'ASC'}" for s in plan.sort
        )
    sql += f" LIMIT {min(plan.limit, HARD_ROW_CEILING)}"
    return sql, params


def execute_analysis(
    dataset_id: str,
    analysis_plan: dict[str, Any],
    registry: DatasetRegistry = REGISTRY,
) -> dict[str, Any]:
    record = registry.get(dataset_id)
    if record is None:
        return {"error": f"Unknown dataset_id: {dataset_id}"}

    verdict = validate_analysis_plan(dataset_id, analysis_plan, registry)
    if not verdict["valid"]:
        return {"error": "Plan failed validation", "validation_errors": verdict["errors"]}
    effective_plan = verdict.get("repaired_plan", analysis_plan)
    plan = AnalysisPlan.model_validate(effective_plan)

    sql, params = build_sql(plan)
    started = time.perf_counter()
    try:
        con = duckdb.connect()
        df: pd.DataFrame = record.df
        con.register("df", df)
        result = con.execute(sql, params).fetchdf()
    except Exception as exc:
        return {"error": f"Execution failed: {exc}", "sql": sql}
    finally:
        try:
            con.close()
        except Exception:
            pass
    elapsed_ms = (time.perf_counter() - started) * 1000

    return {
        "result_table": sanitize_records(result),
        "row_count": int(len(result)),
        "execution_time_ms": round(elapsed_ms, 2),
        "provenance": {
            "dataset_id": dataset_id,
            "source": record.source,
            "columns_used": sorted(
                {c for c in plan.select}
                | {f.column for f in plan.filters}
                | {d.from_ for d in plan.derive}
                | {c for c in plan.group_by if c in record.schema}
                | {a.column for a in plan.aggregations}
            ),
            "filters": [f.model_dump() for f in plan.filters],
            "aggregations": [a.model_dump(by_alias=True) for a in plan.aggregations],
            "chart_type": plan.chart.type if plan.chart else None,
            "sql": sql,
        },
    }
