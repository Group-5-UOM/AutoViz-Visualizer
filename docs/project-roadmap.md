# Project Roadmap

**Critical milestone:** approximately **85%** of the core product demonstrable by **18 August 2026**.

The original late placement of MCP/backend integration is corrected here by prioritizing an end-to-end vertical slice in Weeks 1–4.

> **Status as of 15 August 2026 — 3 days to the milestone.** Everything below is the *plan*; the
> section immediately following is what actually happened, verified against the code. The full
> account is [`Docs/21 — Project Status`](21-Project-Status.md), with export and UI states in
> [`Docs/22`](22-Export-and-UI-States.md).

---

## Status — 15 August 2026

**Nine of the ten milestone acceptance criteria are met; one is unmet.** The product runs end to
end. What is short is *evidence*, not capability: a documented usability cycle is the last open
criterion, and frontend testing now has a floor rather than a suite.

| | Verified value |
|---|---|
| Development elapsed | 21 July → 15 August — **25 days**, 90 non-merge commits |
| Pull requests | 42 · 39 merged · **0 open** |
| Backend tests | **759 passing** in 69 s |
| Frontend tests | **25 passing** — was 0 with no runner installed until 15 Aug |
| Frontend typecheck | `tsc -b` clean |
| MCP tools · HTTP endpoints | 18 · 45 |
| Chart types · cleaning ops · input formats | 10 · 14 · 8 |

### Planned versus actual, by week

Accelerated weeks are counted from the first commit (21 July), which is how the 18 August milestone
date was derived.

| Week | Planned | Actual |
|---|---|---|
| 1 (21–27 Jul) | Scope, contracts, mocks | **Overtaken.** Contracts *and* a working MCP server, DuckDB execution, LangGraph agent, the whole HTTP backend, and risk-tiered preprocessing all landed inside week 1–2 |
| 2 (28 Jul–3 Aug) | Upload, profile, preview, chat shell | **Met and passed.** Parallel-interrupt resume fixed, dashboard autosave shipped, cleaning disclosure and skew-aware axes merged, AWS pipeline stood up |
| 3 (4–10 Aug) | Deterministic analysis, LLM tool calls, canvas | **Met**, except the shared deliverable: the **≥30 NL benchmark prompts do not exist**. In-place chart editing, OAuth, dataset editing, conversations and six phases of preprocessing hardening merged instead |
| 4 (11–17 Aug) | Persistence, editing, export, hardening, usability | **In progress.** Persistence, editing, hardening and export (PNG *and* PDF) are done, and the UI states have been audited against FR-19. **Usability testing has not been run; frontend testing has a runner and 25 logic tests but no component or e2e coverage** |

### The ten acceptance criteria

| # | Criterion | Status |
|---|---|---|
| 1 | CSV upload, profiling, and preview work | ✅ |
| 2 | NL requests trigger typed MCP calls | ✅ |
| 3 | Calculations are deterministic and validated | ✅ |
| 4 | Supported Vega-Lite charts render correctly | ✅ |
| 5 | Charts can be edited and arranged on a dashboard | ✅ |
| 6 | Dashboard layouts can be saved and reopened | ✅ |
| 7 | Image **and PDF** export work | ✅ Both, from one Export menu — [`Docs/22`](22-Export-and-UI-States.md) |
| 8 | Core error/loading states are complete | ✅ Audited against FR-19's six states; gaps closed — [`Docs/22`](22-Export-and-UI-States.md) |
| 9 | One usability-test cycle is documented | ❌ No artifact |
| 10 | Deployed build and local fallback are available | ✅ pipeline · live URL not checked |

### The three days

1. **Commit `Docs/`** — it is gitignored at line 1. Five files predate the rule and are tracked;
   everything numbered 01–22 is not, so most of this documentation is on one laptop. Five minutes.
2. **Run and write up one usability cycle** (Chandrasiri) — criterion 9, and now the only unmet
   one. Needs participants booked today, not on the 17th.
3. **Component tests on top of the new runner** (Chandrasiri) — `npm test` exists and 25 logic
   tests pass; component and e2e coverage is still the largest NFR-09 hole.
4. **Surface the ingest report and the four new cleaning operations in the UI** (Daishika) — six
   merged phases of backend work are currently invisible in a demo.
5. **Freeze ~30 NL benchmark prompts** (Daishika) — the outstanding Week 3 deliverable.
6. **Confirm the deployed build is live and rehearse against it** (Bulagala) — criterion 10.

---

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

*Where each of these stands today is in the [Status](#status--14-august-2026) section above.*

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

**Two dependencies for Weeks 11–12 that have to start earlier than they appear.** "Full benchmark
and error analysis" needs a frozen golden set and an evaluation runner, neither of which exists;
the same two artifacts are what currently block every phase of the planner fine-tune track in
`AutoViz-Planner-Model`. Buildable from `test-data/` in days, but nothing downstream starts without
them — see [`Docs/21 §5`](21-Project-Status.md).

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
