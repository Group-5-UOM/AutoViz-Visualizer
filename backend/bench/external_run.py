"""Run the frozen nvBench / VisEval sample against the live agent and score it.

Run:  uv run python -m bench.external_run [--source all|nvbench|viseval] [--only NV-12,VE-8]
                                          [--shard 1/4] [--out bench/results/external.json]
      uv run python -m bench.external_run --rescore bench/results/external.json   # no LLM

Each case gets the one table its gold SQL reads (see `external_suite`) and the
benchmark's own NL question, and the answer is scored on what the chart shows,
never on how the plan or the specification is spelled:

* **valid**  — a chart came back and its Vega-Lite specification validates
  against the renderer's own JSON schema (VisEval's *validity*)
* **family** — its type is one the benchmark chart allows (`FAMILIES`)
* **x**      — some column of the chart's data holds exactly the gold x values
* **data**   — the chart's data, as (x, series, y) points, equals the gold
  chart's — the strict half of VisEval's *legality*. y compares to 2 decimals;
  timestamps compare at the grain the gold was binned to; zero-valued points
  are ignored on both sides, because nvBench zero-fills bins a GROUP BY never
  returns. Order is not checked, so a query that asks for a sort passes on its
  values alone.

*Structural* success is valid and family and x, the check a reader can make
without recomputing anything; *correct* is data. They are reported side by side
because they disagree exactly when a plausible chart shows the wrong numbers.

A case that pauses for clarification is `asked` and one that returns no chart
is `failed`; neither is folded into the property counts, which are over the
cases that answered.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import os
import statistics
import subprocess
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoviz.agent.service import AgentService
from autoviz.services.dataset import register_dataset
from autoviz.services.registry import DatasetRegistry
from bench.external_suite import (
    FAMILIES,
    binning_unit,
    cases_sha256,
    gold_points,
    load_cases,
    norm_x,
    norm_y,
    table_csv,
)

REPO = Path(__file__).resolve().parents[2]
CACHE = Path(__file__).resolve().parent / ".cache" / "external"
_PAUSED = "waiting_for_user"
_DONE = "completed"


# --------------------------------------------------------------------------
# Vega-Lite schema — the renderer's own, from node_modules, else the CDN copy
# of the same version
# --------------------------------------------------------------------------

def _vl_validator() -> tuple[Any, str]:
    try:
        import jsonschema
    except ImportError:
        return None, "jsonschema not installed"
    local = REPO / "frontend/node_modules/vega-lite/build/vega-lite-schema.json"
    if local.exists():
        path, origin = local, "frontend/node_modules"
    else:
        pkg = json.loads((REPO / "frontend/package.json").read_text(encoding="utf-8"))
        version = (pkg.get("dependencies") or {}).get("vega-lite", "6").lstrip("^~")
        path = CACHE / f"vega-lite-schema-{version}.json"
        origin = f"jsdelivr vega-lite@{version}"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(
                f"https://cdn.jsdelivr.net/npm/vega-lite@{version}/build/vega-lite-schema.json", path)
    schema = json.loads(path.read_text(encoding="utf-8"))
    return jsonschema.Draft7Validator(schema), origin


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------

def _x_matches(rows: list[dict[str, Any]], nonzero_x: set[str], all_x: set[str],
               unit: str | None) -> bool:
    """Some column holds every x the gold draws a non-zero mark at, and nothing
    the gold does not have — so a zero-filled bin may be present or absent."""
    cols = list(rows[0]) if rows else []
    return any(nonzero_x <= {norm_x(r.get(c), unit) for r in rows} <= all_x for c in cols)


def _data_matches(rows: list[dict[str, Any]], gold: Counter, has_series: bool, unit: str | None) -> bool:
    """Is there an (x, [series,] y) choice of the chart's columns whose non-zero
    points are exactly the gold's non-zero points? Columns are searched rather
    than read off the encoding because a horizontal bar, a pie's theta and a
    binned axis all put the same data on differently named channels.

    Zeros are dropped on both sides because nvBench fills every bin and every
    series × x cell its chart draws — a year with no rows is a 0 there, and
    simply absent from a GROUP BY. Dropping them on one side only would score
    a correct answer wrong for not inventing empty groups."""
    if not rows:
        return False
    cols = list(rows[0])
    numeric = [c for c in cols if all(norm_y(r.get(c)) is not None or r.get(c) is None for r in rows)]
    for x in cols:
        for y in numeric:
            if y == x:
                continue
            kept = [r for r in rows if norm_y(r.get(y)) != 0]
            if len(kept) != sum(gold.values()):
                continue
            series_choices = [s for s in cols if s not in (x, y)] if has_series else [None]
            for s in series_choices:
                got = Counter((norm_x(r.get(x), unit), norm_x(r.get(s)) if s else None, norm_y(r.get(y)))
                              for r in kept)
                if got == gold:
                    return True
    return False


def score_chart(case: dict[str, Any], chart: dict[str, Any], validator: Any) -> dict[str, Any]:
    unit = binning_unit(case["binning"])
    every = gold_points(case["vis_obj"], unit)
    # A gold chart that is all zeros keeps them; there is nothing else to match.
    points = [p for p in every if p[2] != 0] or every
    gold = Counter(points)
    rows = (chart.get("result") or {}).get("result_table") or []
    spec = chart.get("vega_lite_spec") or {}
    ctype = (chart.get("chart_spec") or {}).get("type")
    if validator is None:
        valid = bool(spec)
    else:
        valid = bool(spec) and not any(True for _ in itertools.islice(validator.iter_errors(spec), 1))
    return {
        "type": ctype,
        "valid": valid,
        "family": ctype in FAMILIES[case["chart"]],
        "x": _x_matches(rows, {p[0] for p in points}, {p[0] for p in every}, unit),
        "data": _data_matches(rows, gold, bool(case["vis_obj"]["classify"]), unit),
        "rows": len(rows),
    }


def score(case: dict[str, Any], response: dict[str, Any], validator: Any) -> dict[str, Any]:
    status = response.get("status")
    if status == _PAUSED:
        return {"outcome": "asked", "chart": None}
    charts = [c for c in response.get("charts") or [] if c.get("vega_lite_spec")]
    if status != _DONE or not charts:
        return {"outcome": "failed", "chart": None}
    # Several charts can answer one question; the case is scored on its best.
    scored = [score_chart(case, c, validator) for c in charts]
    best = max(scored, key=lambda s: (s["data"], s["x"], s["family"], s["valid"]))
    best["structural"] = best["valid"] and best["family"] and best["x"]
    return {"outcome": "correct" if best["data"] else "wrong", "chart": best}


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------

def wilson(k: int, n: int, z: float = 1.959964) -> list[float] | None:
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(100 * (c - h), 1), round(100 * (c + h), 1)]


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for source in ("nvbench", "viseval"):
        mine = [r for r in rows if r["source"] == source]
        if not mine:
            continue
        answered = [r for r in mine if r["chart"]]
        n = len(mine)

        def count(prop: str, answered: list[dict[str, Any]] = answered) -> int:
            return sum(1 for r in answered if r["chart"][prop])

        correct = count("data")
        lat = sorted(r["latency_ms"] for r in mine)
        out[source] = {
            "cases": n,
            "outcomes": dict(Counter(r["outcome"] for r in mine)),
            "answered": len(answered),
            "valid_spec": count("valid"),
            "chart_family": count("family"),
            "x_field": count("x"),
            "data_match": correct,
            "structural": count("structural"),
            "data_match_pct": round(100 * correct / n, 1),
            "data_match_wilson95": wilson(correct, n),
            "structural_but_wrong_data": sum(1 for r in answered
                                             if r["chart"]["structural"] and not r["chart"]["data"]),
            "latency_ms": {"median": round(statistics.median(lat), 1),
                           "p90": round(lat[int(0.9 * (len(lat) - 1))], 1)},
        }
    return out


def _scored_part(response: dict[str, Any], max_rows: int = 2000) -> dict[str, Any]:
    """The slice of a response `score` reads: status, and per chart its type,
    specification and data. Small enough to keep for every case."""
    charts = []
    for c in response.get("charts") or []:
        table = (c.get("result") or {}).get("result_table") or []
        charts.append({"chart_spec": c.get("chart_spec"), "vega_lite_spec": c.get("vega_lite_spec"),
                       "result": {"result_table": table[:max_rows]}})
    return {"status": response.get("status"), "charts": charts}


def rescore(path: Path) -> None:
    """Re-score a finished run from its stored responses, with no planner."""
    report = json.loads(path.read_text(encoding="utf-8"))
    cases = {c["id"]: c for c in load_cases()}
    validator, origin = _vl_validator()
    for row in report["cases"]:
        verdict = score(cases[row["id"]], row["response"], validator)
        row["outcome"], row["chart"] = verdict["outcome"], verdict["chart"]
    report["summary"] = summarize(report["cases"])
    report["meta"]["rescored_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    report["meta"]["rescored_cases_sha256"] = cases_sha256()
    report["meta"]["vega_lite_schema"] = origin
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))


def _app_commit() -> str | None:
    try:
        return subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):  # not a checkout; recorded as None
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="all", choices=("all", "nvbench", "viseval"))
    ap.add_argument("--only", default=None, help="comma-separated case ids")
    ap.add_argument("--shard", default=None, help="i/n: run the i-th of n interleaved slices")
    ap.add_argument("--out", default="bench/results/external.json")
    ap.add_argument("--model", default=None, help="override AUTOVIZ_PLANNER_MODEL")
    ap.add_argument("--rescore", type=Path, default=None,
                    help="re-score a finished result file in place; runs no planner")
    args = ap.parse_args()
    if args.rescore:
        rescore(args.rescore)
        return

    cases = load_cases()
    if args.source != "all":
        cases = [c for c in cases if c["source"] == args.source]
    if args.only:
        wanted = {c.strip() for c in args.only.split(",")}
        cases = [c for c in cases if c["id"] in wanted]
    if args.shard:
        i, n = (int(v) for v in args.shard.split("/"))
        cases = cases[i - 1::n]

    validator, schema_origin = _vl_validator()
    registry = DatasetRegistry()
    ids: dict[str, str] = {}
    for c in cases:
        path = table_csv(c["db_id"], c["table"])
        if path is None:
            raise SystemExit(f"{c['id']}: no table {c['db_id']}/{c['table']} — run `external_suite check`")
        if str(path) not in ids:
            registered = register_dataset(str(path), registry)
            if "error" in registered:
                raise SystemExit(f"cannot register {path}: {registered['error']}")
            ids[str(path)] = registered["dataset_id"]
        c["_dataset_id"] = ids[str(path)]

    from autoviz.llm.client import GeminiPlanner

    planner = GeminiPlanner(args.model) if args.model else GeminiPlanner()
    agent = AgentService(planner=planner, registry=registry)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_suffix(".partial.jsonl")
    partial.write_text("", encoding="utf-8")

    rows: list[dict[str, Any]] = []
    for i, case in enumerate(cases, 1):
        started = time.perf_counter()
        try:
            response = agent.run(case["prompt"], dataset_id=case["_dataset_id"])
        except Exception as exc:  # a crash is a result, and must be recorded
            response = {"status": "failed", "errors": [f"exception: {exc}"]}
        elapsed = (time.perf_counter() - started) * 1000
        verdict = score(case, response, validator)
        row = {
            "id": case["id"], "source": case["source"], "db_id": case["db_id"],
            "table": case["table"], "prompt": case["prompt"], "gold_chart": case["chart"],
            "hardness": case["hardness"], "status": response.get("status"),
            "latency_ms": round(elapsed, 1), "outcome": verdict["outcome"], "chart": verdict["chart"],
            "plans": [c["plan"] for c in response.get("charts") or [] if c.get("plan")],
            "question": response.get("question"),
            "errors": (response.get("errors") or [])[:3],
            # What the scorer read, kept so `--rescore` can re-score without the LLM.
            "response": _scored_part(response),
        }
        rows.append(row)
        with partial.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
        ch = verdict["chart"] or {}
        flags = "".join(k[0] if ch.get(k) else "." for k in ("valid", "family", "x", "data")) if ch else ""
        print(f"[{i:>3}/{len(cases)}] {case['id']:<20} {verdict['outcome']:<9} "
              f"{elapsed / 1000:6.1f}s  {flags:<4} {case['prompt'][:48]}", flush=True)

    report = {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "app_commit": _app_commit(),
            "planner_model": args.model or os.environ.get("AUTOVIZ_PLANNER_MODEL") or "default",
            "planner_base_url": os.environ.get("AUTOVIZ_PLANNER_BASE_URL"),
            "cases_sha256": cases_sha256(),
            "source": args.source, "only": args.only, "shard": args.shard,
            "vega_lite_schema": schema_origin,
        },
        "summary": summarize(rows),
        "cases": rows,
    }
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("\n" + json.dumps(report["summary"], indent=2))
    print(f"\n[bench] wrote {out}")


if __name__ == "__main__":
    main()
