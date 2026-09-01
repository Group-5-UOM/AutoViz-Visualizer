"""Turn the benchmark JSON into the Markdown tables `Docs/24` publishes.

Generated rather than transcribed, so the document cannot drift from the run
that produced it. Re-run after any benchmark and paste, or redirect straight
into the doc's tables section.

Run:  uv run python -m bench.report [--perf results/perf.json] [--nl ...] [--chart ...]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: str) -> dict[str, Any] | None:
    """Results for one benchmark, or None if it has not been run yet.

    A missing *or* unreadable file is the same situation — no results — and it
    must not stop the other sections rendering.
    """
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None


def _n(value: Any) -> str:
    if value is None:
        return "—"
    # Before the int branch: bool is an int in Python, and "1" is not what a
    # validity column should say.
    if isinstance(value, bool):
        return "yes" if value else "**no**"
    if isinstance(value, float):
        return f"{value:,.1f}" if value >= 100 else f"{value:,.2f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |"]
    out.append("|" + "|".join("---" for _ in headers) + "|")
    for r in rows:
        out.append("| " + " | ".join(_n(c) for c in r) + " |")
    return "\n".join(out)


def perf_tables(d: dict[str, Any]) -> str:
    parts: list[str] = []
    m = d["meta"]
    parts.append(
        f"*Measured {m['generated_at']} on {m['platform']}, {m['cpu_count']} logical "
        f"cores, Python {m['python']}, DuckDB {m['duckdb']}, pandas {m['pandas']}. "
        f"Peak resident set for the whole run: {m.get('peak_rss_mib')} MiB.*"
    )

    parts.append("\n### Ingest — file on disk to queryable dataset\n")
    rows = []
    for r in d["ingest"]:
        if r.get("refused"):
            rows.append([f"{r['rows']:,}", r["csv_mib"], "—", "—", "—",
                         f"**refused** ({r['error_code']})"])
            continue
        rows.append([
            f"{r['rows']:,}", r["csv_mib"], r["frame_mib"],
            r["read_table"]["median_ms"], r["build_record_profile"]["median_ms"],
            r["total_median_ms"],
        ])
    parts.append(_table(
        ["Rows", "CSV MiB", "In RAM MiB", "Read ms", "Profile ms", "Total ms"], rows
    ))

    parts.append("\n### Query latency by plan shape (median ms, `execute_analysis`)\n")
    scales = sorted({r["rows"] for r in d["query"]})
    shapes: list[str] = []
    for r in d["query"]:
        if r["shape"] not in shapes:
            shapes.append(r["shape"])
    rows = []
    for sh in shapes:
        entries = {r["rows"]: r for r in d["query"] if r["shape"] == sh}
        label = next((e.get("label", sh) for e in entries.values() if e.get("label")), sh)
        row: list[Any] = [label]
        for s in scales:
            e = entries.get(s)
            row.append("err" if not e or "error" in e else e["execute"]["median_ms"])
        biggest = entries.get(scales[-1])
        row.append(f"{biggest['result_rows']:,}" if biggest and "error" not in biggest else "—")
        rows.append(row)
    parts.append(_table(
        ["Plan shape", *(f"{s:,}" for s in scales), "Rows out (max scale)"], rows
    ))

    if d.get("ab_scan_source"):
        parts.append("\n### The scan-source change, on `execute_analysis` itself\n")
        rows = [
            [f"{r['rows']:,}", r["shape"], r["pandas"]["median_ms"],
             r["arrow"]["median_ms"], f"{r['speedup_x']}x"]
            for r in d["ab_scan_source"]
        ]
        parts.append(_table(
            ["Rows", "Shape", "pandas scan ms", "Arrow scan ms", "Speed-up"], rows
        ))

    parts.append("\n### Where a query's time goes\n")
    rows = [
        [f"{r['rows']:,}", r["connect_ms"], r["pandas"]["register_ms"],
         r["arrow"]["register_ms"], r["arrow"]["query_ms"], r["pandas_to_arrow_once_ms"]]
        for r in d["overhead"]
    ]
    parts.append(_table(
        ["Rows", "New connection ms", "Expose frame (pandas) ms",
         "Expose frame (Arrow) ms", "Query ms", "One-off conversion ms"], rows
    ))

    parts.append("\n### Memory\n")
    rows = [
        [f"{r['rows']:,}", r["frame_mib"], r["rss_delta_arrow_mib"], r["arrow_logical_mib"]]
        for r in d["memory"]
    ]
    parts.append(_table(
        ["Rows", "Frame MiB", "Added RSS for the Arrow view MiB", "Its logical size MiB"], rows
    ))

    parts.append("\n### Delivering the result (`sanitize_records` + JSON)\n")
    rows = [
        [f"{r['result_rows']:,}", r["columns"], f"{r['cells']:,}",
         r["sanitize"]["median_ms"], r["us_per_cell"], r["json_mib"]]
        for r in d["result_delivery"]
    ]
    parts.append(_table(
        ["Rows out", "Cols", "Cells", "Serialize ms", "µs/cell", "Payload MiB"], rows
    ))

    parts.append("\n### Chart construction\n")
    rows = [
        [f"{r['result_rows']:,}", r["recommend"]["median_ms"],
         r["generate_chart"]["median_ms"], f"{r['spec_bytes'] / 1024:,.0f} KiB", r["spec_valid"]]
        for r in d["chart"]
    ]
    parts.append(_table(
        ["Rows plotted", "Recommend ms", "Build spec ms", "Spec size", "Valid"], rows
    ))

    parts.append("\n### End to end, no LLM (`run_pipeline`)\n")
    rows = [
        [f"{r['rows']:,}", r["shape"], r["chart_type"], r["pipeline"]["median_ms"], r["status"]]
        for r in d["pipeline"]
    ]
    parts.append(_table(["Rows", "Shape", "Chart", "Total ms", "Status"], rows))

    parts.append("\n### Join headroom — engine only, **not a shipped capability**\n")
    rows = [
        [f"{r['rows']:,}", f"{r['dim_rows']:,}", r["join"], r["duckdb"]["median_ms"]]
        for r in d["join_headroom"]
    ]
    parts.append(_table(["Fact rows", "Dim rows", "Case", "DuckDB ms"], rows))

    lim = d["limits"]
    parts.append("\n### Shipped ceilings\n")
    parts.append(_table(
        ["Ceiling", "Value", "Where it bites on this 11-column table"],
        [
            ["Upload size", f"{lim['max_file_mib']} MiB",
             f"~{lim['rows_at_file_limit']:,} rows ({lim['bench_bytes_per_row']} B/row)"],
            ["Rows per dataset", f"{lim['max_rows']:,}", "after the byte ceiling, so rarely first"],
            ["Columns", f"{lim['max_columns']:,}", "—"],
            ["Rows returned", f"{lim['hard_row_ceiling']:,}", "caps any single result"],
            ["Query time", f"{lim['execution_timeout_s']:g} s", "watchdog interrupts the query"],
            ["Engine memory", lim["duckdb_memory_limit"], f"threads={lim['duckdb_threads']}"],
        ],
    ))
    return "\n".join(parts)


def nl_tables(d: dict[str, Any]) -> str:
    s = d["summary"]
    parts = [
        f"*{s['cases']} frozen prompts, planner `{d['meta']['planner_model']}`, "
        f"run {d['meta']['generated_at']}.*\n"
    ]
    parts.append(_table(
        ["Outcome", "Cases", "Share", "Meaning"],
        [
            ["Answered correctly", s["outcomes"].get("correct", 0),
             f"{100 * s['outcomes'].get('correct', 0) / s['cases']:.1f}%",
             "met every assertion for that prompt"],
            ["Asked a clarifying question", s["outcomes"].get("asked", 0),
             f"{100 * s['outcomes'].get('asked', 0) / s['cases']:.1f}%",
             "paused where asking was the right move"],
            ["Declined", s["outcomes"].get("declined", 0),
             f"{100 * s['outcomes'].get('declined', 0) / s['cases']:.1f}%",
             "refused an out-of-scope request"],
            ["**Over-asked**", s.get("over_asked", 0), f"{s.get('over_asked_pct', 0)}%",
             "paused on a request it could have answered"],
            ["**Wrong**", s["wrong"], f"{s['wrong_pct']}%",
             "answered, and the answer was not the question asked"],
        ],
    ))
    lat = s["latency_ms"]
    parts.append(
        f"\nEnd-to-end latency including the planner LLM: median "
        f"**{lat['median'] / 1000:.1f} s**, p90 {lat['p90'] / 1000:.1f} s, "
        f"max {lat['max'] / 1000:.1f} s."
    )
    if s.get("answers_composed"):
        checked = s.get("answers_checked", s["answers_composed"])
        parts.append(
            f"\n**Answer grounding:** {s['answers_composed']} answers were composed by the "
            f"planner, of which **{checked}** described a result small enough to verify "
            f"(the rest exceeded `MAX_GROUNDABLE_CELLS`). Of those, "
            f"**{s['answers_ungrounded']} ({s['ungrounded_pct']}%)** asserted a figure with no "
            "source in the results and were replaced by the deterministic summary.\n\n"
            "The false-positive side is the one to watch: a check that discards *correct* "
            "answers is worse than no check, because the damage is invisible to the user. "
            "An earlier version of this module flagged 3 of 32 — all three wrongly."
        )
    bad = [c for c in d["cases"] if c["outcome"] in ("wrong", "over_asked")]
    if bad:
        parts.append("\n**Every case that did not pass:**\n")
        parts.append(_table(
            ["Case", "Prompt", "Outcome", "What happened"],
            [[c["id"], c["prompt"], c["outcome"], (c["failures"] or ["—"])[0]] for c in bad],
        ))
    return "\n".join(parts)


def chart_tables(d: dict[str, Any]) -> str:
    ta, sv, lg = d["type_accuracy"], d["spec_validity"], d["legibility"]
    parts = [_table(
        ["Measure", "Result", "What it checks"],
        [
            ["Chart-type accuracy", f"{ta['passed']}/{ta['cases']} ({ta['accuracy_pct']}%)",
             "recommender picks a chart from the family the question calls for"],
            ["Spec validity",
             "skipped" if "skipped" in sv
             else f"{sv['schema_valid']}/{sv['chart_types']} ({sv['schema_valid_pct']}%)",
             "every chart type validates against the real Vega-Lite v6 JSON schema"],
            ["Legibility guards", f"{lg['fired']}/{lg['guards']}",
             "series ceilings, pie category ceiling, empty-result disclosure"],
        ],
    )]
    return "\n".join(parts)


def ambiguity_tables(d: dict[str, Any]) -> str:
    """Recall and over-ask, side by side, because neither means anything alone.

    Either number is trivial to max out on its own — never ask, or always ask —
    so the pair is the result and a single figure would be a way of hiding half
    of it.
    """
    s = d["summary"]
    meta = d["meta"]
    layer = "detectors only" if meta.get("mode") == "detectors" else "detectors + LLM layer"
    parts = [
        f"*{s['cases']} labelled prompts ({s['positives']} ambiguous, {s['negatives']} clear), "
        f"{layer}, run {meta['generated_at']}.*\n"
    ]
    rec, det, llm = s["recall"], s["recall_detector_reachable"], s["recall_llm_reachable"]
    parts.append(_table(
        ["Measure", "Result", "Meaning"],
        [
            ["Recall", f"{rec['asked']}/{s['positives']} ({rec['recall_pct']}%)",
             "underspecified requests that were questioned, not guessed at"],
            ["  lexically reachable",
             f"{det['asked']}/{det['cases']} ({det['recall_pct']}%)",
             "decidable from the words and the schema alone"],
            ["  meaning-dependent",
             f"{llm['asked']}/{llm['cases']} ({llm['recall_pct']}%)",
             "needs to know that 'revenue' is a column under another name"],
            ["**Over-asked**", f"{s['over_asked']}/{s['negatives']} ({s['over_ask_pct']}%)",
             "clear requests interrupted anyway — the cost side of recall"],
            ["Slot accuracy", f"{s['slot_accuracy_pct']}%",
             "asked about the right thing, not merely asked"],
            ["Option accuracy", f"{s['offer_accuracy_pct']}%",
             "put the columns a correct answer needs on the table"],
            ["Bind rate", f"{s['bind_rate_pct']}%",
             "answers that resolve a plan slot instead of being re-guessed"],
            ["**Ungrounded options**", str(s["grounding_violations"]),
             "options naming a column or value the dataset lacks — must be 0"],
        ],
    ))
    if s["grounding_violations"]:
        parts.append(
            "\n**Ungrounded options were released.** Every one is a question that "
            "offered the user something the data does not contain:\n"
        )
        parts.extend(f"- {v}\n" for v in s["grounding_violation_detail"])
    return "\n".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--perf", default="bench/results/perf.json")
    ap.add_argument("--nl", default="bench/results/nl.json")
    ap.add_argument("--chart", default="bench/results/chart_quality.json")
    ap.add_argument("--ambiguity", default="bench/results/ambiguity-full.json")
    ap.add_argument("--ambiguity-detectors", default="bench/results/ambiguity-detectors.json")
    ap.add_argument("--out", default=None, help="write here (UTF-8) instead of stdout")
    args = ap.parse_args()

    chunks = []
    for title, path, fn in (
        ("Performance", args.perf, perf_tables),
        ("Natural-language accuracy", args.nl, nl_tables),
        ("Chart quality", args.chart, chart_tables),
        # Both layers, because the split is the finding: what the deterministic
        # rules reach on their own, and what asking a model adds on top.
        ("Ambiguity detection (deterministic layer)",
         args.ambiguity_detectors, ambiguity_tables),
        ("Ambiguity detection (with the LLM layer)", args.ambiguity, ambiguity_tables),
    ):
        data = _load(path)
        chunks.append(f"\n## {title}\n")
        chunks.append(
            fn(data) if data else f"*(no results at `{path}` — run the benchmark first)*"
        )
    text = "\n".join(chunks)
    # Everything here is published *inside* a numbered section of Docs/24, so the
    # whole block is demoted one level. Written at natural depth above and shifted
    # once here, rather than hard-coding `####` at ten call sites where one would
    # eventually be missed.
    text = "\n".join(
        ("#" + line) if line.startswith("#") else line for line in text.split("\n")
    )
    if args.out:
        # Always UTF-8: the tables carry em dashes and ×, and a Windows console
        # writing cp1252 mangles them into the document.
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"[bench] wrote {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
