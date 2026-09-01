# bench — the measurement harness

Not part of the shipped package: `bench` measures `autoviz`, and `autoviz` never imports it.

Until 16 August 2026 this project had 773 passing tests and no numbers. Tests say a thing is
correct; they say nothing about how fast it is, how it degrades, or how often the planner
understands the question. Building this found six real defects that the suite did not — see
[`Docs/24 §6`](../../Docs/24-Performance-and-Evaluation.md).

## Running it

```bash
cd backend

uv run python -m bench.perf                 # latency, memory, ceilings          ~5 min
uv run python -m bench.perf --quick         # small scales, fewer repeats        ~1 min
uv run python -m bench.nl_run               # 39 NL prompts, live planner        ~6 min
uv run python -m bench.nl_run --only T01,W03 # one or two cases while iterating
uv run python -m bench.chart_quality        # type / spec / legibility           instant
uv run python -m bench.ambiguity_run --detectors-only   # 58 labelled prompts, no LLM  instant
uv run python -m bench.ambiguity_run        # the same 58, detectors + LLM layer  ~8 min

uv run python -m bench.report --out bench/results/tables.md   # Markdown for Docs/24 §7
```

`nl_run` and `ambiguity_run` need a `GOOGLE_API_KEY` in `backend/.env`; everything else runs
fully offline, including `ambiguity_run --detectors-only`.
Results land in `bench/results/` as JSON, each carrying the machine, library versions and
repeat counts that produced it.

## What each module is for

| File | Measures |
|---|---|
| `gen.py` | The synthetic table — one seeded 11-column schema at 1k…1M rows, so a latency curve measures size and nothing else |
| `plans.py` | Ten real `analysis_plan`s chosen to separate costs a single "query latency" would blend: scan, filter, 1-key and 2-key grouping, high-cardinality output, holistic aggregates, a computed key, a full ranking, and a cleaning block |
| `perf.py` | Ingest, query, per-query overhead decomposition, the Arrow-vs-pandas A/B on `execute_analysis` itself, memory, result delivery, chart building, the end-to-end pipeline, join headroom, and the shipped ceilings |
| `nl_suite.py` | **The frozen 39-prompt benchmark.** Freezing it matters more than growing it |
| `nl_run.py` | Runs the suite against the live agent and scores it — five outcomes, never one averaged accuracy. Also wraps `planner.compose` to capture the **raw** prose before the grounding guard can replace it, which is the only way to measure how often the composer had to be overruled (`answers_ungrounded`) |
| `ambiguity_suite.py` | **The labelled ambiguity set** — 30 prompts that should be questioned, 28 that should not. The second half is the load-bearing one: over-asking is what a broader detector costs, and only the negatives can price it |
| `ambiguity_run.py` | Scores that set at either layer. Reports recall and over-ask together, since either alone is trivial to max out, plus three properties a raw ask/don't-ask count cannot see: options grounded in real columns, answers that bind to a plan slot, and asking about the right slot |
| `chart_quality.py` | Chart-type accuracy, spec validity against the real Vega-Lite v6 schema, legibility guards |
| `report.py` | Turns the JSON into the Markdown tables `Docs/24 §7` publishes, so the document cannot drift from the run |

## Two rules for changing this

**The NL suite is a held-out set.** Add cases; never remove or weaken one because it fails.
A benchmark edited when a result disappoints measures nothing, and this is the set the planner
fine-tune in `AutoViz-Planner-Model` will be judged against.

The same holds for `ambiguity_suite`, with one addition: `expect` is held-out, but `reachable`
is a *prediction* about which layer can decide a case, and correcting it against evidence is
fair. Three cases were moved from `detector` to `llm` when the benchmark showed no lexical rule
could fire on them without also firing on a structurally identical negative. Their `expect`
never changed.

**Assertions describe any correct answer, not one plan.** Most prompts have several right
plans — group then filter, or filter then group; `pclass` or `class`. Scoring on plan equality
would count paraphrase as failure. See the `nl_suite` docstring for what an expectation may
legitimately assert.
