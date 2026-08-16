"""Performance benchmark for the AutoViz analysis path.

Measures the shipped code — `ingest.read_table`, `dataset.build_record`,
`execution.execute_analysis`, `charts.generate_chart`, `orchestrator.run_pipeline`
— rather than a reimplementation of it, so the numbers describe the product a
user actually waits on.

Run:  uv run python -m bench.perf [--quick] [--out results.json]

Every phase reports a median and a p95 over repeated runs after a warm-up, and
records the machine it ran on. A single number without the machine beside it is
not a measurement, so the header block is part of the output.
"""

from __future__ import annotations

import argparse
import ctypes
import gc
import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable

# Import the package from src/ without requiring an editable install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import duckdb  # noqa: E402
import pandas as pd  # noqa: E402

from bench import gen  # noqa: E402
from bench.plans import SHAPES, plan_for  # noqa: E402

from autoviz.services import charts, dataset as dataset_svc, ingest  # noqa: E402
from autoviz.services.execution import execute_analysis  # noqa: E402
from autoviz.services.orchestrator import run_pipeline  # noqa: E402
from autoviz.services.registry import DatasetRegistry  # noqa: E402
from autoviz.services.validation import validate_analysis_plan  # noqa: E402

SCALES = [1_000, 10_000, 100_000, 500_000, 1_000_000]
QUICK_SCALES = [1_000, 10_000, 100_000]

# Fewer repeats where a single run already costs real time; the p95 of three
# runs is weaker evidence than the p95 of nine, and the report says which is
# which by carrying `repeats` alongside every measurement.
def _repeats(rows: int, quick: bool) -> int:
    if quick:
        return 3
    if rows <= 100_000:
        return 9
    return 4


# ---------------------------------------------------------------- timing


def timed(fn: Callable[[], Any], repeats: int, warmup: int = 1) -> dict[str, Any]:
    """Run `fn` and return the latency distribution in milliseconds."""
    for _ in range(warmup):
        fn()
    samples: list[float] = []
    result = None
    for _ in range(repeats):
        gc.collect()
        t0 = time.perf_counter()
        result = fn()
        samples.append((time.perf_counter() - t0) * 1000)
    samples.sort()
    # With few samples the "p95" is the slowest observed run. Naming it p95
    # anyway would overstate it, so the key says max_ms when n < 20.
    tail_key = "p95_ms" if repeats >= 20 else "max_ms"
    return {
        "median_ms": round(statistics.median(samples), 2),
        "min_ms": round(samples[0], 2),
        tail_key: round(samples[-1], 2),
        "repeats": repeats,
        "_result": result,
    }


def _strip(m: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in m.items() if not k.startswith("_")}


if sys.platform == "win32":
    import ctypes.wintypes as _wt

    class _PMC(ctypes.Structure):
        _fields_ = [("cb", _wt.DWORD), ("PageFaultCount", _wt.DWORD)] + [
            (n, ctypes.c_size_t)
            for n in (
                "PeakWorkingSetSize", "WorkingSetSize",
                "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
                "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                "PagefileUsage", "PeakPagefileUsage",
            )
        ]

    # Both signatures must be declared. Left implicit, ctypes truncates the
    # 64-bit process handle to an int and the call silently returns 0 — which
    # reads as "0 MiB resident" rather than as the failure it is.
    _K32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    _K32.GetCurrentProcess.restype = ctypes.c_void_p
    _K32.K32GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(_PMC), _wt.DWORD
    ]
    _K32.K32GetProcessMemoryInfo.restype = _wt.BOOL


def rss_mb() -> tuple[float, float] | None:
    """(current, peak) working set of this process in MiB. Windows and POSIX."""
    if sys.platform == "win32":
        counters = _PMC()
        counters.cb = ctypes.sizeof(_PMC)
        if not _K32.K32GetProcessMemoryInfo(
            _K32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        ):
            return None
        return (
            round(counters.WorkingSetSize / 1024 / 1024, 1),
            round(counters.PeakWorkingSetSize / 1024 / 1024, 1),
        )
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux reports KiB, macOS bytes.
        scaled = peak / 1024 if sys.platform != "darwin" else peak / 1024 / 1024
        return (round(scaled, 1), round(scaled, 1))
    except Exception:
        return None


# ---------------------------------------------------------------- phases


def phase_ingest(scales: list[int], workdir: Path, quick: bool) -> list[dict[str, Any]]:
    """CSV on disk -> registered, typed, profiled dataset."""
    rows_out = []
    for rows in scales:
        frame = gen.make_frame(rows)
        csv_path = workdir / f"bench_{rows}.csv"
        if not csv_path.exists():
            frame.to_csv(csv_path, index=False)
        size_bytes = csv_path.stat().st_size
        reps = max(2, _repeats(rows, quick) // 3)

        # The byte ceiling is a shipped policy, and at this schema it fires
        # before the row ceiling does. Recording the refusal is the measurement;
        # raising past it would be benchmarking a product that does not exist.
        try:
            read = timed(lambda p=csv_path: ingest.read_table(p), reps)
        except ingest.IngestError as exc:
            rows_out.append(
                {
                    "rows": rows,
                    "columns": len(frame.columns),
                    "csv_bytes": size_bytes,
                    "csv_mib": round(size_bytes / 1024 / 1024, 2),
                    "refused": True,
                    "error_code": exc.code,
                    "error": exc.message,
                }
            )
            del frame
            gc.collect()
            continue
        loaded, _report = read["_result"]

        registry = DatasetRegistry()
        build = timed(
            lambda f=loaded, r=registry: dataset_svc.build_record(f, "bench", r), reps
        )
        record = build["_result"]

        rows_out.append(
            {
                "rows": rows,
                "columns": len(frame.columns),
                "csv_bytes": size_bytes,
                "csv_mib": round(size_bytes / 1024 / 1024, 2),
                "frame_mib": round(record.nbytes() / 1024 / 1024, 2),
                "expansion_x": round(record.nbytes() / size_bytes, 2),
                "refused": False,
                "read_table": _strip(read),
                "build_record_profile": _strip(build),
                "total_median_ms": round(
                    read["median_ms"] + build["median_ms"], 2
                ),
            }
        )
        del frame, loaded, record, registry
        gc.collect()
    return rows_out


def phase_query(scales: list[int], quick: bool) -> list[dict[str, Any]]:
    """execute_analysis latency per plan shape per scale."""
    out = []
    for rows in scales:
        frame = gen.make_frame(rows)
        registry = DatasetRegistry()
        record = dataset_svc.build_record(frame, f"bench-{rows}", registry)
        registry.add(record)
        did = record.dataset_id
        reps = _repeats(rows, quick)

        for shape in SHAPES:
            plan = plan_for(shape, did)
            # Validation is timed on its own: it is pure Python over the schema
            # and does not touch the engine, so blending it into the query would
            # misattribute a fixed cost as a scaling one.
            v = timed(lambda p=plan, d=did, r=registry: validate_analysis_plan(d, p, r), reps)
            m = timed(lambda p=plan, d=did, r=registry: execute_analysis(d, p, r), reps)
            res = m["_result"]
            if "error" in res:
                out.append(
                    {"rows": rows, "shape": shape["id"], "error": res.get("error")}
                )
                continue
            out.append(
                {
                    "rows": rows,
                    "shape": shape["id"],
                    "label": shape["label"],
                    "note": shape["note"],
                    "result_rows": res["row_count"],
                    # The engine-side span, as `execute_analysis` times it: the
                    # governed connection and the query, without validation or
                    # the confirmation gate around them.
                    "engine_reported_ms": res["execution_time_ms"],
                    "validate": _strip(v),
                    "execute": _strip(m),
                }
            )
        del frame, record, registry
        gc.collect()
    return out


def phase_overhead(scales: list[int], quick: bool) -> list[dict[str, Any]]:
    """Where a query's wall time actually goes.

    Every `execute_analysis` call opens its own governed DuckDB connection,
    exposes the frame to it, and runs one statement. Reporting only the total
    hides which of those three is the cost — and for small tables it is not the
    one anybody assumes.

    Also measures the scan source both ways. AutoViz hands DuckDB a cached Arrow
    view of the frame; before that it handed over the pandas frame, and DuckDB
    re-crossed the pandas boundary on every query. Both are timed here so the
    change is evidenced rather than asserted.
    """
    import pyarrow as pa

    query = 'SELECT region, category, sum(revenue) AS t FROM x GROUP BY region, category'
    out = []
    for rows in scales:
        frame = gen.make_frame(rows)
        table = pa.Table.from_pandas(frame, preserve_index=False)
        reps = 3 if quick else 7

        def governed(src):
            con = duckdb.connect()
            try:
                con.execute("SET memory_limit='1GB'")
                con.execute("SET threads=2")
                con.register("x", src)
                return con.execute(query).fetchdf()
            finally:
                con.close()

        connect = timed(lambda: duckdb.connect().close(), reps)
        convert = timed(
            lambda f=frame: pa.Table.from_pandas(f, preserve_index=False), reps
        )

        # Isolate registration and the statement on a live connection.
        con = duckdb.connect()
        con.execute("SET memory_limit='1GB'")
        con.execute("SET threads=2")
        reg_pd = timed(lambda f=frame: con.register("x", f), reps)
        con.register("x", frame)
        q_pd = timed(lambda: con.execute(query).fetchdf(), reps)
        reg_ar = timed(lambda t=table: con.register("x", t), reps)
        con.register("x", table)
        q_ar = timed(lambda: con.execute(query).fetchdf(), reps)
        con.close()

        full_pd = timed(lambda f=frame: governed(f), reps)
        full_ar = timed(lambda t=table: governed(t), reps)

        out.append(
            {
                "rows": rows,
                "connect_ms": connect["median_ms"],
                "pandas_to_arrow_once_ms": convert["median_ms"],
                "pandas": {
                    "register_ms": reg_pd["median_ms"],
                    "query_ms": q_pd["median_ms"],
                    "governed_total_ms": full_pd["median_ms"],
                },
                "arrow": {
                    "register_ms": reg_ar["median_ms"],
                    "query_ms": q_ar["median_ms"],
                    "governed_total_ms": full_ar["median_ms"],
                },
                "speedup_x": round(
                    full_pd["median_ms"] / max(full_ar["median_ms"], 1e-9), 2
                ),
                "repeats": reps,
            }
        )
        del frame, table
        gc.collect()
    return out


def phase_memory(scales: list[int]) -> list[dict[str, Any]]:
    """What a resident dataset costs, and what the Arrow view adds on top.

    Measured as real working-set delta, not as logical buffer size: under
    Arrow-backed pandas the view shares the frame's buffers, so `Table.nbytes`
    would report a copy that was never made.
    """
    import pyarrow as pa

    out = []
    for rows in scales:
        gc.collect()
        base = rss_mb()
        frame = gen.make_frame(rows)
        registry = DatasetRegistry()
        record = dataset_svc.build_record(frame, f"mem-{rows}", registry)
        registry.add(record)
        gc.collect()
        loaded = rss_mb()
        table = record.arrow()
        gc.collect()
        with_arrow = rss_mb()
        out.append(
            {
                "rows": rows,
                "frame_mib": round(record.nbytes() / 1024 / 1024, 2),
                "rss_after_load_mib": loaded[0] if loaded else None,
                "rss_delta_frame_mib": (
                    round(loaded[0] - base[0], 1) if base and loaded else None
                ),
                "rss_delta_arrow_mib": (
                    round(with_arrow[0] - loaded[0], 1) if loaded and with_arrow else None
                ),
                "arrow_logical_mib": round(table.nbytes / 1024 / 1024, 1) if table else None,
            }
        )
        del frame, record, registry, table
        gc.collect()
    return out


def phase_ab_scan_source(scales: list[int], quick: bool) -> list[dict[str, Any]]:
    """The Arrow change, measured on `execute_analysis` itself rather than a proxy.

    `phase_overhead` times the pieces; this times the shipped function with the
    escape hatch flipped, which is the only comparison that answers "what did
    the user's wait actually become".
    """
    out = []
    for rows in scales:
        frame = gen.make_frame(rows)
        registry = DatasetRegistry()
        record = dataset_svc.build_record(frame, f"ab-{rows}", registry)
        registry.add(record)
        reps = _repeats(rows, quick)
        for sid in ("agg_2key", "derive_trend", "top_n"):
            shape = next(s for s in SHAPES if s["id"] == sid)
            plan = plan_for(shape, record.dataset_id)
            arm: dict[str, Any] = {"rows": rows, "shape": sid}
            for source in ("pandas", "arrow"):
                os.environ["AUTOVIZ_SCAN_SOURCE"] = source
                m = timed(
                    lambda p=plan, d=record.dataset_id, r=registry: execute_analysis(d, p, r),
                    reps,
                )
                arm[source] = _strip(m)
            os.environ.pop("AUTOVIZ_SCAN_SOURCE", None)
            arm["speedup_x"] = round(
                arm["pandas"]["median_ms"] / max(arm["arrow"]["median_ms"], 1e-9), 2
            )
            out.append(arm)
        del frame, record, registry
        gc.collect()
    return out


def phase_result_delivery(quick: bool) -> list[dict[str, Any]]:
    """How much of a query's cost is turning the result into JSON-safe records.

    `execute_analysis` returns `result_table` as a list of dicts. The conversion
    is O(result rows x columns) — per *cell*, not per row, which is why a
    100k-row two-column ranking and a 100k-row eleven-column extract cost very
    different amounts. Both axes are swept so the ceiling can be argued about
    with a rate rather than a single anecdote.
    """
    from autoviz.services.dataset import sanitize_records

    out = []
    frame = gen.make_frame(200_000)
    narrow = ["customer_id", "revenue"]
    for n in (100, 1_000, 10_000, 50_000, 100_000):
        for width, cols in (("full_11col", list(frame.columns)), ("narrow_2col", narrow)):
            chunk = frame.head(n)[cols]
            m = timed(lambda c=chunk: sanitize_records(c), 3 if quick else 5)
            payload = json.dumps(m["_result"], default=str)
            out.append(
                {
                    "result_rows": n,
                    "shape": width,
                    "columns": len(cols),
                    "cells": n * len(cols),
                    "sanitize": _strip(m),
                    "us_per_cell": round(m["median_ms"] * 1000 / (n * len(cols)), 3),
                    "json_bytes": len(payload),
                    "json_mib": round(len(payload) / 1024 / 1024, 2),
                }
            )
    del frame
    gc.collect()
    return out


def phase_chart(quick: bool) -> list[dict[str, Any]]:
    """Recommendation + Vega-Lite spec build, against result size."""
    out = []
    frame = gen.make_frame(120_000)
    reps = 3 if quick else 7
    for n in (12, 100, 1_000, 10_000, 100_000):
        table = frame.head(n)[["region", "revenue"]].to_dict("records")
        schema = [{"name": "region", "type": "string"}, {"name": "revenue", "type": "number"}]
        rec = timed(lambda s=schema: charts.recommend_chart_type(s, "ranking"), reps)
        spec = {"type": "bar", "x": "region", "y": "revenue", "intent": "ranking"}
        build = timed(lambda t=table, s=dict(spec): charts.generate_chart(t, s), reps)
        built = build["_result"]
        out.append(
            {
                "result_rows": n,
                "recommend": _strip(rec),
                "generate_chart": _strip(build),
                "spec_valid": bool(built.get("valid")),
                "spec_bytes": len(json.dumps(built.get("vega_lite_spec") or {}, default=str)),
            }
        )
    del frame
    gc.collect()
    return out


def phase_pipeline(scales: list[int], quick: bool) -> list[dict[str, Any]]:
    """validate -> execute -> recommend -> generate, as one call. No LLM."""
    out = []
    picks = [s for s in scales if s in (10_000, 100_000, 1_000_000)] or scales[-1:]
    for rows in picks:
        frame = gen.make_frame(rows)
        registry = DatasetRegistry()
        record = dataset_svc.build_record(frame, f"bench-{rows}", registry)
        registry.add(record)
        reps = _repeats(rows, quick)
        for sid in ("agg_2key", "derive_trend", "top_n"):
            shape = next(s for s in SHAPES if s["id"] == sid)
            plan = plan_for(shape, record.dataset_id)
            m = timed(
                lambda p=plan, d=record.dataset_id, r=registry: run_pipeline(d, p, r), reps
            )
            res = m["_result"]
            out.append(
                {
                    "rows": rows,
                    "shape": sid,
                    "status": res.get("status"),
                    "pipeline": _strip(m),
                    "chart_type": (res.get("chart_spec") or {}).get("type"),
                }
            )
        del frame, record, registry
        gc.collect()
    return out


def phase_join_headroom(scales: list[int], quick: bool) -> list[dict[str, Any]]:
    """What a join would cost, if the plan grammar had one.

    AutoViz ships single-table analysis: `analysis_plan` has no join clause, so
    this measures the *engine* under the same governors the product sets, not a
    product capability. It is here to size the roadmap item, and it is labelled
    that way everywhere it is reported.
    """
    import pyarrow as pa

    out = []
    # Arrow on both sides, so the estimate describes a join built on today's
    # scan path rather than on the pandas one the Arrow change replaced.
    small = pa.Table.from_pandas(gen.make_dimension("small"), preserve_index=False)
    large = pa.Table.from_pandas(gen.make_dimension("large"), preserve_index=False)
    for rows in scales:
        if rows < 100_000:
            continue
        fact = pa.Table.from_pandas(gen.make_frame(rows), preserve_index=False)
        reps = 3 if quick else 4
        for kind, dim, key in (("small_dim", small, "product"), ("large_dim", large, "customer_id")):
            def run(f=fact, d=dim, k=key):
                con = duckdb.connect()
                try:
                    con.execute("SET memory_limit='1GB'")
                    con.execute("SET threads=2")
                    con.register("fact", f)
                    con.register("dim", d)
                    return con.execute(
                        f'SELECT d.* EXCLUDE ("{k}"), sum(f.revenue) AS total '
                        f'FROM fact f JOIN dim d USING ("{k}") '
                        f"GROUP BY ALL LIMIT 100000"
                    ).fetchdf()
                finally:
                    con.close()

            m = timed(run, reps)
            out.append(
                {
                    "rows": rows,
                    "join": kind,
                    "dim_rows": dim.num_rows,
                    "result_rows": int(len(m["_result"])),
                    "duckdb": _strip(m),
                    "shipped_capability": False,
                }
            )
        del fact
        gc.collect()
    return out


def phase_limits(workdir: Path) -> dict[str, Any]:
    """Where the shipped resource ceilings actually bite, in rows for this schema."""
    probe = gen.make_frame(50_000)
    path = workdir / "bench_probe.csv"
    probe.to_csv(path, index=False)
    bytes_per_row = path.stat().st_size / 50_000
    return {
        "max_file_bytes": ingest.MAX_FILE_BYTES,
        "max_file_mib": round(ingest.MAX_FILE_BYTES / 1024 / 1024, 1),
        "max_rows": ingest.MAX_ROWS,
        "max_columns": ingest.MAX_COLUMNS,
        "hard_row_ceiling": __import__(
            "autoviz.schema.allowlists", fromlist=["HARD_ROW_CEILING"]
        ).HARD_ROW_CEILING,
        "bench_bytes_per_row": round(bytes_per_row, 1),
        # The binding constraint for an 11-column sales table is the byte
        # ceiling, not the row ceiling — this is the row count at which it fires.
        "rows_at_file_limit": int(ingest.MAX_FILE_BYTES / bytes_per_row),
        "duckdb_memory_limit": os.environ.get("AUTOVIZ_DUCKDB_MEMORY_LIMIT", "1GB"),
        "duckdb_threads": os.environ.get("AUTOVIZ_DUCKDB_THREADS", "2"),
        "execution_timeout_s": float(os.environ.get("AUTOVIZ_EXECUTION_TIMEOUT_S", 30.0)),
    }


# ---------------------------------------------------------------- driver


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="small scales, fewer repeats")
    ap.add_argument("--out", default="bench/results/perf.json")
    ap.add_argument("--workdir", default=None, help="where the generated CSVs go")
    args = ap.parse_args()

    scales = QUICK_SCALES if args.quick else SCALES
    workdir = Path(args.workdir) if args.workdir else Path(
        os.environ.get("TEMP", "/tmp")
    ) / "autoviz-bench"
    workdir.mkdir(parents=True, exist_ok=True)

    started = time.time()
    report: dict[str, Any] = {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "processor": platform.processor() or platform.machine(),
            "cpu_count": os.cpu_count(),
            "duckdb": duckdb.__version__,
            "pandas": pd.__version__,
            "quick": args.quick,
            "scales": scales,
        },
        "limits": phase_limits(workdir),
    }
    print(f"[bench] limits done  ({time.time() - started:.0f}s)", flush=True)

    report["ingest"] = phase_ingest(scales, workdir, args.quick)
    print(f"[bench] ingest done  ({time.time() - started:.0f}s)", flush=True)

    report["query"] = phase_query(scales, args.quick)
    print(f"[bench] query done  ({time.time() - started:.0f}s)", flush=True)

    report["overhead"] = phase_overhead(scales, args.quick)
    print(f"[bench] overhead done  ({time.time() - started:.0f}s)", flush=True)

    report["memory"] = phase_memory(scales)
    print(f"[bench] memory done  ({time.time() - started:.0f}s)", flush=True)

    report["ab_scan_source"] = phase_ab_scan_source(scales, args.quick)
    print(f"[bench] A/B done  ({time.time() - started:.0f}s)", flush=True)

    report["result_delivery"] = phase_result_delivery(args.quick)
    print(f"[bench] delivery done  ({time.time() - started:.0f}s)", flush=True)

    report["chart"] = phase_chart(args.quick)
    print(f"[bench] chart done  ({time.time() - started:.0f}s)", flush=True)

    report["pipeline"] = phase_pipeline(scales, args.quick)
    print(f"[bench] pipeline done  ({time.time() - started:.0f}s)", flush=True)

    report["join_headroom"] = phase_join_headroom(scales, args.quick)
    print(f"[bench] joins done  ({time.time() - started:.0f}s)", flush=True)

    peak = rss_mb()
    report["meta"]["peak_rss_mib"] = peak[1] if peak else None
    report["meta"]["wall_seconds"] = round(time.time() - started, 1)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[bench] wrote {out}  ({report['meta']['wall_seconds']}s total)")


if __name__ == "__main__":
    main()
