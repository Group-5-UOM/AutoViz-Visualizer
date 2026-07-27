"""Deterministic plan execution: analysis_plan -> DuckDB SQL -> result table.

Translation is a pure function over the closed plan grammar — identifiers are
quoted, literals are bound as parameters, and only allow-listed ops/fns can
appear, so injection is structurally impossible. A hard output-row ceiling is
enforced regardless of the requested limit.
"""

import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

import duckdb

from autoviz.errors import (
    CANCELLED,
    CONFIRMATION_REQUIRED,
    EXECUTION_ERROR,
    INVALID_PLAN,
    TIMEOUT,
    UNKNOWN_DATASET,
    make_error,
)
from autoviz.schema.allowlists import (
    HARD_ROW_CEILING,
    ROW_DROP_CONFIRM_FRACTION,
    ROW_DROP_NOTICE_FRACTION,
)
from autoviz.schema.analysis_plan import AnalysisPlan
from autoviz.services import dataset
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

# Safe-tier value rewrites. Each is a pure function of the cell — no aggregate, no
# reference to other rows — which is what makes them replayable and cheap.
_REWRITE_SQL = {
    "trim_whitespace": "trim({col})",
    # trim inside nullif so "   " counts as empty without also rewriting values
    # that are merely padded (trim_whitespace is a separate, explicit op).
    "empty_string_to_null": "nullif(trim({col}), '')",
    "normalize_case": "lower({col})",
}

_CAST_SQL = {
    "number": "TRY_CAST({col} AS DOUBLE)",
    "datetime": "TRY_CAST({col} AS TIMESTAMP)",
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
        elif op.op == "fill_nulls":  # imputes, never changes the row count
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
            # DuckDB already unifies a VARCHAR literal into a TIMESTAMP column
            # inside coalesce, so no explicit CAST is needed here. Datetime
            # constants are parsed during validation instead — a bad literal must
            # fail as a plan defect, not as a runtime engine error.
            cte_defs.append(f"{name} AS (SELECT * REPLACE (coalesce({col}, ?) AS {col}) FROM {current})")
            params.append(value)
            report.append({
                "operation": "fill_nulls", "column": op.column, "strategy": op.strategy,
                "fill_value": _sanitize_scalar(value), "rows_affected": int(nulls),
                "confirmation_required": False,
            })
            current = name
        elif op.op in ("trim_whitespace", "empty_string_to_null", "normalize_case"):
            # Value rewrites: same shape, one expression each. REPLACE swaps the
            # column in place inside the working view, so downstream references
            # keep their names and the source frame is untouched.
            targets = (
                [op.column] if op.op == "normalize_case" else list(dict.fromkeys(op.columns))
            )
            exprs = ", ".join(
                f"{_REWRITE_SQL[op.op].format(col=_q(c))} AS {_q(c)}" for c in targets
            )
            cte_defs.append(f"{name} AS (SELECT * REPLACE ({exprs}) FROM {current})")
            changed = con.execute(
                _with(cte_defs)
                + "SELECT count(*) FROM "
                + f"{current} WHERE "
                + " OR ".join(
                    # DISTINCT FROM so a null on either side counts as a change
                    # rather than swallowing the comparison.
                    f"{_q(c)} IS DISTINCT FROM {_REWRITE_SQL[op.op].format(col=_q(c))}"
                    for c in targets
                ),
                list(params),
            ).fetchone()[0]
            report.append({
                "operation": op.op, "columns": targets,
                "rows_affected": int(changed), "confirmation_required": False,
            })
            current = name
        elif op.op == "drop_empty_rows":
            # A row is empty when every column is null; keep it if any column is not.
            pred = " OR ".join(f"{_q(c)} IS NOT NULL" for c in schema)
            cte_defs.append(f"{name} AS (SELECT * FROM {current} WHERE {pred})")
            after = con.execute(
                _with(cte_defs) + f"SELECT count(*) FROM {name}", list(params)
            ).fetchone()[0]
            report.append({
                "operation": "drop_empty_rows",
                "rows_affected": int(prev_rows - after), "confirmation_required": False,
            })
            prev_rows, current = after, name
        elif op.op == "cast_column":
            col = _q(op.column)
            expr = _CAST_SQL[op.to].format(col=col)
            # Admissibility is decided here, against the working view, not against
            # the raw frame: casting after empty_string_to_null is the normal
            # shape, and by this point the sentinels that would have blocked the
            # conversion are already null. TRY_CAST yields null for anything that
            # will not convert, so comparing the two counts is exact.
            present, convertible = con.execute(
                _with(cte_defs) + f"SELECT count({col}), count({expr}) FROM {current}",
                list(params),
            ).fetchone()
            if convertible < present:
                # Silently nulling values is data loss dressed up as a repair. Refuse
                # and let the user say what those rows mean.
                raise PreprocessError(
                    f"cannot cast column '{op.column}' to {op.to}: "
                    f"{present - convertible} of {present} value(s) would not convert "
                    "and would be discarded"
                )
            cte_defs.append(f"{name} AS (SELECT * REPLACE ({expr} AS {col}) FROM {current})")
            report.append({
                "operation": "cast_column", "column": op.column, "to": op.to,
                "rows_affected": int(present),  # nulls stay null and are not counted
                "confirmation_required": False,
            })
            current = name
        elif op.op == "clean_categories":
            col = _q(op.column)
            # One CASE arm per mapping entry, every literal bound. Values the
            # mapping does not name fall through to ELSE unchanged.
            arms = " ".join("WHEN ? THEN ?" for _ in op.mapping)
            case_params: list[Any] = []
            for source, target in op.mapping.items():
                case_params.extend([source, target])
            changed = con.execute(
                _with(cte_defs)
                + f"SELECT count(*) FROM {current} WHERE {col} IN "
                + f"({', '.join('?' for _ in op.mapping)})",
                list(params) + list(op.mapping),
            ).fetchone()[0]
            cte_defs.append(
                f"{name} AS (SELECT * REPLACE "
                f"(CASE {col} {arms} ELSE {col} END AS {col}) FROM {current})"
            )
            params.extend(case_params)
            report.append({
                "operation": "clean_categories", "column": op.column,
                "mapping": dict(op.mapping), "rows_affected": int(changed),
                "confirmation_required": False,
            })
            current = name
        elif op.op == "group_rare_categories":
            col = _q(op.column)
            if op.min_frequency is not None:
                # A window count needs no keep-set: each row can see how often its
                # own value occurs. Nulls keep their own partition, so the explicit
                # IS NULL arm is what stops missing being relabelled as rare.
                expr = (
                    f"CASE WHEN {col} IS NULL THEN NULL "
                    f"WHEN count(*) OVER (PARTITION BY {col}) >= ? THEN {col} "
                    f"ELSE ? END"
                )
                new_params: list[Any] = [op.min_frequency, op.other_label]
                bucketed = con.execute(
                    _with(cte_defs)
                    + f"SELECT count(*) FROM (SELECT {col}, count(*) OVER "
                    f"(PARTITION BY {col}) AS _n FROM {current}) "
                    f"WHERE {col} IS NOT NULL AND _n < ?",
                    list(params) + [op.min_frequency],
                ).fetchone()[0]
            else:
                # top_n: the keep-set is bounded by top_n, so an IN list is cheap.
                # Same deterministic tie-break as `mode` — frequency desc, then
                # value asc — so a tie never depends on scan order.
                keep = [
                    row[0]
                    for row in con.execute(
                        _with(cte_defs)
                        + f"SELECT {col} FROM {current} WHERE {col} IS NOT NULL "
                        f"GROUP BY {col} ORDER BY count(*) DESC, {col} ASC LIMIT ?",
                        list(params) + [op.top_n],
                    ).fetchall()
                ]
                placeholders = ", ".join("?" for _ in keep)
                expr = (
                    f"CASE WHEN {col} IS NULL THEN NULL "
                    + (f"WHEN {col} IN ({placeholders}) THEN {col} " if keep else "")
                    + "ELSE ? END"
                )
                new_params = [*keep, op.other_label]
                bucketed = con.execute(
                    _with(cte_defs)
                    + f"SELECT count(*) FROM {current} WHERE {col} IS NOT NULL"
                    + (f" AND {col} NOT IN ({placeholders})" if keep else ""),
                    list(params) + list(keep),
                ).fetchone()[0]
            cte_defs.append(
                f"{name} AS (SELECT * REPLACE ({expr} AS {col}) FROM {current})"
            )
            params.extend(new_params)
            report.append({
                "operation": "group_rare_categories", "column": op.column,
                "other_label": op.other_label,
                **({"top_n": op.top_n} if op.top_n is not None else
                   {"min_frequency": op.min_frequency}),
                "rows_affected": int(bucketed), "confirmation_required": False,
            })
            current = name
        else:
            # Unreachable through the closed grammar (validation rejects an op with
            # no rule before we get here). Kept because the alternative — falling
            # through to a neighbouring op's branch — reads a field the op does not
            # have and surfaces as a *retryable* EXECUTION_ERROR, so the agent would
            # sit in a backoff loop re-running a plan that can never succeed.
            raise PreprocessError(
                f"preprocessing op '{op.op}' has no execution rule and cannot be applied"
            )

    return cte_defs, params, current, report, int(input_rows), int(prev_rows)


def _imputation_notices(
    plan: AnalysisPlan, report: list[dict[str, Any]], input_rows: int
) -> list[dict[str, Any]]:
    """Disclose imputations that are large enough to move the answer.

    ``fill_nulls`` keeps every row, so it never trips the row-removal gate — but
    replacing 80% of a column with its median makes the resulting mean mostly a
    synthetic constant. Percentage cannot decide *consent* here (that is the risk
    tier's job), but it is exactly the right axis for deciding whether the number
    deserves a caveat printed next to it.

    ``ROW_DROP_NOTICE_FRACTION`` is the same "small enough to mention rather than
    ask about" line already used for row removal, reused deliberately so the two
    disclosures share one threshold instead of drifting apart.
    """
    if not input_rows:
        return []
    notices: list[dict[str, Any]] = []
    for entry in report:
        if entry.get("operation") != "fill_nulls":
            continue
        affected = int(entry.get("rows_affected") or 0)
        fraction = affected / input_rows
        if affected and fraction >= ROW_DROP_NOTICE_FRACTION:
            notices.append(
                {
                    "column": entry.get("column"),
                    "strategy": entry.get("strategy"),
                    "rows_imputed": affected,
                    "fraction": round(fraction, 4),
                    "note": (
                        f"{affected} of {input_rows} values in "
                        f"'{entry.get('column')}' ({round(fraction * 100, 1)}%) were "
                        f"filled in, not measured."
                    ),
                }
            )
    return notices


def _implicit_null_exclusions(
    con: "duckdb.DuckDBPyConnection",
    cte_defs: list[str],
    params: list[Any],
    relation: str,
    plan: AnalysisPlan,
    schema: dict[str, str],
) -> dict[str, int]:
    """Null counts for numeric columns fed to null-skipping aggregates — so
    provenance states the exclusion instead of hiding it.

    Callers measure this on the *pre*-preprocessing relation. Measuring it after
    cleaning inverts the signal: a ``fill_nulls`` that makes an average 80%
    synthetic would report zero exclusions, so the more misleading plan would
    produce the cleaner-looking provenance."""
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
    record: DatasetRecord,
    analysis_plan: dict[str, Any],
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    """Row-level impact of a plan's preprocessing, without running the analysis.

    Used by the confirmation gate. Counts only, no mutation. Returns
    {input_rows, output_rows, dropped, fraction, preprocessing}.

    Runs under the same governors as execute_analysis: measuring the impact walks
    the whole CTE chain, so it is comparable work to the query itself and must be
    just as interruptible — an ungoverned safety check would be the one place a
    pathological plan could hang, and it runs *before* every unapproved removal.
    """
    plan = AnalysisPlan.model_validate(analysis_plan)
    with _governed_connection(cancel_event) as (con, guard):
        con.register("df_raw", record.df)
        try:
            _ctes, _params, _rel, report, input_rows, output_rows = _apply_preprocessing(
                con, plan, record.schema
            )
        except PreprocessError:
            raise
        except Exception as exc:
            raise _guard_failure(guard, exc) from exc
    dropped = input_rows - output_rows
    return {
        "input_rows": input_rows,
        "output_rows": output_rows,
        "dropped": dropped,
        "fraction": (dropped / input_rows) if input_rows else 0.0,
        "preprocessing": report,
    }


class GovernedFailure(Exception):
    """A governed query was interrupted. ``code`` says by what (TIMEOUT/CANCELLED),
    or is EXECUTION_ERROR when the engine simply failed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _guard_failure(guard: "_Guard", exc: Exception) -> GovernedFailure:
    """Classify a raised exception against the guard's interrupt flags.

    A timeout and a cancellation both surface as the same DuckDB interrupt, so the
    events are the only thing that tells them apart — reporting a user-cancelled
    query as a TIMEOUT would send the caller off narrowing a perfectly fine query.
    """
    if guard.cancelled.is_set():
        return GovernedFailure(CANCELLED, "Execution was cancelled by the caller.")
    if guard.timed_out.is_set():
        return GovernedFailure(
            TIMEOUT, f"Execution exceeded the {EXECUTION_TIMEOUT_S:g}s time budget."
        )
    return GovernedFailure(EXECUTION_ERROR, f"Execution failed: {exc}")


@dataclass
class _Guard:
    """The interrupt flags a governed connection sets on the caller's behalf."""

    timed_out: threading.Event
    cancelled: threading.Event


@contextmanager
def _governed_connection(
    cancel_event: threading.Event | None = None,
) -> "Iterator[tuple[duckdb.DuckDBPyConnection, _Guard]]":
    """A DuckDB connection under the memory/thread/time/cancel governors.

    Every path that runs preprocessing SQL goes through here, so none of them can
    be accidentally left ungoverned: the memory limit caps the engine's working
    set, the watchdog bounds wall-clock so a pathological query cannot hang a
    synchronous call, and the cancel watcher lets a user's Cancel actually stop
    the query instead of leaving it to run to completion unobserved.
    """
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

    watcher = (
        threading.Thread(target=_watch_cancel, daemon=True)
        if cancel_event is not None
        else None
    )
    try:
        con.execute(f"SET memory_limit='{DUCKDB_MEMORY_LIMIT}'")
        con.execute(f"SET threads={DUCKDB_THREADS}")
        watchdog.start()
        if watcher is not None:
            watcher.start()
        yield con, _Guard(timed_out=timed_out, cancelled=cancelled)
    finally:
        finished.set()
        watchdog.cancel()
        try:
            con.close()
        except Exception:
            pass


def _confirmation_gate(
    record: DatasetRecord,
    plan: AnalysisPlan,
    dataset_id: str,
    effective_plan: dict[str, Any],
    approved_preprocessing_hash: str | None,
    cancel_event: threading.Event | None,
) -> dict[str, Any] | None:
    """Refuse a large, unapproved row removal. Returns an error dict, or None to proceed.

    This lives in ``execute_analysis`` rather than a layer above it because
    ``execute_analysis`` is the only function that can run ``_apply_preprocessing``.
    A gate one layer up guards a door with another door beside it: both the MCP
    ``execute_analysis`` tool and ``POST /analysis/execute`` reach the cleaning
    stage directly, so a gate in the orchestrator alone protects neither.
    """
    if not plan.has_row_dropping_preprocessing():
        return None
    version = plan.preprocessing_version(dataset_id)
    if approved_preprocessing_hash == version:
        return None
    try:
        impact = preprocessing_impact(record, effective_plan, cancel_event=cancel_event)
    except PreprocessError as exc:
        # Measuring the impact runs the cleaning stage, so it can fail on an
        # unfillable column. That is a plan defect, not a refusal.
        return make_error(INVALID_PLAN, str(exc))
    except GovernedFailure as exc:
        return make_error(exc.code, str(exc))
    if impact["fraction"] <= ROW_DROP_CONFIRM_FRACTION:
        return None
    pct = round(impact["fraction"] * 100, 1)
    return make_error(
        CONFIRMATION_REQUIRED,
        f"This cleaning step would remove {impact['dropped']} of "
        f"{impact['input_rows']} rows ({pct}%). Approval is required before it runs.",
        confirmation={
            "question": (
                f"This cleaning step would remove {impact['dropped']} of "
                f"{impact['input_rows']} rows ({pct}%). Proceed?"
            ),
            "options": ["Proceed with cleaning", "Skip cleaning (keep all rows)"],
            "impact": impact,
            # The dataset-bound logical version of this cleaning block. Consent is
            # bound to it so approving a 4-row removal on one dataset cannot
            # authorise the identical block on another where it removes 99%.
            "preprocessing_hash": version,
        },
    )


def materialize_cleaned_dataset(
    dataset_id: str,
    preprocessing: list[dict[str, Any]],
    registry: DatasetRegistry = REGISTRY,
    approved_preprocessing_hash: str | None = None,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    """Promote a cleaning block's working view into a dataset of its own.

    Everywhere else, cleaning is a per-analysis view that is never stored — the
    plan is the recipe and the source is immutable, so the cleaned frame is always
    reproducible and holding a copy would only spend memory. This is the one
    explicit exception, for when a user wants to keep working from the cleaned
    data: preview it, chart it repeatedly, or build further analyses on it without
    restating the cleaning each time.

    It is a *write*, so it goes through the same confirmation gate as any other
    execution — materialising a 90% row removal is no less consequential for being
    deliberate. The parent is untouched and remains the lineage root.
    """
    record = registry.get(dataset_id)
    if record is None:
        return make_error(UNKNOWN_DATASET, f"Unknown dataset_id: {dataset_id}")

    # Wrap the block in a minimal plan so it is validated by exactly the same
    # rules as one embedded in an analysis — a cleaning step is not safer for
    # arriving on its own.
    stub = {
        "dataset_id": dataset_id,
        "intent": "comparison",
        "preprocessing": list(preprocessing),
    }
    verdict = validate_analysis_plan(dataset_id, stub, registry)
    if not verdict["valid"]:
        return make_error(
            verdict.get("error_code", INVALID_PLAN),
            "Plan failed validation",
            validation_errors=verdict["errors"],
        )
    plan = AnalysisPlan.model_validate(stub)
    if not plan.preprocessing:
        return make_error(
            INVALID_PLAN, "materialize_cleaned_dataset needs at least one cleaning step."
        )

    refusal = _confirmation_gate(
        record, plan, dataset_id, stub, approved_preprocessing_hash, cancel_event
    )
    if refusal is not None:
        return refusal

    version = plan.preprocessing_version(dataset_id)
    try:
        with _governed_connection(cancel_event) as (con, guard):
            con.register("df_raw", record.df)
            try:
                cte_defs, params, source_rel, report, input_rows, output_rows = (
                    _apply_preprocessing(con, plan, record.schema)
                )
                cleaned = con.execute(
                    _with(cte_defs) + f"SELECT * FROM {source_rel}", list(params)
                ).fetchdf()
            except PreprocessError:
                raise
            except Exception as exc:
                raise _guard_failure(guard, exc) from exc
            if guard.cancelled.is_set():
                raise GovernedFailure(CANCELLED, "Execution was cancelled by the caller.")
    except PreprocessError as exc:
        return make_error(INVALID_PLAN, str(exc))
    except GovernedFailure as exc:
        return make_error(exc.code, str(exc))

    new_record = dataset.build_record(
        cleaned,
        f"{record.source} [cleaned {version}]",
        registry,
        lineage={
            "parent_id": dataset_id,
            "version_id": version,
            "preprocessing": [op.model_dump(by_alias=True) for op in plan.preprocessing],
            "steps": report,
            "input_rows": input_rows,
            "output_rows": output_rows,
            # Whether a person approved this specific block, as opposed to it
            # simply falling under the threshold.
            "confirmed_by_user": approved_preprocessing_hash == version,
        },
    )
    registry.add(new_record)
    return {
        "dataset_id": new_record.dataset_id,
        "parent_id": dataset_id,
        "version_id": version,
        "row_count": int(len(cleaned)),
        "column_count": int(len(cleaned.columns)),
        "input_rows": input_rows,
        "output_rows": output_rows,
        "preprocessing": report,
    }


def execute_analysis(
    dataset_id: str,
    analysis_plan: dict[str, Any],
    registry: DatasetRegistry = REGISTRY,
    cancel_event: threading.Event | None = None,
    approved_preprocessing_hash: str | None = None,
) -> dict[str, Any]:
    """Run a validated plan against DuckDB and return the result with provenance.

    ``cancel_event`` lets a caller abort a query that is already running: a
    watcher interrupts the connection the moment it is set, the same mechanism
    the timeout watchdog uses. The MCP layer wires it to request cancellation so
    a user pressing Cancel actually stops the query instead of leaving it to run
    to completion unobserved.

    ``approved_preprocessing_hash`` carries the user's consent for a cleaning step
    that removes a large share of rows. Without a matching token such a plan is
    refused with ``CONFIRMATION_REQUIRED`` — enforced here, so every caller is
    covered, not only the ones that go through ``run_pipeline``.
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

    refusal = _confirmation_gate(
        record, plan, dataset_id, effective_plan, approved_preprocessing_hash, cancel_event
    )
    if refusal is not None:
        return refusal

    started = time.perf_counter()
    sql = ""
    try:
        with _governed_connection(cancel_event) as (con, guard):
            # Immutable source: register the raw frame under df_raw and build the
            # preprocessing working view over it — record.df is never modified.
            con.register("df_raw", record.df)
            try:
                pp_ctes, pp_params, source_rel, pp_report, input_rows, output_rows = (
                    _apply_preprocessing(con, plan, record.schema)
                )
                # Measured on df_raw, *before* cleaning: an imputation that turns a
                # mean 80% synthetic must not also empty the disclosure that says so.
                null_notes = _implicit_null_exclusions(
                    con, [], [], "df_raw", plan, record.schema
                )
                sql, where_params = build_sql(
                    plan, pp_ctes=pp_ctes, source_relation=source_rel
                )
                result = con.execute(sql, pp_params + where_params).fetchdf()
                imputation_notices = _imputation_notices(plan, pp_report, input_rows)
            except PreprocessError:
                raise
            except Exception as exc:
                raise _guard_failure(guard, exc) from exc
            # con.interrupt() only aborts a query already in flight, so a short query
            # can finish in the gap between the cancel and the interrupt landing.
            # Honour the caller's intent either way.
            if guard.cancelled.is_set():
                raise GovernedFailure(CANCELLED, "Execution was cancelled by the caller.")
    except PreprocessError as exc:
        return make_error(INVALID_PLAN, str(exc))
    except GovernedFailure as exc:
        return make_error(exc.code, str(exc), sql=sql)

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
                # Cleaning columns count as used: they decide which rows survive,
                # so a result whose row set is determined by `fare` must say so
                # even when `fare` appears nowhere in the select or aggregation.
                | {c for c in plan.preprocessing_columns() if c in record.schema}
            ),
            "filters": [f.model_dump() for f in plan.filters],
            "aggregations": [a.model_dump(by_alias=True) for a in plan.aggregations],
            "chart_type": plan.chart.type if plan.chart else None,
            "preprocessing": pp_report,
            "preprocessing_sql": pp_ctes,
            "implicit_null_exclusions": null_notes,
            "imputation_notices": imputation_notices,
            # Logical id of the cleaned view these numbers came from. Reproducible
            # from (source, preprocessing) without materialising anything.
            "preprocessing_version": plan.preprocessing_version(dataset_id),
            # Full cleaning account in one place: what was inspected, what each
            # step did, the before/after row counts, whether a person approved it,
            # and — when the source is itself a cleaned dataset — where it came
            # from. This is what makes a number traceable back through cleaning
            # rather than only back to a query.
            "cleaning": {
                "version_id": plan.preprocessing_version(dataset_id),
                "columns_inspected": sorted(plan.preprocessing_columns()),
                "steps": pp_report,
                "input_rows": input_rows,
                "output_rows": output_rows,
                "confirmed_by_user": (
                    approved_preprocessing_hash == plan.preprocessing_version(dataset_id)
                ),
                # When the source is itself a cleaned dataset, both halves of the
                # chain are needed: `parent` says which dataset it derives from and
                # `source_version_id` which cleaning produced it. Without the
                # latter the trail stops one link short of the original rows.
                "parent": (record.profile or {}).get("lineage", {}).get("parent_id"),
                "source_version_id": (record.profile or {}).get("lineage", {}).get(
                    "version_id"
                ),
            },
            "sql": sql,
        },
    }
