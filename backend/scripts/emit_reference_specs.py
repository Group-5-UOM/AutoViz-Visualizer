"""Emit one generated spec per chart type, for the renderer verification harness.

Python tests can assert a spec's *structure*; only the real Vega-Lite compiler
can tell you the spec renders, and only the scenegraph can tell you it renders
the thing you meant. Two bugs got through structural tests and were caught this
way (Docs/13 §5): single-series charts silently ignoring the palette, and
selection params throwing on composite marks.

    python backend/scripts/emit_reference_specs.py
    -> backend/exports/_reference_specs.json   (consumed by frontend/scripts/verify-specs.mjs)
"""

import json
import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "src"))

from autoviz.services.charts import generate_chart  # noqa: E402

_GRID = [
    {"cls": cls, "grp": grp, "n": float(i * 3 + 1)}
    for i, (cls, grp) in enumerate((c, g) for c in "abc" for g in "xyz")
]
_RAW = [
    {"cls": cls, "v": float(i) + (0 if cls == "a" else 6)}
    for cls in ("a", "b")
    for i in range(12)
]
_PARTS = [
    {"region": r, "revenue": v}
    for r, v in (("north", 300.0), ("south", 1200.0), ("east", 700.0))
]
_XY = [{"a": float(i), "b": float(i * i % 7), "g": "g%d" % (i % 3)} for i in range(20)]
_TIME = [{"d": f"2024-{m:02d}-01", "v": float(m * 2 % 7)} for m in range(1, 13)]
_NUM = [{"price": float(p)} for p in (100, 120, 130, 250, 260, 270, 350, 355, 500)]

# name -> (rows, chart_spec). One per chart type, plus the pairs whose difference
# is behavioural rather than structural (grouped vs stacked, donut vs pie).
CASES: dict[str, tuple[list[dict], dict]] = {
    "bar": (_PARTS, {"type": "bar", "x": "region", "y": "revenue"}),
    "bar_ranking": (
        _PARTS,
        {"type": "bar", "x": "region", "y": "revenue", "intent": "ranking"},
    ),
    "stacked_bar": (_GRID, {"type": "bar", "x": "cls", "y": "n", "color": "grp"}),
    "grouped_bar": (_GRID, {"type": "grouped_bar", "x": "cls", "y": "n", "color": "grp"}),
    "line": (
        _TIME,
        {"type": "line", "x": "d", "y": "v", "column_types": {"d": "datetime", "v": "number"}},
    ),
    "line_color": (
        [{"m": m, "v": float(m * (2 if s == "web" else 3)), "s": s}
         for s in ("web", "store") for m in range(1, 7)],
        {"type": "line", "x": "m", "y": "v", "color": "s"},
    ),
    "area": (_TIME, {"type": "area", "x": "d", "y": "v",
                     "column_types": {"d": "datetime", "v": "number"}}),
    "scatter": (_XY, {"type": "scatter", "x": "a", "y": "b"}),
    "scatter_color": (_XY, {"type": "scatter", "x": "a", "y": "b", "color": "g"}),
    "histogram": (_NUM, {"type": "histogram", "x": "price"}),
    "pie": (_PARTS, {"type": "pie", "x": "region", "y": "revenue"}),
    "donut": (_PARTS, {"type": "donut", "x": "region", "y": "revenue"}),
    "heatmap": (_GRID, {"type": "heatmap", "x": "cls", "y": "grp", "color": "n"}),
    "boxplot": (_RAW, {"type": "boxplot", "x": "cls", "y": "v"}),
    # --- awkward data --------------------------------------------------------
    # Every case above is well-formed: several rows, all populated, all
    # positive. Real results are not, and three defects lived in the gap. They
    # were all invisible to structural tests — the specs were valid, and only
    # the scenegraph showed a blank panel or two full-height bars standing in
    # for an empty answer. See tests/test_chart_edge_data.py.
    "edge_line_one_point": (
        [{"d": "2024-01-01", "v": 5.0}],
        {"type": "line", "x": "d", "y": "v",
         "column_types": {"d": "datetime", "v": "number"}},
    ),
    "edge_bar_all_null": (
        [{"region": "north", "revenue": None}, {"region": "south", "revenue": None}],
        {"type": "bar", "x": "region", "y": "revenue"},
    ),
    "edge_bar_some_null": (
        [{"region": "north", "revenue": 300.0},
         {"region": "south", "revenue": None},
         {"region": "east", "revenue": 900.0}],
        {"type": "bar", "x": "region", "y": "revenue"},
    ),
}


def main() -> int:
    specs, failures = {}, []
    for name, (rows, chart_spec) in CASES.items():
        out = generate_chart(rows, chart_spec)
        if not out["valid"]:
            failures.append(f"{name}: {out['warnings']}")
            continue
        specs[name] = out["vega_lite_spec"]

    for f in failures:
        print(f"  FAIL {f}")

    dest = BACKEND / "exports" / "_reference_specs.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(specs, indent=2), encoding="utf-8")
    print(f"{len(specs)}/{len(CASES)} specs -> {dest}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
