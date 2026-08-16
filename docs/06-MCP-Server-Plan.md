# AutoViz AI — MCP Server Plan

Owner: K.S.H. Daishika (LLM, MCP & System Integration). Scope: the MCP server, its typed tools, the analysis-plan schema those tools share, and validation. This is the working spec for Week 1–2 of the individual execution plan (see [Docs/04-Improvement-Plan.md](04-Improvement-Plan.md) §3 for the original schema draft this finalizes, and [Docs/01-Project-Proposal.md](01-Project-Proposal.md) §4.4 for the "small typed tools" design principle).

---

## 1. Architectural Pattern Mapping

AutoViz's MCP server combines three of the patterns catalogued in [MCP Server Architecture Patterns](Research%20Papers/markdown/MCP-Server-Architecture-Patterns-2606.30317.md) (Rodrigues & Vas, ICSME 2026). Naming them explicitly avoids ambiguity the paper itself flags as common (its own inter-rater study found these exact pattern boundaries the hardest to classify from a functional description alone).

| Pattern | Where it shows up in AutoViz | Obligation it brings |
|---|---|---|
| **Domain-Specific Adapter** (primary) | Translating natural-language analytical intent into a validated `analysis_plan` over Pandas/DuckDB. Pandas/DuckDB's raw API is exactly the "useful but LLM-hostile" surface the pattern describes — arbitrary code, unsafe for direct LLM use. | The paper's own framing of this pattern's LLM-client delta is *"validation as natural-language guardrails"* — this **is** the analysis-plan schema and its validation rules (§2 below), not a separate concern. |
| **Resource Gateway** | `register_dataset`, `get_dataset_schema`, `get_dataset_profile`, `preview_dataset` — all mediate read access to the uploaded dataset. | The pattern requires a sanitization layer on backend content before it reaches the LLM. This is the concrete implementation of Proposal §4.7's promise that "CSV cell contents [are] treated strictly as data" — dataset values must never be interpretable as instructions. |
| **Tool Orchestrator** | The controlled orchestration component that sequences `validate_analysis_plan → execute_analysis → recommend_chart_type → generate_chart` behind one coordinated flow. | The pattern's named liability is that **partial-failure handling becomes the server's responsibility** — e.g. `execute_analysis` succeeds but `generate_chart` fails. Per the paper's cross-cutting error-handling guidance (§VII-B), return structured error *content* from the orchestrator, not a thrown exception, so the caller can reason about retry vs. escalation. |

**Shared service layer (not a named pattern, but load-bearing):** both the MCP tools above and the FastAPI endpoints call the same underlying service functions — this is the concrete mechanism for Proposal §4.1's commitment that "the same core services are reused by both the standalone web client and external MCP-compatible AI hosts." Business logic (validation, execution, chart generation) lives in the service layer; the MCP tool handlers and FastAPI routes are thin adapters over it, not separate implementations.

---

## 2. Canonical Analysis-Plan Schema

This is the single source of truth for the `analysis_plan` shape. It supersedes the two earlier drafts (the JSON in 04-Improvement-Plan.md and the informal version in the Week-1 task plan) — field names and operator lists below are final; update this section, not the others, if it changes again.

```jsonc
{
  "dataset_id": "ds_abc123",
  "intent": "trend",            // comparison | trend | distribution | relationship | composition | ranking
  "select": ["region", "revenue"],
  "filters": [
    { "column": "year", "op": "gte", "value": 2023 }
  ],
  "derive": [                    // safe derived columns only
    { "name": "month", "from": "order_date", "fn": "month" }
  ],
  "group_by": ["region", "month"],   // MVP cap: max 2 columns
  "aggregations": [
    { "column": "revenue", "fn": "sum", "as": "total_revenue" }
  ],
  "sort": [{ "by": "total_revenue", "dir": "desc" }],
  "limit": 100,
  "chart": {
    "type": "line",              // chosen by recommender, validated
    "x": "month", "y": "total_revenue", "color": "region"
  }
}
```

### Operator / function allow-lists

| Field | Full allow-list | MVP subset (Week 1–3) |
|---|---|---|
| `filters[].op` | `eq, neq, gt, gte, lt, lte, in, between, contains` | `eq, neq, gt, lt, contains` for launch; add `gte/lte/between` as soon as a date-range task appears in the benchmark (needed for `seattle-weather.csv`, `taxis.csv`, `precipitation_innsbruck.csv` style tasks) |
| `aggregations[].fn` | `sum, mean, count, min, max, median, count_distinct` | `sum, mean, min, max, count` |
| `derive[].fn` | `month, year, day, lower, round` | same |
| `chart.type` | any validated Vega-Lite mark | `bar, line, scatter, pie` |
| `group_by` | any number of columns | capped at 2 |

Anything outside these lists is a validation failure, not a warning — the LLM never gets a fallback to raw expressions.

### Validation rules (the safety layer)

- Every `column` referenced anywhere in the plan exists in the dataset's profiled schema.
- Every `column` has a type compatible with the `op`/`fn` applied to it (no `sum` on a string column, no `month` derive on a non-date column).
- `op`, `fn`, and `derive.fn` must be in the allow-lists above — no raw expressions, no arbitrary code.
- `limit` is capped (e.g. 100000); execution enforces a hard row-output ceiling regardless of what the plan requests.
- `chart.x` / `chart.y` / `chart.color` must reference columns that are actually present in `select`, `group_by`, or `aggregations[].as` — the chart can't reference something the query never produced.
- Reject anything resembling arbitrary Python, SQL, or shell execution outright.

---

## 3. MCP Tools

Eight small, independently testable tools — each maps to one step of the end-to-end workflow in [01-Project-Proposal.md §4.3](01-Project-Proposal.md).

| # | Tool | Input | Output |
|---|---|---|---|
| 1 | `register_dataset` | `file_ref` (upload or host-provided path) | `{ dataset_id, row_count, column_count }` |
| 2 | `get_dataset_schema` | `dataset_id` | `{ columns: [{ name, type }] }` |
| 3 | `get_dataset_profile` | `dataset_id` | `{ null_counts, duplicate_count, cardinality, summary_stats }` |
| 4 | `preview_dataset` | `dataset_id, limit` | sample rows as records |
| 5 | `validate_analysis_plan` | `dataset_id, analysis_plan` | `{ valid: bool, errors: [...], repaired_plan?: {...} }` |
| 6 | `execute_analysis` | `dataset_id, analysis_plan` (must be pre-validated) | `{ result_table, row_count, execution_time_ms, provenance }` |
| 7 | `recommend_chart_type` | `result_schema, intent` | `{ chart_type, x, y, color?, rationale }` |
| 8 | `generate_chart` | `result_table, chart_spec` | `{ vega_lite_spec, valid: bool, warnings: [...] }` |

Notes:
- `register_dataset` exists because every other tool assumes a `dataset_id` already exists — it's what turns a raw upload or an external host's file reference into one (Proposal §4.2).
- `validate_analysis_plan` is deliberately separate from `execute_analysis` so it can be unit-tested standalone (Week 1 Day 5 deliverable) and so the orchestrator can retry validation alone during the auto-repair step (Week 2 Day 10) without re-running a full execution.
- `recommend_chart_type` is separate from `generate_chart` per the hybrid-recommender design (Proposal §4.6) — rule-based scoring of intent/type/cardinality/readability happens here; Vega-Lite spec construction + validation happens in `generate_chart`.
- Dashboard actions (add/drag/resize/save/export) are frontend-owned (Chandrasiri's track) — not MCP tools.

---

## 4. Orchestration Pipeline

```
register_dataset
      │
      ▼
get_dataset_schema + get_dataset_profile   ──►  fed into LLM prompt as context
      │
      ▼
LLM produces analysis_plan (NL request → structured plan)
      │
      ▼
validate_analysis_plan ──fail──► repair attempt (1x) ──fail──► return error to user
      │ pass
      ▼
execute_analysis
      │
      ▼
recommend_chart_type
      │
      ▼
generate_chart ──► returned to caller with provenance (dataset, columns, filters, aggregations, chart type)
```

One automatic repair attempt on validation failure, per the Week 2 Day 10 plan — precedent: DynaVis's synthesis pipeline averages 1.16 validate→retry cycles per generation ([Research Papers/markdown/DynaVis-2401.10880.md](Research%20Papers/markdown/DynaVis-2401.10880.md)). If repair also fails, surface the validation errors to the user rather than silently degrading.

---

## 5. Testing

Per-tool tests (Week 1 Day 5) should run against real files in [`test-data/`](../test-data/), not synthetic fixtures — e.g. `iris.csv` for the smoke-test path, `titanic.csv`/`penguins.csv` for profiling with real nulls, `taxis.csv` for date-typed filter/derive validation, `diamonds.csv` for the row-limit/performance path. Reserve hand-authored benchmark tasks (per [04-Improvement-Plan.md §2](04-Improvement-Plan.md)) for end-to-end pipeline evaluation in Week 3, not individual tool unit tests.

The MCP **protocol** contract needs its own suite (`backend/tests/test_mcp_envelope.py`), separate from the service tests. Asserting on a service's return dict cannot catch a tool that reports a failure as a successful call — only the `CallToolResult` envelope shows that. Test `result.isError`, `result.structuredContent`, and the published `outputSchema`, not just the dict the service produced.

---

## 6. The MCP Protocol Contract

Sections 1–5 describe the internal architecture. This section covers what an **external MCP host** actually sees, which is a separate concern: internally correct structured results can still be an impoverished protocol surface.

### Typed output

Every tool declares a Pydantic return model (`autoviz/mcp/results.py`). A tool annotated `-> dict[str, Any]` publishes `{"type": "object", "additionalProperties": true}` — valid, and useless: it does not tell the host that `dataset_id`, `provenance.sql`, or `vega_lite_spec` exist, so the host must pass the whole payload to an LLM to interpret rather than branching on it. With real models the host can drive the result table, the "how this was calculated" panel, the renderer, and the confirmation dialog directly.

Two SDK behaviours constrain the models (both verified against `mcp` 1.28.x):

- **No top-level unions.** A `-> A | B` annotation sets FastMCP's `wrap_output`, and `structuredContent` arrives as `{"result": {...}}` — every field moves one level down. Multi-state tools use one flat model with a `status` discriminator, which also matches what `run_pipeline` already returns.
- **A typed output schema and an error-shaped `CallToolResult` are mutually exclusive.** `FuncMetadata.convert_result` validates a returned `CallToolResult.structuredContent` against the tool's *success* model, so an error payload fails validation and surfaces as a Pydantic dump. Terminal failures therefore `raise ToolError`, with the error code folded into the message.

### Failure signalling

Terminal failures set `isError: true`; a negative result from a tool that worked correctly does not. The full matrix lives in [Doc 07 § Error signalling](07-MCP-Tool-Inventory.md#error-signalling-iserror). The design rule: **the services keep returning structured dicts and never raise** — the translation happens only in `autoviz/mcp/envelope.py`, so business logic stays independent of the protocol and the FastAPI routes keep returning identical bodies.

The one case worth restating: a chart-step failure carries a complete, provenanced result table. It becomes `status: "partial"` with `isError: false`. Marking it an error would throw away valid numbers and contradict the agent's own chart-fallback routing.

### Context budget

Tool descriptions and schemas are sent to the host's model on every session init, competing with the user's actual question for context. The plan grammar was embedded in three tool descriptions — 15.5k characters, 83% of the payload, the same document three times. It is now the `autoviz://docs/analysis-plan-guide` resource, fetched once, with the server's `instructions` telling the host to read it before its first plan. Longer context does not mean better tool selection; repetition makes the choice noisier.

### Progress and cancellation

`run_analysis_pipeline` and `analyze` are async and take an injected `Context`. The pipeline emits its five stage boundaries as MCP progress notifications, and request cancellation propagates through a `cancel_event` to `con.interrupt()`, reusing the same interrupt machinery as the execution timeout. `@observed` has an async branch specifically for this: wrapping a coroutine function in a plain `def` makes FastMCP read `is_async=False`, so it never awaits and the coroutine leaks.

### Profiles

`AUTOVIZ_MCP_PROFILE=default` narrows the surface to five tools for external hosts; `advanced` (the default) exposes all 14 for orchestration and testing. Overlapping levels of abstraction make the model's tool choice harder, and most hosts do not need the per-step tools.
