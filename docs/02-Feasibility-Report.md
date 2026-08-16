# AutoViz AI — Feasibility Report

**A Conversational Data Visualization and Dashboard Builder Using LLM-Guided CSV Analysis**

| | |
|---|---|
| Course | In22-S5-CS3501 Data Science and Engineering Project |
| Department | Computer Science and Engineering, University of Moratuwa |
| Group ID | 5 |
| Project ID | P09 |
| Mentor | Dr. Chathuranga Hettiaracchi |
| Teaching Assistant | Shaveen Silva |

**Team Members:** K.S.H. Daishka (230112C), J.M.T.D. Chandrasiri (230101R), D.W.K.G. Bulagala (230094U)

---

> **Note:** The Feasibility Report shares the same body content (Sections 1–8) as the Project Proposal. The full extracted content — Executive Summary, Problem Statement, Data Description, Methods, Architecture, Evaluation Plan, Expected Outcomes, Division of Work, and Bibliography — is documented in [01-Project-Proposal.md](01-Project-Proposal.md).

## Feasibility Highlights

The feasibility of AutoViz AI rests on the following being achievable with mature, well-documented, open technologies:

- **Technical feasibility** — Built on established tools: Next.js + FastAPI, Pandas/DuckDB for deterministic data processing, Vega-Lite for rendering, and the Model Context Protocol (MCP) for model-independent tool access. The LLM only *plans*; AutoViz validates, computes, and renders.
- **Model independence** — Reusing the same core services across the standalone web client and external MCP-compatible AI hosts (ChatGPT, Claude, others) avoids lock-in to a single provider.
- **Safety feasibility** — Read-only execution, no arbitrary code/SQL, session isolation, output limits, and validated Vega-Lite specs keep the system safe to run on arbitrary user CSVs.
- **Scope feasibility** — A working end-to-end MVP (~85% of scope) is targeted before the Week 8 mid-evaluation, with refinement and testing in later iterations (see [03-Schedule-Report.md](03-Schedule-Report.md)).
- **Evaluation feasibility** — Measurable metrics (profiling accuracy, query-plan correctness, chart suitability, response time, task completion) validated against manually prepared reference outputs.
