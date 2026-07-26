# Project Roadmap

**Critical milestone:** approximately **85%** of the core product demonstrable by **18 August 2026**.

The original late placement of MCP/backend integration is corrected here by prioritizing an end-to-end vertical slice in Weeks 1–4.

## Weeks 1–4 — Accelerated milestone

### Week 1 — Scope, architecture, contracts, and mocks

**Outcome:** One frozen vertical-slice contract; independent development possible.

| Owner | Focus |
|-------|-------|
| Daishika | MCP-first architecture; six tools; typed schemas; registry skeleton |
| Chandrasiri | Wireframes; React/Vega-Lite/canvas choices; API types + mocks; app shell |
| Bulagala | CSV constraints; lifecycle; API contracts; query rules; sample CSVs |
| All | Freeze P0/P1/P2; repo/CI; shared contract document |

**Exit criteria:** contracts committed; mocks for P0 UI states; local run for everyone; no P2 work started.

### Week 2 — Upload, profile, preview, chat shell, MCP skeleton

**Outcome:** CSV moves through the first half of the workflow.

| Owner | Focus |
|-------|-------|
| Daishika | MCP server + wrappers for register/profile/preview; discovery; logging |
| Chandrasiri | Upload UI; profile/preview; chat with mocks; core UI states; sample Vega-Lite |
| Bulagala | CSV validation/registration; profiling/preview; safe errors; unit tests |

**Exit criteria:** upload → validate → register → profile → preview end to end; chat accepts NL; sample charts render.

### Week 3 — Deterministic analysis, LLM tool calls, dashboard canvas

**Outcome:** NL request produces a verified result and chart.

| Owner | Focus |
|-------|-------|
| Daishika | LLM MCP client; `query_dataset` orchestration; rule-based recommendation |
| Chandrasiri | Chat → orchestration; tables/charts; add to dashboard; drag/resize/delete |
| Bulagala | Filters/group/agg/sort/limit; validation/limits; Vega-Lite core specs; refs |
| All | ≥30 NL benchmark prompts; first full vertical slice |

**Exit criteria:** upload → prompt → MCP → deterministic result → chart → dashboard on sample data; invalid ops rejected.

### Week 4 — Persistence, editing, export, hardening, usability

**Outcome:** ~85% core product demonstrable by 18 August 2026.

| Owner | Focus |
|-------|-------|
| Daishika | Provenance/logging; recommendation fixes; safe ambiguity/tool errors; MCP tests |
| Chandrasiri | Chart editing; save/reopen; image/PDF export; component/e2e tests; usability cycle |
| Bulagala | Dashboard persistence APIs; backend tests; session limits/cleanup; deploy + fallback |
| All | P0 regression; freeze milestone build; demo script; SRS/architecture evidence |

**Milestone acceptance criteria**

- CSV upload, profiling, and preview work  
- NL requests trigger typed MCP calls  
- Calculations are deterministic and validated  
- Supported Vega-Lite charts render correctly  
- Charts can be edited and arranged on a dashboard  
- Dashboard layouts can be saved and reopened  
- Image and PDF export work  
- Core error/loading states are complete  
- One usability-test cycle is documented  
- Deployed build and local fallback are available  

## Full 14-week roadmap

| Week | Main goal | Daishika | Chandrasiri | Bulagala | Shared deliverable |
|------|-----------|----------|-------------|----------|--------------------|
| 1 | Scope and contracts | MCP architecture and typed tool draft | Wireframes, UI libraries, frontend mocks | CSV/storage/query constraints | Frozen P0 scope and contracts |
| 2 | First data workflow | MCP registry and dataset tool wrappers | Upload/profile/preview/chat UI | CSV registration and profiling | Upload-to-profile vertical slice |
| 3 | Analysis and charts | LLM client, query orchestration, recommendation | Chat integration, charts, dashboard canvas | Query engine, validation, chart specs | Prompt-to-dashboard vertical slice |
| 4 | 85% milestone | Provenance, safe orchestration, MCP tests | Editing, persistence UI, export, usability | Persistence APIs, backend tests, deployment | Stable August 18 demo build |
| 5 | Integration cleanup | Fix tool discovery and wrapper issues | Fix frontend integration issues | Fix dataset/profile issues | Reproducible CI-tested build |
| 6 | Correctness hardening | Improve tool-selection reliability | Improve tool-progress/table states | Expand numerical and resource-limit tests | Verified analytical workflow |
| 7 | Complete multi-tool workflow | Finalize recommendation and provenance | Refine dashboard behavior | Harden chart-spec generation | Full representative workflow |
| 8 | Mid-evaluation release | Help triage orchestration failures | Fix UX and display failures | Fix backend/data failures | Deployed and rehearsed build |
| 9 | Feedback and P1 | Controlled follow-up context | Improve follow-up UX and persistence | Complete metadata/persistence APIs | Resolved evaluation feedback |
| 10 | Feature freeze | Improve tool descriptions | UI polish and accessibility | Session isolation and cleanup | Feature-complete release candidate |
| 11 | Formal evaluation | MCP/orchestration unit tests | Usability evaluation | Profiling/query tests | Full benchmark and error analysis |
| 12 | Critical fixes and reports | Connector go/no-go decision | Frontend fixes and documentation | Setup/deployment documentation | Draft final and testing reports |
| 13 | Final regression and demo | Multi-tool regression | Final usability/demo testing | Performance, reliability, fallback tests | GitHub page, video, slides |
| 14 | Submission | Explain MCP and orchestration | Explain frontend and usability | Explain backend and evaluation | Tagged release and final submission |

## Weekly management process

### Start of week

- Select highest-priority unblocked P0 tasks  
- Confirm one owner each  
- Review dependencies and API changes  
- Agree on the weekly integrated demonstration  

### During the week

- Track status in GitHub issues or Notion  
- Record blockers with owner and required decision  
- Integrate continuously; update mocks when contracts change  
- Attach evidence to completed tasks  

### End of week

- Demonstrate working results  
- Run relevant automated tests  
- Review risks; ensure P2 did not displace P0  
- Record completed / blocked / deferred work  

### Suggested weekly update template

```markdown
## Week N Update

### Planned
- [ ] Task, owner, and acceptance criterion

### Completed
- [x] Demonstrated result and evidence link

### Blocked
- Blocker, owner, required decision, and target resolution date

### Risks
- New or changed risk and mitigation

### Next Week
- Highest-priority P0 work

### Scope Check
- Confirm that no P2 work displaced P0 work
```
