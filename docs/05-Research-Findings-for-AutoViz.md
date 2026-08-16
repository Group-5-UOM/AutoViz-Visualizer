# Research Findings for AutoViz AI

Consolidated, project-relevant extraction from the six papers in [`Research Papers/`](Research%20Papers/) (full per-paper summaries in [`Research Papers/markdown/`](Research%20Papers/markdown/)). Organized by **what to build**, **what to measure**, and **what to cite** — not by paper.

**Sources:** VisEval (Microsoft, TVCG'24) · PandasPlotBench (JetBrains, 2025) · InsightLens (TVCG'24) · DynaVis (Harvard/MS, 2024) · WaitGPT (UIST'24, HKUST) · ChartGen (MIT/IBM, 2025)

---

## 1. The core thesis is empirically supported

AutoViz's central bet — **the LLM plans, it never computes or freely codes; execution is deterministic and validated** — is directly backed by measured failure rates in the literature, not just intuition:

| Evidence | Source |
|---|---|
| Even **GPT-4 fails legality checks on ~21–25%** of chart-generation tasks (wrong columns, wrong legends, chart doesn't match query) | VisEval |
| **Plotly code fails 22% of the time** even from GPT-4o — LLMs mis-use unfamiliar library APIs | PandasPlotBench |
| Common recurring LLM code defects: **incomplete workflows** (e.g., not excluding nulls before averaging), **non-existent symbols**, **edge-case transform failures**, **wrong columns**, **unreasonable parameter values** | WaitGPT (formative study) |
| Even when code *executes without error*, models still fail to faithfully reconstruct/represent data (best model: 0.58/1 data fidelity) | ChartGen |
| The single most common data-context failure was **fabricating a column that doesn't exist** (e.g., inventing "Decade" from "Year") | InsightLens |
| A generated Vega-Lite spec's most frequent bug: **wrong date-format representation** (string instead of Vega-Lite's `{date,month,year}` object) | DynaVis |

**Takeaway for the report:** Cite these numbers directly in your Problem Statement / Related Work to justify *why* AutoViz constrains the LLM to a structured, validated plan instead of letting it generate/execute arbitrary code — this is the strongest, most concrete argument you have, and it's backed by three independent research groups (Microsoft, JetBrains, HKUST/Harvard).

---

## 2. Concrete design patterns to adopt

### 2.1 Data profiling / schema summarization
- **Best-performing DataFrame description** (PandasPlotBench): `head(5)` rows **+ column names + column types**. This alone let single-sentence user tasks perform almost as well as detailed ones (task-score 89→85, vs. 36 with no task info at all).
- **LIDA-style summarizer** (used by DynaVis): atomic types + summary stats + sample values, **enriched by an LLM** with semantic descriptions and semantic-type prediction — pass the *summary*, never the raw data, into prompts.
- **Action for AutoViz:** the profiling layer should emit exactly this shape (head rows + types + LLM-enriched semantic tags) as the standard context object handed to the planning LLM.

### 2.2 Validation-first plan design
- **Restrict column/attribute selection to the actual schema** — InsightLells's IO agent explicitly constrains attribute selection to the given list specifically to prevent fabrication. This is the single most important validation rule for AutoViz's analysis-plan validator.
- **Closed grammars, not free text/code**, are the recurring winning pattern: VisEval's meta-information (allowed channels, sort spec), InsightLens's typed JSON insight schema, DynaVis's Vega-Lite spec + widget callback templates — none of these systems let the LLM emit arbitrary code for the parts that must be correct.
- **Post-generation program analysis / retry-on-error** (DynaVis): parse and validate the generated spec; on failure, feed the error back to the LLM and retry. Average **1.16 automatic retries** per edit was enough to reach a working result. AutoViz's Vega-Lite validation step should follow this retry pattern rather than failing outright.

### 2.3 Hybrid / deterministic scoring layered under the LLM
- **InsightLens's "interestingness" score** is a directly reusable recipe for ranking which insights/charts to surface: `S_final = ω·S_semantic + (1-ω)·S_statistical`, with **ω = 0.6**, where the statistical half is computed via actual function calls (e.g., Pearson r), never guessed by the LLM. This is a template for AutoViz's chart/insight ranking logic.
- Reinforces AutoViz's own hybrid recommender plan (rule-based compatibility scoring + LLM intent classification) — this pattern appears repeatedly across the literature as the way to keep LLM "judgment" bounded by deterministic checks.

### 2.4 Editing & steering UX (beyond one-shot NL)
- **DynaVis: persistent synthesized widgets.** Instead of only accepting more NL commands, when a user asks for an edit, generate both the edit *and* a lightweight widget (slider, dropdown) bound to a JS callback `(event, chart) => (transforms, chart)` so the user can keep tweaking that one property without new LLM calls. In DynaVis's study, this cut NL commands per task from 8.4 to 2.67 while participants explored far more values, and 96% preferred it. **Strong candidate feature for AutoViz's dashboard-editing experience** — e.g., "give me a slider for the date filter" instead of only "filter to 2023."
- **WaitGPT: steer without full regeneration.** Let users tweak a single step of an analysis pipeline in place and re-run only what changed, using a sandbox that preserves intermediate state. Maps well onto AutoViz's analysis-plan being edited field-by-field and re-executed deterministically.
- **Provenance / evidence display** (InsightLens): keep a visible link from every chart/insight back to the exact data/columns/operations that produced it — users actively use this to verify LLM output. AutoViz's "provenance" goal is validated as a real, used feature, not just a nice-to-have.

### 2.5 Chart-type & library choices
- **Vega-Lite is empirically validated** as the right rendering substrate — DynaVis builds its whole editing model around Vega-Lite's declarative, per-property-editable JSON, which is exactly AutoViz's plan.
- **Avoid/deprioritize Plotly-style complex-API libraries** for LLM-generated code; if AutoViz ever needs a Python-code fallback path, Matplotlib/Seaborn are far more reliable for LLMs than Plotly (1.8–5.2% vs. 22% failure rate).
- **3+ visual-channel charts (stacked bar, grouped line, grouped scatter) are measurably harder for LLMs** than 2-channel equivalents, and quality degrades further with query "hardness." AutoViz's chart recommender/validator should apply extra scrutiny to these chart types.

---

## 3. Evaluation methodology to borrow (fixes the weakest part of the proposal)

This is the highest-value section — it turns the vague "evaluation plan" in the proposal into a concrete, citable methodology.

### 3.1 Multi-dimensional metrics (VisEval framework)
Adopt VisEval's three-axis structure directly:
- **Validity** — does execution succeed / does a chart render at all (no crash)?
- **Legality** — does the chart actually match the query (right columns, right chart type, right sort/order, right channels)?
- **Readability** — is the chart visually clear (layout, scale/ticks, overlap, contrast)? VisEval shows this is automatable with a GPT-4V(ision) judge + rule checks, reaching **SRCC = 0.843** against human raters (comparable to the **0.782** inter-human-expert agreement) — i.e., automated readability judging is essentially as reliable as another human expert.

### 3.2 Ground truth as a feasible region, not exact match
VisEval's key insight: many NL queries have **multiple valid chart mappings** (e.g., "count by rank and gender" could put gender on the color channel or the x-axis — both correct). Label ground truth as a **set of acceptable configurations + meta-information** (allowed channels, sort rules), not a single fixed answer. This avoids false negatives when scoring AutoViz's outputs.

### 3.3 Dual scoring: visual + task-based
PandasPlotBench's approach: score generated charts two ways — **visual similarity to a reference** and **task-adherence** (does it satisfy what was asked) — via a multimodal LLM judge, since these only correlate at **r = 0.58** (they catch different failure modes). Task-based scoring correlated much better with human judgment (**r = 0.85**) than visual scoring (**r = 0.66**) — **prefer task-adherence scoring** as primary, visual as secondary.

### 3.4 Metrics NOT to use
**Code/spec string-similarity metrics (e.g., CodeBERTScore) were tested and explicitly discarded** by PandasPlotBench — they showed no correlation with actual quality, since correct and incorrect code targeting the same task often differ only in irrelevant implementation details. **Do not use naive JSON/code diffing** as an AutoViz accuracy metric; measure functional/task correctness instead.

### 3.5 Existing datasets to benchmark against or cite
- **nvBench** — the standard NL2VIS dataset (153 databases, ~7,247 visualizations, 25,750 NL/VIS pairs), cited by nearly every paper in this set. Known to have noisy/ambiguous labels.
- **VisEval** — a cleaned, curated subset of nvBench (1,150 visualizations, 2,524 NL/VIS pairs, 146 databases), open source (github.com/microsoft/VisEval), with the validity/legality/readability evaluation code ready to reuse or adapt.
- **PandasPlotBench** — 175 tasks with real CSV files + ground-truth Matplotlib code, open source (HuggingFace + GitHub), useful if AutoViz ever needs a code-generation fallback baseline for comparison.

### 3.6 A concrete benchmark recipe for AutoViz
Combining the above with the existing improvement plan ([`04-Improvement-Plan.md`](04-Improvement-Plan.md)):
1. Build **15–20 datasets × 5–10 tasks** (~100–150 total), gold-labeled as a **feasible region** (VisEval-style meta-information), not single exact answers.
2. Score every generated result on **validity / legality / readability** (VisEval axes) plus **task-adherence** (PandasPlotBench-style LLM judge).
3. Report **plan accuracy, chart-type match, task-completion rate** as headline numbers — do **not** report code/JSON similarity scores.
4. Sanity-check the automated judge against a small human-rated subset and report the correlation (both papers show ~0.65–0.85 is achievable and expected).

---

## 4. Risk checklist — guard against these specific, observed failure modes

Distilled into a validator checklist AutoViz's plan-validation layer should explicitly test for:

- [ ] **Fabricated columns** — LLM references a column/field not in the schema (InsightLens's top failure mode).
- [ ] **Wrong column selection** — right operation, wrong field (WaitGPT, VisEval).
- [ ] **Incomplete workflow** — e.g., aggregating without excluding nulls (WaitGPT).
- [ ] **Bad date/temporal formatting** — dates as raw strings instead of structured date objects (DynaVis's most common bug).
- [ ] **Illegal chart-query mismatch** — chart type or encoding doesn't reflect what was asked (VisEval legality).
- [ ] **Unreasonable parameter values** — e.g., absurd outlier thresholds, bad bucket sizes (WaitGPT).
- [ ] **Non-existent function/operation calls** — LLM invents an aggregation or transform not in the allow-list (WaitGPT).
- [ ] **Overly complex chart encodings** — 3+ channel charts (stacked/grouped) are disproportionately error-prone; validate these more strictly (VisEval).

---

## 5. Bibliography additions for the Proposal / Final Report

Add these six papers plus the two datasets they all point to, replacing the current thin "prior art" coverage:

1. Chen, N., Zhang, Y., Xu, J., Ren, K., Yang, Y. (2024). *VisEval: A Benchmark for Data Visualization in the Era of Large Language Models.* IEEE TVCG. arXiv:2407.00981.
2. Galimzyanov, T., Titov, S., Golubev, Y., Bogomolov, E. (2025). *Drawing Pandas: A Benchmark for LLMs in Generating Plotting Code.* arXiv:2412.02764.
3. Weng, L., Wang, X., Lu, J., Feng, Y., Liu, Y., Feng, H., Huang, D., Chen, W. (2024). *InsightLens: Augmenting LLM-Powered Data Analysis with Interactive Insight Management and Navigation.* IEEE TVCG. arXiv:2404.01644.
4. Vaithilingam, P., Glassman, E.L., Inala, J.P., Wang, C. (2024). *DynaVis: Dynamically Synthesized UI Widgets for Visualization Editing.* arXiv:2401.10880.
5. Xie, L., Zheng, C., Xia, H., Qu, H., Zhu-Tian, C. (2024). *WaitGPT: Monitoring and Steering Conversational LLM Agent in Data Analysis with On-the-Fly Code Visualization.* UIST '24. arXiv:2408.01703.
6. Kondic, J., et al. (2025). *ChartGen: Scaling Chart Understanding via Code-Guided Synthetic Chart Generation.* arXiv:2507.19492.
7. Luo, Y., Tang, J., Li, G. (2021). *nvBench: A Large-Scale Synthesized Dataset for Cross-Domain Natural Language to Visualization Task.* arXiv:2112.12926.
8. (Existing) Satyanarayan, A., Moritz, D., Wongsuphasawat, K., Heer, J. (2017). *Vega-Lite: A Grammar of Interactive Graphics.* IEEE TVCG.

**Also worth naming and contrasting explicitly** (mentioned inside these papers, not separately read, but directly relevant competitors/prior art): **LIDA** (Microsoft), **PandasAI**, **Chat2VIS**, **ChartLlama**, **MatPlotAgent/MatPlotBench**, **Plot2Code**, **ChartMimic**, **DS-1000** — see each paper's own related-work section in [`Research Papers/markdown/`](Research%20Papers/markdown/) for how they position against these.

---

## 6. One-paragraph synthesis (usable in the report intro)

> Recent work confirms that letting an LLM directly generate and execute arbitrary visualization code is unreliable: state-of-the-art models fail legality checks on roughly a quarter of NL2VIS tasks (VisEval), produce non-executable or API-incompatible code on unfamiliar libraries at rates up to 22% (PandasPlotBench), and commonly fabricate non-existent columns or mishandle structured values such as dates (InsightLens; DynaVis). These findings motivate AutoViz's core design decision: the LLM is restricted to producing a **validated, schema-constrained analysis plan**, which is then executed **deterministically** and rendered through the well-supported **Vega-Lite** grammar — with every result traceable back to its source query (provenance), following patterns shown effective in InsightLens and WaitGPT.
