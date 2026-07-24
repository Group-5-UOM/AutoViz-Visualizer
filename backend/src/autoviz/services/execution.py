"""Deterministic plan execution: analysis_plan -> DuckDB SQL -> result table.

Translation is a pure function over the closed plan grammar — identifiers are
quoted, literals are bound as parameters, and only allow-listed ops/fns can
appear, so injection is structurally impossible. A hard output-row ceiling is
enforced regardless of the requested limit.
"""

import os
import threading
import time
from typing import Any

import duckdb
import pandas as pd

from autoviz.errors import (
    EXECUTION_ERROR,
    INVALID_PLAN,
    TIMEOUT,
    UNKNOWN_DATASET,
    make_error,
)
from autoviz.schema.allowlists import HARD_ROW_CEILING
from autoviz.schema.analysis_plan import AnalysisPlan
from autoviz.services.dataset import sanitize_records
from autoviz.services.registry import REGISTRY, DatasetRegistry
from autoviz.services.validation import validate_analysis_plan


def _env_value(name: str, default: str) -> str:
    raw = os.environ.get(name, "").strip()
    return raw or default


def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


# DuckDB resource governors, all overridable. memory_limit caps the engine's
# working set; the timeout bounds wall-clock so a pathological query can't hang
# a synchronous MCP call. threads is capped to keep one query from saturating
# the host.
DUCKDB_MEMORY_LIMIT = _env_value("AUTOVIZ_DUCKDB_MEMORY_LIMIT", "1GB")
DUCKDB_THREADS = _env_value("AUTOVIZ_DUCKDB_THREADS", "2")
EXECUTION_TIMEOUT_S = _env_float("AUTOVIZ_EXECUTION_TIMEOUT_S", 30.0)

_DERIVE_SQL = {
    "month": "date_part('month', {col})",
    "year": "date_part('year', {col})",
    "day": "date_part('day', {col})",
    "weekday": "date_part('dow', {col})",
    "lower": "lower({col})",
    "upper": "upper({col})",
    "trim": "trim({col})",
    "round": "round({col})",
    "abs": "abs({col})",
}

# Scalar-valued ops; "in" and "between" build their placeholders in build_sql.
_FILTER_SQL = {
    "eq": "{col} = ?",
    "neq": "{col} != ?",
    "gt": "{col} > ?",
    "gte": "{col} >= ?",
    "lt": "{col} < ?",
    "lte": "{col} <= ?",
    "contains": "contains(CAST({col} AS VARCHAR), ?)",
}

_AGG_SQL = {
    "sum": "sum({col})",
    "mean": "avg({col})",
    "min": "min({col})",
    "max": "max({col})",
    "count": "count({col})",
    "median": "median({col})",
    "count_distinct": "count(DISTINCT {col})",
}


def _interrupt(con: "duckdb.DuckDBPyConnection") -> None:
    """Best-effort cancel of a running query from the watchdog thread."""
    try:
        con.interrupt()
    except Exception:
        pass


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
        col = _q(f.column)
        if f.op == "between":
            where_parts.append(f"{col} BETWEEN ? AND ?")
            params.extend(f.value)
        elif f.op == "in":
            placeholders = ", ".join("?" for _ in f.value)
            where_parts.append(f"{col} IN ({placeholders})")
            params.extend(f.value)
        else:
            where_parts.append(_FILTER_SQL[f.op].format(col=col))
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
    # An explicit limit is honored (e.g. ranking "top 10"); None means "return
    # everything up to the safety ceiling" so distributions/scatter plots aren't
    # silently truncated before the chart bins/plots them.
    cap = HARD_ROW_CEILING if plan.limit is None else min(plan.limit, HARD_ROW_CEILING)
    sql += f" LIMIT {cap}"
    return sql, params


def execute_analysis(
    dataset_id: str,
    analysis_plan: dict[str, Any],
    registry: DatasetRegistry = REGISTRY,
) -> dict[str, Any]:
    record = registry.get(dataset_id)
    if record is None:
        return make_error(UNKNOWN_DATASET, f"Unknown dataset_id: {dataset_id}")

    verdict = validate_analysis_plan(dataset_id, analysis_plan, registry)
    if not verdict["valid"]:
        # Preserve the historical message/keys; add the taxonomy code so routing
        # can tell a plan defect from an infrastructure fault.
        return make_error(
            verdict.get("error_code", INVALID_PLAN),
            "Plan failed validation",
            validation_errors=verdict["errors"],
        )
    effective_plan = verdict.get("repaired_plan", analysis_plan)
    plan = AnalysisPlan.model_validate(effective_plan)

    sql, params = build_sql(plan)
    started = time.perf_counter()
    timed_out = threading.Event()
    con = duckdb.connect()
    watchdog = threading.Timer(
        EXECUTION_TIMEOUT_S, lambda: (timed_out.set(), _interrupt(con))
    )
    try:
        con.execute(f"SET memory_limit='{DUCKDB_MEMORY_LIMIT}'")
        con.execute(f"SET threads={DUCKDB_THREADS}")
        df: pd.DataFrame = record.df
        con.register("df", df)
        watchdog.start()
        result = con.execute(sql, params).fetchdf()
    except Exception as exc:
        if timed_out.is_set():
            return make_error(
                TIMEOUT,
                f"Execution exceeded the {EXECUTION_TIMEOUT_S:g}s time budget.",
                sql=sql,
            )
        return make_error(EXECUTION_ERROR, f"Execution failed: {exc}", sql=sql)
    finally:
        watchdog.cancel()
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
