# AutoViz AI — Improvement Plan

Concrete, actionable fixes for the four highest-leverage weak areas identified in the project analysis: **novelty framing**, **evaluation rigor**, the **analysis-plan schema**, and **MVP scope**. In priority order of payoff.

---

## 1. Fix the Novelty Framing

The project *is* novel — but the proposal doesn't defend that novelty against known tools. Fix it with two artifacts.

### (a) One-sentence positioning statement

Put this in the intro and repeat it verbatim in the final report:

> *"Unlike LLM-viz tools that let the model generate and run arbitrary code (LIDA, PandasAI) or closed enterprise assistants (Power BI Copilot, Tableau Agent), AutoViz constrains the LLM to a **validated, read-only analysis plan** whose every number is **traceable to a deterministic query**, and exposes the same analytics core to **any MCP-compatible host** — no model lock-in."*

Three defensible claims: *deterministic/verifiable*, *provenance*, *model-independent*.

### (b) Differentiation table (for Related Work)

| Tool | Deterministic exec | Provenance | Model-independent | Open/lightweight |
|---|:---:|:---:|:---:|:---:|
| Power BI Copilot | partial | ✗ | ✗ | ✗ |
| Tableau Agent | partial | ✗ | ✗ | ✗ |
| ChatGPT Advanced Data Analysis | ✗ (runs code) | ✗ | ✗ | ✗ |
| **LIDA** (Microsoft) | ✗ (gen code) | ✗ | partial | ✓ |
| **PandasAI** | ✗ (gen code) | ✗ | partial | ✓ |
| Vizro-AI | ✗ | ✗ | partial | ✓ |
| **AutoViz (this project)** | **✓** | **✓** | **✓ (MCP)** | **✓** |

**Key move:** cite your closest prior art yourself. Add **LIDA**, **PandasAI**, **Vizro-AI**, and **nvBench** to the bibliography and contrast explicitly. Graders trust a project that names its rivals.

---

## 2. Fix the Evaluation (biggest score-mover)

Replace vague "chart-type suitability" with a concrete benchmark and numeric metrics.

### Benchmark construction (do this in Iteration 1)

- **15–20 datasets** across target domains (sales, health, finance, weather…) from Kaggle + government open data.
- For each dataset, author **5–10 natural-language tasks** by hand with a reference answer: correct columns/filters/aggregation + expected chart type. **~100–150 tasks total.**
- Store as JSON:

```jsonc
{
  "dataset": "sales_2024.csv",
  "question": "Show monthly revenue by region",
  "gold_plan": { "group_by": ["region", "month"], "aggregations": [/* … */] },
  "gold_chart_type": "line",
  "gold_result_shape": { "rows": 36, "columns": ["region", "month", "total_revenue"] }
}
```

### Metrics (reproducible definitions)

| Metric | How to compute |
|---|---|
| **Plan accuracy** | Field-level match of predicted vs. gold plan (columns, filter, groupby, agg). Report field-level F1. |
| **Result correctness** | Run predicted plan → compare numeric output to gold (float tolerance). % exact-match. |
| **Chart-type match** | Predicted chart type == gold (or in accepted set). Accuracy %. |
| **Column-resolution accuracy** | Correctly maps e.g. "revenue" → `total_sales`. % correct. |
| **Task completion** | End-to-end: valid chart, no error. % success. |
| **Latency** | p50 / p95 seconds per request. |

### Two moves that impress graders

- **Ablation:** LLM-only chart selection vs. the hybrid recommender → show the rule layer helps. A mini research result.
- **Human study:** 10–15 users, tasks + a short SUS usability questionnaire. Validates the "accessible to non-technical users" claim.

> Target statement for the final report: *"AutoViz achieved 87% plan accuracy and 91% chart-type match on a 120-task benchmark."* Numbers move the report up a tier.

---

## 3. Draft the Analysis-Plan Schema Now (the real contribution)

Define the intermediate representation **before** coding the pipeline. It is the spine everything hangs off.

### Draft schema

```jsonc
{
  "dataset_id": "ds_abc123",
  "intent": "trend",           // comparison | trend | distribution |
                               // relationship | composition | ranking
  "select": ["region", "revenue"],
  "filters": [
    { "column": "year", "op": "gte", "value": 2023 }
  ],
  "derive": [                  // safe derived columns only
    { "name": "month", "from": "order_date", "fn": "month" }
  ],
  "group_by": ["region", "month"],
  "aggregations": [
    { "column": "revenue", "fn": "sum", "as": "total_revenue" }
  ],
  "sort": [{ "by": "total_revenue", "dir": "desc" }],
  "limit": 100,
  "chart": {
    "type": "line",            // chosen by recommender, validated
    "x": "month", "y": "total_revenue", "color": "region"
  }
}
```

### Validation rules (this IS the safety layer)

- Every `column` exists in the profiled schema, with a compatible type for its `op`/`fn`.
- `op` ∈ fixed allow-list: `eq, neq, gt, gte, lt, lte, in, between, contains`. No raw expressions.
- `fn` (aggregation) ∈ allow-list: `sum, mean, count, min, max, median, count_distinct`.
- `derive.fn` ∈ safe set: `month, year, day, lower, round, …`. No arbitrary code.
- `limit` capped; output rows capped; chart channels must reference selected/aggregated columns.

### Why this matters

Because the plan is a **closed grammar**, translation to DuckDB SQL is a pure function and injection is structurally impossible. Write the schema as a **JSON Schema file** to get validation for free.

---

## 4. Trim the MVP (protects the timeline)

| Keep for MVP (Week 8) | Defer / cut |
|---|---|
| CSV upload + profiling | User accounts / auth |
| Analysis-plan generation + validation | Dashboard versioning |
| DuckDB execution | Multi-user persistence |
| Chart recommender + Vega-Lite render | PDF export (PNG is enough for MVP) |
| Single dashboard: add / drag / resize | Session sharing / collaboration |
| Provenance display | Fancy chart-editing controls |

**Also: commit to DuckDB, drop the "or Pandas" dual path** (keep Pandas only for profiling). Saves a subsystem's worth of work.

---

## Priority Summary

1. **Analysis-plan schema** — define first; it's the spine and the safety layer.
2. **Evaluation benchmark** — build in Iteration 1; biggest score-mover.
3. **Novelty framing** — cheap to fix; cite and contrast prior art (LIDA, PandasAI, nvBench).
4. **MVP trim + DuckDB commitment** — protects the Week 8 milestone.

These four are worth more than any new feature.
