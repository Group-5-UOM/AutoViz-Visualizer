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
| What does the whole round trip cost a user? | **7–12 s median across runs**, and ~99% of it is the planner LLM | §4.3 |
| Does it pick the right chart? | **14/14** type accuracy, **10/10** specs valid against the real Vega-Lite v6 schema | §4.2 |
| Does it understand the question? | **39/39 acceptable** on a frozen benchmark — 32 correct, 7 clarified, **0 over-asked, 0 wrong** | §4.1 |
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

Results are in §7. As of the 16 August run the suite is **39/39 acceptable: 32 answered
correctly, 7 clarified or declined, none over-asked and none wrong.** All seven cases that
paused are ones where pausing is the right behaviour — two underspecified requests, one with two
plausible temperature columns, three out of scope, and one prompt injection.

That is a floor, not a victory: 39 prompts is a small set, and the last `wrong` was only closed
by defect 7 below. Read it as "nothing in this set produces a confident wrong answer today", and
keep adding cases.

**Two caveats on reading this score.**

*The planner is not deterministic.* It runs at `temperature=0` against a hosted model, and
successive runs of the identical suite still differ by a case or two — a prompt that answers on
one run may ask a clarifying question on the next. Quote the outcome *counts* and the shape of
the failures, not a percentage to one decimal place, and re-run before presenting.

*The scorer is part of the experiment and can itself be wrong.* One case scored `wrong` on an
earlier run because `_columns_touched` did not look inside `preprocessing`. The plan under test
was in fact the best available answer — "Chart the temperature" resolved by folding `temp_max`
and `temp_min` into one series with `pivot_longer` — but after that fold neither column name
appears anywhere else in the plan, so the assertion saw no temperature column. The extractor was
fixed; the case was not weakened. **A benchmark that is only ever debugged when the system looks
bad will quietly drift into flattering it**, so corrections in that direction are recorded here.

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
measured across the 39 benchmark prompts had a median of **7.2 s, 8.6 s, 9.7 s and 11.6 s** on
four successive runs of the identical suite. That spread is the hosted planner API, not AutoViz —
which is the point of the next paragraph, and the reason to quote a range rather than a figure.

**Over 99% of what a user waits for is the planner LLM**, not AutoViz. That single ratio is the
strongest argument in the project for the local Qwen fine-tune in `AutoViz-Planner-Model`:
optimising the analysis engine further would be invisible to users, and the fine-tune track is
where the remaining latency actually lives.

### 4.4 Is the prose answer grounded in the numbers?

The chart and the table are computed deterministically. **The sentence next to them was not
checked at all** until 16 August — and it is the part most users read first.

[`Docs/16 §1.1`](16-Planner-Model-Strategy.md) had this documented as a known asymmetry: of the
four `PlannerLLM` jobs, `classify`, `generate_plan` and `style_patch` all emit JSON that is
validated before it can reach anyone, while `compose` emits free prose whose "failure caught by"
column read **Nothing**. Its system prompt does say *"ground every number strictly in the
provided result tables — never estimate, extrapolate, or invent values"*, but that is an
instruction, and instruction-following is precisely what failed in defect 7.

[`services/grounding.py`](../backend/src/autoviz/services/grounding.py) closes it the way the
rest of the system closes things — deterministically, with no second model:

| Treated as grounded | Why |
|---|---|
| Any value in a result cell, and its rounded forms | A composer rounds; rounding is not invention |
| ×100 / ÷100 of a cell value | A rate reported as a percentage is a unit change |
| `row_count`, `input_rows`, `output_rows`, per-op `rows_affected` | The scope figures a truthful summary quotes |
| Literals from the plan's own filters | "fares above **100**" is in the request, never in a cell |
| Figures inside notices | That prose is written by the system from the same counts |
| Whole numbers ≤ the largest row count on screen | Counts and ordinals, never measurements |

Anything left over is a figure with no visible source, and the fluent answer is **replaced by the
deterministic template summary**, which is grounded by construction. The charts and the numbers
behind them are untouched — only the prose is.

**The guard has a stated blind spot, and measuring it is what put it there.** Above
`MAX_GROUNDABLE_CELLS = 2,000` result cells the check is switched off and the answer is reported
as grounded. Two measurements forced that:

| Result size | Cost to check | Catches an invented `45.67`? |
|---|---|---|
| 3 rows × 3 cols | 0.09 ms | yes |
| 660 rows × 3 cols | 9.9 ms | yes |
| 5,000 rows × 3 cols | 248 ms | **no** |
| 100,000 rows × 3 cols | 5,676 ms | **no** |

The cost is the lesser problem. The real one is that **the check stops working long before it
gets expensive**: by a few thousand rows the set of admissible values is dense enough that
invented figures match it by coincidence, so it would return "grounded" regardless. A check with
no power that also costs 5.7 seconds is worse than no check, so it is bounded to the regime where
it bites — which is the regime composers actually quote from, since answers summarise
*aggregates*, not raw extracts. `is_checkable()` exposes the distinction so coverage can be
reported rather than assumed.

**Two measurements make this a guard rather than a guess.**

*It catches fabrication:* an answer asserting `42.99` against a result set containing no such
value is rejected, and the user is served the template instead
([`tests/test_grounding.py`](../backend/tests/test_grounding.py), 31 tests).

*It does not cost good answers:* after the fixes below, **0 of the 29 checkable answers across
the 39-prompt benchmark were flagged** (32 were composed; 3 described results above the cell
budget). But that is only true of the *second* version — the benchmark proved the first one did
cost good answers, which is the part worth reading.

### The false positives, and why they are the important half

The first version of this module was spot-checked against six real answers, flagged none, and
looked finished. Run over the full 39-prompt benchmark it flagged **3 of 32 composed answers, and
all three were correct**. Shipping on the spot-check would have silently downgraded roughly one
answer in ten.

| What was flagged | Why it was wrong |
|---|---|
| A survival rate written as `0.968085` | The stored value is `0.9680851063829787`. The check expanded each data value to a *fixed* set of roundings (0–3 dp) and six decimal places was not among them |
| The years `2012`–`2015` in a trend | A `year_start` derive stores `2012-01-01T00:00:00`. The composer writes the year; nothing connected the two |
| `2014` at the end of a sentence | The number regex swallowed the full stop, so the token was `2014.` — a different string from the `2014` in the date filter |

The fix for the first is a principle, not a patch: **round the data to the precision the prose
used, never the prose to a precision the data happens to have.** No fixed expansion of a stored
value can anticipate how a composer chooses to print it. The other two are named rules — years
are read out of timestamps and date-range filters, and a decimal point only counts when digits
follow it. All three shapes are now regression tests.

The number to watch is the false-positive rate, not the catch rate. **A grounding check that
discards correct answers is worse than no check at all**, because the damage is invisible: the
user simply gets a worse answer and never learns why. That is why the check fails open above its
budget, why every rejection is logged as an `ungrounded_answer` event, and why `answers_ungrounded`
in §7 is reported on every benchmark run rather than measured once.

This is also the clearest argument in this document for the harness existing at all: **the guard
against the LLM being unreliable was itself unreliable, and only running it over real output
showed that.**

The claim this earns is narrow and worth stating exactly — and the qualifier is not optional:
**for any answer summarising an aggregate result, every number a user reads either came out of a
result table or out of a sentence the system wrote itself.** Answers over very large raw extracts
are not covered, and the code says so rather than implying otherwise.

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

**Eight defects were found by building this harness, not by the 759-test suite** that was passing
before it existed. **All eight are real and all eight are now fixed**, each with regression
tests — the suite is **820**.

The eighth is different in kind from the other seven and worth reading first: it was not found by
a failing case at all. It was found by *reading the project's own documentation*, where
[`Docs/16 §1.1`](16-Planner-Model-Strategy.md) had recorded — in a table about something else
entirely — that the LLM output the user actually reads was the one output nothing validated.

| # | Defect | Status |
|---|---|---|
| 1 | **`is_null` and `is_not_null` were advertised but never implemented.** Both are in `FILTER_OPS`, both pass validation, and `build_sql` had no rule for either — so a plan that validated cleanly died on a `KeyError` inside the engine. It surfaced as a *retryable* `EXECUTION_ERROR`, so the agent re-ran a plan that could never succeed. The most severe of the six | ✅ Fixed, 3 regression tests |
| 2 | **Every query re-crossed the pandas→DuckDB boundary.** 26× slower than necessary at 1M rows | ✅ Fixed (§3.2), `test_arrow_source.py` |
| 3 | **"maximum"/"minimum" were treated as ranking superlatives.** "How did the *maximum* temperature change over the years?" stopped to ask *"Which measure should rank them? 'best'/'most' isn't a column."* — quoting words the user never typed, about a ranking nobody requested. Blocked two ordinary prompts | ✅ Fixed — measure adjectives count only when used substantively; the question now quotes the word that actually fired; 5 regression tests |
| 4 | **Every boxplot spec was invalid.** `tooltip: true` sat on the composite mark, but `BoxPlotDef` sets `additionalProperties: false` and has no `tooltip` — so the spec failed the Vega-Lite v6 schema *and* produced no tooltip. Moved to the `box` and `outliers` sub-parts | ✅ Fixed, spec validity 9/10 → 10/10 |
| 5 | **An empty result rendered as a normal chart.** A query matching zero rows produced a valid spec, drew empty axes, and said nothing. Now carries an `empty_result` advisory notice, on the spec's own subtitle so a saved dashboard keeps the explanation | ✅ Fixed, 4 regression tests |
| 6 | **Over-asking on trivial defects.** "Compare average fare across embarkation towns" paused the whole analysis to ask about **2 missing values in 891 rows (0.2%)** | ✅ Fixed — missing-value questions now need `ROW_DROP_NOTICE_FRACTION` (5%) before they interrupt; below that the finding is disclosed through the notice channel instead. Judgement call; threshold named and shared with row-removal |
| 7 | **Out-of-scope requests answered instead of declined.** "Forecast next year's rainfall" returned a historical trend and presented it as the answer | ✅ Fixed — a deterministic capability check now declines *and offers the nearest supported thing*, so the substitution is the user's choice rather than a silent one. 10 regression tests. See below |
| 8 | **The prose answer was never checked against the numbers.** `compose` is the one `PlannerLLM` job emitting free text rather than validated JSON, so a figure it invented reached the user unopposed. Documented as a known hole in [`Docs/16 §1.1`](16-Planner-Model-Strategy.md) — "failure caught by: **Nothing**" | ✅ Fixed — `services/grounding.py` traces every figure back to the results and falls back to the deterministic summary when one has no source. 31 regression tests; 0 of 29 checkable benchmark answers flagged. [§4.4](#44-is-the-prose-answer-grounded-in-the-numbers) |

Defects 1 and 6 are worth reading together, because they show why a benchmark finds things a
test suite does not. The over-ask in #6 had been *masking* #1: the cleaning gate paused before
execution was ever reached, so the unimplemented operator never ran. Fixing the friction exposed
the correctness bug underneath it. No unit test would have found either, because both required
the planner to choose `is_not_null` on a real dataset with a small number of nulls in a
grouped column — a combination nobody thought to write down.

### Defect 7 in full: declining without dead-ending

This was the only one where the *chart* was fine. Asked to "Forecast next year's rainfall", the
planner emitted a valid historical trend — a good chart, correctly computed, answering a
question the user did not ask. **Silently substituting a different question is precisely the
failure this project's whole architecture exists to prevent**, and it had survived to the
benchmark because no test asks for something the product cannot do.

Three decisions shaped the fix.

**It is deterministic, and it runs before the planner.** Wording the system prompt more firmly
is what was already being relied on, and it is what failed. `agent/ambiguity.py` gained a
`_detect_unsupported_capability` detector alongside the four existing ones, so "can this even be
asked?" is a computed signal rather than a prompt guess — the same principle as every other
gate in the system.

**It declines *and* offers, rather than dead-ending.** A flat refusal is true but rarely the
most useful true answer. The detector returns an `Ambiguity` whose question states plainly what
cannot be done and whose options offer the nearest supported thing:

> *"AutoViz describes data that already exists — it cannot forecast or predict. What would you
> like instead?"* → **[ Show what the data does say, over time ] [ Nothing — cancel this request ]**

The user who accepts gets the same historical trend as before. The difference is consent: they
were told what the system cannot do, and chose the substitute. The defect was never the chart.

Accepting also folds a *prohibition* into the task, not just a substitution — `apply_resolutions`
appends "do NOT forecast, predict or extend beyond the last observation", because the planner has
already demonstrated it will extrapolate if left to infer.

**The vocabulary is short on purpose, and schema beats vocabulary.** A false positive blocks
legitimate work, so a term earns its place only when no supported reading exists. `relationship`,
`related` and `correlation` are deliberately absent — a scatter plot is a legitimate answer to
"is X related to Y", and `bench/nl_suite.py` has two such prompts that must keep working.
`trend`, `growth` and `over time` are all supported and absent too. And when a term matches a
real column name (`join_date`, `cluster_id`) the schema wins: the user naming their own column
is not a request for a feature.

Three capability families are covered — forecasting, statistical modelling, and joins. The join
case also makes the product's largest known gap (§5.3) fail *honestly* rather than by luck.

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
### Performance

*Measured 2026-08-16T11:02:24 on Windows-11-10.0.26200-SP0, 16 logical cores, Python 3.12.13, DuckDB 1.5.5, pandas 3.0.3. Peak resident set for the whole run: 897.2 MiB.*

#### Ingest — file on disk to queryable dataset

| Rows | CSV MiB | In RAM MiB | Read ms | Profile ms | Total ms |
|---|---|---|---|---|---|
| 1,000 | 0.10 | 0.13 | 7.72 | 18.01 | 25.73 |
| 10,000 | 0.95 | 1.33 | 26.50 | 53.80 | 80.30 |
| 100,000 | 9.50 | 13.34 | 213.1 | 424.0 | 637.0 |
| 500,000 | 47.50 | 66.68 | 1,134.4 | 2,137.6 | 3,272.0 |
| 1,000,000 | 94.99 | — | — | — | **refused** (RESOURCE_LIMIT) |

#### Query latency by plan shape (median ms, `execute_analysis`)

| Plan shape | 1,000 | 10,000 | 100,000 | 500,000 | 1,000,000 | Rows out (max scale) |
|---|---|---|---|---|---|---|
| Projection + limit (1k rows out) | 28.99 | 27.69 | 33.02 | 31.49 | 36.32 | 1,000 |
| Filter + projection (1k rows out) | 21.90 | 25.67 | 33.70 | 54.04 | 79.53 | 1,000 |
| Group by 1 key, sum (5 groups) | 21.86 | 19.18 | 24.97 | 34.87 | 50.04 | 5 |
| Group by 2 keys, 2 aggregates (60 groups) | 20.89 | 21.68 | 27.72 | 50.15 | 76.13 | 60 |
| Group by high-cardinality key (n/8 groups) | 20.92 | 26.97 | 91.91 | 347.6 | 570.6 | 100,000 |
| Group by 1 key, median | 20.66 | 21.31 | 27.02 | 43.63 | 73.33 | 5 |
| Group by 1 key, count_distinct | 21.36 | 29.42 | 37.09 | 76.59 | 134.3 | 5 |
| Derive month_start + group + sum (36 points) | 21.17 | 25.94 | 25.70 | 43.69 | 68.77 | 36 |
| Filter + group + sort + limit 10 (“top 10”) | 19.93 | 21.71 | 27.00 | 54.21 | 89.35 | 10 |
| Cleaning block (3 ops) + group + sum | 51.84 | 86.07 | 197.8 | 856.9 | 1,830.2 | 5 |

#### The scan-source change, on `execute_analysis` itself

| Rows | Shape | pandas scan ms | Arrow scan ms | Speed-up |
|---|---|---|---|---|
| 1,000 | agg_2key | 25.24 | 23.21 | 1.09x |
| 1,000 | derive_trend | 23.47 | 21.02 | 1.12x |
| 1,000 | top_n | 24.04 | 20.83 | 1.15x |
| 10,000 | agg_2key | 37.74 | 21.77 | 1.73x |
| 10,000 | derive_trend | 39.03 | 20.55 | 1.9x |
| 10,000 | top_n | 36.34 | 22.16 | 1.64x |
| 100,000 | agg_2key | 237.0 | 33.99 | 6.97x |
| 100,000 | derive_trend | 187.9 | 24.74 | 7.6x |
| 100,000 | top_n | 188.4 | 27.38 | 6.88x |
| 500,000 | agg_2key | 1,100.0 | 50.10 | 21.96x |
| 500,000 | derive_trend | 1,142.3 | 58.59 | 19.5x |
| 500,000 | top_n | 900.3 | 60.32 | 14.93x |
| 1,000,000 | agg_2key | 2,099.2 | 80.53 | 26.07x |
| 1,000,000 | derive_trend | 2,148.4 | 65.78 | 32.66x |
| 1,000,000 | top_n | 1,909.8 | 83.03 | 23.0x |

#### Where a query's time goes

| Rows | New connection ms | Expose frame (pandas) ms | Expose frame (Arrow) ms | Query ms | One-off conversion ms |
|---|---|---|---|---|---|
| 1,000 | 12.95 | 3.75 | 0.70 | 2.51 | 0.69 |
| 10,000 | 12.63 | 10.30 | 0.72 | 2.77 | 2.15 |
| 100,000 | 12.17 | 83.58 | 0.72 | 6.78 | 2.60 |
| 500,000 | 11.79 | 459.6 | 0.70 | 24.73 | 3.47 |
| 1,000,000 | 14.69 | 995.7 | 0.73 | 50.95 | 5.04 |

#### Memory

| Rows | Frame MiB | Added RSS for the Arrow view MiB | Its logical size MiB |
|---|---|---|---|
| 1,000 | 0.13 | 0.00 | 0.10 |
| 10,000 | 1.33 | -1.00 | 1.30 |
| 100,000 | 13.34 | 0.00 | 13.30 |
| 500,000 | 66.68 | 0.00 | 66.70 |
| 1,000,000 | 133.4 | 0.20 | 133.5 |

#### Delivering the result (`sanitize_records` + JSON)

| Rows out | Cols | Cells | Serialize ms | µs/cell | Payload MiB |
|---|---|---|---|---|---|
| 100 | 11 | 1,100 | 3.61 | 3.28 | 0.03 |
| 100 | 2 | 200 | 0.77 | 3.85 | 0.00 |
| 1,000 | 11 | 11,000 | 24.02 | 2.18 | 0.25 |
| 1,000 | 2 | 2,000 | 4.43 | 2.21 | 0.05 |
| 10,000 | 11 | 110,000 | 257.9 | 2.35 | 2.52 |
| 10,000 | 2 | 20,000 | 49.00 | 2.45 | 0.50 |
| 50,000 | 11 | 550,000 | 1,435.9 | 2.61 | 12.59 |
| 50,000 | 2 | 100,000 | 276.5 | 2.77 | 2.49 |
| 100,000 | 11 | 1,100,000 | 2,718.8 | 2.47 | 25.17 |
| 100,000 | 2 | 200,000 | 512.5 | 2.56 | 4.97 |

#### Chart construction

| Rows plotted | Recommend ms | Build spec ms | Spec size | Valid |
|---|---|---|---|---|
| 12 | 0.01 | 0.11 | 3 KiB | yes |
| 100 | 0.01 | 0.18 | 6 KiB | yes |
| 1,000 | 0.01 | 1.03 | 41 KiB | yes |
| 10,000 | 0.01 | 7.56 | 393 KiB | yes |
| 100,000 | 0.01 | 87.26 | 3,920 KiB | yes |

#### End to end, no LLM (`run_pipeline`)

| Rows | Shape | Chart | Total ms | Status |
|---|---|---|---|---|
| 10,000 | agg_2key | grouped_bar | 20.41 | ok |
| 10,000 | derive_trend | line | 19.01 | ok |
| 10,000 | top_n | bar | 19.68 | ok |
| 100,000 | agg_2key | grouped_bar | 25.10 | ok |
| 100,000 | derive_trend | line | 24.16 | ok |
| 100,000 | top_n | bar | 25.81 | ok |
| 1,000,000 | agg_2key | grouped_bar | 78.09 | ok |
| 1,000,000 | derive_trend | line | 68.33 | ok |
| 1,000,000 | top_n | bar | 76.68 | ok |

#### Join headroom — engine only, **not a shipped capability**

| Fact rows | Dim rows | Case | DuckDB ms |
|---|---|---|---|
| 100,000 | 200 | small_dim | 33.10 |
| 100,000 | 125,000 | large_dim | 42.24 |
| 500,000 | 200 | small_dim | 68.52 |
| 500,000 | 125,000 | large_dim | 77.48 |
| 1,000,000 | 200 | small_dim | 141.6 |
| 1,000,000 | 125,000 | large_dim | 153.5 |

#### Shipped ceilings

| Ceiling | Value | Where it bites on this 11-column table |
|---|---|---|
| Upload size | 50.0 MiB | ~526,450 rows (99.6 B/row) |
| Rows per dataset | 1,000,000 | after the byte ceiling, so rarely first |
| Columns | 512 | — |
| Rows returned | 100,000 | caps any single result |
| Query time | 30 s | watchdog interrupts the query |
| Engine memory | 1GB | threads=2 |

### Natural-language accuracy

*39 frozen prompts, planner `AUTOVIZ_PLANNER_MODEL default`, run 2026-08-16T13:54:51.*

| Outcome | Cases | Share | Meaning |
|---|---|---|---|
| Answered correctly | 32 | 82.1% | met every assertion for that prompt |
| Asked a clarifying question | 7 | 17.9% | paused where asking was the right move |
| Declined | 0 | 0.0% | refused an out-of-scope request |
| **Over-asked** | 0 | 0.0% | paused on a request it could have answered |
| **Wrong** | 0 | 0.0% | answered, and the answer was not the question asked |

End-to-end latency including the planner LLM: median **17.9 s**, p90 39.1 s, max 82.3 s.

**Answer grounding:** 32 answers were composed by the planner, of which **29** described a result small enough to verify (the rest exceeded `MAX_GROUNDABLE_CELLS`). Of those, **0 (0.0%)** asserted a figure with no source in the results and were replaced by the deterministic summary.

The false-positive side is the one to watch: a check that discards *correct* answers is worse than no check, because the damage is invisible to the user. An earlier version of this module flagged 3 of 32 — all three wrongly.

### Chart quality

| Measure | Result | What it checks |
|---|---|---|
| Chart-type accuracy | 14/14 (100.0%) | recommender picks a chart from the family the question calls for |
| Spec validity | 10/10 (100.0%) | every chart type validates against the real Vega-Lite v6 JSON schema |
| Legibility guards | 3/3 | series ceilings, pie category ceiling, empty-result disclosure |
<!-- END GENERATED TABLES -->

---

*Raw results: [`backend/bench/results/`](../backend/bench/results/) — `perf.json`, `nl.json`,
`chart_quality.json`. Each carries the machine, library versions and repeat counts that produced
it, so a figure can always be traced to a run.*
