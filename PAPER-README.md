# AutoViz AI — Conference Paper

IEEE conference manuscript for **AutoViz AI** (CS3501 · Group 05 · Project P09).

## Files

| Path | Role |
| --- | --- |
| `paper.tex` | Main IEEE manuscript |
| `paper-figures/` | Figures (architecture, NL outcomes, scaling, testing, UI, plans, …) |
| `PAPER-README.md` | This file |

**Related project docs (sources for the paper):**

| Doc | Use in paper |
| --- | --- |
| SRS v1.1 (29 Jul 2026) | Requirements baseline, UC-01–UC-04, FR/UR/REL/PERF/SEC IDs, T/D/I/A matrix |
| Project proposal / feasibility | Problem, scope, stack constraints |
| `docs/24-Performance-and-Evaluation.md` | NL suite, chart benches, scaling numbers |
| `docs/08` / `09` / `11` | Agent, architecture, API/persistence |
| `validations/README.md` | nvBench / VisEval runners |

## Authors (paper layout)

**Line 1:** K.S.H. Daishika · J.M.T.D. Chandrasiri · D.W.K.G. Bulagala  
**Line 2:** Shaveen De Silva · Chathuranga Hettiarachchi  

(`\linebreakand` after the third student author.)

## What the paper claims (aligned with SRS + shipped system)

- **Trust model:** LLM emits typed `AnalysisPlan` only; DuckDB computes; Vega-Lite renders (SRS FR-63–FR-136).
- **Use cases:** UC-01 upload/profile · UC-02 ask/chart · UC-03 dashboard · UC-04 MCP.
- **Privacy:** schema/profile to LLM, not full rows (FR-76–FR-82).
- **MVP extensions called out honestly:** 8 file types (SRS said CSV-only); React+Vite (SRS named Next.js); OAuth; LangGraph interrupts; AWS+Playwright CI.
- **REL-06:** 39 prompts → 32 correct, 7 safe clarify/decline, **0** silent wrong.
- **Verification:** pytest (~1083), frontend unit (56), Playwright (30 runs), corpus benches → SRS methods T/D/I/A.

## Compile

```bash
cd AutoViz-Visualizer
pdflatex paper.tex
pdflatex paper.tex
```

Needs `IEEEtran` plus: `graphicx`, `booktabs`, `cite`, `amsmath`, `url`.

Figures resolve via `\graphicspath{{paper-figures/}}`.

## Before submission checklist

1. Confirm author names/emails/ORCID (esp. Shaveen De Silva, Dr. Hettiarachchi).
2. Replace illustrative UI/testing figures with production screenshots if the venue requires.
3. Re-run benches and refresh Table numbers if the planner changed:
   ```bash
   cd backend && uv run python -m bench.nl_run
   uv run python -m bench.chart_quality
   uv run python -m bench.perf
   ```
4. Check venue **page limit**; trim Discussion / abridge Table~\ref{tab:trace} if needed.
5. Attach or cite the full SRS PDF in the submission package if the conference allows supplementary material.
6. Optional: convert `\begin{thebibliography}` to BibTeX for the venue’s style file.

## Regenerating figures

```bash
cd backend
uv run --with matplotlib python /path/to/figure_script.py
# or re-run the matplotlib snippets used to build paper-figures/
```

UI/testing overview PNGs under `paper-figures/` may be illustrative; prefer real screenshots for camera-ready.
