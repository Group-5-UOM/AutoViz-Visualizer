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

from autoviz.errors import (
    CANCELLED,
    EXECUTION_ERROR,
    INVALID_PLAN,
    TIMEOUT,
    UNKNOWN_DATASET,
    make_error,
)
from autoviz.schema.allowlists import HARD_ROW_CEILING
from autoviz.schema.analysis_plan import AnalysisPlan
from autoviz.services.dataset import _sanitize_scalar, sanitize_records
from autoviz.services.registry import REGISTRY, DatasetRecord, DatasetRegistry
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
# How often the cancellation watcher checks its event. Short enough that Cancel
# feels immediate, long enough that the extra thread costs nothing.
_CANCEL_POLL_S = 0.05

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


def build_sql(
    plan: AnalysisPlan,
    *,
    pp_ctes: list[str] | None = None,
    source_relation: str = "df_raw",
) -> tuple[str, list[Any]]:
    """Translate a validated plan into (sql, bound_params).

    The analysis runs over `source_relation` — the raw frame (`df_raw`) when there
    is no preprocessing, or the final preprocessing CTE otherwise. `pp_ctes` are the
    preprocessing CTE definitions prepended to the WITH clause; their bound params
    are threaded in by the caller (they appear before this query's WHERE params).
    """
    pp_ctes = pp_ctes or []
    derive_exprs = [
        _DERIVE_SQL[d.fn].format(col=_q(d.from_)) + f" AS {_q(d.name)}"
        for d in plan.derive
    ]
    base = "SELECT *" + ("".join(f", {e}" for e in derive_exprs)) + f" FROM {source_relation}"

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

    all_ctes = pp_ctes + [f"base AS ({base})"]
    sql = f"WITH {', '.join(all_ctes)} SELECT {', '.join(select_parts)} FROM base"
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


class PreprocessError(Exception):
    """A preprocessing step cannot be computed (e.g. median of an all-null column).

    Treated as plan-repairable (INVALID_PLAN) so the agent can drop/replace the step
    rather than retrying an environment fault that will never resolve.
    """


def _with(cte_defs: list[str]) -> str:
    """`WITH a AS (…), b AS (…) ` prefix, or empty when there are no CTEs yet."""
    return f"WITH {', '.join(cte_defs)} " if cte_defs else ""


def _fill_value(
    con: "duckdb.DuckDBPyConnection",
    cte_defs: list[str],
    params: list[Any],
    relation: str,
    op: Any,
) -> Any:
    """Compute the value a fill_nulls op substitutes, from the working view at this stage.

    constant -> the (already-validated) literal; median -> DuckDB median(); mode ->
    the most frequent value with a deterministic smallest-value tie-break (never
    DuckDB mode(), which is arbitrary on ties). None from median/mode means the
    column is entirely null at this stage.
    """
    if op.strategy == "constant":
        return op.value
    col = _q(op.column)
    if op.strategy == "median":
        expr = f"median({col})"
    else:  # mode: highest frequency, smallest normalized value on ties (R6)
        sql = (
            _with(cte_defs)
            + f"SELECT {col} FROM {relation} WHERE {col} IS NOT NULL "
            f"GROUP BY {col} ORDER BY count(*) DESC, {col} ASC LIMIT 1"
        )
        row = con.execute(sql, list(params)).fetchone()
        return row[0] if row is not None else None
    row = con.execute(_with(cte_defs) + f"SELECT {expr} FROM {relation}", list(params)).fetchone()
    return row[0] if row is not None else None


def _apply_preprocessing(
    con: "duckdb.DuckDBPyConnection", plan: AnalysisPlan, schema: dict[str, str]
) -> tuple[list[str], list[Any], str, list[dict[str, Any]], int, int]:
    """Compile the preprocessing block into a parameterized CTE chain over `df_raw`.

    Returns (cte_defs, params, final_relation, report, input_rows, output_rows). Row
    counts are taken over each CTE prefix so every op reports its exact effect. The
    source frame is never mutated — this only builds views. Raises PreprocessError
    when an imputation value cannot be computed.
    """
    input_rows = con.execute("SELECT count(*) FROM df_raw").fetchone()[0]
    cte_defs: list[str] = []
    params: list[Any] = []
    report: list[dict[str, Any]] = []
    current = "df_raw"
    prev_rows = input_rows

    for i, op in enumerate(plan.preprocessing):
        name = f"_pp_{i}"
        if op.op == "drop_nulls":
            # how="any": drop a row if ANY listed column is null => keep where all are
            # NOT NULL (AND). how="all": drop only if all are null => keep where any is
            # NOT NULL (OR).
            joiner = " AND " if op.how == "any" else " OR "
            pred = joiner.join(f"{_q(c)} IS NOT NULL" for c in op.columns)
            cte_defs.append(f"{name} AS (SELECT * FROM {current} WHERE {pred})")
            after = con.execute(_with(cte_defs) + f"SELECT count(*) FROM {name}", list(params)).fetchone()[0]
            report.append({
                "operation": "drop_nulls", "columns": list(op.columns), "how": op.how,
                "rows_affected": int(prev_rows - after), "confirmation_required": False,
            })
            prev_rows, current = after, name
        elif op.op == "drop_exact_duplicates":
            cte_defs.append(f"{name} AS (SELECT DISTINCT * FROM {current})")
            after = con.execute(_with(cte_defs) + f"SELECT count(*) FROM {name}", list(params)).fetchone()[0]
            report.append({
                "operation": "drop_exact_duplicates",
                "rows_affected": int(prev_rows - after), "confirmation_required": False,
            })
            prev_rows, current = after, name
        else:  # fill_nulls — imputes, never changes the row count
            col = _q(op.column)
            nulls = con.execute(
                _with(cte_defs) + f"SELECT count(*) FROM {current} WHERE {col} IS NULL", list(params)
            ).fetchone()[0]
            value = _fill_value(con, cte_defs, params, current, op)
            if value is None and op.strategy in ("median", "mode"):
                raise PreprocessError(
                    f"cannot compute {op.strategy} for column '{op.column}': "
                    "it is entirely null at this stage"
                )
            # datetime columns need the string constant cast to a timestamp so
            # coalesce's argument types unify.
            fill_expr = "?"
            if op.strategy == "constant" and schema.get(op.column) == "datetime":
                fill_expr = "CAST(? AS TIMESTAMP)"
            cte_defs.append(f"{name} AS (SELECT * REPLACE (coalesce({col}, {fill_expr}) AS {col}) FROM {current})")
            params.append(value)
            report.append({
                "operation": "fill_nulls", "column": op.column, "strategy": op.strategy,
                "fill_value": _sanitize_scalar(value), "rows_affected": int(nulls),
                "confirmation_required": False,
            })
            current = name

    return cte_defs, params, current, report, int(input_rows), int(prev_rows)


def _implicit_null_exclusions(
    con: "duckdb.DuckDBPyConnection",
    cte_defs: list[str],
    params: list[Any],
    relation: str,
    plan: AnalysisPlan,
    schema: dict[str, str],
) -> dict[str, int]:
    """Null counts (in the working view) for numeric columns fed to null-skipping
    aggregates — so provenance states the exclusion instead of hiding it."""
    cols = sorted({
        a.column for a in plan.aggregations
        if a.fn in ("sum", "mean", "min", "max", "median") and schema.get(a.column) == "number"
    })
    if not cols:
        return {}
    exprs = ", ".join(f"count(*) - count({_q(c)}) AS c{i}" for i, c in enumerate(cols))
    row = con.execute(_with(cte_defs) + f"SELECT {exprs} FROM {relation}", list(params)).fetchone()
    return {c: int(row[i]) for i, c in enumerate(cols) if row[i]}


def preprocessing_impact(
    record: DatasetRecord, analysis_plan: dict[str, Any]
) -> dict[str, Any]:
    """Row-level impact of a plan's preprocessing, without running the analysis.

    Used by the shared confirmation gate. Counts only, no mutation. Returns
    {input_rows, output_rows, dropped, fraction, preprocessing}.
    """
    plan = AnalysisPlan.model_validate(analysis_plan)
    con = duckdb.connect()
    try:
        con.register("df_raw", record.df)
        _ctes, _params, _rel, report, input_rows, output_rows = _apply_preprocessing(
            con, plan, record.schema
        )
    finally:
        try:
            con.close()
        except Exception:
            pass
    dropped = input_rows - output_rows
    return {
        "input_rows": input_rows,
        "output_rows": output_rows,
        "dropped": dropped,
        "fraction": (dropped / input_rows) if input_rows else 0.0,
        "preprocessing": report,
    }


def execute_analysis(
    dataset_id: str,
    analysis_plan: dict[str, Any],
    registry: DatasetRegistry = REGISTRY,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    """Run a validated plan against DuckDB and return the result with provenance.

    ``cancel_event`` lets a caller abort a query that is already running: a
    watcher interrupts the connection the moment it is set, the same mechanism
    the timeout watchdog uses. The MCP layer wires it to request cancellation so
    a user pressing Cancel actually stops the query instead of leaving it to run
    to completion unobserved.
    """
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

    started = time.perf_counter()
    timed_out = threading.Event()
    cancelled = threading.Event()
    finished = threading.Event()
    con = duckdb.connect()
    watchdog = threading.Timer(
        EXECUTION_TIMEOUT_S, lambda: (timed_out.set(), _interrupt(con))
    )

    def _watch_cancel() -> None:
        # Poll rather than block forever so the thread exits with the query.
        while not finished.is_set():
            if cancel_event.wait(_CANCEL_POLL_S):  # type: ignore[union-attr]
                cancelled.set()
                _interrupt(con)
                return

    cancel_watcher = (
        threading.Thread(target=_watch_cancel, daemon=True)
        if cancel_event is not None
        else None
    )
    sql = ""
    try:
        con.execute(f"SET memory_limit='{DUCKDB_MEMORY_LIMIT}'")
        con.execute(f"SET threads={DUCKDB_THREADS}")
        # Immutable source: register the raw frame under df_raw and build the
        # preprocessing working view over it — record.df is never modified.
        con.register("df_raw", record.df)
        watchdog.start()
        if cancel_watcher is not None:
            cancel_watcher.start()
        pp_ctes, pp_params, source_rel, pp_report, input_rows, output_rows = _apply_preprocessing(
            con, plan, record.schema
        )
        sql, where_params = build_sql(plan, pp_ctes=pp_ctes, source_relation=source_rel)
        result = con.execute(sql, pp_params + where_params).fetchdf()
        null_notes = _implicit_null_exclusions(
            con, pp_ctes, pp_params, source_rel, plan, record.schema
        )
    except PreprocessError as exc:
        return make_error(INVALID_PLAN, str(exc))
    except Exception as exc:
        # Both a timeout and a cancellation surface as the same DuckDB interrupt,
        # so the events are what distinguish them — reporting a user-cancelled
        # query as a TIMEOUT would send the caller off narrowing a fine query.
        if cancelled.is_set():
            return make_error(CANCELLED, "Execution was cancelled by the caller.", sql=sql)
        if timed_out.is_set():
            return make_error(
                TIMEOUT,
                f"Execution exceeded the {EXECUTION_TIMEOUT_S:g}s time budget.",
                sql=sql,
            )
        return make_error(EXECUTION_ERROR, f"Execution failed: {exc}", sql=sql)
    finally:
        finished.set()
        watchdog.cancel()
        try:
            con.close()
        except Exception:
            pass

    # con.interrupt() only aborts a query that is already in flight, so a short
    # query can finish in the gap between the cancel and the interrupt landing.
    # Honour the caller's intent either way: once cancellation is requested, no
    # result is returned.
    if cancelled.is_set():
        return make_error(CANCELLED, "Execution was cancelled by the caller.", sql=sql)

    elapsed_ms = (time.perf_counter() - started) * 1000

    return {
        "result_table": sanitize_records(result),
        "row_count": int(len(result)),
        "execution_time_ms": round(elapsed_ms, 2),
        # Cleaning-stage row accounting (before analysis filters/limit).
        "input_rows": input_rows,
        "output_rows": output_rows,
        "preprocessing": pp_report,
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
            "preprocessing": pp_report,
            "preprocessing_sql": pp_ctes,
            "implicit_null_exclusions": null_notes,
            "sql": sql,
        },
    }
