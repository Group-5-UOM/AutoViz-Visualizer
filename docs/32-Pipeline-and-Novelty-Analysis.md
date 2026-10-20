# 32 — How the Pipeline Actually Works, and Where the Novelty Is

*(verified against the code on `main` at `378ed49`, 2 Oct 2026 — not from a PDF)*

A paper cannot say "our novelty is X" until X is shown to exist in the code and to differ from prior work. This document walks the pipeline end to end, then checks eight areas where an NL-to-visualization system can make a contribution: dataset profiling, visualization selection, chart ranking, insight detection, dashboard layout, LLM prompting and agent architecture, validation against incorrect charts, and evaluation methodology. For each area it gives what was built, where it lives, the closest prior work, and a verdict.

Paths are relative to `backend/src/autoviz/` unless they start with `frontend/`, `backend/bench/` or `validations/`.

---

## 1. Verdict at a glance

| Area | Built? | Verdict |
|---|---|---|
| Dataset profiling and quality scan | Yes | Custom but incremental |
| Visualization selection | Yes, as a rule list | Standard technique |
| Chart ranking | **No** | Not a contribution |
| Insight detection | **No** (the number-grounding check is built) | Grounding check is a candidate contribution |
| Dashboard layout | Free-form canvas, no layout algorithm | Not a contribution |
| LLM prompting and agent architecture | Yes | Plan-only LLM with no rows in planning is the core idea; the agent framework is standard |
| Validation against incorrect charts | Yes, layered | **Strongest contribution** |
| Evaluation methodology | Yes | **Strong contribution** |

In one sentence, the defensible novelty is that the LLM is confined to proposing a typed, closed-grammar plan, and everything that can be wrong is checked by deterministic code. The checks cover the plan before execution, consent before rows are removed, every number in the prose after execution, and the drawn chart geometry in testing. The evaluation is built to measure exactly those failure modes: wrong answers versus justified questions, over-asking, ungrounded numbers and silent rendering defects.

---

## 2. The pipeline, step by step

What the LLM sees at each step matters for the privacy claim, so it is listed explicitly.

| # | Step | Who does it | What the LLM sees | Code |
|---|---|---|---|---|
| 1 | Upload and ingest: detect encoding, delimiter, header row, decimal comma, day-first dates and multiple tables in one file; record every guess as a disclosed assumption | Code | Nothing | `services/ingest.py` |
| 2 | Profile: logical types, cardinality, null counts, duplicates, coded-category columns, sample values for low-cardinality text | Code | Nothing yet | `services/dataset.py` `_build_profile` |
| 3 | Load context and run six ambiguity detectors **before** any LLM call | Code | Nothing | `agent/ambiguity.py` |
| 4 | If ambiguous, ask the user (an interrupt) with 2–5 options grounded in real columns or values | Code | Nothing | `agent/graph.py` `clarify` |
| 5 | Classify intent and split into at most 6 tasks | LLM | Request, schema, cardinality, last 3 turns, neutralized sample values (≤50 per low-cardinality text column) | `llm/client.py` `classify` |
| 6 | Fan out one worker per task (LangGraph `Send`) | Code | — | `agent/graph.py` |
| 7 | Generate an `analysis_plan` JSON | LLM | Task, schema, cardinality, coded-category columns; on retry, the rejected plan plus validator errors | `llm/client.py` `generate_plan` |
| 8 | Validate the plan against schema and types; on failure, re-plan (at most 3 planner calls in total) | Code | — | `services/validation.py` |
| 9 | Quality scan; ask about cleaning that changes values (at most 2 questions) | Code + user | Nothing | `services/quality.py`, `assess_quality` |
| 10 | Compile to parameterized DuckDB SQL (CTE chain over an Arrow view) and execute under resource limits | Code | Nothing | `services/execution.py` |
| 11 | If more than 30% of rows would be removed, require approval tied to a hash of the preprocessing | Code + user | Nothing | `_confirmation_gate` |
| 12 | Choose the chart if the user did not name one; build the Vega-Lite spec; apply skew, null and slice guards with notices | Code | Nothing | `services/charts.py`, `services/skew.py` |
| 13 | Write a 2–5 sentence summary | LLM | ≤25 result rows, row count, SQL, notices | `llm/client.py` `compose` |
| 14 | Check every number in the summary against the result; if one is unsupported, replace the prose with a template | Code | — | `services/grounding.py`, `compose_response` |
| 15 | Place the chart on the board; the user can edit the plan, style or position | Code + user | Style patch only, for style edits | `frontend/src/lib/chartWidgets.ts` |

**Privacy, stated precisely:** the *planner* never receives data rows. The summary step (13) does see up to 25 aggregated result rows, and the classifier (5) sees up to 50 distinct values from low-cardinality text columns. The raw file never leaves the server. The paper's limitations section already says this; keep it that way.

---

## 3. Area by area

### 3.1 Dataset profiling

**What it does**
- **Ingest** (`services/ingest.py`):
  - Encoding: byte-order mark, then strict UTF-8, then cp1252, then latin-1.
  - Delimiter: the candidate (`, ; \t |`) on which the most rows agree on field count; `csv.Sniffer` only breaks ties.
  - Header: the first row with the modal field count and no empty cells.
  - Decimal comma: considered only when the delimiter is `;`.
  - **"NA" as Namibia:** if at least 90% of a column is two-letter uppercase codes, "NA" is kept as data rather than treated as missing (`_na_exclusions`, `CODE_COLUMN_FRACTION`).
  - Day-first dates are decided only when a value proves the order; otherwise the ambiguity is disclosed.
  - Several blank-line-separated tables in one file are split, with titles.
  - Every guess becomes a named, disclosed assumption (eight kinds, `IngestReport`).
- **Profile** (`services/dataset.py`):
  - Four logical types: boolean, number, datetime, string. There is no semantic typing (geo, currency, ID).
  - A number column is treated as a category when it is all whole numbers with at most 20 distinct values (`CATEGORICAL_NUMERIC_MAX_CARDINALITY`).
  - A column becomes datetime only if every value passes a shape check and a parse.
- **Quality scan** (`services/quality.py`):
  - Checks: missing values, placeholder codes, invalid emails or web addresses, untrimmed whitespace, blank strings, case variants (only if folding actually merges groups), more than 25 categories, empty rows, duplicates.
  - A numeric placeholder is flagged only if all three hold:
    - it is a known code (`-1, -9, -99, -999, -9999, 999, 9999, 99999, -111111`)
    - it appears at least twice
    - it lies outside Q1 − 3·IQR or Q3 + 3·IQR
- **Cleaning policy:**
  - Trim, blank-to-null, case normalization and dropping empty rows are applied automatically.
  - Missing values are asked about only when they affect a group-by column and reach 5% or more; below 5% they are disclosed instead.
  - Every cleaning operation declares a risk tier (SAFE, VALUE_CHANGING or AMBIGUOUS) and whether it removes rows.

**Closest prior work:** profiling libraries such as ydata-profiling and Great Expectations; LIDA's data summarizer, which also builds a compact profile for the LLM; NL4DV's attribute-type inference.

**Verdict: custom but incremental.** The individual techniques (modal field counts, IQR fences) are standard. The combination of a placeholder having to be a known code *and* repeated *and* an outlier, protecting "NA" in code columns, and disclosing every guess is careful engineering, not a research contribution. In the paper it belongs in the system section, not the contributions list.

### 3.2 Visualization selection

**What it does:** `recommend_chart_type` in `services/charts.py` runs only when the user did not name a chart. It is an ordered decision list where the first matching rule wins:

1. No numeric column → refuse.
2. Trend + date → line, coloured by category.
3. Trend + ordered category → line.
4. Relationship + at least 2 numeric columns → scatter.
5. Composition → donut.
6. Ranking → sorted bar.
7. Distribution or relationship + at least 2 categories → heatmap.
8. Distribution with no category → histogram; with a category → bar of counts.
9. At least 2 categories → grouped bar.
10. One category → bar.
11. Date only → line.
12. Trend with numbers only → line.
13. At least 2 numeric columns → scatter.
14. A single row → refuse.
15. Otherwise → histogram.

**Guards applied after selection:**
- Colour series: at most 8 (3 for scatter). Pie and donut warn above 6 slices and refuse negative values or a zero total.
- At most 2 group-by keys and 12 facets.
- More than 25 categories → offer top 10 plus "Other".
- **Skew** (`services/skew.py`): triggers when max/median is at least 25, or the middle half of the data spans at most 3% of the axis.
  - Line and scatter switch to a log scale (symlog when there are zero or negative values).
  - A heatmap's colour scale is rescaled.
  - Bar, area and histogram get a notice only.
  - Data is never dropped, and a scale is never changed without a notice.
- Seven forbidden modifier combinations (`services/chart_modifiers.py` `modifier_conflicts`).
- Ten chart families plus modifiers (orientation, stacking, normalization, interpolation, error bars, time unit) replace more than twenty separate type names.

**Closest prior work:** Mackinlay's APT and Show Me, Voyager's CompassQL rules, and Draco (weighted constraints learned from perception studies).

**Verdict: standard technique.** It is a hand-written rule table keyed on intent and column types. Its docstring says it "scores", but nothing is scored. What *is* distinctive is the policy of keeping chart choice out of the LLM (DracoGPT shows LLM preferences diverge from perceptual guidelines) and disclosing every degradation (skew, nulls, slice count) instead of silently fixing it. Frame it as a design decision, not an algorithm.

### 3.3 Chart ranking

**Not built.** No code path generates several candidate charts and orders them. The nearest things are:
- the first-match rule order above;
- `chart_fallback` (`agent/nodes.py`), which produces a plain bar chart when generation fails;
- ordering of clarification options (cleaning proposals by affected fraction, metric options by cardinality in `_rank_by_cardinality`).

**Closest prior work:** DeepEye, VizML, Voyager's recommendation list, Draco's cost ranking, InsightLens's interestingness scoring.

**Verdict: not a contribution; do not claim it.** If the team wants one, the cheapest credible version would rank the recommender's top-k candidates with Draco-style perceptual costs and compare them with the single rule choice.

### 3.4 Insight detection

**Automatic insight mining is not built.** Nothing scans the data for trends, outliers, correlations or anomalies and proposes them. The LLM writes a 2–5 sentence summary of a result the user already asked for (`_COMPOSE_SYSTEM`). Skew and placeholder detection find data problems, not insights.

**What is built is the number-grounding check** (`services/grounding.py`), which checks every number in the summary against the actual result.

1. **Collect the accepted numbers** (`grounded_values`): numeric result cells, years from timestamps, row and input/output counts, preprocessing counts, numbers inside notices, filter values and the plan's limit.
2. **Extract the numbers from the prose**, ignoring markdown table rules and sentence-ending full stops. Dates are matched by calendar day.
3. **Accept a number** if it is:
   - a year present in the data; or
   - a whole number from 0 to the larger of the row-count ceiling and 12; or
   - a source value at scale ×1, ×100 or ×0.01 (`_SCALES`, which covers percentages and rates), after rounding **the data to the precision the prose used** (`_supported`, `_EPS = 1e-9`).
4. **If any number is unsupported**, the prose is replaced by a deterministic template (`_template_answer`), and the event is logged as `ungrounded_answer`.
5. **Above 2,000 result cells** (`MAX_GROUNDABLE_CELLS`) the check is skipped, and the benchmark reports that coverage separately.

A companion check (`services/fidelity.py` `unmet_requests`) adds a notice when the chart did not honour something the user asked for: a log scale, a named chart type or sub-type, or a sort order.

**Measured:**
- 29 of 32 composed answers were small enough to check, and 0 were flagged (an earlier version wrongly flagged 3 of 32).
- In the planner comparison, the check replaced 12%, 7.2% and 1.3% of summaries for the base, Gemini and fine-tuned planners respectively.

**Closest prior work:** Foresight and QuickInsights (automatic insight mining, which is a different problem); fact-checking and attribution work in data-to-text generation; LIDA and MatPlotAgent, which repair *code*, not prose.

**Verdict: insight detection is not a contribution. The grounding check is a candidate contribution**: it is deterministic, tolerant of scale and rounding, and has a deterministic fallback, so no unsupported number reaches the user. To make the claim strong, report a small labelled set of injected wrong numbers (recall) alongside the measured false-positive rate.

### 3.5 Dashboard layout

**There is no layout algorithm.**
- **Placement** (`frontend/src/lib/chartWidgets.ts` `placement`): two fixed columns of 400×280 px cards with gaps of 20 px across and 40 px down, starting 24 px from the corner, continuing from the current card count. It does not consider chart type, importance, relationships between charts or packing.
- **Editing:** users drag and resize freely (minimum 280×200; `components/canvas/ChartWidget.tsx`). A refined chart keeps its position, size and styling.
- **Autosave:** 1.5 s after the last change (`hooks/useDashboard.ts`). The change check (`lib/dashboardSync.ts` `persistSignature`) covers layout and spec version but deliberately not the spec, because the spec holds the data rows.
- **Sharing:** a public flag plus a `/shared/{id}` link.
- **Export:**
  - PNG via html2canvas.
  - PDF via a hand-written single-page PDF writer (`lib/pdf.ts`), which prefers lossless Flate compression and falls back to JPEG.
- **Accessibility:** a data-table view of up to 500 rows, and a plain-English chart description built from the plan without an LLM (`lib/chartDescription.ts`).

**Closest prior work:** MultiVision and Calliope (automatic multi-chart layout and story ordering).

**Verdict: not a contribution; do not claim it.** It is a usable product feature; mention it under interaction, not novelty.

### 3.6 LLM prompting and agent architecture

**What it does**
- **Graph** (`agent/graph.py`, LangGraph):
  - Parent graph: `load_context` → `detect_ambiguity` ⇄ `clarify` → `classify_intent` → one worker per task via `Send` → `compose_response`.
  - Worker subgraph: `plan` → `assess_quality` → `execute` → (`confirm_preprocessing` | `chart_fallback`) → `finalize`, with loops back to `plan` on INVALID_PLAN or TYPE_MISMATCH.
- **Three human-in-the-loop interrupts:** clarification, choosing a cleaning option, and confirming a large row removal.
  - When several workers pause at once, `agent/service.py` groups their questions by a hash of kind and content and resumes them together.
  - The user is not asked the same question twice.
- **Checkpointing:** in memory, or Postgres when configured (`storage/checkpoint.py`).
- **Budgets** (`agent/state.py`): every loop has a limit, so the graph always terminates.
  - `MAX_PLAN_ATTEMPTS = 2` repairs after the first plan, so at most 3 planner calls per task.
  - `MAX_TASKS = 6`.
  - `MAX_CLARIFICATIONS = 2`, `MAX_CONFIRMATIONS = 2`, `MAX_CLEANING_PROMPTS = 2`.
  - 1 execution retry with a 0.25 s backoff.
- **Prompts** (`llm/client.py`):
  - `_CLASSIFY_SYSTEM`:
    - one task by default, at most 6, never one task per statistic;
    - any question it raises must use a JSON schema with 2–5 options that resolve to real columns;
    - the user's request is treated as data, not as instructions.
  - `_PLAN_SYSTEM`: the full plan grammar guide (about 18k characters); schema columns only; no chart unless the user named one; on retry, change only what the errors require.
  - `_COMPOSE_SYSTEM`: 2–5 sentences, every number grounded, rules for each notice severity.
  - `_STYLE_SYSTEM`: a presentation-only patch with a fixed set of keys.
- **Prompt-injection defence:** all user and file text passes through `services/safety.py` `neutralize_text`, which strips instruction-override phrases, role markers and ChatML tokens and caps length.
- **Model independence:**
  - The planner model is chosen with `init_chat_model` at temperature 0 (Gemini by default; OpenAI also supported).
  - The same tools are exposed over MCP (`mcp/server.py`): 19 tools, 4 resources, 3 profiles of 8, 12 and 19 tools.
- **Fine-tuned planner** (companion `AutoViz-Planner-Model` repo, Doc 17):
  - Qwen3.5-4B trained with QLoRA (r=16, α=32) on 2,772 training examples.
  - A training example is kept only if the app itself validates and executes the plan, so the application acts as the labelling oracle (rejection sampling).
  - Inference uses a 375-character prompt stub instead of the full guide.
  - Result: acceptable outcomes rose from 53 to 94 out of 100, versus Gemini's 96 (McNemar p = 0.75).

**Closest prior work:** LIDA and Chat2VIS (LLM writes code); MatPlotAgent (code plus a visual critic); Data Formulator and DynaVis (structured intermediate representations); NL4DV (rule-based analytic specs); rejection-sampling fine-tuning (RFT).

**Verdict: the agent framework is standard; the confinement policy is the core idea.**
- LangGraph fan-out, interrupts and checkpointing are off the shelf. Typed JSON plans validated with retry are now common: DynaVis, Data Formulator and InsightLens all use structured intermediate representations.
- What is specific to AutoViz is the *combination*:
  - the planner sees no data rows;
  - the plan grammar is closed and has no escape into code;
  - the LLM cannot pick the chart;
  - questions are raised by deterministic detectors before any LLM call;
  - every loop has a budget.
- The fine-tuned planner is a secondary contribution: a small open model trained only on examples the app accepted matches the commercial teacher on this benchmark. It needs the held-out-dataset caveat already in the paper.

### 3.7 Validation mechanism to prevent incorrect charts

This is the most layered part of the system. Each layer stops a specific class of error *before* the user sees it.

| Layer | What it stops | Code |
|---|---|---|
| Closed plan grammar (Pydantic v2, `extra="forbid"`; 6 intents, 7 aggregations, 11 filter operators, 13 derive functions, 14 cleaning operations, 10 chart families; at most 2 group-by keys and 10 cleaning steps) | Invented operations, free-form code, unknown fields | `schema/analysis_plan.py` |
| Plan validator: columns exist and are not entirely null; aggregations only on numeric columns; sort on a column the query produces; **every chart channel must be produced by the query**; rules per chart type (e.g. histogram has no y, heatmap colour must be numeric); code-like names and values rejected | Hallucinated columns, type errors, axes not in the result | `services/validation.py` `validate_analysis_plan` |
| Re-plan loop: the rejected plan and the validator errors go back to the planner, at most twice | One-off LLM slips | `agent/nodes.py`, `errors.py` |
| Six deterministic ambiguity detectors (unsupported capability, unknown reference, ambiguous time column, ambiguous column reference, a value present in several columns, missing metric), plus checks on LLM-proposed questions (every option must resolve to real data) | Confidently answering the wrong question; asking a question that cannot be answered | `agent/ambiguity.py` |
| Capability check: forecasting, statistical models and joins are declined with the nearest supported alternative | Pretending to do what the grammar cannot | `_detect_unsupported_capability` |
| SQL safety: quoted identifiers, filter values bound as parameters, a CTE chain with row counts per step; 1 GB memory, 2 threads, 30 s watchdog | Injection, runaway queries | `services/execution.py` |
| Consent: cleaning carries risk tiers; removing more than 30% of rows needs approval, and the approval is **tied to a sha256 of the dataset plus the exact preprocessing block** | Silently discarding data; an approval being reused for a different operation | `_confirmation_gate`, `preprocessing_version` |
| Chart guards: skew, nulls, pie validity, slice and colour caps, forbidden modifier combinations, always with a notice | Misleading or unreadable charts | `services/charts.py`, `services/skew.py`, `services/chart_modifiers.py` |
| Grounding check on the prose (§3.4) | Numbers in the summary that the data does not support | `services/grounding.py` |
| Fidelity notices (§3.4) | A chart that ignores a stated preference | `services/fidelity.py` |

Two of the ambiguity detectors (aggregation and time grain) were **removed** because measured over-asking rose to 25%. That is an evidence-driven design decision worth mentioning in the paper.

**What is not done at runtime:** validation against the official Vega-Lite JSON schema, and render checks, run only in the test harnesses (§3.8), not in production.

**Closest prior work:** LIDA's self-repair and MatPlotAgent's visual critic (fix *after* code runs); constrained decoding and SQL validators in text-to-SQL; DynaVis and Data Formulator (structured specs).

**Verdict: strongest contribution.** Individually, each layer resembles something known. Together they make a single contract in which an incorrect chart can arise only from a *semantically wrong but valid plan*, and the plan editor makes that error visible. The failure taxonomy in the paper (57 of 97 failures are valid-but-wrong plans; hallucinated columns, axes absent from the query and invalid specs were all caught) is the evidence for that claim.

### 3.8 Evaluation methodology

**What it does**
- **Frozen NL suite** (`backend/bench/nl_suite.py`, `nl_run.py`; `validations/run_nl_suite.py`):
  - 100 prompts over 6 tables. The first 39 are hash-pinned, so editing one fails CI.
  - The other 61 were screened for overlap with the fine-tuning corpus.
- **Scoring by properties, not exact plans:** a case asserts only properties every correct answer must have:
  - `must_columns`, `any_of` (interchangeable columns such as `pclass` and `class`), `forbid_columns`;
  - aggregation, intent, chart family;
  - whether a filter or limit is present.

  Columns used inside cleaning steps count as used.
- **Six outcomes:** correct, asked, declined, over-asked, wrong and failed. *Acceptable* means correct, asked or declined; wrong and over-asked are always reported on their own.
- **Ambiguity suite** (`backend/bench/ambiguity_suite.py`): 58 labelled prompts, 30 that should trigger a question and 28 that should not. It reports recall, over-asking, slot accuracy, bind rate and grounding violations together.
  - Detectors alone: 17/17 on cases the detectors can reach, 0/28 over-asked.
- **Chart quality in four layers** (Doc 28):
  1. Type choice on 14 data shapes: 14/14.
  2. Spec validity against the official Vega-Lite v6 schema: 10/10 (`bench/chart_quality.py`, `jsonschema`). This layer found that every boxplot was invalid.
  3. Render scenegraph checks: 17/17 (`frontend/scripts/verify-specs.mjs`). The real Vega runtime draws each spec headlessly, and the checks assert on the drawn marks: grouped bars not stacked, normalized stacks fill every column, donut inner radius, labels present or absent, no default palette leaking through, data rows inline. A **mutant spec file proves each check fails when its modifier is removed.**
  4. Legibility guards: 3/3.

  Edge-case data found 4 silent defects: a one-point line was invisible, a negative pie swept backwards, a zero-sum pie was blank, and an all-null measure drew two full-height bars.
- **External benchmarks** (`validations/`):
  - nvBench gold: all 7,247 reference charts reproduced from gold SQL. This tests execution fidelity, not NL accuracy.
  - nvBench and VisEval NL samples, scored structurally and **at the value level** against the gold `x_data` and `y_data`. Value-level scoring exposed one structural false positive (yearly binning omitted).
- **Statistics:** Wilson 95% intervals, McNemar's test, latency median and IQR.
- **Systems testing:** performance and scaling (`bench/perf.py`), Locust load tests, security, failover and integrity suites; about 1,083 backend tests.
- **Measuring the measurement:** the harness found 8 defects that the unit test suite missed (Doc 24 §6).

**Closest prior work:**
- VisEval (validity, legality and readability, with an LLM judge; it also accepts any feasible answer);
- PandasPlotBench (warns against diffing specs);
- nvBench and nvBench 2.0 (ambiguity-aware gold);
- ad-hoc user studies in LIDA and Chat2VIS.

**Verdict: strong contribution, credited honestly.** Property-based scoring that accepts any feasible answer is credited to VisEval. The incremental parts are:
- scoring a clarification or decline as acceptable, while reporting wrong answers and over-asking separately;
- measuring the clarification gate on both sides, with deliberate negative cases;
- render-level geometric checks with mutation testing, which go beyond schema validity;
- value-level legality scoring against gold data;
- grounding coverage as a reported metric.

Caveats the paper must keep:
- The nvBench NL runner answers clarifications automatically (the first option, or "skip"), which steers the result.
- The VisEval runner uses AutoViz's own scorer, not the official VisEval evaluator, so there is no readability score.
- The external samples are small (13 and 20 cases).

---

## 4. Recommended contribution statement for the paper

Three to four contributions, in this order, each backed by code and a measurement:

1. **A plan-confined architecture.** The LLM proposes only a closed-grammar, user-editable analysis plan and never receives data rows. Deterministic code validates, executes, charts and fact-checks it. Evidence: all 7,247 nvBench gold charts reproduced; the failure taxonomy shows schema and spec errors fail closed before rendering.
2. **Layered correctness guards with consent and grounding.** Six pre-LLM ambiguity detectors, a schema- and type-aware validator with a bounded repair loop, consent tied to a hash of the preprocessing for large row removals, and a number-grounding check with a deterministic fallback. Evidence: 17/17 detector recall at 0/28 over-asking, 0 unsupported numbers reaching users, and grounding replacement rates per planner.
3. **An evaluation methodology for trustworthy NL2VIS.** Property-based scoring with six outcomes (including over-asking), value-level legality against gold data, and render-level chart checks with mutation testing. Evidence: 4 silent rendering defects and 8 harness-found defects that 759 unit tests missed.
4. *(Secondary)* **A 4B planner fine-tuned only on examples the app accepted**, which matches the commercial teacher (94 vs 96, p = 0.75) with a 375-character prompt.

Do **not** list chart ranking, insight detection, dashboard layout, profiling, or the chart-selection rules as contributions.

---

## 5. Claims that must be corrected or qualified

These came up while checking the code. Each one is checkable by a reviewer with the repository.

**Status (2 Oct 2026):** items 1 and 2 are fixed in `conference-paper/autoviz-conference.tex`.
- Item 1: the abstract, the RQ4 hypothesis and the failure-taxonomy paragraph now say "chart-encoding errors", and schema validation is attributed to the test harness.
- Item 2: the Planner-Executor-Critic sentence is removed.

1. **"Every specification is validated against the official Vega-Lite v6 schema before rendering"** (paper, Section IV, Visualization techniques). This is false at runtime: schema validation runs only in `backend/bench/chart_quality.py`, and there is no `jsonschema` or Vega-Lite schema check anywhere in `backend/src` or `frontend/src`. Either reword it to "every chart type's specification is validated against the official Vega-Lite v6 schema in the test harness", or add a runtime check.
2. **The Planner-Executor-Critic comparison** (paper, RQ4 paragraph: "55/72 in both … 8% total runtime").
   - The PEC code (`critic`, `repair`, `sanitize_plan`, `services/plan_repair.py`, the `AUTOVIZ_AGENT_ARCHITECTURE` switch) exists only on the local `agent` branch (commit `245443b`, dated 5 Sep). It is not on `main`, and `main` ignores the switch.
   - The comparison ran on 29 Aug (`validations/exports/compare_*`). The exports contain no trace that critic or repair nodes executed.
   - It is therefore **unverified** whether the two runs exercised different code. Identical correctness on every pack is consistent with the same code running twice.
   - Either re-run from the `agent` branch with a node trace, or remove the sentence.
3. **"The planner never receives data rows"** is true, but the summary step sees up to 25 aggregated rows and the classifier sees up to 50 distinct low-cardinality values. The limitations section already says the first part; keep both.
4. **"Recommender scores candidates"** (the docstring in `services/charts.py`): nothing is scored. Do not describe it as scoring or ranking in the paper.
5. **"Four ambiguity detectors"**: the code has six. Use six, or name the four the paper discusses as examples.

---

## 6. What would make the novelty stronger (if time allows)

| Addition | Effort | What it would let the paper claim |
|---|---|---|
| Same-model ablation: the same LLM writes pandas/matplotlib code instead of a plan, on the 100-request suite | 1–2 days | A direct test of "plans beat code" rather than an argument from the literature |
| Inject wrong numbers into summaries and measure grounding recall | Half a day | The grounding check as a measured contribution, not only a design |
| Runtime Vega-Lite schema check (`jsonschema` against the pinned v6 schema before returning a spec) | Half a day | Makes the current paper sentence true |
| Re-run Planner-Executor-Critic vs minimal from the `agent` branch with node traces | Half a day | A valid architecture comparison, or the sentence is dropped |
| Official VisEval evaluator on the same 20 cases | 1 day | Comparable readability and legality numbers |
| Draco-cost ranking of the recommender's top-k candidates | 2–3 days | A real chart-ranking component, if the team wants that area |
| A small within-subjects user study (5–8 participants) | 1 week | Trust and verification claims, currently future work |
