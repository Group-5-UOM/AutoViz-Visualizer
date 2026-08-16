# AutoViz AI — Project Documentation

**A Conversational Data Visualization and Dashboard Builder Using LLM-Guided CSV Analysis**

Semester 5 · In22-S5-CS3501 Data Science and Engineering Project · Department of Computer Science and Engineering, University of Moratuwa · **Group 5 / Project P09**

## What is AutoViz AI?

Upload a CSV, describe the charts or dashboards you want in plain English, and an LLM-guided agent profiles the data, plans a validated query, and builds interactive Vega-Lite dashboards you can arrange, resize, and export — no formulas, query languages, or manual chart configuration. The LLM only *plans*; Pandas/DuckDB deterministically *computes*, and the system *validates and renders*.

## Team

| Name | Index | Area |
|---|---|---|
| K.S.H. Daishka | 230112C | LLM, MCP & System Integration |
| J.M.T.D. Chandrasiri | 230101R | Frontend, Visualization & Dashboard Canvas |
| D.W.K.G. Bulagala | 230094U | Data Engine, Profiling & Backend Services |

Mentor: Dr. Chathuranga Hettiaracchi · TA: Shaveen Silva

## Documents (extracted from source PDFs)

| Doc | Source PDF |
|---|---|
| [01 — Project Proposal](01-Project-Proposal.md) | `DSEP grp5_project_proposal.pdf` |
| [02 — Feasibility Report](02-Feasibility-Report.md) | `Feasibility Report.pdf` |
| [03 — Schedule Report](03-Schedule-Report.md) | `Schedule report.pdf` |
| [04 — Improvement Plan](04-Improvement-Plan.md) | *(analysis — not from a PDF)* |
| [05 — Research Findings for AutoViz](05-Research-Findings-for-AutoViz.md) | Synthesized from 6 papers in [Research Papers/](Research%20Papers/) |
| [06 — MCP Server Plan](06-MCP-Server-Plan.md) | *(working spec — not from a PDF)* |
| [07 — MCP Tool Inventory](07-MCP-Tool-Inventory.md) | *(reference for the implemented `backend/` server — not from a PDF)* |
| [08 — Agentic Workflow Architecture](08-Agentic-Workflow-Architecture.md) | *(the implemented LangGraph workflow — not from a PDF)* |
| [09 — System Architecture & Design](09-System-Architecture.md) | *(system-level view of the implemented five layers — not from a PDF)* |
| [10 — Validation, Privacy, Security & Resource Controls](10-Validation-Security-Resource-Controls.md) | *(the implemented safety controls — not from a PDF)* |
| [11 — Backend API & Persistence](11-Backend-API-and-Persistence.md) | *(the implemented FastAPI gateway + PostgreSQL storage — not from a PDF)* |
| [12 — Software Architecture Document](12-Software-Architecture-Document.md) | `Template for Software Architecture Document.pdf` |
| [13 — Chart Library Expansion Research](13-Chart-Library-Expansion-Research.md) | *(research behind the expanded chart type set — not from a PDF)* |
| [14 — Cleaning Disclosure & Outlier-Robust Axes](14-Disclosure-and-Outlier-Handling.md) | *(the implemented notices channel + skew-aware axis scaling — not from a PDF)* |
| [15 — In-Place Chart Editing & Arbitrary Colours](15-In-Place-Chart-Editing.md) | *(the implemented chart identity, style block and edit surfaces — not from a PDF)* |
| [16 — Planner Model Strategy](16-Planner-Model-Strategy.md) | *(options analysis for replacing the hosted planner with a fine-tuned open-weight model — not from a PDF)* |
| [17 — Fine-Tuning Execution Plan](17-Fine-Tuning-Execution-Plan.md) | *(the phase plan the companion `AutoViz-Planner-Model` repo executes — not from a PDF)* |
| [18 — Complete Component Reference](18-Complete-Component-Reference.md) | *(every module, tool and route in the implemented system — not from a PDF)* |
| [19 — Preprocessing Parity: Ingestion, Correctness, Disclosure](19-Preprocessing-Parity-Roadmap.md) | *(the engineering record for the six-phase preprocessing work — not from a PDF)* |
| [20 — Preprocessing: Before, After, and What's Left](20-Preprocessing-Before-And-After.md) | *(the before/after account of the same work: capability gained, gaps remaining, and the order to take them in — not from a PDF)* |
| [21 — Project Status](21-Project-Status.md) | *(**start here** — whole-project status, verified against the code — not from a PDF)* |
| [22 — PDF Export and the FR-19 State Audit](22-Export-and-UI-States.md) | *(the dependency-free PDF writer, and the loading/empty/success/validation/recoverable/retry audit that closed criteria 7 and 8 — not from a PDF)* |
| [23 — Usability Evaluation](23-Usability-Evaluation.md) | *(heuristic evaluation — 14 findings, 6 fixed — plus the ready-to-run test protocol in [`usability/session-pack.md`](usability/session-pack.md). The sessions themselves are not run — not from a PDF)* |
| [24 — Performance and Evaluation](24-Performance-and-Evaluation.md) | *(the project's first measured numbers — latency, scaling, memory, ceilings, NL accuracy, chart quality, answer grounding — and the eight defects measuring them found. Harness in [`backend/bench/`](../backend/bench/) — not from a PDF)* |
| [25 — Mid-Evaluation Presentation](25-Mid-Evaluation-Presentation.md) | *(what to present and in what order: slide plan, demo script, the numbers to put on screen, rehearsed Q&A, and the completion arithmetic — not from a PDF)* |
| [26 — Remote MCP Access](26-Remote-MCP-Access.md) | *(**plan, not yet built** — per-user connection links so Gemini and other MCP hosts can drive AutoViz's tools directly. Verified against Google's connector requirements, the MCP auth spec, and the live EC2 host — not from a PDF)* |

## At a Glance

- **Stack:** Next.js (frontend) · FastAPI (backend) · Pandas / DuckDB (data engine) · Vega-Lite (charts) · Model Context Protocol (model-independent tool access)
- **Architecture:** Five layers — user interaction, MCP/API access, intelligence core, deterministic execution, storage — reused across a standalone web client and external MCP hosts (ChatGPT, Claude, etc.).
- **Timeline:** 12 July 2026 → 30 October 2026 (14 weeks, traditional SDLC). MVP (~85% of scope) targeted before the Week 8 mid-evaluation.
- **Status (16 Aug 2026):** 820 backend tests · 25 frontend tests · 18 MCP tools · 46 HTTP endpoints · 10 chart types · 14 cleaning operations · 8 input formats. **Nine of the ten** 18-August milestone criteria met; the outstanding one is a documented usability cycle — see [Doc 21](21-Project-Status.md).
- **Measured (16 Aug 2026):** a 1M-row question answered and charted in **68–78 ms**; 1000× the data costs **2.3×** the time; **39** frozen NL benchmark prompts; **10/10** chart specs valid against the real Vega-Lite schema — see [Doc 24](24-Performance-and-Evaluation.md).
