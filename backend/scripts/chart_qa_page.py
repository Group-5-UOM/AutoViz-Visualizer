"""Build a local QA page rendering every chart type through the real pipeline.

The theme and interaction layers (Docs/13 §4-5) are verified in tests and by
compiling specs through the Vega-Lite compiler, but neither of those tells you
whether the result actually *looks* right. This renders one of each into a single
page you can open and click.

    python backend/scripts/chart_qa_page.py
    -> backend/exports/_chart_qa.html
"""

import json
import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "src"))

from autoviz.services.dataset import register_dataset  # noqa: E402
from autoviz.services.orchestrator import run_pipeline  # noqa: E402
from autoviz.services.registry import DatasetRegistry  # noqa: E402
from autoviz.vega import CDN_SCRIPT_TAGS  # noqa: E402

DATA = BACKEND.parent / "test-data"

# (title, what to look for, csv, plan)
CASES = [
    (
        "Ranking bar — sorted, hover-dim",
        "Bars descend left to right; hovering one dims the rest.",
        "general-testing/titanic.csv",
        {"intent": "ranking", "group_by": ["pclass"],
         "aggregations": [{"column": "fare", "fn": "mean", "as": "avg_fare"}]},
    ),
    (
        "Grouped bar — side by side, legend filter",
        "Bars sit beside each other rather than stacking. Click a legend entry to "
        "isolate a series; click again to clear.",
        "general-testing/titanic.csv",
        {"intent": "comparison", "group_by": ["pclass", "sex"],
         "aggregations": [{"column": "fare", "fn": "mean", "as": "avg_fare"}]},
    ),
    (
        "Stacked bar — part-to-whole",
        "The same plan as above with type 'bar': a colour channel without xOffset "
        "stacks, which answers part-to-whole instead.",
        "general-testing/titanic.csv",
        {"intent": "comparison", "group_by": ["pclass", "sex"],
         "aggregations": [{"column": "fare", "fn": "mean", "as": "avg_fare"}],
         "chart": {"type": "bar", "x": "pclass", "y": "avg_fare", "color": "sex"}},
    ),
    (
        "Heatmap — two categories crossed",
        "Colour carries the measure, not a series, so the legend is a gradient and "
        "hover highlights a cell.",
        "general-testing/titanic.csv",
        {"intent": "distribution", "group_by": ["pclass", "sex"],
         "aggregations": [{"column": "fare", "fn": "mean", "as": "avg_fare"}]},
    ),
    (
        "Box plot — distribution per class",
        "Built from raw rows, not aggregates. Hover a box for its quartiles; a "
        "composite mark takes no selection params.",
        "general-testing/titanic.csv",
        {"intent": "distribution", "select": ["pclass", "fare"],
         "chart": {"type": "boxplot", "x": "pclass", "y": "fare"}},
    ),
    (
        "Trend line — temporal zoom",
        "Scroll to zoom, drag to pan. Tooltip dates read as 'Jan 01, 2014'.",
        "weather-climate/seattle-weather.csv",
        {"intent": "trend", "group_by": ["date"],
         "aggregations": [{"column": "temp_max", "fn": "mean", "as": "avg_temp"}],
         "limit": 400},
    ),
    (
        "Scatter — zoom + point rings",
        "Scroll to zoom. Overlapping points keep a white ring so they stay countable.",
        "general-testing/penguins.csv",
        {"intent": "relationship",
         "select": ["bill_length_mm", "flipper_length_mm", "species"]},
    ),
    (
        "Donut — the composition default",
        "The centre hole removes the wedge-area comparison that makes pies hard to "
        "read. Radius derives from the view, so it survives resizing.",
        "general-testing/titanic.csv",
        {"intent": "composition", "group_by": ["pclass"],
         "aggregations": [{"column": "pclass", "fn": "count", "as": "passengers"}]},
    ),
    (
        "Histogram — binned, hover-dim",
        "Tooltip shows the bin range and the count.",
        "sales-retail/diamonds.csv",
        {"intent": "distribution", "select": ["price"], "limit": 5000},
    ),
]

_PAGE = """<!doctype html>
<meta charset="utf-8">
<title>AutoViz chart QA</title>
{cdn_script_tags}
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root {{ --bg-app:#f4f5f7; --bg-surface:#fff; --border:#d9dde3; --border-subtle:#e6e9ee;
           --text-primary:#1c1f26; --text-secondary:#60636c; --text-muted:#8b909a; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:32px; background:var(--bg-app); color:var(--text-primary);
          font-family:'DM Sans',system-ui,sans-serif; }}
  h1 {{ font-size:20px; margin:0 0 4px; }}
  .sub {{ color:var(--text-secondary); font-size:14px; margin:0 0 28px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(440px,1fr)); gap:20px; }}
  .card {{ background:var(--bg-surface); border:1px solid var(--border); border-radius:14px;
           display:flex; flex-direction:column; height:400px; overflow:hidden;
           box-shadow:0 1px 2px rgba(28,31,38,.06); }}
  .card h3 {{ margin:0; padding:12px 14px 4px; font-size:13px; font-weight:600; }}
  .card p {{ margin:0; padding:0 14px 8px; font-size:12px; color:var(--text-secondary); }}
  .plot {{ flex:1; min-height:0; padding:4px 12px 10px; display:flex; align-items:stretch; }}
  .plot .vega-embed, .plot .vega-embed .chart-wrapper {{ width:100%; height:100%; }}
  .plot .vega-embed summary {{ display:none; }}
</style>
<h1>AutoViz chart QA</h1>
<p class="sub">Every chart below is a real pipeline output over the repo's test data —
same specs the app renders. Workstreams A (interaction) + B (theme), Docs/13.</p>
<div class="grid" id="grid"></div>
<script>
const CHARTS = {charts};
const grid = document.getElementById('grid');
for (const c of CHARTS) {{
  const card = document.createElement('div');
  card.className = 'card';
  card.innerHTML = `<h3></h3><p></p><div class="plot"></div>`;
  card.querySelector('h3').textContent = c.title;
  card.querySelector('p').textContent = c.note;
  grid.appendChild(card);
  vegaEmbed(card.querySelector('.plot'), c.spec, {{actions:false, renderer:'svg', tooltip:true}})
    .catch(e => {{ card.querySelector('.plot').textContent = 'render failed: ' + e.message; }});
}}
</script>
"""


def main() -> int:
    registry = DatasetRegistry()
    charts, failures = [], []

    for title, note, csv, plan in CASES:
        dataset_id = register_dataset(str(DATA / csv), registry)["dataset_id"]
        out = run_pipeline(dataset_id, {**plan, "dataset_id": dataset_id}, registry)
        if out["status"] != "ok" or not out.get("vega_lite_spec"):
            failures.append(f"{title}: {out.get('failed_step')} {out.get('errors')}")
            continue
        charts.append({"title": title, "note": note, "spec": out["vega_lite_spec"]})
        print(f"  ok   {title}  ({out['chart_spec']['type']}, {out['result']['row_count']} rows)")

    for f in failures:
        print(f"  FAIL {f}")

    dest = BACKEND / "exports" / "_chart_qa.html"
    dest.parent.mkdir(parents=True, exist_ok=True)
    page = _PAGE.replace("{cdn_script_tags}", CDN_SCRIPT_TAGS).replace(
        "{charts}", json.dumps(charts)
    )
    dest.write_text(page, encoding="utf-8")
    print(f"\n{len(charts)}/{len(CASES)} rendered -> {dest}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
