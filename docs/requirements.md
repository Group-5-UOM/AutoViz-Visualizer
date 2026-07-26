# Requirements

## Functional requirements (P0)

| ID | Requirement |
|----|-------------|
| FR-01 | User can upload a structured CSV file |
| FR-02 | System validates encoding, size, row/column limits, and basic schema |
| FR-03 | System registers the file and returns a dataset ID |
| FR-04 | System profiles column types, missing values, duplicates, and summary statistics |
| FR-05 | User can preview a limited row/column sample of the dataset |
| FR-06 | User can submit natural-language analytical requests in a chat UI |
| FR-07 | LLM selects approved typed MCP tools; does not compute final numbers |
| FR-08 | System creates a structured semantic analysis plan (columns, filters, group, agg, sort) |
| FR-09 | Validation rejects invalid columns, incompatible types, and unsafe operations |
| FR-10 | Deterministic engine executes filtering, grouping, aggregation, sorting, and limiting |
| FR-11 | Hybrid recommender selects a suitable supported chart type |
| FR-12 | System generates and validates a Vega-Lite JSON specification |
| FR-13 | Frontend renders Vega-Lite charts with clear fallback on invalid specs |
| FR-14 | User can add charts to a dashboard and drag, resize, rearrange, and delete widgets |
| FR-15 | User can apply basic chart edits (title, labels, legend, colors, presentation) |
| FR-16 | User can save and reopen dashboard layouts |
| FR-17 | User can export the dashboard as image and PDF |
| FR-18 | System records provenance (dataset, fields, filters, aggregations, chart type, tool sequence) |
| FR-19 | UI exposes loading, empty, success, validation-error, recoverable-error, and retry states |
| FR-20 | API and MCP tools expose typed request/response/error schemas |

## Non-functional requirements

| ID | Requirement |
|----|-------------|
| NFR-01 | MCP-first architecture reusable by web client and external hosts |
| NFR-02 | LLM never trusted for final analytical calculations |
| NFR-03 | Session isolation and temporary-file lifecycle for uploaded datasets |
| NFR-04 | Read-only analytical execution with timeouts, memory, and output-row limits |
| NFR-05 | No arbitrary Python, shell, or unrestricted SQL from model output |
| NFR-06 | CSV cell contents treated strictly as data (prompt-injection resistant handling) |
| NFR-07 | Configuration via environment variables; no secrets in git |
| NFR-08 | TypeScript strict mode; Python type hints |
| NFR-09 | Unit, contract, integration, and e2e tests in CI |
| NFR-10 | Documented local setup and verified local demo fallback |

## Explicit non-requirements (MVP)

- Multi-format uploads beyond CSV (P2)  
- Production multi-tenant SaaS hardening  
- Guaranteed chart suitability for every ambiguous prompt  
- External MCP host connectors before P0 freeze (P2 go/no-go)  
