"""Chart quality, measured three ways.

"Quality" is not one number, so this does not report one. A chart can be the
wrong *type* for the question, a valid type whose *spec* is malformed, or a
valid spec that is *illegible* — twelve pie slices, forty scatter series. Those
are three different defects with three different fixes, so they are scored
separately:

1. **Type accuracy** — does the rule-based recommender pick a chart from the
   family the question calls for, over a labelled matrix of result shapes and
   intents?
2. **Spec validity** — does every generated spec validate against the *real*
   Vega-Lite v6 JSON schema, not merely against our own structural checks? The
   schema ships in `frontend/node_modules`, so this is the renderer's own
   contract rather than a restatement of it.
3. **Legibility guards** — do the ceilings that keep a chart readable actually
   fire? A pie with 40 slices is a valid spec and a useless chart.

Run:  uv run python -m bench.chart_quality [--out results/chart.json]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoviz.schema.allowlists import (  # noqa: E402
    CHART_TYPES,
    MAX_SERIES_ADJACENT,
    MAX_SERIES_ALL_PAIRS,
)
from autoviz.services.charts import generate_chart, recommend_chart_type  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
VL_SCHEMA = REPO / "frontend/node_modules/vega-lite/build/vega-lite-schema.json"


def _schema(*cols: tuple[str, str]) -> list[dict[str, str]]:
    return [{"name": n, "type": t} for n, t in cols]


# (label, result_schema, intent, acceptable chart types)
#
# "Acceptable" is a family, not a single answer: a ranking over one category is
# a bar chart, but a donut is not *wrong* for a part-to-whole reading of the
# same table. The cases where only one answer is defensible list only one.
CASES: list[tuple[str, list[dict[str, str]], str, set[str]]] = [
    # --- time -----------------------------------------------------------
    ("trend over time", _schema(("month", "datetime"), ("total", "number")), "trend", {"line"}),
    (
        "trend over time, split by series",
        _schema(("month", "datetime"), ("total", "number"), ("region", "string")),
        "trend",
        {"line"},
    ),
    (
        "trend over an ordered category",
        _schema(("quarter_label", "string"), ("total", "number")),
        "trend",
        {"line", "bar"},
    ),
    # --- ranking / comparison -------------------------------------------
    (
        "ranking over one category",
        _schema(("product", "string"), ("revenue", "number")),
        "ranking",
        {"bar"},
    ),
    (
        "comparison over one category",
        _schema(("region", "string"), ("revenue", "number")),
        "comparison",
        {"bar"},
    ),
    (
        "comparison across two categories",
        _schema(("region", "string"), ("channel", "string"), ("revenue", "number")),
        "comparison",
        {"grouped_bar", "heatmap"},
    ),
    # --- composition -----------------------------------------------------
    (
        "part-to-whole, few categories",
        _schema(("channel", "string"), ("share", "number")),
        "composition",
        {"donut", "pie", "bar"},
    ),
    # --- relationship ----------------------------------------------------
    (
        "two measures",
        _schema(("total_bill", "number"), ("tip", "number")),
        "relationship",
        {"scatter"},
    ),
    (
        "two measures, coloured by class",
        _schema(("sepal_length", "number"), ("sepal_width", "number"), ("species", "string")),
        "relationship",
        {"scatter"},
    ),
    (
        "two categories crossed with a measure",
        _schema(("day", "string"), ("time", "string"), ("avg_tip", "number")),
        "relationship",
        {"heatmap", "grouped_bar"},
    ),
    # --- distribution ----------------------------------------------------
    (
        "one measure, no dimension",
        _schema(("age", "number"),),
        "distribution",
        {"histogram"},
    ),
    (
        "counts per category",
        _schema(("weather", "string"), ("days", "number")),
        "distribution",
        {"bar", "histogram"},
    ),
    (
        "measure across two categories",
        _schema(("class", "string"), ("sex", "string"), ("fare", "number")),
        "distribution",
        {"heatmap", "grouped_bar", "bar"},
    ),
    # --- degenerate inputs the recommender has to refuse -----------------
    (
        "no measure to plot",
        _schema(("region", "string"), ("channel", "string")),
        "comparison",
        set(),  # empty = must refuse
    ),
]


def score_types() -> dict[str, Any]:
    rows = []
    for label, schema, intent, acceptable in CASES:
        got = recommend_chart_type(schema, intent)
        if not acceptable:
            ok = "error" in got
            rows.append(
                {
                    "case": label,
                    "intent": intent,
                    "expected": "refusal",
                    "got": got.get("error_code", got.get("chart_type")),
                    "pass": ok,
                }
            )
            continue
        chart = got.get("chart_type")
        rows.append(
            {
                "case": label,
                "intent": intent,
                "expected": sorted(acceptable),
                "got": chart,
                "pass": chart in acceptable,
                "rationale": got.get("rationale"),
            }
        )
    passed = sum(1 for r in rows if r["pass"])
    return {
        "cases": len(rows),
        "passed": passed,
        "accuracy_pct": round(100 * passed / len(rows), 1),
        "detail": rows,
    }


def _sample_rows(chart_type: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """A small table and a chart spec that the type can legitimately draw."""
    cats = ["North", "South", "East", "West"]
    if chart_type in ("scatter",):
        rows = [{"x_val": i * 1.5, "y_val": i * 2.25} for i in range(20)]
        return rows, {"type": chart_type, "x": "x_val", "y": "y_val"}
    if chart_type == "histogram":
        rows = [{"age": float(i % 60)} for i in range(60)]
        return rows, {"type": chart_type, "x": "age"}
    if chart_type == "line":
        rows = [{"month": f"2026-{m:02d}-01T00:00:00", "total": m * 10.0} for m in range(1, 13)]
        return rows, {
            "type": chart_type,
            "x": "month",
            "y": "total",
            "column_types": {"month": "datetime", "total": "number"},
        }
    if chart_type in ("heatmap", "grouped_bar"):
        rows = [
            {"region": r, "channel": c, "revenue": (i + 1) * 100.0}
            for i, (r, c) in enumerate((r, c) for r in cats[:3] for c in ("Online", "Retail"))
        ]
        return rows, {
            "type": chart_type,
            "x": "region",
            "y": "channel" if chart_type == "heatmap" else "revenue",
            "color": "revenue" if chart_type == "heatmap" else "channel",
        }
    rows = [{"region": r, "revenue": (i + 1) * 250.0} for i, r in enumerate(cats)]
    return rows, {"type": chart_type, "x": "region", "y": "revenue"}


def score_specs() -> dict[str, Any]:
    """Every chart type, validated against the renderer's own JSON schema."""
    try:
        import jsonschema
    except ImportError:
        return {"skipped": "jsonschema is not installed"}
    if not VL_SCHEMA.exists():
        return {"skipped": f"Vega-Lite schema not found at {VL_SCHEMA}"}

    schema = json.loads(VL_SCHEMA.read_text(encoding="utf-8"))
    validator = jsonschema.Draft7Validator(schema)

    rows = []
    for chart_type in sorted(CHART_TYPES):
        data, spec = _sample_rows(chart_type)
        built = generate_chart(data, dict(spec))
        entry: dict[str, Any] = {
            "chart_type": chart_type,
            "structurally_valid": bool(built.get("valid")),
            "warnings": built.get("warnings", []),
        }
        vega_spec = built.get("vega_lite_spec")
        if not vega_spec:
            entry["schema_valid"] = False
            entry["schema_errors"] = ["no spec produced"]
        else:
            errors = sorted(
                validator.iter_errors(vega_spec), key=lambda e: list(e.absolute_path)
            )
            entry["schema_valid"] = not errors
            entry["schema_errors"] = [
                f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message[:160]}"
                for e in errors[:3]
            ]
        rows.append(entry)

    valid = sum(1 for r in rows if r["schema_valid"])
    return {
        "chart_types": len(rows),
        "schema_valid": valid,
        "schema_valid_pct": round(100 * valid / len(rows), 1),
        "vega_lite_schema": str(VL_SCHEMA.relative_to(REPO)),
        "detail": rows,
    }


def score_legibility() -> dict[str, Any]:
    """The ceilings that stop a technically-valid chart being unreadable."""
    rows = []

    # Adjacent forms (bar/line) carry up to MAX_SERIES_ADJACENT colour series;
    # all-pairs forms (scatter) far fewer, because any two hues can end up next
    # to each other.
    many = MAX_SERIES_ADJACENT + 4
    data = [
        {"x_val": float(i), "y_val": float(i * 2), "series": f"S{i % many}"}
        for i in range(many * 3)
    ]
    built = generate_chart(
        data, {"type": "scatter", "x": "x_val", "y": "y_val", "color": "series"}
    )
    rows.append(
        {
            "guard": f"scatter colour series > {MAX_SERIES_ALL_PAIRS}",
            "series": many,
            "warned": bool(built.get("warnings")),
            "detail": (built.get("warnings") or [None])[0],
        }
    )

    built = generate_chart(
        [{"cat": f"C{i}", "val": float(i + 1)} for i in range(40)],
        {"type": "pie", "x": "cat", "y": "val"},
    )
    rows.append(
        {
            "guard": "pie with 40 categories",
            "series": 40,
            "warned": bool(built.get("warnings")),
            "detail": (built.get("warnings") or [None])[0],
        }
    )

    # An empty result is the known bug worth measuring rather than asserting:
    # a zero-row table has historically still produced a "valid" chart.
    built = generate_chart([], {"type": "bar", "x": "region", "y": "revenue"})
    told = (
        bool(built.get("notices"))
        or bool(built.get("warnings"))
        or not built.get("valid")
    )
    rows.append(
        {
            "guard": "empty result table",
            "series": 0,
            "warned": told,
            "detail": (
                (built.get("notices") or [{}])[0].get("note")
                or (built.get("warnings") or [None])[0]
                or f"valid={built.get('valid')}"
            ),
        }
    )

    fired = sum(1 for r in rows if r["warned"])
    return {
        "guards": len(rows),
        "fired": fired,
        "fired_pct": round(100 * fired / len(rows), 1),
        "detail": rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="bench/results/chart_quality.json")
    args = ap.parse_args()

    report = {
        "meta": {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S")},
        "type_accuracy": score_types(),
        "spec_validity": score_specs(),
        "legibility": score_legibility(),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    ta, sv, lg = report["type_accuracy"], report["spec_validity"], report["legibility"]
    print(f"type accuracy   {ta['passed']}/{ta['cases']}  ({ta['accuracy_pct']}%)")
    for r in ta["detail"]:
        if not r["pass"]:
            print(f"  MISS  {r['case']}: got {r['got']}, expected {r['expected']}")
    if "skipped" in sv:
        print(f"spec validity   SKIPPED: {sv['skipped']}")
    else:
        print(f"spec validity   {sv['schema_valid']}/{sv['chart_types']}  ({sv['schema_valid_pct']}%)")
        for r in sv["detail"]:
            if not r["schema_valid"]:
                print(f"  INVALID  {r['chart_type']}: {r['schema_errors']}")
    print(f"legibility      {lg['fired']}/{lg['guards']} guards fired")
    for r in lg["detail"]:
        if not r["warned"]:
            print(f"  SILENT  {r['guard']}")
    print(f"\n[bench] wrote {out}")


if __name__ == "__main__":
    main()
