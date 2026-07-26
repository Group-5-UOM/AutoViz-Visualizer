# Member 01 — K.S.H. Daishika

## Member name

K.S.H. Daishika (230112C)

## Assigned role

MCP, LLM orchestration, and system integration

## Project objective of the component

Expose AutoViz as typed, independently testable MCP tools; integrate one LLM provider as an MCP client; orchestrate validated multi-tool sequences so natural-language requests become deterministic analyses and chart recommendations — without letting the LLM calculate final numbers.

## Detailed responsibilities

- Confirm the MCP-first architecture  
- Define the initial MCP tool list and end-to-end call sequences  
- Define typed request, response, and error schemas for every MCP tool  
- Document tool descriptions, examples, validation boundaries, and failure behavior  
- Build the MCP server skeleton and tool registry  
- Integrate one LLM provider as the MCP client  
- Implement `query_dataset` orchestration using the approved schema  
- Connect registration, profiling, and preview tools to the web workflow  
- Implement intent + rule-based chart recommendation  
- Add tool-call logging and chart provenance  
- Implement recoverable orchestration errors  
- Evaluate tool-selection correctness on the NL benchmark  
- Make the external connector go/no-go decision after the P0 freeze (P2)  

## Expected deliverables

MCP server/registry, typed tool interfaces, LLM client integration, orchestration layer, chart recommender, provenance/logging, MCP/orchestration tests, integration with backend tools and frontend chat responses.

## Required input data

- Frozen MCP / API contracts  
- Backend dataset, profile, preview, and query engines (or stubs)  
- NL benchmark prompts  

## Output contracts

MCP tool schemas; chat / tool-progress / provenance response shapes consumed by the frontend.

## Recommended implementation stages

1. Architecture + six-tool contract draft  
2. MCP registry skeleton + discovery  
3. Wrappers for register / profile / preview  
4. LLM client + `query_dataset` orchestration  
5. Rule-based chart recommendation  
6. Provenance, safe errors, MCP tests  
7. Benchmark-driven tool-description improvements  
8. P1 multi-turn context; P2 connector go/no-go  

## Baseline method

Single LLM provider selecting typed tools against stub or live backends with strict schema validation.

## Improved method

Hybrid recommendation, richer tool descriptions from benchmark failures, controlled multi-turn context (P1), optional external MCP hosts (P2).

## Evaluation metrics

Valid typed tool-call rate; multi-tool sequence success; recommendation suitability; absence of LLM-computed final numbers; recoverable error rate on invalid/ambiguous prompts.

## Dependencies on other members

- Query engine, profiling, chart-spec generation (Bulagala)  
- Chat UI, tool-progress display, dashboard rendering (Chandrasiri)  

## What can be developed independently

MCP registry, schema validation, LLM client against tool stubs, recommendation unit tests with synthetic field metadata.

## Integration procedure

Expose tools → wrap Bulagala engines → connect Chandrasiri chat to orchestration endpoint → weekly vertical-slice demo.

## Testing responsibilities

MCP discovery; valid/invalid calls; multi-tool sequences; benchmark tool-selection tests; provenance assertions.

## Documentation responsibilities

`docs/mcp-tools.md`, orchestration notes in architecture/integration docs; keep this member brief updated.

## Weekly milestone suggestions

- W1: architecture + typed tool draft + registry skeleton  
- W2: dataset tool wrappers + discovery + logging  
- W3: LLM client + query orchestration + initial recommendation  
- W4: provenance, safe errors, MCP tests  

## Definition of done

Matches `docs/definition-of-done.md` plus: supported request triggers a valid typed tool sequence; every displayed number comes from the deterministic backend; charts record provenance.

## Possible risks and solutions

| Risk | Solution |
|------|----------|
| LLM fabricates numbers | Never display model-calculated values; engine only |
| Waiting on backend | Use typed stubs/mocks until engines land |
| P2 connectors eat P0 time | Go/no-go only after feature freeze |

## First branch

`feat/01-mcp-tool-registry`
