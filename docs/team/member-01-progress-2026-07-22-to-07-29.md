# Member 01 — Progress Log: 22–29 July 2026

**Member:** K.S.H. Daishika (230112C) · MCP, LLM orchestration, and system integration
**Period:** Wednesday 22 July 2026 → Wednesday 29 July 2026
**Repository:** `codevector-2003/AutoViz-Visualizer`

## Summary

| Metric | Value |
|---|---|
| Non-merge commits | 30 |
| Pull requests merged | 8 (#3, #4, #5, #6, #7, #9, #14, #16, #18, #21) |
| Pull requests open | 1 (#22) |
| Backend test count | 371 → 463 passing |
| MCP tools exposed | 8 → 19 |

Days 1–2 built the verifiable core, days 3–4 turned it into a real service, days 5–6 made it usable, and days 7–8 hardened the parts that were quietly wrong. Four of the fixes landed this week — the `LIMIT 100` truncation, the bypassable confirmation gate, name-based op inference, and post-cleaning null accounting — were bugs that produced *plausible-looking but incorrect output*, the worst failure mode for a data tool.

---

## Wednesday 22 July — the MCP core

### 1. AutoViz MCP server + validated analysis-plan pipeline
`91e6a88` · ~2,349 lines

The foundation of the whole product. Instead of a mock backend, this built a real pipeline: pandas profiling → DuckDB execution → Vega-Lite generation.

- The `analysis_plan` is a Pydantic v2 model acting as the single source of truth. Allow-lists (filter ops, aggregation functions, chart types) are enforced **structurally** as `Literal` types at parse time — an invalid plan cannot be constructed, rather than being caught later by a validator someone might forget to call.
- Execution compiles a plan into DuckDB SQL as a pure function over a closed grammar, with quoted identifiers and bound parameters. This is what makes "every number comes from a deterministic SQL query" true rather than aspirational.
- 33 tests against real files (iris, titanic, penguins, diamonds at 53.9K rows). Caught a pandas 3.x bug where text inferred as the new `str` dtype silently skipped datetime detection.

### 2. Repository restructure into `backend/`
`b86bf5a`

Moved all Python under `backend/` to make room for the frontend track, and split into adapter packages (`mcp/`, `llm/`, `api/`) so business logic in `services/` stays adapter-agnostic. This is what later allowed the FastAPI routes to reuse the *exact* functions the MCP tools call.

### 3. Widened the analysis grammar + dataset lifecycle
`67ac680`

Added `gte`/`lte`/`in`/`between` filters, `median`/`count_distinct` aggregations, more derive functions, and area/histogram charts. Also chart export to self-contained HTML with slug-sanitised filenames confined to `backend/exports` — a path-traversal guard, not just tidiness. 24 new tests.

### 4. LangGraph agentic workflow with the Gemini planner
`319dda9` · ~2,047 lines

The agent layer: classify/split intent → `Send` fan-out into parallel analysis workers → each does plan → `run_pipeline` → repair loop (max 2 repairs on `failed_step`). Clarification interrupts are resumable by `thread_id`. The planner sits behind a `PlannerLLM` protocol so tests run offline with a scripted `FakePlanner` — no API key needed in CI.

---

## Thursday 23 July — making it trustworthy

### 5. Observability + prompt-injection defence
`2d5b9b3`

Per-call logging for every MCP tool, and neutralisation of untrusted text before it reaches the LLM. Since datasets are user-uploaded CSVs, a column name or cell value is an injection vector — this treats dataset content as hostile input.

### 6. Structured error handling and retry logic
`fa66254`, `e6bcc03`

The pipeline returns structured errors naming the *failed step* instead of raising exceptions, so the agent's repair loop knows what to fix. Outcome classification then captured error codes, plus end-to-end Titanic workflow tests.

---

## Friday 24 July — the HTTP backend, shipped as four stacked PRs

Split deliberately so each piece could be reviewed on its own.

### 7. Storage foundation + auth (PR #3)
`e866aa7`

- Lazy, rebuildable DB engine so offline tests can point `DATABASE_URL` at SQLite while production stays on PostgreSQL — portable column types keep the schema identical.
- PBKDF2-HMAC-SHA256 folded into a single self-describing hash string (`pbkdf2_sha256$iterations$salt$hash`), sized to fit the *existing* `users.password_hash` column: no schema change, no bcrypt/passlib dependency.
- Bearer tokens stored in the existing `sessions` table. New models `SavedChart`, `Dashboard`, `DashboardWidget` + Alembic migration 002 (upgrades and downgrades cleanly on both SQLite and PostgreSQL).

### 8. Stateless analysis, charts, and agent routes (PR #4)
`8016d2b`

Thin adapters over the same layer-4 services the MCP tools use — only the HTTP status is chosen at this layer, via `api/errors.respond()`. One implementation, two protocols.

### 9. Dataset routes with session-isolated uploads (PR #5)
`dc42967`

Owner-scoped upload / schema / profile / preview / list / delete. The important detail: `repository.resolve_dataset` lazily re-registers a dataset from its upload file **keeping the durable id** if it fell out of the in-memory registry after a restart — so a server restart doesn't break the user's saved work. Uploads land under `UPLOAD_DIR/<user_id>/<uuid>.csv` with a best-effort TTL sweep.

### 10. Saved charts + dashboard CRUD (PR #6)
`3520994`

The persisted-artifact layer the frontend canvas needs: owner-scoped saved charts and dashboards with positioned widgets. Dashboards reject widgets that reference charts the caller does not own.

### 11. Docker support
`7aa51c9`, `bb0f9d0`

Dockerfile, entrypoint, and `.dockerignore`. `AUTOVIZ_PLANNER_MODEL` is passed through as env so the planner model can be swapped per-deployment without rebuilding the image.

### 12. Fixed silently-wrong charts — *bug*
`1ef68c9`

`limit` defaulted to 100 and execution applied it as a hard `LIMIT 100`, so non-aggregated queries — distribution histograms and scatter plots — were binned from **only the first 100 rows**. The chart looked fine and was wrong. `limit` now defaults to `None` ("no explicit cap"): execution returns the full result up to `HARD_ROW_CEILING`, while an explicit limit ("top 10") is still honoured. Regression tests: a limitless distribution over titanic returns all 891 rows.

---

## Friday–Saturday 24–25 July — agent intelligence

### 13. Ambiguity resolution via grounded clarifying questions (PR #7)
`12b5276`

Replaced single-shot, prompt-only clarification with **deterministic detectors** that run over request × schema × profile *before* the planner LLM:

| Detector | Fires when |
|---|---|
| `time_column` | temporal ask, more than one datetime column, none named |
| `missing_metric` | a superlative with no measure named (options ranked by profile cardinality, so `fare`/`age` beat 0/1 codes) |
| `column_reference` | a concept word matching more than one column, none named in full |
| `value_reference` | a literal that is a value in more than one column |

Each detector emits grounded options (real columns and values), and `bind_answer` maps the reply to an exact plan slot — so a clicked option **provably** steers the plan rather than nudging a prompt. Bounded multi-round loop (`MAX_CLARIFICATIONS` 1 → 2); the prior LLM-authored path is preserved as a fallback. 44 tests.

### 14. Provenance-tracked preprocessing layer (PR #9)
`1b53837`

Opt-in cleaning that **never mutates the source CSV** — it runs as a per-analysis, read-only DuckDB CTE working view ahead of filters/derive/aggregate.

- Ops: `drop_nulls` (any/all), `fill_nulls` (constant/median/mode), `drop_exact_duplicates`, plus `is_null`/`is_not_null` filters. Deliberately **no mean imputation**.
- A >30% row-removal confirmation gate keyed by a content hash of the preprocessing block — approval is bound to *what was approved*, not a boolean someone could flip.
- Reports per-op `rows_affected`, `input_rows`/`output_rows`, the exact SQL, and implicit null exclusions for null-skipping aggregates.

### 15. Categorical-numeric detection and row limits
`a33431d`, `4c9af08`

Numeric-coded categoricals (`pclass`, `survived`) were being treated as continuous measures. Row limit for analysis plans raised and capped at 100,000.

---

## Sunday 26 July — charts and durability

### 16. Typed MCP result envelope + error taxonomy (PR #14)
`c57a71d`

Every MCP tool returns structured content rather than a bare dict, and failures carry an error **code** instead of a free-text string. The same taxonomy feeds HTTP status mapping in `api/errors.py` and is recorded alongside each observability span.

### 17. Interactive, themed chart library
`86de1b9` · ~2,397 lines · documented in [Doc 13](../13-Chart-Library-Expansion-Research.md)

Charts were six types rendered as bare Vega-Lite defaults — no params, no tooltip encoding, no config, no sizing. Now ten types (adds heatmap, boxplot, grouped bar, donut) with per-channel tooltips, legend-click series filtering, hover dimming, and scale-bound pan/zoom.

- Theming is baked in on the **backend**, not at embed time, because a spec handed to an MCP host or written into an exported file has no frontend to theme it.
- Two Vega-Lite constraints had to be gated around: a conditional opacity is per-datum so it fragments a line mark (→ no hover condition on line/area), and `bind:"scales"` needs continuous axes (→ no zoom on nominal or binned axes).
- `range.category` only feeds a colour scale, so single-series charts needed an explicit mark colour or they kept rendering Vega's default tableau blue.

### 18. Table view and brush-to-select
`1b5fdb1`, `236a137`

Toggle any chart to its underlying table; drag-select on dense charts filters the linked table. This is the "verify the number" affordance that backs the provenance claim.

### 19. Durable dataset payloads + bounded LRU registry cache (PR #16)
`25595a9`

Dataset payloads survive restarts, and the in-memory registry is bounded so a long-running server cannot grow without limit.

### 20. Wired the board to the real agent and dataset APIs
`57515c4`

Frontend stopped using mocks. Includes session-expiry handling: `apiRequest` raises an `autoviz:session-expired` event when the server rejects a token we believed was valid, so the app returns to the sign-in screen instead of leaving every subsequent action to fail with "Invalid or expired token".

### 21. Removed the orphaned cookie/JWT auth path
`56cbdf6` · −418 lines

A merge had left two auth systems in the tree. Bearer won; the dead one was removed rather than left to confuse the next reader.

---

## Monday 27 July — risk-tiered preprocessing (PR #18)

`a876d9d` · 36 files, ~4,000 lines

The largest piece of the week. Goal: *a user who does not know what imputation is still gets a correct chart, and a user who does can ask for exactly what they want.*

**Core idea:** consent is classified by **risk**, not by percentage. Percentage escalates within a tier but never demotes one — changing 1% of a revenue column can move a total, while trimming whitespace in 80% of labels cannot.

### Hardening that had to land first

Four genuine correctness/security defects made extending the layer unsafe:

1. **The confirmation gate was bypassable.** It lived in `run_pipeline`, but the code it guards lives in `execute_analysis`, which the MCP `execute_analysis` tool and `POST /analysis/execute` both reach directly — and a passing test had pinned the bypass as correct. Moved the gate into `execute_analysis`, beside the only function that can run the cleaning stage. *Enforce beside the code that does the thing, not a layer above it.*
2. **Five sites inferred op behaviour from op *names*, all defaulting to unsafe.** An unrecognised row-dropping op skipped the gate, survived "Skip cleaning", and crashed as a retryable error — so the agent looped forever on a plan that could never succeed. Ops now **declare** `removes_rows` / `risk` / `columns_touched()` on the model; omitting either is a definition-time `TypeError`.
3. **Approval is now bound to `(dataset_id + block)`**, not the block alone — consent is for a measured impact, and the same block on another frame may remove far more.
4. **`implicit_null_exclusions` was measured *after* cleaning**, so a `fill_nulls` that made an average 80% synthetic reported zero exclusions: the more misleading plan produced the cleaner-looking provenance. Now measured before.

Also: governors applied to `preprocessing_impact`; datetime constants validated at plan time rather than crashing as a retryable engine fault; confirmation loop budgeted; `ROW_DROP_NOTICE_FRACTION` wired up instead of sitting dead.

### New capability

- **SAFE ops** (auto-applied, reported): `trim_whitespace`, `empty_string_to_null`, `normalize_case`, `drop_empty_rows`, `cast_column`. **VALUE_CHANGING** adds `clean_categories` and `group_rare_categories`. Category cleaning is deliberately not SAFE — both merge values that were distinct.
- `services/quality.py`: deterministic scan and recommender, scoped to the columns the plan reads, so a messy unused column never interrupts. `clean_categories` is never auto-proposed — inferring "U.K." means "UK" is a guess, and a wrong guess silently merges two real categories.
- `assess_quality` worker node applies safe repairs silently and asks one plain-language question at a time. Missing values are only asked about for **dimension** columns: a null grouping key is a spurious category, but a null measure is already skipped and disclosed, and a null in a selected column is not plotted at all. An unreadable answer resolves to "do nothing", never to the recommendation.
- Read-only `analyze_data_quality` and `preview_preprocessing` (MCP + REST).
- Versioning is logical: `preprocessing_version` identifies the cleaned view without storing it. `materialize_cleaned_dataset` is the one opt-in write, persisted like an upload so a dataset the user owns cannot vanish on cache eviction.

**463 tests pass (was 371); frontend typechecks.**

---

## Wednesday 29 July — today

### 22. Fixed parallel interrupt resume (PR #21 — merged)
`288b99b`

A fanned-out request runs its tasks as parallel subgraphs, so two workers can call `interrupt()` in the same superstep. LangGraph rejects a bare `Command(resume=...)` when several interrupts are pending, and the service sent exactly that.

Real symptom: *"complete analysis about deck with other attributes"* on Titanic — `deck` is 688/891 null, so every worker hit the row-removal gate — failed with `"you must specify the interrupt id when resuming"`. `_interrupt_payload` compounded it by returning the first interrupt and silently dropping the rest, so only one question ever reached the chat.

**Fix:** concurrent pauses are grouped by the **decision** they represent rather than the worker raising them — confirmation by `preprocessing_hash`, cleaning choice by slot, clarification by question text. Each group gets an opaque `interrupt_id`; one decision is presented at a time alongside a `pending_count`, and the answer is broadcast to every worker asking it. Distinct questions queue instead of colliding.

Two LangGraph behaviours the fix depends on, both pinned by tests: `StateSnapshot.interrupts` keeps answered entries forever (a task's `INTERRUPT` pending write is never deleted), so live pauses are read off `task.result is None`; and once any resume-map is used, those hanging writes make a bare resume raise even for a single live interrupt, so `resume()` always builds a map.

Also fixed a latent MCP bug: `AnalyzeOutput` is `extra="forbid"` but never declared `cleaning_choice`, `slot`, `issue`, or dict-shaped options, so `unwrap()` raised on every cleaning pause. Raised `MAX_TASKS` 3 → 6 (the classifier prompt capped tasks at 3 independently, so the constant alone would have been inert).

### 23. Dashboard autosave + working Save button (PR #22 — open)
`f1e4566`

The canvas only ever existed in React state, so a reload lost it. All the persistence a dashboard needs was already built and tested on the backend, and `BoardPage` even had a `handleSaveDashboard` — but nothing called it, and `TopBar` rendered Save as a disabled "Coming soon" without ever declaring an `onSave` prop, so the wiring `BoardPage` attempted did not compile.

A dashboard now creates itself as soon as the first chart lands, named from the CSV, and every later change is pushed 1500 ms after the canvas settles — dragging a chart fires `onMove` per pointer frame, so without that debounce a single drag would be a hundred PUTs. The Save button flushes immediately and, the first time only, asks what the board should be called. A failed save is sticky: autosave stops rather than retrying against a backend that is down, and the button becomes Retry.

**Three races the design turns on:**

- `inFlight` is set synchronously before the first `await` — two overlapping first saves would each POST `/dashboards` and leave a duplicate board.
- The baseline signature is captured before the `await`, not after, so an edit made while a request is in flight stays dirty instead of being swallowed.
- `renameDashboard` hands the new name to `saveNow()` rather than reading it back, because `setDashboard` has not flushed by the time the save runs.

The engine lives in `lib/dashboardSync.ts` with no React in it, returning the ids it minted rather than mutating state. This is also the **first commit where the frontend builds** — it fixed the two `tsc -b` errors that were broken on main.

**Known gaps, deliberate:** deleting a saved widget orphans its `saved_charts` row (`DELETE /charts/{id}` cascades to widgets on other dashboards, so it is not a safe fix from here); there is no `PUT /charts/{id}`, though nothing in the UI edits a saved chart; and chart explanations still reload empty, as `SavedChart` has no field for them.

---

## Pull request index

| PR | Title | State | Diff |
|---|---|---|---|
| #22 | feat(frontend): autosave dashboards and make the Save button work | Open | +604 / −63 |
| #21 | fix(agent): resume parallel interrupts by decision, not by worker | Merged 29 Jul | +656 / −55 |
| #18 | feat(preprocessing): risk-tiered cleaning, automated repair, and materialisation | Merged 27 Jul | +3,988 / −249 |
| #16 | feat: durable datasets, bounded registry cache, real agent wiring in the board | Merged 26 Jul | +1,541 / −780 |
| #14 | feat(charts): interactive, themed chart library with table view and brush selection | Merged 26 Jul | +3,862 / −229 |
| #9 | feat(preprocessing): provenance-tracked preprocessing layer | Merged 25 Jul | +1,238 / −41 |
| #7 | feat(agent): ambiguity resolution via clarifying questions | Merged 24 Jul | +1,661 / −16 |
| #6 | feat(backend): saved charts + dashboard CRUD | Merged 24 Jul | +273 / −3 |
| #5 | feat(backend): dataset routes with session-isolated uploads + ownership | Merged 24 Jul | +539 / −22 |
| #4 | feat(backend): stateless analysis, charts, and agent routes | Merged 24 Jul | +835 / −62 |
| #3 | feat(backend): storage layer + auth foundation | Merged 24 Jul | +2,371 / −112 |

Teammates' PRs reviewed and merged into `main` during the period: #8, #19, #20.
