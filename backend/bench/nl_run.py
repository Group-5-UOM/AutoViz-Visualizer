"""Run the frozen NL benchmark against the live planner and score it.

Run:  uv run python -m bench.nl_run [--only T01,P02] [--out results/nl.json]

Scoring is deliberately conservative about what counts as correct. A prompt has
many right plans, so a case passes on the properties every right answer shares
(columns touched, aggregate family, intent, chart family) and never on plan
equality. Three outcomes are tracked separately, because averaging them would
hide the one that matters:

* **answered correctly**  — produced an answer meeting every assertion
* **asked instead**       — paused for clarification where that was allowed
* **wrong**               — answered, but the answer fails an assertion

A confident wrong answer is the expensive failure for a tool like this, so
`wrong` is reported on its own rather than folded into an accuracy figure.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bench.nl_suite import CASES, DATASETS  # noqa: E402

from autoviz.agent.service import AgentService  # noqa: E402
from autoviz.schema.allowlists import DATETIME_DERIVE_FNS  # noqa: E402
from autoviz.services.dataset import register_dataset  # noqa: E402
from autoviz.services.registry import DatasetRegistry  # noqa: E402

REPO = Path(__file__).resolve().parents[2]

# How a run ends. `compose_response` reports "completed" when at least one
# worker produced a usable result and "failed" otherwise; a paused run reports
# "waiting_for_user" from `_shape_pending`. Per-chart statuses (ok / partial /
# error) live one level down, on each entry of `charts`.
_PAUSED = "waiting_for_user"
_DONE = "completed"


def _plans_of(response: dict[str, Any]) -> list[dict[str, Any]]:
    return [c["plan"] for c in response.get("charts") or [] if c.get("plan")]


def _columns_touched(plan: dict[str, Any]) -> set[str]:
    cols: set[str] = set()
    cols |= set(plan.get("select") or [])
    cols |= {c for c in plan.get("group_by") or []}
    cols |= {f.get("column") for f in plan.get("filters") or []}
    cols |= {a.get("column") for a in plan.get("aggregations") or []}
    cols |= {d.get("from") for d in plan.get("derive") or []}
    chart = plan.get("chart") or {}
    cols |= {chart.get(k) for k in ("x", "y", "color")}
    # A derived column stands for the column it came from, which is already
    # added above; the derived *name* is not a dataset column and must not be
    # matched against one.
    return {c for c in cols if isinstance(c, str) and c}


def _aggs_of(plan: dict[str, Any]) -> set[str]:
    return {a.get("fn") for a in plan.get("aggregations") or [] if a.get("fn")}


def _chart_types(response: dict[str, Any]) -> set[str]:
    out = set()
    for c in response.get("charts") or []:
        spec = c.get("chart_spec") or {}
        if spec.get("type"):
            out.add(spec["type"])
    return out


def score(case: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    """Return {outcome, failures[]} for one case against one response."""
    expect = case["expect"]
    status = response.get("status")
    failures: list[str] = []

    paused = status == _PAUSED
    answered = status == _DONE and bool(response.get("charts"))

    # --- cases where asking, or declining, is the correct behaviour ---------
    if expect == "clarification":
        if paused:
            return {"outcome": "asked", "failures": []}
        return {
            "outcome": "wrong",
            "failures": [f"answered an underspecified request (status={status})"],
        }

    if expect in ("refusal_or_clarification", "clarification_or_analysis"):
        if paused:
            return {"outcome": "asked", "failures": []}
        if expect == "refusal_or_clarification":
            if status == "failed" or not response.get("charts"):
                return {"outcome": "declined", "failures": []}
            return {
                "outcome": "wrong",
                "failures": ["produced a chart for an out-of-scope request"],
            }
        # clarification_or_analysis: answering is allowed, but the answer still
        # has to be about the right columns.
        if not answered:
            return {"outcome": "declined", "failures": []}

    # --- from here the case had to produce a real answer --------------------
    if paused:
        # Pausing on an answerable request is its own outcome. It is not a wrong
        # answer — nothing false was asserted — but it is not the answer either,
        # and folding it into "failed" hides the difference between a system
        # that guesses badly and one that interrupts too readily. Over-asking is
        # a usability defect with a usability fix; both need their own count.
        return {
            "outcome": "over_asked",
            "failures": [f"asked instead of answering: {response.get('question')!r}"],
        }
    if not answered:
        return {
            "outcome": "failed",
            "failures": [f"no chart produced (status={status})", *response.get("errors", [])],
        }

    plans = _plans_of(response)
    if not plans:
        return {"outcome": "failed", "failures": ["answered with no plan attached"]}

    touched: set[str] = set()
    aggs: set[str] = set()
    intents: set[str] = set()
    has_filter = has_limit = False
    truncating = False
    for p in plans:
        touched |= _columns_touched(p)
        aggs |= _aggs_of(p)
        if p.get("intent"):
            intents.add(p["intent"])
        has_filter = has_filter or bool(p.get("filters"))
        has_limit = has_limit or p.get("limit") is not None
        truncating = truncating or any(
            d.get("fn") in DATETIME_DERIVE_FNS for d in p.get("derive") or []
        )

    missing = set(case.get("must_columns") or ()) - touched
    if missing:
        failures.append(f"did not touch required column(s): {sorted(missing)}")

    # Each group is a set of interchangeable spellings of the same fact —
    # titanic carries `pclass` and `class`, `survived` and `alive`, `embarked`
    # and `embark_town`. Requiring a particular one would score a correct answer
    # as wrong, so the assertion is "hit at least one member of every group".
    for group in case.get("any_of") or ():
        if not (set(group) & touched):
            failures.append(f"touched none of {sorted(group)}")

    forbidden = set(case.get("forbid_columns") or ()) & touched
    if forbidden:
        failures.append(f"touched forbidden column(s): {sorted(forbidden)}")

    want_agg = set(case.get("agg") or ())
    if want_agg and not (want_agg & aggs):
        failures.append(f"used {sorted(aggs) or 'no aggregate'}, expected one of {sorted(want_agg)}")

    want_intent = set(case.get("intent") or ())
    if want_intent and not (want_intent & intents):
        failures.append(f"intent {sorted(intents)} not in {sorted(want_intent)}")

    fam = set(case.get("chart_family") or ())
    produced_types = _chart_types(response)
    if fam and produced_types and not (fam & produced_types):
        failures.append(f"chart {sorted(produced_types)} not in {sorted(fam)}")

    if case.get("needs_filter") and not has_filter:
        failures.append("the request named a subset but the plan filtered nothing")
    if case.get("needs_limit") and not has_limit:
        failures.append("the request asked for a top-N but the plan set no limit")
    if case.get("prefer_truncating_derive") and not truncating:
        failures.append(
            "a multi-year trend without a truncating derive collapses years together"
        )
    if case.get("multi_task") and len(plans) < case["multi_task"]:
        failures.append(f"expected {case['multi_task']} tasks, produced {len(plans)}")

    return {"outcome": "correct" if not failures else "wrong", "failures": failures}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="comma-separated case ids")
    ap.add_argument("--out", default="bench/results/nl.json")
    ap.add_argument("--model", default=None, help="override AUTOVIZ_PLANNER_MODEL")
    args = ap.parse_args()

    cases = CASES
    if args.only:
        wanted = {c.strip() for c in args.only.split(",")}
        cases = [c for c in CASES if c["id"] in wanted]

    registry = DatasetRegistry()
    ids: dict[str, str] = {}
    for name, rel in DATASETS.items():
        registered = register_dataset(str(REPO / rel), registry)
        if "error" in registered:
            raise SystemExit(f"cannot register {rel}: {registered['error']}")
        ids[name] = registered["dataset_id"]

    planner = None
    if args.model:
        from autoviz.llm.client import GeminiPlanner

        planner = GeminiPlanner(args.model)
    agent = AgentService(planner=planner, registry=registry)

    rows: list[dict[str, Any]] = []
    for i, case in enumerate(cases, 1):
        started = time.perf_counter()
        try:
            response = agent.run(case["prompt"], dataset_id=ids[case["dataset"]])
        except Exception as exc:  # a crash is a result, and must be recorded
            response = {"status": "failed", "errors": [f"exception: {exc}"]}
        elapsed = (time.perf_counter() - started) * 1000
        verdict = score(case, response)
        rows.append(
            {
                "id": case["id"],
                "dataset": case["dataset"],
                "prompt": case["prompt"],
                "expect": case["expect"],
                "status": response.get("status"),
                "latency_ms": round(elapsed, 1),
                "outcome": verdict["outcome"],
                "failures": verdict["failures"],
                "plans": _plans_of(response),
                "chart_types": sorted(_chart_types(response)),
                "question": response.get("question"),
                "errors": response.get("errors", [])[:3],
            }
        )
        print(
            f"[{i:>2}/{len(cases)}] {case['id']:<4} {verdict['outcome']:<9} "
            f"{elapsed / 1000:6.1f}s  {case['prompt'][:52]}",
            flush=True,
        )
        if verdict["failures"]:
            for f in verdict["failures"]:
                print(f"           ! {f}", flush=True)

    counts: dict[str, int] = {}
    for r in rows:
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
    latencies = sorted(r["latency_ms"] for r in rows)
    # "Acceptable" = nothing false was told to the user: it answered correctly,
    # or it asked, or it declined. `over_asked` and `wrong` are both excluded,
    # for opposite reasons, and both are reported on their own below.
    ok = counts.get("correct", 0) + counts.get("asked", 0) + counts.get("declined", 0)

    def pct(n: int) -> float:
        return round(100 * n / len(rows), 1) if rows else 0.0

    summary = {
        "cases": len(rows),
        "outcomes": counts,
        "acceptable": ok,
        "acceptable_pct": pct(ok),
        "over_asked": counts.get("over_asked", 0),
        "over_asked_pct": pct(counts.get("over_asked", 0)),
        "wrong": counts.get("wrong", 0),
        "wrong_pct": pct(counts.get("wrong", 0)),
        "latency_ms": {
            "median": round(statistics.median(latencies), 1) if latencies else None,
            "min": latencies[0] if latencies else None,
            "max": latencies[-1] if latencies else None,
            "p90": round(latencies[int(0.9 * (len(latencies) - 1))], 1) if latencies else None,
        },
    }
    report = {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "planner_model": args.model or "AUTOVIZ_PLANNER_MODEL default",
        },
        "summary": summary,
        "cases": rows,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("\n" + json.dumps(summary, indent=2))
    print(f"\n[bench] wrote {out}")


if __name__ == "__main__":
    main()
