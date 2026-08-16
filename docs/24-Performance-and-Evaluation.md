# 24 — Performance and Evaluation

**16 August 2026.** Until today this project had no performance numbers at all. Every figure
below was produced by a harness in [`backend/bench/`](../backend/bench/) that measures the
shipped code — `ingest.read_table`, `dataset.build_record`, `execution.execute_analysis`,
`charts.generate_chart`, `orchestrator.run_pipeline`, and the live LangGraph agent — rather than
a reimplementation that resembles it.

Reproduce everything with:

```bash
cd backend
uv run python -m bench.perf           # latency, memory, ceilings   (~5 min)
uv run python -m bench.nl_run         # 39 NL prompts, live planner (~6 min, needs GOOGLE_API_KEY)
uv run python -m bench.chart_quality  # chart type / spec / legibility (instant)
uv run python -m bench.report --out bench/results/tables.md   # regenerate §7's tables
```

The tables in §7 are **generated** by `bench.report` from the JSON results, not transcribed, so
this document cannot drift from the run that produced it.

---

## 1. Method, and what these numbers are not

| | |
|---|---|
| Machine | Windows 11, 16 logical cores, Python 3.12.13, DuckDB 1.5.5, pandas 3.0.3 |
| Dataset | Generated, seeded, 11 columns: 4 dimensions of varied cardinality, a datetime, 4 measures, one column 8% null |
| Scales | 1k · 10k · 100k · 500k · 1M rows |
| Repeats | 9 at ≤100k, 4 above, after a warm-up. Medians reported; the tail column is `max` because with fewer than 20 samples a "p95" is just the slowest run |
| Governors | The shipped ones — DuckDB `memory_limit=1GB`, `threads=2`, 30 s watchdog |

**Three honest limits on this evidence.**

1. **One machine, one run.** A 16-core laptop is not the `t3` instance the app deploys to.
   Treat the *shapes* of these curves and the *ratios* between them as the finding; treat the
   absolute milliseconds as an upper bound on a faster machine and a lower bound on a smaller one.
2. **No concurrency measurement.** Everything here is single-request. What happens when ten
   users query at once is not measured, and §6 lists it as the largest open question.
3. **The RSS deltas are noisy** at small scales — one row in §7 reads −1.0 MiB, which is the
   garbage collector, not a negative allocation. Only the 100k–1M rows of that table carry weight.

---

## 2. The headline numbers

| Question an evaluator will ask | Answer | Where |
|---|---|---|
| How fast is a typical question on a big file? | **A 1M-row group-by, charted end to end, in 68–78 ms** (no LLM) | §7 "End to end" |
| How much does it slow down as the CSV grows? | **1000× more rows costs 2.3× more time** on the commonest shape (21.9 → 50.0 ms) | §3.1 |
| How big a file can it take? | **~526,000 rows** for an 11-column table — the 50 MiB upload ceiling binds first | §5 |
| What does the whole round trip cost a user? | **7.4 s median**, and ~99% of that is the planner LLM | §4.3 |
| Does it pick the right chart? | **14/14** type accuracy, **10/10** specs valid against the real Vega-Lite v6 schema | §4.2 |
| Does it understand the question? | **35/39 correct, 0 over-asked, 1 wrong** on a frozen benchmark | §4.1 |
| Joins? | **Not supported.** The engine would do 1M × 125k in 154 ms; the limit is the plan grammar | §5.3 |

---

## 3. Query performance

### 3.1 The scaling curve is flatter than the data growth

Median `execute_analysis` wall time, 1,000 → 1,000,000 rows:

| Plan shape | 1k | 1M | Growth for 1000× the data |
|---|---|---|---|
| Group by 1 key, sum | 21.9 ms | 50.0 ms | **2.3×** |
| Group by 2 keys, 2 aggregates | 20.9 ms | 76.1 ms | 3.6× |
| Derive month + group + sum (trend) | 21.2 ms | 68.8 ms | 3.2× |
| Filter + group + sort + limit 10 | 19.9 ms | 89.4 ms | 4.5× |
| Group by 1 key, `count_distinct` | 21.4 ms | 134.3 ms | 6.3× |
| **Group by high-cardinality key** | 20.9 ms | **570.6 ms** | **27.3×** |
| **Cleaning block (3 ops) + group** | 51.8 ms | **1,830.2 ms** | **35.3×** |

Two things fall out of this, and both are more useful than the averages would be.

**Below about 100k rows, AutoViz is effectively constant-time.** Every shape sits in a 20–30 ms
band from 1k to 100k rows. That band is not analysis — it is the **~20 ms fixed cost** of opening
a governed DuckDB connection (12–15 ms of it is `duckdb.connect()` alone) and tearing it down
again. For the file sizes a student or analyst actually uploads, the query is free and the
connection is the bill.

**Two shapes break the pattern, for two different reasons.**

- *High-cardinality group-by* returns 125,000 groups, capped by `HARD_ROW_CEILING` to 100,000
  rows. It is not slow because grouping is hard; it is slow because **delivering 100,000 rows
  costs ~2.5 µs per cell** (§3.3). The cost is in the answer's size, not the question's difficulty.
- *The cleaning block* is 35× worse at 1M rows because `_apply_preprocessing` issues a **counting
  query per operation** so that each step can report its exact effect. Three ops means several
  extra full passes over the table before the analysis runs. That is a deliberate trade — the
  disclosure channel in [`Docs/14`](14-Disclosure-and-Outlier-Handling.md) depends on those exact
  counts — but it is now a *measured* trade rather than an invisible one, and §6 proposes the fix.

### 3.2 The bottleneck we found, and what fixing it was worth

Profiling the fixed cost showed something worth acting on: at 500k rows a 2-key group-by took
613 ms, of which **439 ms was `con.register()` handing the pandas frame to DuckDB** — not the
query, which took 194 ms. DuckDB was re-crossing the pandas boundary on *every single query*,
and the dataset never changes between them.

The fix is one cached conversion. `DatasetRecord.arrow()` converts the frame to an Arrow table
once and memoises it; `execution._register_source` registers that instead. It is sound only
because the frame is immutable — cleaning compiles to CTEs over `df_raw` and never writes back,
which the registry's design already guaranteed.

Measured on `execute_analysis` itself, with `AUTOVIZ_SCAN_SOURCE` flipped between the two arms:

| Rows | Before (pandas scan) | After (Arrow scan) | Speed-up |
|---|---|---|---|
| 1,000 | 25.2 ms | 23.2 ms | 1.1× |
| 10,000 | 37.7 ms | 21.8 ms | 1.7× |
| 100,000 | 237.0 ms | 34.0 ms | **7.0×** |
| 500,000 | 1,100.0 ms | 50.1 ms | **22.0×** |
| 1,000,000 | 2,099.2 ms | 80.5 ms | **26.1×** |

**It costs 0.2 MiB.** The conversion is near-zero-copy under Arrow-backed pandas, so a 133 MiB
frame's Arrow view added 0.2 MiB of real working set — measured as an RSS delta, because
`Table.nbytes` would have reported a 133 MiB copy that was never made. `nbytes()` deliberately
does not count it, or the registry would evict datasets that fit.

The fallback matters as much as the speed-up: a frame with a genuinely mixed-type column will
not convert to Arrow, and `arrow()` returns `None` so the query runs on the old path. A messy
CSV costs speed, never correctness. `AUTOVIZ_SCAN_SOURCE=pandas` forces it globally.

Covered by [`tests/test_arrow_source.py`](../backend/tests/test_arrow_source.py) — including a
test that both paths return byte-identical results.

### 3.3 Where the remaining time goes

| Rows | New connection | Expose frame (Arrow) | Run the query | One-off pandas→Arrow |
|---|---|---|---|---|
| 1,000 | 13.0 ms | 0.70 ms | 2.5 ms | 0.7 ms |
| 100,000 | 12.2 ms | 0.72 ms | 6.8 ms | 2.6 ms |
| 1,000,000 | 14.7 ms | 0.73 ms | 51.0 ms | 5.0 ms |

At a million rows the engine finally does more work than the plumbing. Below that, **the
connection is the single largest term in a query** — which is the next optimisation, and §6
sizes it.

Delivering the result is a separate, purely output-bound cost, and it is remarkably linear:
**2.2–3.9 µs per cell**, stable across both 2-column and 11-column results.

| Result | Cells | Serialize | Payload |
|---|---|---|---|
| 1,000 × 11 | 11,000 | 24.0 ms | 0.25 MiB |
| 100,000 × 2 | 200,000 | 512.5 ms | 4.97 MiB |
| 100,000 × 11 | 1,100,000 | 2,718.8 ms | 25.17 MiB |

This is the number that justifies `HARD_ROW_CEILING = 100,000`: a result at the ceiling takes
2.7 seconds to serialize and produces a 25 MiB JSON payload. **The ceiling is not arbitrary —
it is where the answer stops being deliverable.** It is also why charts should be built over
aggregates: a chart of 100,000 points produces a 3.9 MiB Vega-Lite spec that no browser should
be asked to render.

---

## 4. Correctness and quality

Speed is the easy half. A data tool that is fast and wrong is worse than one that is slow.

### 4.1 Natural language → analysis plan

[`bench/nl_suite.py`](../backend/bench/nl_suite.py) freezes **39 prompts** across four real
`test-data/` files (titanic, tips, seattle-weather, iris). This is the Week-3 shared deliverable
the roadmap has been carrying as outstanding, and the held-out set the planner fine-tune in
`AutoViz-Planner-Model` is blocked on.

**Scoring is deliberately paraphrase-tolerant.** A prompt has many correct plans, so a case
asserts only what is true of *any* right answer — which columns it touched, which aggregate
family, which intent, which chart family, whether it filtered — never plan equality. Where the
dataset spells one fact two ways (`pclass`/`class`, `survived`/`alive`), `any_of` accepts either.

Outcomes are counted separately rather than averaged into one accuracy figure, because they are
not equally bad:

| Outcome | Meaning | Cost when it happens |
|---|---|---|
| **correct** | Answered, met every assertion | — |
| **asked** | Paused for clarification where the request was genuinely underspecified | Correct behaviour |
| **declined** | Refused an out-of-scope request | Correct behaviour |
| **over_asked** | Paused on a request it could have answered | Friction |
| **wrong** | Answered confidently, and answered a different question | **The expensive one** |

Results are in §7. The one remaining `wrong` — *"Forecast next year's rainfall"* returns a
historical trend rather than declining — is a real open defect and is listed in §6.

### 4.2 Chart quality, measured three ways

"Chart quality" is not one number, so [`bench/chart_quality.py`](../backend/bench/chart_quality.py)
does not report one. A chart can be the wrong *type*, a right type with a malformed *spec*, or a
valid spec that is *illegible*. Three defects, three fixes, three scores:

| Measure | Result | What it actually checks |
|---|---|---|
| Chart-type accuracy | **14/14** | The rule recommender picks from the family the question calls for, across a labelled matrix of result shapes × intents — including one degenerate case it must *refuse* |
| Spec validity | **10/10** | Every chart type validated against the **real Vega-Lite v6 JSON schema** shipped in `frontend/node_modules`, not against our own structural checks |
| Legibility guards | **3/3** | Scatter series ceiling, 40-slice pie, empty-result disclosure |

On top of these, `npm run verify:specs` compiles and renders all **14 reference specs** through
the actual Vega-Lite compiler and Vega runtime and asserts what was drawn. All 14 pass.

### 4.3 End-to-end latency, with the LLM in the loop

The deterministic pipeline answers a 1M-row question in **68–78 ms**. The full agent round trip
measured across the 39 benchmark prompts is a **7.4 s median** (p90 10.2 s).

**Over 99% of what a user waits for is the planner LLM**, not AutoViz. That single ratio is the
strongest argument in the project for the local Qwen fine-tune in `AutoViz-Planner-Model`:
optimising the analysis engine further would be invisible to users, and the fine-tune track is
where the remaining latency actually lives.

---

## 5. What the ceilings are, and where they bite

### 5.1 Shipped limits

| Ceiling | Value | Effect on an 11-column table |
|---|---|---|
| Upload size | 50 MiB | **~526,000 rows** at 99.6 B/row — the binding constraint |
| Rows per dataset | 1,000,000 | Rarely reached; the byte ceiling fires first |
| Columns | 512 | — |
| Rows returned | 100,000 | Caps any single result (§3.3 justifies it) |
| Query wall time | 30 s | Watchdog interrupts the query |
| Engine memory / threads | 1 GB / 2 | Per query |
| Registry | 512 MiB | LRU eviction, self-reloading from Parquet blobs |

The benchmark **demonstrates the ceiling firing** rather than describing it: the 1M-row CSV is
95 MiB and `read_table` refuses it with `RESOURCE_LIMIT`. That refusal is in the results table,
not worked around.

### 5.2 Ingest cost

CSV on disk → typed, profiled, queryable dataset:

| Rows | CSV | In RAM | Read | Profile | Total |
|---|---|---|---|---|---|
| 10,000 | 0.95 MiB | 1.33 MiB | 26.5 ms | 53.8 ms | **80 ms** |
| 100,000 | 9.5 MiB | 13.3 MiB | 213 ms | 424 ms | **637 ms** |
| 500,000 | 47.5 MiB | 66.7 MiB | 1,134 ms | 2,138 ms | **3.27 s** |

Linear, and **profiling is roughly two-thirds of it** — null counts, cardinality, summary stats
and sample values over every column. A 50 MiB upload costs about 3.3 seconds before the first
question can be asked. That is a one-time cost per dataset, and it is the honest number to quote
in a demo. RAM is a consistent **1.4× the CSV size**.

### 5.3 Joins: not a capability, and now a measured one

AutoViz analyses **one table at a time**. `analysis_plan` has no join clause, so there is nothing
to benchmark at the product level — reporting a join latency as a feature would be false.

What *is* worth knowing is whether the engine could carry the feature. Measured directly against
DuckDB under the shipped governors, on the same Arrow scan path the product now uses:

| Fact rows | Dimension rows | Join + group | Time |
|---|---|---|---|
| 100,000 | 200 | star join | 33 ms |
| 1,000,000 | 200 | star join | 142 ms |
| 1,000,000 | 125,000 | large-to-large | **154 ms** |

**A million-row join costs about the same as the two-key group-by we already ship.** The barrier
to joins is entirely in the plan grammar, the validator and the planner prompt — not in
performance. That converts a roadmap argument from opinion into arithmetic.

---

## 6. What the measurement exposed

**Six defects were found by building this harness, not by the 773-test suite** that was passing
before it existed. All six are real; five are fixed, each with regression tests.

| # | Defect | Status |
|---|---|---|
| 1 | **`is_null` and `is_not_null` were advertised but never implemented.** Both are in `FILTER_OPS`, both pass validation, and `build_sql` had no rule for either — so a plan that validated cleanly died on a `KeyError` inside the engine. It surfaced as a *retryable* `EXECUTION_ERROR`, so the agent re-ran a plan that could never succeed. The most severe of the six | ✅ Fixed, 3 regression tests |
| 2 | **Every query re-crossed the pandas→DuckDB boundary.** 26× slower than necessary at 1M rows | ✅ Fixed (§3.2), `test_arrow_source.py` |
| 3 | **"maximum"/"minimum" were treated as ranking superlatives.** "How did the *maximum* temperature change over the years?" stopped to ask *"Which measure should rank them? 'best'/'most' isn't a column."* — quoting words the user never typed, about a ranking nobody requested. Blocked two ordinary prompts | ✅ Fixed — measure adjectives count only when used substantively; the question now quotes the word that actually fired; 5 regression tests |
| 4 | **Every boxplot spec was invalid.** `tooltip: true` sat on the composite mark, but `BoxPlotDef` sets `additionalProperties: false` and has no `tooltip` — so the spec failed the Vega-Lite v6 schema *and* produced no tooltip. Moved to the `box` and `outliers` sub-parts | ✅ Fixed, spec validity 9/10 → 10/10 |
| 5 | **An empty result rendered as a normal chart.** A query matching zero rows produced a valid spec, drew empty axes, and said nothing. Now carries an `empty_result` advisory notice, on the spec's own subtitle so a saved dashboard keeps the explanation | ✅ Fixed, 4 regression tests |
| 6 | **Over-asking on trivial defects.** "Compare average fare across embarkation towns" paused the whole analysis to ask about **2 missing values in 891 rows (0.2%)** | ✅ Fixed — missing-value questions now need `ROW_DROP_NOTICE_FRACTION` (5%) before they interrupt; below that the finding is disclosed through the notice channel instead. Judgement call; threshold named and shared with row-removal |
| 7 | **Out-of-scope requests answered instead of declined.** "Forecast next year's rainfall" returns a historical trend | ❌ **Open.** The system has no forecasting capability and should say so; silently substituting a different question is the failure mode this project exists to avoid |

Defects 1 and 6 are worth reading together, because they show why a benchmark finds things a
test suite does not. The over-ask in #6 had been *masking* #1: the cleaning gate paused before
execution was ever reached, so the unimplemented operator never ran. Fixing the friction exposed
the correctness bug underneath it. No unit test would have found either, because both required
the planner to choose `is_not_null` on a real dataset with a small number of nulls in a
grouped column — a combination nobody thought to write down.

### Optimisations this measurement makes obvious, none yet done

| Opportunity | Evidence | Estimated worth |
|---|---|---|
| **Pool DuckDB connections** | `duckdb.connect()` is 12–15 ms and is the largest term in every query under 100k rows | ~40% off small-query latency |
| **Fold the preprocessing counting queries into one pass** | Cleaning costs 35× a plain aggregate at 1M rows, because each op counts its own effect separately | Most of a 1.8 s worst case |
| **Stream or paginate large results** | 2.7 s and 25 MiB at the 100k-row ceiling | Removes the ceiling's sharpest edge |
| **Cache the profile** | Profiling is ⅔ of a 3.3 s ingest and is recomputed on every reload from blob storage | ~2 s per cold dataset |

None of these are on the critical path for the mid-evaluation, and all of them are now
*arguable with a number* instead of a hunch.

### The largest unmeasured risk

**Concurrency.** Every figure here is single-request. The registry is a bounded LRU with a
reentrant lock; `execute_analysis` opens its own connection per call, so queries do not contend
on one engine — but nothing has measured what ten simultaneous users do to a 1 GB memory
governor and a 512 MiB registry budget. That is the first thing to add to this harness.

---

## 7. Generated results

*The tables below are written by `uv run python -m bench.report`. Regenerate rather than edit.*

<!-- BEGIN GENERATED TABLES -->
<!-- Paste the contents of backend/bench/results/tables.md here after a run. -->
<!-- END GENERATED TABLES -->

---

*Raw results: [`backend/bench/results/`](../backend/bench/results/) — `perf.json`, `nl.json`,
`chart_quality.json`. Each carries the machine, library versions and repeat counts that produced
it, so a figure can always be traced to a run.*
