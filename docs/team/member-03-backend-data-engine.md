# Member 03 — D.W.K.G. Bulagala

## Member name

D.W.K.G. Bulagala (230094U)

## Assigned role

Data engine, profiling, and backend services

## Project objective of the component

Provide safe CSV registration, accurate profiling, deterministic query execution, validated Vega-Lite specification generation, persistence APIs, and reliability controls so the LLM and frontend never need unrestricted code execution.

## Detailed responsibilities

- Define supported CSV encodings, file-size limits, row/column limits, and type rules  
- Define dataset storage, IDs, expiry, cleanup, and lifecycle behavior  
- Collect at least four representative evaluation CSV datasets  
- Define structured query operations and validation rules  
- Implement CSV upload validation and registration  
- Implement schema inference, preview, and quality/statistical profiling  
- Implement deterministic filters, grouping, aggregations, sorting, and limiting  
- Reject unsupported or unsafe requests without executing them  
- Implement the chart-specification service for supported Vega-Lite types  
- Implement dashboard metadata and persistence APIs  
- Implement session isolation and temporary-file cleanup  
- Create numerical reference tests and backend automated tests  
- Prepare deployable backend and documented local fallback  

## Expected deliverables

Backend APIs, data engine, profiling, chart-spec service, persistence, security/limits, backend tests, deployment docs, sample/evaluation datasets.

## Required input data

- Public/sample CSVs from Kaggle / open-data portals  
- Frozen query-plan and dashboard schemas  
- Supported chart-type list from recommendation contract  

## Output contracts

Dataset/profile/preview/query-result/chart-spec/dashboard persistence schemas consumed by MCP wrappers and frontend.

## Recommended implementation stages

1. CSV constraints + lifecycle + API contract draft  
2. Upload validation + registration + profiling + preview  
3. Query engine + validation + resource limits  
4. Vega-Lite core chart-spec generation  
5. Dashboard persistence APIs  
6. Numerical references + hardening + deploy/fallback  

## Baseline method

Pandas-based profiling and controlled operations with strict validation and output limits.

## Improved method

DuckDB where beneficial for larger tabular ops; stronger cleanup/isolation (P1); expanded chart types (P2).

## Evaluation metrics

Profiling accuracy vs references; query correctness; invalid-input rejection quality; chart-spec validation pass rate; latency under limits; cleanup/isolation reliability.

## Dependencies on other members

- MCP wrappers and orchestration calling the engines (Daishika)  
- Dashboard widget schema and export UX (Chandrasiri)  

## What can be developed independently

Full CSV → profile → query → chart-spec pipeline against sample files and unit tests without UI or LLM.

## Integration procedure

Expose stable HTTP APIs → Daishika wraps as MCP tools → Chandrasiri replaces mocks → weekly vertical-slice demo.

## Testing responsibilities

CSV edge cases; profiling/query numerical references; invalid ops; Vega-Lite schema tests; persistence tests; deploy/fallback checks.

## Documentation responsibilities

Backend setup, env, migrations, test commands; `docs/deployment.md` / privacy notes; keep this member brief updated.

## Weekly milestone suggestions

- W1: CSV/storage/query constraints + sample datasets  
- W2: registration, profiling, preview + unit tests  
- W3: query engine, validation, chart specs + numerical refs  
- W4: persistence APIs, cleanup/limits, deploy + local fallback  

## Definition of done

Matches `docs/definition-of-done.md` plus: valid CSVs get IDs; invalid files get safe specific errors; supported ops are deterministic and tested; specs validate; temp data is isolated/cleaned.

## Possible risks and solutions

| Risk | Solution |
|------|----------|
| Malformed / huge CSVs | Hard limits + specific errors before processing |
| Waiting on UI schemas | Freeze examples early; iterate via contract PRs |
| Demo deployment failure | Documented local fallback with `test-data/` |

## First branch

`feat/03-csv-registration-profiling`
