# 07 — AutoViz MCP Tool Inventory

Complete reference for the `autoviz` MCP server surface as implemented in
`backend/src/autoviz/mcp/server.py`. All business logic lives in `backend/src/autoviz/services/`;
the MCP tools are thin typed adapters over it (the same functions will back the FastAPI routes in
Week 3).

- **Run:** `uv --directory backend run python -m autoviz.mcp` (stdio transport)
- **Registry is in-memory, per process** — datasets must be registered each session; use
  `list_datasets` to recover ids instead of re-registering.
- **Typed output.** Every tool declares a Pydantic return model (`autoviz.mcp.results`), so each
  publishes a real `outputSchema` with named required fields and `additionalProperties: false`.
  A host can read `structuredContent["result"]["provenance"]["sql"]` programmatically instead of
  asking an LLM to interpret an untyped blob.
- **Error contract:** see [§ Error signalling](#error-signalling-iserror) below. Terminal failures
  set MCP's `isError: true`; negative-but-successful results (an invalid plan, a pending
  confirmation) stay ordinary successful calls carrying structured content.

## Error signalling (`isError`)

MCP separates two things that are easy to conflate. A *protocol* success carrying a negative
payload ("this plan is invalid", "confirm before I drop 688 rows") is a tool that **did** its job.
A *tool-execution failure* ("that dataset does not exist") is a tool that **could not**. Hosts use
`isError` to stop a chain, retry, show an error state, or skip downstream tools — so a failure that
reports itself as a success will be fed straight into the next call.

The rule, implemented once in `autoviz.mcp.envelope`:

> `isError: true` when the tool could not fulfil its contract. Structured negative results when the
> tool successfully determined the request was invalid, unsupported, or awaiting confirmation.

| Result | `isError` | Why |
|---|---|---|
| `{valid: false, errors}` from validation | `false` | The validator worked; the plan is wrong. Repair and retry. |
| `status: "confirmation_required"` | `false` | Nothing failed — the workflow paused for a decision. |
| `status: "waiting_for_user"` (agent) | `false` | Same, one layer up. Check `pause_kind`. |
| `status: "partial"` (chart step failed) | `false` | The query succeeded; `result` and its provenance are returned. |
| `recommended: false` | `false` | The recommender answered: nothing here is plottable. |
| `valid: false` from `generate_chart` | `false` | The spec was checked and does not fit the result table. |
| `UNKNOWN_DATASET` | `true` | Cannot operate on a dataset that is not registered. |
| `TIMEOUT`, `EXECUTION_ERROR` | `true` | The engine faulted. |
| `RESOURCE_LIMIT` | `true` | A hard ceiling was hit. |
| `FILE_ERROR`, `FORBIDDEN_PATH`, `INVALID_SPEC` | `true` | The input or target is unusable. |
| `CANCELLED` | `true` | The caller cancelled; no result was produced. |
| Agent `status: "failed"` | `true` | The workflow produced nothing usable. |

Because `isError` results have no `structuredContent`, the error code and its remediation travel in
the message text: `[UNKNOWN_DATASET] Unknown dataset_id: ds_9 Register the dataset first, then
reference the dataset_id it returns.` (This is a constraint of the SDK, not a choice — FastMCP
validates a returned `CallToolResult`'s `structuredContent` against the tool's *success* output
model, so an error-shaped payload cannot be attached to a tool that declares a typed output.)

Codes come from `autoviz.errors`, which also classifies each as plan-repairable / retryable /
terminal — see [Doc 10 §1](10-Validation-Security-Resource-Controls.md) for how the agent routes
replan vs retry vs stop on them. Internally the services still return structured dicts and never
raise; the translation to `isError` happens only at the MCP boundary, so the FastAPI routes keep
returning the same bodies.

## Surface at a glance

| # | Tool | Purpose |
|---|------|---------|
| 1 | `register_dataset` | Load a CSV, profile it, get a `dataset_id` |
| 2 | `list_datasets` | Enumerate registered datasets in this session |
| 3 | `unregister_dataset` | Remove a dataset and free its memory |
| 4 | `get_dataset_schema` | Column names + logical types |
| 5 | `get_dataset_profile` | Nulls, duplicates, cardinality, numeric stats |
| 6 | `preview_dataset` | First N rows as sanitized records |
| 7 | `validate_analysis_plan` | Check a plan against schema + allow-lists |
| 8 | `execute_analysis` | Deterministic DuckDB execution with provenance |
| 9 | `recommend_chart_type` | Rule-based chart recommendation |
| 10 | `generate_chart` | Build + validate a Vega-Lite spec |
| 11 | `run_analysis_pipeline` | validate → execute → recommend → generate in one call (**preferred**) |
| 12 | `export_chart` | Save a chart as a self-contained HTML file |
| 13 | `analyze` | **Agentic**: NL request → validated charts via the internal LangGraph workflow (see [Doc 08](08-Agentic-Workflow-Architecture.md)) |
| 14 | `answer_clarification` | Resume an `analyze` run paused on a clarification question |
| 15 | `analyze_data_quality` | Scan a dataset (optionally scoped to columns) → issues, auto-appliable SAFE ops, and proposals with exact counts. Read-only |
| 16 | `preview_preprocessing` | What a plan's cleaning block would do, before committing to it. Read-only |
| 17 | `materialize_cleaned_dataset` | Run a cleaning block and register the result as a new dataset. The **only** write tool in the preprocessing surface |

Plus **4 MCP resources** (`autoviz://docs/analysis-plan-guide`, `autoviz://datasets`,
`autoviz://datasets/{id}/schema`, `autoviz://datasets/{id}/profile`) and **1 MCP prompt**
(`analyze_dataset`).

### Tool profiles

The 17 tools span overlapping levels of abstraction, and a host's LLM must choose between them on
every turn ("execute_analysis, run_analysis_pipeline, or analyze?"). `AUTOVIZ_MCP_PROFILE` narrows
the surface:

| Profile | Tools | For |
|---|---|---|
| `advanced` (default) | all 17 | Development, testing, granular orchestration |
| `default` | `register_dataset`, `list_datasets`, `analyze_data_quality`, `run_analysis_pipeline`, `analyze`, `export_chart` | External hosts wanting one coherent path |

`analyze_data_quality` is in the `default` profile despite being a diagnostic: a host that cannot
see a dataset's problems plans around them badly, and this is the tool that makes the cleaning
decision explicit rather than guessed. It is read-only, so it is safe to expose everywhere. The two
`preview_preprocessing` and `materialize_cleaned_dataset` stay in `advanced`: the first is a
lower-level view of what `analyze_data_quality` already summarises, and the second is the one tool
in this group that creates something.

`advanced` is the default so an upgrade never silently removes a tool a host already calls. The
`default` profile is still a complete workflow on its own. An unrecognised value falls back to
`advanced`.

### Context size

The plan grammar is ~5.2k characters. It used to be embedded in all three plan-taking tool
descriptions — 15.5k characters, 83% of the whole `tools/list` payload, three copies of one
document sent at every session init. It is now published once as the
`autoviz://docs/analysis-plan-guide` resource, and the server's `instructions` tell the host to
read it once before building a plan. Total tool-description text: **18,690 → ~3,600 characters**
(~2,100 on the `default` profile). `tests/test_mcp_envelope.py` fails if it grows past 6,000.

---

## Dataset tools (Resource Gateway)

Cell contents are treated strictly as data — values are returned as inert JSON scalars, never
interpreted or executed. Beyond type-sanitization, all text values **and column names** emitted to
an LLM (`preview_dataset` rows, `execute_analysis` result tables, schema/profile) pass through
`services/safety.neutralize_text`, which defangs instruction-injection control markers ("ignore
previous instructions…", role tags, ChatML tokens, code fences, control chars). This is the
mitigation the MCP Server Architecture Patterns paper prescribes for its **Unsanitized Resource
Content** anti-pattern, and the concrete form of Proposal §4.7's "CSV cell contents treated strictly
as data". Neutralization targets control semantics only — ordinary values ("North America",
"2023-05-01") are byte-exact, and grouping/SQL always use the real underlying values, not the
neutralized copies.

### 1. `register_dataset(file_ref: str)`

Loads a CSV, infers logical column types (`number | boolean | datetime | string`, with automatic
datetime promotion for cleanly-parsing text columns), builds the profile, and stores the DataFrame.

- `file_ref`: absolute path, **or** a path relative to an approved data root. Default roots are
  `<repo>/test-data` and the repo root (so `"general-testing/iris.csv"` and
  `"test-data/general-testing/iris.csv"` both resolve). Override roots with the
  `AUTOVIZ_DATA_ROOTS` env var (path-separator-delimited). Traversal out of a root is rejected.
- **Resource limits** enforced before/at load: file size (50 MiB), column count (512), row count
  (1,000,000) — all env-overridable; exceeding any returns `error_code: RESOURCE_LIMIT`
  (Doc 10 §4.1).
- **Returns** `{dataset_id, row_count, column_count}`
- **Errors** `{error, hint}` (hint lists the approved roots) for missing files;
  `{error}` for unreadable CSVs; `{error, error_code: "RESOURCE_LIMIT"}` for oversized inputs.

### 2. `list_datasets()`

**Returns** `{datasets: [{dataset_id, source, row_count, column_count}]}` for the current process.

### 3. `unregister_dataset(dataset_id: str)`

**Returns** `{removed: true, dataset_id}` — or `{error}` for an unknown id.

### 4. `get_dataset_schema(dataset_id: str)`

**Returns** `{columns: [{name, type}]}` with logical types.

### 5. `get_dataset_profile(dataset_id: str)`

**Returns** `{null_counts, duplicate_count, cardinality, summary_stats}` —
`summary_stats` is pandas `describe()` per numeric column.

### 6. `preview_dataset(dataset_id: str, limit: int = 10)`

**Returns** `{rows: [...]}` — first `limit` rows (clamped to 1–50), `NaN`/`Inf` sanitized to
`null`, timestamps as ISO strings.

---

## The analysis-plan grammar (shared by tools 7, 8, 11)

The plan is a **closed grammar**: the LLM fills a validated form; anything outside the allow-lists
is a validation *error*, never a warning, and there is no raw-expression fallback. Single source of
truth: `backend/src/autoviz/schema/analysis_plan.py` + `allowlists.py`.

```jsonc
{
  "dataset_id": "<from register_dataset>",          // required
  "intent": "comparison" | "trend" | "distribution" // required
          | "relationship" | "composition" | "ranking",
  "select": ["col", ...],
  "filters": [{"column": "col",
               "op": "eq"|"neq"|"gt"|"gte"|"lt"|"lte"|"in"|"between"|"contains",
               "value": <scalar> }],                // "in": list of 1-20 scalars;
                                                    // "between": [low, high]
  "derive": [{"name": "new_col", "from": "source_col",
              "fn": "month"|"year"|"day"|"weekday"|"lower"|"upper"|"trim"|"round"|"abs"}],
  "group_by": ["col1", "col2"],                     // max 2
  "aggregations": [{"column": "col",
                    "fn": "sum"|"mean"|"min"|"max"|"count"|"median"|"count_distinct",
                    "as": "alias"}],
  "sort": [{"by": "col", "dir": "asc"|"desc"}],
  "limit": 100,                                     // max 100000 (over-limit is auto-clamped)
  "chart": {"type": "bar"|"line"|"scatter"|"pie"|"area"|"histogram",
            "x": "col", "y": "col", "color": "col"} // optional — omit to auto-recommend
}
```

Semantic rules enforced by validation:

- Every referenced column must exist in the profiled schema (derived columns become referenceable).
- Type contracts: `sum/mean/min/max/median` need numeric; `month/year/day/weekday` derives need
  datetime; `lower/upper/trim` need string; `round/abs` need numeric; `contains` needs string;
  `gt/gte/lt/lte/between` need numeric or datetime.
- Value shapes: `in`/`between` take lists (arity checked); every other op takes a scalar.
- `chart.x/y/color` may only reference columns the query **produces** (group_by columns +
  aggregation aliases, or select/derive names when there is no grouping). `histogram` requires a
  numeric `x` and takes **no `y`** (y is the binned count); every other type requires `y`.
- Anything resembling code/SQL/shell in filter values, derive names, or aliases is rejected.
- Unknown fields anywhere in the plan are rejected (`extra="forbid"`).

### 7. `validate_analysis_plan(dataset_id, analysis_plan)`

**Returns** `{valid, errors, repaired_plan?}`. `repaired_plan` appears only for the single
deterministic repair: clamping `limit` to 100000.

### 8. `execute_analysis(dataset_id, analysis_plan, approved_preprocessing_hash?)`

Re-validates (never trusts the caller), translates the plan to DuckDB SQL as a pure function —
quoted identifiers, all literals bound as `?` parameters — and enforces a hard 100000-row output
ceiling regardless of the requested limit.

**This is where the row-removal gate lives**, not in `run_analysis_pipeline`. It is the only
function that can apply a `preprocessing` block, so it is the only place a gate cannot be walked
around: this tool and `POST /analysis/execute` both reach the cleaning chain without going through
the orchestrator. Without a matching `approved_preprocessing_hash`, a block that would remove more
than 30% of rows returns `error_code: CONFIRMATION_REQUIRED` and nothing executes.

Execution runs under DuckDB governors — `memory_limit` (1GB), `threads` (2), and a wall-clock
timeout (30s, via `con.interrupt()`), all env-overridable (Doc 10 §4.2).

- **Returns** `{result_table, row_count, execution_time_ms, provenance}` where `provenance` =
  `{dataset_id, source, columns_used, filters, aggregations, chart_type, sql}` — the exact SQL, so
  every number is traceable. When a `preprocessing` block ran, provenance also carries
  `preprocessing[_sql]`, `implicit_null_exclusions` (measured *before* cleaning, so imputing cannot
  erase the disclosure it should trigger), `imputation_notices`, `preprocessing_version`, and a
  `cleaning` block collecting the whole account — columns inspected, per-step effect, input/output
  row counts, and `confirmed_by_user`.
- **Errors** `{error: "Plan failed validation", validation_errors, error_code: INVALID_PLAN|TYPE_MISMATCH}`,
  `{error, error_code: UNKNOWN_DATASET}`, or `{error, sql, error_code: EXECUTION_ERROR|TIMEOUT}` on an
  execution failure — the `error_code` tells the caller whether to replan, retry, or stop.

### 9. `recommend_chart_type(result_schema, intent)`

Rule-based (intent × column types): trend+temporal → `line`; relationship+2 numeric → `scatter`;
composition → `pie`; ranking → `bar`; distribution over numeric-only → `histogram`, over
categorical → `bar` of counts.

- `result_schema`: `[{name, type}]` of the **result** table (not the source dataset).
- **Returns** `{recommended: true, chart_type, x, y?, color?, rationale}` (`y` omitted for
  histogram).
- **No fit** `{recommended: false, rationale}` when the result has no numeric measure. This is a
  successful call, not an error — the recommender answered the question.

### 10. `generate_chart(result_table, chart_spec)`

Builds a Vega-Lite v5 spec with inline data; encoding types inferred from values (or an optional
`column_types` hint in the spec). Mark mapping: scatter → `point`, pie → `arc`,
histogram → binned `bar` (`bin: true` x, count y).

- **Returns** `{vega_lite_spec, valid, warnings}`. Structural problems (disallowed mark, channel
  referencing an absent column, histogram given a `y`) → `valid: false` with a null spec — a
  successful call reporting that the spec does not fit. Soft problems only warn: pie with
  > 6 categories, color with > 10 distinct values.

### 11. `run_analysis_pipeline(dataset_id, analysis_plan, approved_preprocessing_hash?)` — preferred

Orchestrates validate → execute → (recommend if `chart` omitted) → generate. Three outcomes, all
`isError: false`:

- **`status: "ok"`** — `{result, chart_spec, recommendation, vega_lite_spec, warnings}`
  (`recommendation` is `null` when the plan supplied its own chart).
- **`status: "partial"`** — the query succeeded but no chart could be built. `result` (with full
  provenance) and `failed_step` ∈ `recommend_chart_type | generate_chart` are both returned;
  partial results are never discarded. Internally `run_pipeline` still reports these as
  `status: "error"` so the LangGraph repair loop can route them to a chart fallback; the MCP
  boundary translates the status, because over the wire a fully-provenanced result table is not
  a failure.
- **`status: "confirmation_required"`** — the plan's cleaning step would drop more than
  `ROW_DROP_CONFIRM_FRACTION` (30%) of rows. Nothing executes. Returns
  `{confirmation: {question, options, impact, preprocessing_hash}}`; call again passing that
  `preprocessing_hash` as `approved_preprocessing_hash` to proceed. The token is
  `preprocessing_version(dataset_id)` = `pp_<12 hex>` over the dataset id **and** the canonical
  block — not a boolean, and not the block alone. Consent is given for a *measured impact*, so the
  same block replayed against a different dataset, where it may remove far more, re-gates. Fields
  whose order carries no meaning (`drop_nulls.columns`) are canonicalised, so a replan that merely
  reorders them does not re-prompt; the op list order is left alone, being genuinely semantic.
  `run_analysis_pipeline` only *translates* this outcome — the refusal itself came from
  `execute_analysis` underneath it.

Genuine failures (unknown dataset, timeout, engine fault) leave as `isError: true`.

**Progress and cancellation.** This tool and `analyze` are async and take an injected MCP
`Context`. The pipeline reports its five stage boundaries (validate → cleaning impact → execute →
select chart → build chart) as MCP progress notifications, and host cancellation propagates to
`con.interrupt()` so a cancelled query actually stops rather than running to completion unobserved.

### 12. `export_chart(vega_lite_spec, filename?)`

Writes a self-contained HTML page (vega-embed via CDN, spec inlined) to `backend/exports/` —
double-click to open in a browser. Filenames are slug-sanitized (`[a-z0-9_-]`, default
timestamped) and can never escape the exports directory.

- **Returns** `{path, filename}`. A spec that isn't a Vega-Lite dict, or a filename that would
  escape the exports directory, is `isError: true` (`INVALID_SPEC` / `FORBIDDEN_PATH`).

### 13–14. `analyze` / `answer_clarification` — the agentic path

`analyze(request, dataset_id?, file_ref?, thread_id?)` runs the internal LangGraph workflow:
its own planner LLM (Gemini by default, `GOOGLE_API_KEY` required) interprets the request,
generates/repairs plans against this same grammar, and executes through `run_pipeline`.

- **`status: "completed"`** — `{answer, charts, thread_id}`. Each entry in `charts` carries its own
  `status` (`ok | partial | error`), so a run can complete with some charts unbuilt.
- **`status: "waiting_for_user"`** — `{question, options, pause_kind, thread_id}`, answered via
  `answer_clarification(thread_id, answer)`. **`pause_kind`** distinguishes the three reasons a run
  pauses: `"clarification"` (an ambiguous request), `"cleaning_choice"` (a data-quality decision
  that would change values or drop rows — carries `slot`, `issue`, and *structured* options
  `{label, detail, technique, recommended}` rather than plain strings), or `"confirmation"` (a
  cleaning step that would drop more than 30% of rows, which also carries `preprocessing_hash` and
  `impact`). Without it a host cannot tell which decision it is putting to the user. A host that
  ignores the distinction still works — all three resume through the same call.
- A run that produced nothing usable is `isError: true`.

Reusing `thread_id` enables refinements. Full architecture:
[Doc 08](08-Agentic-Workflow-Architecture.md). The granular tools above remain the host-LLM path
and need no API key.

---

## Preprocessing tools

Consent for data cleaning is classified by **risk**, not by percentage. `SAFE` ops are
semantics-preserving and apply automatically; `VALUE_CHANGING` ops are confirmed at *any*
percentage; `AMBIGUOUS` ops are never proposed. Changing 1% of a revenue column can move a total,
while trimming whitespace from 80% of category labels changes nothing — so row count alone cannot
decide consent, it only escalates within a tier. Full rationale: [Doc 08 §9](08-Agentic-Workflow-Architecture.md).

All cleaning is expressed as `preprocessing` entries **in the analysis plan** — one write path. The
tools below inspect that path or, in exactly one case, commit its result.

### 15. `analyze_data_quality(dataset_id, columns?)` — read-only

Deterministic scan (no LLM) of the dataset, optionally scoped to the columns an analysis actually
reads. Returns `{row_count, columns_inspected, issues, auto_apply, proposals}`:

- **`issues`** — `{kind, column, affected, fraction, detail}` for missing values, duplicate rows,
  empty rows, whitespace/case variants, mixed types, and high cardinality.
- **`auto_apply`** — the SAFE ops that fix what they can without changing an answer, ready to paste
  into a plan's `preprocessing`.
- **`proposals`** — one plain-language question per remaining finding, each with options carrying
  exact counts, the underlying `technique` kept separate from the `label`, and one flagged
  `recommended`. The recommendation is a suggestion, never a default that applies itself.

Pass `columns` whenever you know what the analysis needs. A messy `comments` column must not
generate findings for "average salary by department".

### 16. `preview_preprocessing(dataset_id, analysis_plan)` — read-only

Runs the cleaning chain's impact measurement without executing an analysis: per-op `rows_affected`,
`input_rows`/`output_rows`, and whether the block would trip the 30% gate. Governed by the same
`memory_limit` / `threads` / timeout / cancellation as any other execution.

### 17. `materialize_cleaned_dataset(dataset_id, preprocessing, approved_preprocessing_hash?)`

The one tool here that creates something. Versioning is otherwise **logical**: a cleaned frame is
fully determined by (immutable source, ops), so `preprocessing_version` identifies it without
storing anything and every analysis carries its version for free. Nothing is materialized
implicitly.

This tool is for a user who wants to keep working *from* cleaned data. It runs the chain, registers
the result as an ordinary dataset recording `parent_id` / `version_id` in its profile's `lineage`,
leaves the parent untouched, and passes through **the same gate** — a 60% removal is no less
consequential for being deliberate. Returns a new `dataset_id` that can be previewed, charted,
exported, or cleaned further.

---

## MCP resources

| URI | Content |
|-----|---------|
| `autoviz://docs/analysis-plan-guide` | The full plan grammar (~5.2k chars). **Read once per session** before building a plan — the server's `instructions` say so, and the plan-taking tool descriptions point here instead of inlining it. |
| `autoviz://datasets` | JSON list of registered datasets |
| `autoviz://datasets/{dataset_id}/schema` | JSON column schema |
| `autoviz://datasets/{dataset_id}/profile` | JSON profile |

The last three are read-only mirrors for hosts that attach resources as context instead of calling
tools.

## MCP prompt

**`analyze_dataset(file_ref, question)`** — reusable host prompt walking the canonical flow:
register → schema/profile → read the plan-guide resource → build a plan →
`run_analysis_pipeline` (fix and retry on structured errors) → offer `export_chart`, reporting
numbers from `result_table` with their SQL provenance.

---

## Limits and safety summary

| Guard | Value / mechanism |
|-------|-------------------|
| CSV file size | max 50 MiB, checked **before** load (`AUTOVIZ_MAX_FILE_BYTES`) |
| CSV columns | max 512, checked from the header (`AUTOVIZ_MAX_COLUMNS`) |
| CSV rows | max 1,000,000 (`AUTOVIZ_MAX_ROWS`) |
| DuckDB memory / threads | `memory_limit` 1GB, `threads` 2 (env-overridable) |
| Execution timeout | 30s wall-clock via `con.interrupt()` → `error_code: TIMEOUT` (`AUTOVIZ_EXECUTION_TIMEOUT_S`) |
| Request cancellation | host cancel → `cancel_event` → `con.interrupt()` → `error_code: CANCELLED` |
| `group_by` columns | max 2 |
| `limit` | max 100000 (auto-clamped via `repaired_plan`) |
| Output rows | hard ceiling 100000, enforced in SQL regardless of plan |
| `in` list size | 1–20 values |
| Preview rows | 1–50 |
| SQL injection | structurally impossible: closed grammar, quoted identifiers, bound parameters, plus a rejection pattern for code-like values |
| Prompt injection (content) | LLM-facing text values + column names neutralized via `services/safety.neutralize_text` (instruction/role/ChatML/fence markers defanged, control chars stripped, length capped at 2000) |
| Path traversal | relative `file_ref`s resolve only inside approved data roots; exports only inside `backend/exports/` |
| Error taxonomy | every failure carries a typed `error_code` (+ `retryable`, `user_action`) — Doc 10 §1 |
| Exceptions | never thrown to the host — always structured error content |

Full detail: [Doc 10 — Validation, Privacy, Security & Resource Controls](10-Validation-Security-Resource-Controls.md).

---

## Observability

Every tool call is logged once by the `@observed` decorator (`autoviz/observability.py`), satisfying
Proposal §4.7's "logging of tool calls, validation failures, execution steps, chart provenance" and
the MCP Server Architecture Patterns paper's cross-cutting logging guidance. Each record is a single
JSON line:

```json
{"tool": "execute_analysis", "input_hash": "a3f19c...", "ms": 12.4, "out_bytes": 880, "outcome": "ok"}
{"tool": "execute_analysis", "input_hash": "77b0e2...", "ms": 0.3, "out_bytes": 120, "outcome": "error", "error_code": "UNKNOWN_DATASET"}
```

- **`input_hash`** — SHA-256 (12 hex) of the JSON-serialized arguments. Only the hash is logged, so
  raw cell values and file paths never enter the log.
- **`outcome`** — derived from the tool's structured return, never from an exception: `ok` |
  `error` (has an `error` key) | `invalid` (`valid: false`) | `failed` (`status: "error"`, plus the
  `failed_step`). This is how "validation failures" and pipeline step failures surface in the log.
- **`error_code`** — on any failed outcome, the typed taxonomy code (`autoviz.errors`) is echoed
  into the record, so a plan defect vs. an infrastructure fault vs. a resource limit is visible at a
  glance (Doc 10 §1, §5).
- **Sinks** — stderr **and** a rotating file (`backend/logs/autoviz.log`, gitignored). **Never
  stdout**: stdio transport reserves stdout for the JSON-RPC channel, so a stray stdout write would
  corrupt the protocol handshake. `configure_logging()` is called from `autoviz/mcp/__main__.py`.
