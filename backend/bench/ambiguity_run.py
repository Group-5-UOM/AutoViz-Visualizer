"""Run the labelled ambiguity suite and score it.

Run:  uv run python -m bench.ambiguity_run --detectors-only   # no LLM, CI-safe
      uv run python -m bench.ambiguity_run                    # live planner

Two questions are being asked at once, and they pull against each other:

* **recall**   — of the requests that should have been questioned, how many were?
* **over-ask** — of the requests that should have been answered, how many were
                 questioned anyway?

Either is trivial to max out alone (never ask; always ask), so neither is
reported alone. A change that lifts recall while lifting over-ask by as much has
moved friction around, not reduced ambiguity.

Three further measures guard properties that a raw ask/don't-ask count cannot see:

* **grounding violations** — options naming a column or value that does not exist
  in the dataset. Must be 0. A question offering an invented column is worse than
  no question: the user picks it and the planner then has to honour something
  meaningless.
* **bind rate** — options that `bind_answer` resolves to ``source="option"``
  rather than ``"free_text"``. An option that does not bind is a question whose
  answer gets re-guessed downstream instead of being obeyed, which is invisible
  from the outside and was the original defect in the LLM clarification path.
* **slot accuracy** — asking the right question, not merely asking.

`--detectors-only` calls the detectors directly with no agent and no network, so
it is deterministic and fast. The default mode drives the real graph through
`AgentService`, which is the only way to see what the LLM layer contributes.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bench.ambiguity_suite import CASES, DATASETS  # noqa: E402

from autoviz.agent.ambiguity import detect_ambiguities  # noqa: E402
from autoviz.schema.clarification import Ambiguity, bind_answer  # noqa: E402
from autoviz.services.dataset import (  # noqa: E402
    get_dataset_profile,
    get_dataset_schema,
    register_dataset,
)
from autoviz.services.registry import DatasetRegistry  # noqa: E402

REPO = Path(__file__).resolve().parents[2]

_PAUSED = "waiting_for_user"

# Aggregate functions and time grains an option is allowed to bind to. Anything
# else in a `resolves_to` is a fabrication, whoever wrote it.
_VALID_FNS = {"count", "sum", "mean", "median", "min", "max"}
_VALID_GRAINS = {"day", "month", "year"}


def _option_columns(amb: Ambiguity) -> set[str]:
    return {
        str(o.resolves_to["column"])
        for o in amb.options
        if isinstance(o.resolves_to.get("column"), str)
    }


def _grounding_violations(
    amb: Ambiguity, schema: list[dict[str, str]], profile: dict[str, Any]
) -> list[str]:
    """Everything in this ambiguity's options that does not exist in the dataset."""
    names = {c["name"] for c in schema}
    samples: dict[str, list[str]] = profile.get("sample_values", {}) or {}
    bad: list[str] = []
    for opt in amb.options:
        rt = opt.resolves_to
        col = rt.get("column")
        if col is not None:
            if col not in names:
                bad.append(f"column {col!r} is not in the schema")
                continue  # a value check against a phantom column is meaningless
            val = rt.get("value")
            if val is not None and str(val) not in (samples.get(str(col)) or []):
                bad.append(f"value {val!r} is not a value of {col!r}")
        elif rt.get("value") is not None:
            bad.append(f"value {rt['value']!r} is offered with no column")
        fn = rt.get("fn")
        if fn is not None and fn not in _VALID_FNS:
            bad.append(f"aggregate {fn!r} is not an allowed function")
        grain = rt.get("grain")
        if grain is not None and grain not in _VALID_GRAINS:
            bad.append(f"grain {grain!r} is not an allowed grain")
    return bad


def _binds(amb: Ambiguity) -> bool:
    """Does clicking the first option actually resolve the slot it was asked for?

    The check is deliberately made through `bind_answer` on the option's own
    label — exactly what happens when a user clicks it — rather than by
    inspecting `resolves_to` directly. A label the binder cannot match back to
    its option is a real defect even when the structure behind it is perfect.
    """
    if not amb.options:
        return False
    resolution = bind_answer(amb, amb.options[0].label)
    # A cancel option legitimately binds to {}, so an empty value is only a
    # failure when the binder also failed to recognise which option was picked.
    return resolution.source == "option"


def score(
    case: dict[str, Any],
    asked: Ambiguity | None,
    schema: list[dict[str, str]],
    profile: dict[str, Any],
) -> dict[str, Any]:
    """Return {outcome, failures[], checks{}} for one case."""
    failures: list[str] = []
    checks: dict[str, Any] = {}

    if case["expect"] == "answer":
        if asked is None:
            return {"outcome": "correct", "failures": [], "checks": checks}
        return {
            "outcome": "over_asked",
            "failures": [f"asked instead of answering: {asked.question!r}"],
            "checks": {"slot": asked.slot, "type": asked.type},
        }

    # --- an `ask` case ------------------------------------------------------
    if asked is None:
        return {"outcome": "missed", "failures": ["answered an ambiguous request"],
                "checks": checks}

    checks["slot"] = asked.slot
    checks["type"] = asked.type
    checks["origin"] = getattr(asked, "origin", "detector")

    want_slot = case.get("slot")
    checks["slot_ok"] = (want_slot is None) or (asked.slot == want_slot)
    if not checks["slot_ok"]:
        failures.append(f"asked about slot {asked.slot!r}, expected {want_slot!r}")

    must_offer = set(case.get("must_offer") or ())
    if must_offer:
        offered = _option_columns(asked)
        checks["offer_ok"] = bool(must_offer & offered)
        if not checks["offer_ok"]:
            failures.append(
                f"offered {sorted(offered) or 'no columns'}, none of {sorted(must_offer)}"
            )

    violations = _grounding_violations(asked, schema, profile)
    checks["grounding_violations"] = violations
    if violations:
        failures.append(f"ungrounded option(s): {violations}")

    checks["binds"] = _binds(asked)
    if not checks["binds"]:
        failures.append("the first option does not bind back to its slot")

    # Asking is the outcome; the sub-checks are quality of the question and are
    # reported alongside rather than folded in. A question with the wrong slot
    # still beat answering, and flattening the two hides that.
    return {"outcome": "asked", "failures": failures, "checks": checks}


def _register_all(registry: DatasetRegistry) -> dict[str, str]:
    ids: dict[str, str] = {}
    for name, rel in DATASETS.items():
        registered = register_dataset(str(REPO / rel), registry)
        if "error" in registered:
            raise SystemExit(f"cannot register {rel}: {registered['error']}")
        ids[name] = registered["dataset_id"]
    return ids


def _context(dataset_id: str, registry: DatasetRegistry) -> tuple[list[dict[str, str]], dict]:
    schema = get_dataset_schema(dataset_id, registry)
    if "error" in schema:
        raise SystemExit(f"cannot read schema for {dataset_id}: {schema['error']}")
    return schema["columns"], get_dataset_profile(dataset_id, registry)


def run_detectors_only(
    cases: list[dict[str, Any]], registry: DatasetRegistry, ids: dict[str, str]
) -> list[dict[str, Any]]:
    """The deterministic layer alone: no agent, no network, no model."""
    rows: list[dict[str, Any]] = []
    for case in cases:
        schema, profile = _context(ids[case["dataset"]], registry)
        started = time.perf_counter()
        found = detect_ambiguities(case["prompt"], schema, profile)
        elapsed = (time.perf_counter() - started) * 1000
        asked = found[0] if found else None
        verdict = score(case, asked, schema, profile)
        rows.append(
            {
                "id": case["id"],
                "dataset": case["dataset"],
                "prompt": case["prompt"],
                "expect": case["expect"],
                "reachable": case.get("reachable"),
                "latency_ms": round(elapsed, 3),
                "question": asked.question if asked else None,
                "options": [o.label for o in asked.options] if asked else [],
                "n_detected": len(found),
                **verdict,
            }
        )
    return rows


def run_live(
    cases: list[dict[str, Any]], registry: DatasetRegistry, ids: dict[str, str], model: str | None
) -> list[dict[str, Any]]:
    """The whole graph, detectors and LLM layer together.

    The ambiguity that was actually asked is captured by wrapping the functions
    the `detect_ambiguity` / `classify_intent` nodes call, rather than
    reconstructed from the wire payload: `Ambiguity.to_wire` flattens options to
    labels, and grounding and bind-rate both need the structure underneath. This
    is the same wrapped-not-replaced trick `nl_run` uses on `planner.compose`,
    and for the same reason — the evidence is gone by the time the response is
    shaped.
    """
    from autoviz.agent import nodes
    from autoviz.agent.service import AgentService
    from autoviz.llm.client import GeminiPlanner

    captured: list[Ambiguity] = []

    real_detect = nodes.detect_ambiguities

    def detect_spy(*args: Any, **kwargs: Any) -> list[Ambiguity]:
        found = real_detect(*args, **kwargs)
        captured.extend(found)
        return found

    nodes.detect_ambiguities = detect_spy  # type: ignore[assignment]

    # The LLM proposal gate does not exist until Layer 2 lands; wrap it only if
    # it is there, so this runner produces a usable baseline against today's code.
    real_ground = getattr(nodes, "ground_ambiguity", None)
    if real_ground is not None:

        def ground_spy(*args: Any, **kwargs: Any) -> Ambiguity | None:
            grounded = real_ground(*args, **kwargs)
            if grounded is not None:
                captured.append(grounded)
            return grounded

        nodes.ground_ambiguity = ground_spy  # type: ignore[assignment]

    planner = GeminiPlanner(model) if model else GeminiPlanner()
    agent = AgentService(planner=planner, registry=registry)

    rows: list[dict[str, Any]] = []
    try:
        for i, case in enumerate(cases, 1):
            schema, profile = _context(ids[case["dataset"]], registry)
            captured.clear()
            started = time.perf_counter()
            try:
                response = agent.run(case["prompt"], dataset_id=ids[case["dataset"]])
            except Exception as exc:  # a crash is a result, and must be recorded
                response = {"status": "failed", "errors": [f"exception: {exc}"]}
            elapsed = (time.perf_counter() - started) * 1000

            paused = response.get("status") == _PAUSED
            # Match the paused question back to the structured object behind it.
            # A run can detect several and surface one; only the surfaced one is
            # what the user was actually asked.
            asked = None
            if paused:
                question = response.get("question")
                asked = next(
                    (a for a in captured if a.question == question),
                    captured[0] if captured else None,
                )
            verdict = score(case, asked, schema, profile)
            if paused and asked is None:
                # Paused for a reason this suite cannot see (a cleaning question,
                # a preprocessing gate). Recorded, not silently scored as a
                # clarification it was not.
                verdict = {
                    "outcome": "paused_other",
                    "failures": [f"paused on {response.get('pause_kind')!r}, not a clarification"],
                    "checks": {},
                }
            rows.append(
                {
                    "id": case["id"],
                    "dataset": case["dataset"],
                    "prompt": case["prompt"],
                    "expect": case["expect"],
                    "reachable": case.get("reachable"),
                    "latency_ms": round(elapsed, 1),
                    "status": response.get("status"),
                    "pause_kind": response.get("pause_kind") if paused else None,
                    "question": response.get("question"),
                    "options": response.get("options") or [],
                    "n_detected": len(captured),
                    **verdict,
                }
            )
            print(f"  [{i}/{len(cases)}] {case['id']} {verdict['outcome']}", file=sys.stderr)
    finally:
        nodes.detect_ambiguities = real_detect  # type: ignore[assignment]
        if real_ground is not None:
            nodes.ground_ambiguity = real_ground  # type: ignore[assignment]
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    positives = [r for r in rows if r["expect"] == "ask"]
    negatives = [r for r in rows if r["expect"] == "answer"]
    asked = [r for r in positives if r["outcome"] == "asked"]
    over = [r for r in negatives if r["outcome"] == "over_asked"]

    def pct(n: int, d: int) -> float:
        return round(100 * n / d, 1) if d else 0.0

    def recall_for(kind: str) -> dict[str, Any]:
        subset = [r for r in positives if r.get("reachable") == kind]
        hit = [r for r in subset if r["outcome"] == "asked"]
        return {"cases": len(subset), "asked": len(hit), "recall_pct": pct(len(hit), len(subset))}

    with_offer = [r for r in asked if "offer_ok" in r["checks"]]
    violations = [v for r in rows for v in (r["checks"].get("grounding_violations") or [])]

    return {
        "cases": len(rows),
        "positives": len(positives),
        "negatives": len(negatives),
        "recall": {"asked": len(asked), "recall_pct": pct(len(asked), len(positives))},
        # Split because a detectors-only run is not answerable for the cases that
        # need meaning, and averaging the two halves hides which layer moved.
        "recall_detector_reachable": recall_for("detector"),
        "recall_llm_reachable": recall_for("llm"),
        "over_asked": len(over),
        "over_ask_pct": pct(len(over), len(negatives)),
        "missed": sum(1 for r in positives if r["outcome"] == "missed"),
        "paused_other": sum(1 for r in rows if r["outcome"] == "paused_other"),
        # Quality of the questions that were asked.
        "slot_accuracy_pct": pct(sum(1 for r in asked if r["checks"].get("slot_ok")), len(asked)),
        "offer_accuracy_pct": pct(
            sum(1 for r in with_offer if r["checks"].get("offer_ok")), len(with_offer)
        ),
        "bind_rate_pct": pct(sum(1 for r in asked if r["checks"].get("binds")), len(asked)),
        # Hard gate. Any value above zero is a released question that offers the
        # user something the dataset does not contain.
        "grounding_violations": len(violations),
        "grounding_violation_detail": violations[:20],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="comma-separated case ids")
    ap.add_argument("--detectors-only", action="store_true",
                    help="run the deterministic layer alone (no LLM, no network)")
    ap.add_argument("--out", default=None,
                    help="default: results/ambiguity[-detectors].json")
    ap.add_argument("--model", default=None, help="override AUTOVIZ_PLANNER_MODEL")
    args = ap.parse_args()

    cases = CASES
    if args.only:
        wanted = {c.strip() for c in args.only.split(",")}
        cases = [c for c in CASES if c["id"] in wanted]

    registry = DatasetRegistry()
    ids = _register_all(registry)

    mode = "detectors" if args.detectors_only else "full"
    rows = (
        run_detectors_only(cases, registry, ids)
        if args.detectors_only
        else run_live(cases, registry, ids, args.model)
    )
    summary = summarize(rows)
    payload = {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "mode": mode,
            "planner_model": args.model or "AUTOVIZ_PLANNER_MODEL default",
        },
        "summary": summary,
        "cases": rows,
    }

    out = Path(args.out or f"bench/results/ambiguity-{mode}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    s = summary
    print(f"\nmode: {mode}   cases: {s['cases']}")
    print(f"  recall            {s['recall']['asked']}/{s['positives']}  ({s['recall']['recall_pct']}%)")
    print(f"    detector-reachable  {s['recall_detector_reachable']['asked']}/"
          f"{s['recall_detector_reachable']['cases']}  "
          f"({s['recall_detector_reachable']['recall_pct']}%)")
    print(f"    llm-reachable       {s['recall_llm_reachable']['asked']}/"
          f"{s['recall_llm_reachable']['cases']}  "
          f"({s['recall_llm_reachable']['recall_pct']}%)")
    print(f"  over-ask          {s['over_asked']}/{s['negatives']}  ({s['over_ask_pct']}%)")
    print(f"  slot accuracy     {s['slot_accuracy_pct']}%")
    print(f"  offer accuracy    {s['offer_accuracy_pct']}%")
    print(f"  bind rate         {s['bind_rate_pct']}%")
    print(f"  grounding viol.   {s['grounding_violations']}")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
