# AutoViz AI — Project Proposal

**A Conversational Data Visualization and Dashboard Builder Using LLM-Guided CSV Analysis**

| | |
|---|---|
| Course | In22-S5-CS3501 Data Science and Engineering Project |
| Department | Computer Science and Engineering, University of Moratuwa |
| Group ID | 5 |
| Project ID | P09 |
| Mentor | Dr. Chathuranga Hettiaracchi |
| Teaching Assistant | Shaveen Silva |

**Team Members**

| Name | Index |
|---|---|
| K.S.H. Daishka | 230112C |
| J.M.T.D. Chandrasiri | 230101R |
| D.W.K.G. Bulagala | 230094U |

---

## 1. Executive Summary

A conversational data visualization platform where users upload a CSV file and describe the charts or dashboards they need in plain English. An LLM-based agent analyzes the dataset, generates validated queries and transformations, and creates suitable visualizations. **Pandas or DuckDB** handles data processing; **Vega-Lite** renders structured charts. Users can combine multiple charts on an interactive dashboard, rearrange and resize them, and export the final dashboard as an image or PDF. The goal is to help non-technical users turn raw data into complete dashboards without formulas, query languages, or manual chart configuration.

## 2. Problem Statement

Creating charts and dashboards from raw data usually requires manual cleaning, query/formula writing, chart selection, and dashboard arrangement — difficult for students, small businesses, and non-technical users, and repetitive/time-consuming for analysts. Existing natural-language tools (Power BI Copilot, Tableau Agent) target large, paid enterprise platforms. AutoViz provides a lightweight, chat-based alternative: upload a CSV, describe what you want, and the system automatically handles data profiling, transformations, chart selection, and dashboard creation.

## 3. Data Description

- Works with structured tabular data in **CSV** format uploaded by users.
- Supports numerical, categorical, and date/time attributes across domains: sales, education, healthcare, finance, weather, public open data.
- Development/testing uses public datasets from **Kaggle** and government open-data portals.
- On upload, the system performs automatic **data profiling**: column types, missing values, duplicate records, summary statistics.
- General-purpose — not limited to a single dataset; analyzes any well-structured CSV.

## 4. Methods

Combines data profiling, NLP, and data visualization. After upload, the system profiles the data (column types, missing values, summary stats via Pandas/DuckDB). An LLM agent interprets the natural-language request, identifies required operations (filter, group, aggregate), and generates a structured query. It recommends an appropriate chart type and generates a Vega-Lite visualization on an interactive dashboard where users edit, arrange, save, and export.

**Evaluation criteria:** query accuracy, chart recommendation accuracy, visualization correctness, user satisfaction.

### 4.1 Architectural Approach

Five layers: user interaction, standardized MCP/API access, AutoViz intelligence core, deterministic execution, and storage. The same core services are reused by both the standalone web client and external MCP-compatible AI hosts — preventing dependency on a single model provider (**hybrid, model-independent architecture**).

### 4.2 Main System Components

- **User Interaction Layer** — Upload CSV, ask questions in natural language, edit the dashboard. Via the AutoViz web app or an MCP-compatible AI host.
- **AutoViz MCP Server & API Gateway** — Exposes typed dataset, query, visualization, and dashboard tools. Normalizes host-specific file references into an internal dataset identifier.
- **AutoViz Intelligence Core** — Profiles the dataset, converts user intent into a structured semantic analysis plan, validates columns/operations, recommends chart types.
- **Deterministic Data Processing Layer** — Pandas/DuckDB executes filtering, grouping, aggregation, sorting, derived-column creation, and statistics. *The LLM is never trusted to calculate final numerical results.*
- **Visualization & Dashboard Layer** — A validated Vega-Lite spec is generated and rendered on an interactive canvas. Users drag, resize, edit, delete, save, version, and export widgets.
- **Storage Layer** — Datasets in session-isolated temporary storage; user accounts, dataset metadata, chart specs, and dashboard layouts in a database.

### 4.3 End-to-End Processing Workflow

1. User uploads a CSV through AutoViz or an external AI host.
2. AutoViz registers the file, assigns an internal dataset ID, and performs schema + data-quality profiling.
3. User submits a request, e.g. "Show monthly revenue by region."
4. The LLM interprets the request and selects the required AutoViz MCP tools.
5. AutoViz creates a typed semantic analysis plan (columns, filters, grouping, aggregations, sorting, intended visualization).
6. Validation module checks column existence, data-type compatibility, supported operations, output-size limits, and security rules.
7. The validated plan is translated into controlled Pandas operations or read-only DuckDB SQL and executed.
8. The visualization recommender combines analytical intent, column types, cardinality, and readability rules to select a chart.
9. AutoViz generates and validates a Vega-Lite JSON spec and returns the chart, explanation, and provenance.
10. The chart is added to the dashboard canvas; the user can refine the request or edit the layout.

### 4.4 MCP Tool Design

Rather than one large black-box function, the MCP server provides **small, typed, independently testable tools** — improving traceability, validation, reuse across AI hosts, and component-level evaluation.

### 4.5 Structured Query Planning and Validation

The LLM generates a **structured analysis plan** instead of unrestricted Python/SQL. AutoViz validates the plan, executes only safe read-only operations, and attaches provenance (dataset, columns, filters, aggregations, chart type) to every visualization.

### 4.6 Visualization Recommendation

A **hybrid recommender**, not the LLM alone. A rule-based component measures compatibility between analytical intent, column data types, cardinality, temporal structure, and readability. The LLM classifies intent (comparison, trend, distribution, relationship, composition, ranking). Candidate chart types are scored and the best valid option generates the Vega-Lite spec.

### 4.7 Robustness, Privacy, and Security

- Session isolation for uploaded datasets; automatic deletion of temporary files.
- CSV file-size, row-count, encoding, and schema checks before processing.
- Read-only analytical execution with timeouts, memory limits, and output-row limits.
- No arbitrary Python, shell-command, or unrestricted SQL execution.
- CSV cell contents treated strictly as data (prevents dataset text becoming model instructions).
- Every Vega-Lite spec validated before rendering.
- Logging of tool calls, validation failures, execution steps, and chart provenance.

## 5. Evaluation Plan

Evaluated using multiple CSV datasets and predefined natural-language tasks. Metrics: data-profiling accuracy, query-plan correctness, successful tool execution, chart-type suitability, visualization correctness, response time, end-to-end task completion. User testing assesses usability, clarity, and satisfaction; results compared with manually prepared reference outputs.

## 6. Expected Outcomes and Success Criteria

- A web-based intelligent dashboard builder + a reusable MCP server converting natural-language requests into verified data operations and interactive visualizations.
- Upload and profile structured CSV files from multiple domains.
- Explore datasets through natural-language conversation.
- Use external MCP-compatible LLM hosts or the standalone AutoViz chat interface.
- Generate safe, validated filtering, grouping, aggregation, and sorting operations.
- Recommend appropriate chart types using user intent and dataset characteristics.
- Generate valid Vega-Lite visualizations with transparent provenance.
- Create dashboards with multiple draggable and resizable widgets.
- Edit, save, reload, version, and export dashboards as an image or PDF.
- Demonstrate consistent performance across multiple datasets and AI hosts.

## 7. Division of Work

**K.S.H. Daishika — LLM, MCP, and System Integration**
- Design and implement the AutoViz MCP server and typed tool interfaces.
- Develop natural-language intent extraction and semantic analysis plan generation.
- Integrate one or more external MCP-compatible AI hosts with AutoViz.
- Implement tool-call validation, orchestration, logging, and end-to-end integration.

**J.M.T.D. Chandrasiri — Frontend, Visualization, and Dashboard Canvas**
- Develop the AutoViz web interface, CSV upload workflow, and conversational UI.
- Implement Vega-Lite chart rendering and chart-editing controls.
- Build drag, resize, rearrange, delete, save, and export dashboard features.
- Conduct usability testing and improve UX.

**D.W.K.G. Bulagala — Data Engine, Profiling, and Backend Services**
- Implement CSV registration, schema inference, data profiling, and dataset preview.
- Develop controlled Pandas/DuckDB operations for filtering, grouping, aggregation, sorting.
- Implement storage, session isolation, user/dashboard persistence, and backend APIs.
- Develop reliability, resource-limit, privacy, and security mechanisms.

**Shared:** All members contribute to requirements analysis, benchmark creation, integration testing, evaluation, deployment, documentation, and the final symposium demonstration.

## 8. Preliminary Bibliography

1. Satyanarayan, A., Moritz, D., Wongsuphasawat, K., Heer, J. (2017). *Vega-Lite: A Grammar of Interactive Graphics.* IEEE TVCG, 23(1), 341–350.
2. Model Context Protocol (2025). *Specification and Architecture Documentation.* https://modelcontextprotocol.io/
3. OpenAI. *Apps SDK and MCP Documentation.* https://developers.openai.com/apps-sdk/
4. Anthropic. *Model Context Protocol and MCP Connector documentation.* https://docs.anthropic.com/en/docs/mcp
5. DuckDB Foundation. *DuckDB Documentation.* https://duckdb.org/docs/
6. The Pandas Development Team. *Pandas Documentation.* https://pandas.pydata.org/docs/
7. Wilkinson, L. (2005). *The Grammar of Graphics.* Springer.
8. Wongsuphasawat, K., et al. (2016). *Voyager 2: Augmenting Visual Analysis with Partial View Specifications.* Proc. CHI 2017.
9. *Vega-Lite Documentation.* https://vega.github.io/vega-lite/docs/
10. Tableau. *Tableau AI and Natural-Language Analytics Documentation.* https://www.tableau.com/products/artificial-intelligence
