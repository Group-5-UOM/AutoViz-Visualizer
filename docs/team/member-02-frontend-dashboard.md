# Member 02 — J.M.T.D. Chandrasiri

## Member name

J.M.T.D. Chandrasiri (230101R)

## Assigned role

Frontend, visualization, dashboard canvas, and usability

## Project objective of the component

Build the AutoViz web experience so a non-technical user can upload a CSV, converse in plain English, see verified tables and Vega-Lite charts, arrange them on an editable dashboard, and export the result — with clear loading and error states throughout.

## Detailed responsibilities

- Produce wireframes for upload, profile, preview, chat, visualization, dashboard, error, and provenance screens  
- Select and document React, Vega-Lite, and dashboard canvas libraries  
- Define frontend API contracts and mock responses for every core state  
- Build the React application shell and routing  
- Implement CSV drag-and-drop / file-picker upload with progress and failures  
- Build dataset profile cards and a limited preview table  
- Build the conversational chat interface (history, tool progress, tables, charts)  
- Render supported Vega-Lite specs with titles, labels, and fallback errors  
- Create draggable / resizable dashboard widgets (add, rearrange, resize, delete)  
- Add basic chart-editing controls  
- Build save-and-reopen workflow against backend APIs  
- Export the complete dashboard as image and PDF  
- Write component and frontend e2e tests  
- Conduct task-based usability testing and fix critical issues  

## Expected deliverables

React app, upload/profile/chat/dashboard UIs, Vega-Lite rendering, export, frontend tests, usability report, demo-ready UX polish.

## Required input data

- Frozen API / mock response examples  
- Sample Vega-Lite specifications  
- Backend upload/profile/chat/dashboard endpoints (or mocks)  

## Output contracts

Dashboard widget schema (layout, chart, metadata, version) handed to backend persistence.

## Recommended implementation stages

1. Wireframes + library choices + mocks  
2. App shell, navigation, shared state  
3. Upload + profile + preview  
4. Chat shell with mock states + sample chart render  
5. Live orchestration connection + dashboard canvas  
6. Editing, persistence UI, export  
7. Component/e2e tests + usability cycle  

## Baseline method

Mock-driven UI completing the full visual workflow before live APIs.

## Improved method

Live tool-progress streaming, richer provenance display, accessibility polish, follow-up UX (P1).

## Evaluation metrics

Task completion rate/time; critical workflow completion; chart render reliability; export completeness (no clipping); usability feedback scores.

## Dependencies on other members

- Profile/preview/query/chart-spec APIs (Bulagala)  
- Chat/tool-progress/orchestration responses (Daishika)  

## What can be developed independently

Entire UI against frozen mocks and sample Vega-Lite JSON; canvas behavior without live LLM.

## Integration procedure

Replace mocks feature-by-feature after contract tests pass; weekly vertical-slice demo with real upload → chart path.

## Testing responsibilities

Component tests for upload/chat/chart/dashboard/error; frontend e2e for main journey; cross-browser demo checks; usability sessions.

## Documentation responsibilities

Frontend README notes, UX findings; keep this member brief updated.

## Weekly milestone suggestions

- W1: wireframes, libs, mocks, React shell  
- W2: upload/profile/preview/chat UI + sample Vega-Lite  
- W3: live chat integration + dashboard canvas  
- W4: editing, save/reopen, export, usability cycle  

## Definition of done

Matches `docs/definition-of-done.md` plus: user completes full workflow without editing data/chart code; dashboard persists after reopen; exports include all charts without clipping.

## Possible risks and solutions

| Risk | Solution |
|------|----------|
| Waiting on APIs | Frozen mocks for all core states |
| Silent chart failures | Explicit fallback UI on invalid specs |
| Export clipping | Fixed export layout + multi-size tests |

## First branch

`feat/02-frontend-shell-mocks`
