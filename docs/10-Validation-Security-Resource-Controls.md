# 10 — Validation, Privacy, Security & Resource Controls

The controls that make AutoViz safe to point at an untrusted CSV and an LLM at the same time, as
**implemented** in `backend/`. This is the reference for Proposal §4.7 (validation, privacy,
logging, injection) and the MCP Server Architecture Patterns anti-patterns. Every item below is
enforced in code and covered by tests.

## 1. Validation — the closed-grammar guard

The analysis plan is a **closed grammar**, not free text: the LLM (or a host) fills a typed form
and anything outside the allow-lists is a hard **error**, never a warning, with no raw-expression
fallback. Source of truth: `schema/analysis_plan.py` + `schema/allowlists.py`; semantic checks in
`services/validation.py`.

Two enforcement stages:

1. **Structural** (Pydantic, `extra="forbid"`): shape, operator/function/chart-type `Literal`s,
   arity, unknown-field rejection — at parse time.
2. **Semantic** (against the profiled schema):
   - every referenced column must exist (derived columns become referenceable);
   - **type contracts** — `sum/mean/min/max/median` need numeric; `month/year/day/weekday`
     derives need datetime; `lower/upper/trim` need string; `round/abs` need numeric; `contains`
     needs string; `gt/gte/lt/lte/between` need numeric or datetime;
   - value shapes — `in`/`between` take lists (arity checked), others take scalars;
   - `chart.x/y/color` may reference only columns the query **produces**; `histogram` needs a
     numeric `x` and no `y`, every other type needs `y`.

`execute_analysis` **re-validates** — it never trusts the caller, even after `validate_analysis_plan`.

### Typed error taxonomy (`errors.py`)

Validation and execution failures carry a stable `error_code` classifying the correct response,
so the agent replans a plan defect, retries an infrastructure fault, and gives up on a terminal
one — instead of blindly replanning everything.

| `error_code` | Class | Meaning | Response |
|---|---|---|---|
| `INVALID_PLAN` | plan-repairable | Structural / missing-column / arity error | Regenerate the plan |
| `TYPE_MISMATCH` | plan-repairable | Op or fn on an incompatible column type | Regenerate the plan |
| `EXECUTION_ERROR` | retryable | DuckDB faulted on an already-validated plan | Bounded retry w/ backoff |
| `TIMEOUT` | retryable | Query exceeded the time budget | Bounded retry w/ backoff |
| `UNKNOWN_DATASET` | terminal | `dataset_id` not registered | Surface; register first |
| `RESOURCE_LIMIT` | terminal | File / row / column / memory ceiling exceeded | Surface; reduce size |
| `CHART_ERROR` | terminal | Chart step failed after a good result | Keep result, drop chart |

Every structured error also carries `retryable` (bool) and a human `user_action`. The agent replans
**only** for the plan-repairable set (`agent/routing.py`); infrastructure faults are retried in
place in `agent/nodes.execute_node` (`MAX_EXEC_RETRIES`), never sent back to the planner. Tests:
`tests/test_errors.py`, `tests/test_error_taxonomy.py`.

## 2. Privacy

| Control | Mechanism | Where |
|---|---|---|
| No raw arguments in logs | Only a **SHA-256 (12-hex) `input_hash`** of the call arguments is logged — never cell values or file paths | `observability._input_hash` |
| No secrets in logs | `error_code`/`outcome` are derived from structured returns, not exception text or payloads | `observability.classify_outcome` |
| Keys never persisted | API keys live in env / `backend/.env` (gitignored), never in state or checkpoints | `llm/client.py` |
| Raw rows never checkpointed | Only identifiers, metadata, plans, and **row-capped** result tables enter graph state — never DataFrames | `agent/state.py` |
| Logical source names | Provenance/log identify datasets by `dataset_id`; the physical path is not emitted to logs | `observability.py` |

## 3. Security

### 3.1 SQL injection — structurally impossible

Plans are translated to SQL by a **pure function** over the closed grammar (`execution.build_sql`):
identifiers are double-quote-escaped, **all literals are bound as `?` parameters**, and only
allow-listed ops/fns can appear. There is no string concatenation of user values into SQL. A
belt-and-braces rejection pattern also refuses code-like values in filter values / derive names /
aliases.

### 3.2 Prompt injection through CSV content ("Unsanitized Resource Content")

Type-sanitization alone does not stop instructions embedded in cell *text*. Every text value **and
column name** emitted to an LLM (`preview_dataset` rows, `execute_analysis` result tables,
schema/profile) passes through `services/safety.neutralize_text`, which defangs instruction-control
semantics: "ignore previous instructions…", role tags (`system:`), ChatML/special tokens, code
fences, and C0/C1 control chars; length is capped at 2000. **Only control semantics are touched** —
ordinary values ("North America", "2023-05-01") are byte-exact, and grouping/SQL always use the real
underlying values, not the neutralized copies. This is a heuristic mitigation, not a guarantee: it
reduces the attack surface; it does not replace treating tool-returned data as untrusted. Tests:
`tests/test_safety.py`, injection cases in `tests/test_dataset.py`.

### 3.3 Filesystem boundaries

- **Registration:** relative `file_ref`s resolve **only** inside approved data roots
  (`AUTOVIZ_DATA_ROOTS`, default `<repo>/test-data` + repo root); traversal out of a root is
  rejected (`dataset._resolve_file_ref`). Absolute paths are host-provided references (tightened to
  session-scoped tokens when HTTP transport lands — §6).
- **Exports:** filenames are slug-sanitized (`[a-z0-9_-]`) and can never escape `backend/exports/`.

### 3.4 No exceptions to the host

No tool ever raises to the caller. Failures come back as structured content; `AgentService`
wraps any internal exception into `{status: "failed", errors: [...]}`. On MCP-stdio, **stdout is
reserved** for the JSON-RPC channel — logs go only to stderr + file, so a stray write can't corrupt
the protocol (`observability.configure_logging`, called from `mcp/__main__.py`).

## 4. Resource controls

### 4.1 Ingestion (before a CSV is trusted into memory) — `services/dataset.py`

| Guard | Default | Env override |
|---|---|---|
| File size (checked **before** load) | 50 MiB | `AUTOVIZ_MAX_FILE_BYTES` |
| Column count (checked from the header alone) | 512 | `AUTOVIZ_MAX_COLUMNS` |
| Row count (checked after load) | 1,000,000 | `AUTOVIZ_MAX_ROWS` |

Exceeding any of these returns `RESOURCE_LIMIT` (terminal) instead of loading an unbounded file.

### 4.2 Execution (DuckDB governors + timeout) — `services/execution.py`

| Guard | Default | Env override |
|---|---|---|
| DuckDB `memory_limit` | `1GB` | `AUTOVIZ_DUCKDB_MEMORY_LIMIT` |
| DuckDB `threads` | `2` | `AUTOVIZ_DUCKDB_THREADS` |
| Query wall-clock timeout | 30 s | `AUTOVIZ_EXECUTION_TIMEOUT_S` |

The timeout is enforced with a `threading.Timer` that calls `con.interrupt()`; an interrupted query
is classified `TIMEOUT` (retryable), a genuine engine failure `EXECUTION_ERROR`. Test:
`test_error_taxonomy.test_execution_timeout_returns_timeout_code`.

### 4.3 Grammar / output caps — `schema/allowlists.py`

| Guard | Value |
|---|---|
| Output rows | hard ceiling **100000**, enforced in SQL regardless of the plan's `limit` |
| `limit` | max 100000 (over-limit auto-clamped via `repaired_plan`) |
| `group_by` columns | max 2 |
| `in` list size | 1–20 values |
| Preview rows | 1–50 |

### 4.4 Agent-loop bounds — `agent/state.py`

`MAX_TASKS = 3` · `MAX_PLAN_ATTEMPTS = 2` (≤3 plan calls/task) · `MAX_CLARIFICATIONS = 1` ·
`MAX_EXEC_RETRIES = 1`. No unbounded loop exists in the workflow.

## 5. Observability of controls

Every tool call is logged once (`@observed`) as a single JSON line with `tool`, `input_hash`, `ms`,
`out_bytes`, `outcome` (`ok`/`error`/`invalid`/`failed`) and, on failure, the typed `error_code`
and `failed_step`. This is how validation failures, resource-limit rejections, and timeouts surface
operationally without leaking data (§2). See Doc [07 §Observability](07-MCP-Tool-Inventory.md).

## 6. Deferred to HTTP transport (documented, not yet needed)

The current stdio deployment is local and single-user. When Streamable-HTTP transport is added,
these become required and are tracked accordingly: OAuth authorization + least-privilege scopes,
Origin validation, localhost-only binding for local servers, rate limiting, and per-user tool +
dataset access control (session-scoped ownership of `dataset_id`/`thread_id`). The layered design
(Doc 09) isolates these to layer 2.

## 7. Test coverage map

| Control | Tests |
|---|---|
| Closed-grammar + type validation | `tests/test_validation.py` |
| Error taxonomy + routing/retry | `tests/test_errors.py`, `tests/test_error_taxonomy.py` |
| Ingestion resource limits | `tests/test_resource_limits.py` |
| Execution timeout classification | `tests/test_error_taxonomy.py` |
| Prompt-injection neutralization | `tests/test_safety.py`, `tests/test_dataset.py` |
| SQL determinism / provenance | `tests/test_execution.py` |
| Observability (privacy + codes) | `tests/test_observability.py` |
| End-to-end workflow | `tests/test_titanic_workflow.py` |
