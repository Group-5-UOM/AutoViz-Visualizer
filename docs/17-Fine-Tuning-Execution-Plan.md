# 17 — Fine-Tuning Execution Plan

Step-by-step execution plan for replacing the Gemini planner with a fine-tuned Qwen3.5 model,
with the research basis for each methodological choice.

**Companion to [16 — Planner Model Strategy](16-Planner-Model-Strategy.md).** Doc 16 is the
*options analysis* and holds the evidence for why this approach was chosen. This doc is the
*execution plan* — what to build, in what order, and how to know each step worked. Where 17 says
"see §16.x" it means a section of that doc.

Grounded in `backend/` on branch `feat/cleaning-disclosure` (commit `0d5d080`).
Bibliography in §8; citations appear inline as **[N]**.

---

## 0. Decisions taken

| Decision | Choice | Where argued |
|---|---|---|
| Approach | Option C — fine-tune an open-weight model | §16.2 |
| Base models | **Qwen3.5 4B and 9B**, trained identically from one dataset | §16.7.4 |
| Training venue | Free **Kaggle** T4 (16 GB), 30 h/week | §16.7.1 — the 4 GB laptop cannot train |
| Trainer | **Unsloth** (QLoRA) | §16.2 |
| Serving | **Ollama** locally; production home deferred | §16.7.7 |
| Scope | **`generate_plan` only** — `compose` stays hosted | §16.1.1 |
| Retrieval | Built **before** training, shares the same corpus | §16.9 |
| **Teacher** | **Gemini 3.5 Flash, paid tier** | §0.1 below |

### 0.1 Gemini as teacher — the decision and its mitigation

**Decided 2026-08-04: Gemini is the teacher model.** §16.10 recommended otherwise; this overrides it.
The reasoning is sound — Gemini is already the production planner, so its outputs are the highest-quality
labels available with zero additional integration, and the terms contain no explicit prohibition on
training from outputs (§16.10.1).

Three conditions make this defensible, and **all three are mandatory**:

1. **Paid tier only, never free.** The free tier's terms state Google *"uses the content you submit to
   the Services and any generated responses to provide, improve, and develop Google products and
   services and machine learning technologies."* Generating traces on the free tier would send user
   CSV schemas, column names and result rows into Google's training pipeline — while building a
   privacy-motivated feature. The paid tier explicitly does not do this. **This is the one exposure
   that is concrete rather than hypothetical, and it costs a few dollars to eliminate.**
2. **The validator is the labelling authority, not Gemini.** Every candidate plan is filtered through
   `services/validation.py` and actual execution (§3.3). Gemini proposes; the repo's own deterministic
   validator disposes. This is rejection sampling **[6][7]**, and it means the artefact is not a
   distillation of Gemini's judgement but a filtered corpus of plans that provably work.
3. **Write the reading down.** The residual grey area is the clause *"You may not use the Services to
   develop models that compete with the Services"* (§16.10.1). The good-faith reading — a narrow
   CSV-analysis planner emitting a validated `AnalysisPlan` is not a competitor to a general-purpose
   LLM API — belongs in the project report, stated once and explicitly, not left implicit.

Back-translation (§16.10.3, option A) is **not dropped** — it is retained in §3.4 as the coverage
generator, because real traffic cannot cover every chart type and operator no matter who the teacher is.

---

## 1. Prerequisites

Before Phase 0 starts. All are one-off.

| # | Item | Command / note |
|---|---|---|
| 1.1 | Gemini **paid** API key, billing enabled | `GOOGLE_API_KEY` in `backend/.env`; verify the project is not on free quota |
| 1.2 | Kaggle account, phone-verified | Phone verification is required for GPU access |
| 1.3 | Ollama installed | Not currently installed. Windows native build |
| 1.4 | Branch | `git checkout -b feat/planner-finetune` off `feat/cleaning-disclosure` |
| 1.5 | Dataset fixtures | `test-data/` — confirm coverage is wide enough to profile against (§3.2) |

---

## 2. Phase 0 — Evaluation harness  *(3 days)*

**Nothing downstream is meaningful without this.** There is currently no measurement of plan quality
anywhere in `backend/tests/` — the suite injects `FakePlanner` and tests deterministic code (§16.1.6).
Without a harness, "the fine-tune worked" is an unfalsifiable claim.

Methodology follows text-to-SQL benchmark practice **[1][2]**: **execution accuracy** is the primary
metric, because a plan that differs textually from a reference plan may still be correct, while a
plan that fails to execute is definitely not.

### Step 0.1 — Scaffold

Create `backend/evals/` as a package separate from `tests/` (it is slow, costs money, and needs
network — it must not run in CI's `pytest tests/`):

```
backend/evals/
  __init__.py
  cases/            # golden cases, one JSON per case
  runner.py         # takes any PlannerLLM, returns a MetricsReport
  metrics.py
  report.py         # renders the comparison table
```

### Step 0.2 — Golden case set

**50–60 cases.** Each is `(request, dataset_id, expected_properties)`.

Assert **properties, not byte equality** — many distinct plans are correct for one question. Assert on:
required columns present in `group_by`/`aggregations`, aggregation function, chart family, filter
presence. This mirrors execution-accuracy grading **[1]**.

Coverage matrix — every cell needs at least one case:

- **10 chart types** from `ChartType` ([analysis_plan.py:29](../backend/src/autoviz/schema/analysis_plan.py#L29))
- **6 intents** from `Intent` ([analysis_plan.py:41](../backend/src/autoviz/schema/analysis_plan.py#L41))
- **Edge cases:** ambiguous requests (should clarify, not guess), multi-task requests, refinements,
  requests over the numeric-coded categoricals (`pclass`, `survived`), and requests that must trigger
  preprocessing disclosure.

> **Freeze this set and never train on it.** It is the held-out test set for every later phase. A case
> that leaks into training data invalidates every number in §6.

### Step 0.3 — Metrics

| Metric | Definition | Why |
|---|---|---|
| **Schema-valid rate** | Parses as `AnalysisPlan` | Isolates *shape* failures — the class constrained decoding removes |
| **Semantic-valid rate** | Passes `services/validation.py` | Isolates *column-choice* failures — what only a better model or retrieval fixes |
| **Execution success** | Produces a result table | The primary metric **[1][2]** |
| **Property match** | Matches `expected_properties` | Catches "executed but answered the wrong question" |
| **Repair rate** | Mean `plan_attempts` per task | Cost/latency proxy; the first thing a weak model degrades (§16.1.2) |
| **p50 / p95 latency** | Per `generate_plan` call | Serving-viability gate |
| **Tokens in/out** | Per call | Measures the prompt-compression win in §5 |

### Step 0.4 — Baseline

Run against Gemini 3.5 Flash. **Commit the numbers to the repo** (`backend/evals/baselines/`) — this
is the bar every later phase is measured against.

### Step 0.5 — `compose` rubric

`compose` is not being fine-tuned, but it needs a floor so a later change cannot silently regress it.
~20 cases, manually scored. Per [Docs 14](14-Disclosure-and-Outlier-Handling.md), score as
**failure**: any number not present in the result table, and any dropped `disclosed` severity notice.

**Acceptance:** one command produces a metrics table for any `PlannerLLM`; Gemini's baseline is committed.

---

## 3. Phase 1 — Provider plumbing + constrained decoding  *(2 days)*

### Step 1.1 — Connection passthrough

`init_chat_model(self._model_id, temperature=0)`
([client.py:188](../backend/src/autoviz/llm/client.py#L188)) accepts no connection kwargs. Add:

- `AUTOVIZ_PLANNER_BASE_URL`, `AUTOVIZ_PLANNER_API_KEY` → passed through with `model_provider="openai"`
- `langchain-openai` to `pyproject.toml`
- Rename `GeminiPlanner` → `Planner`, keeping `GeminiPlanner` as a deprecated alias (referenced in
  [deps.py:59](../backend/src/autoviz/api/deps.py#L59), [graph.py:27](../backend/src/autoviz/agent/graph.py#L27))
- Document both in `.env.example` and `README.md`

**Acceptance:** Gemini path byte-identical when the new vars are unset; Ollama reachable when set.

### Step 1.2 — Constrained decoding  ⚠️ *do this before any training*

Emit `AnalysisPlan.model_json_schema()` as the grammar constraint — `guided_json` on vLLM, the
`format` field on Ollama. Grammar-constrained decoding makes schema-invalid output **impossible by
construction**; XGrammar **[3]** is the current standard implementation, with **[4]** covering the
dynamic/agentic case.

> ⚠️ **The one experiment that can invalidate the plan.** `AnalysisPlan.preprocessing` is a
> discriminated union with field aliases (`from`, `as`), so its JSON Schema uses `$ref` + `oneOf`.
> Ollama's grammar implementation is less battle-tested than vLLM's, and vLLM has no native Windows
> support (§16.7.5). **If Ollama cannot enforce this schema, the fine-tune must carry the entire load
> of producing valid shapes, which materially increases the training data needed (§3.5).** Test it on
> day one — it is an afternoon's work and it changes the budget.

**Acceptance:** schema-valid rate = 100% on the golden set under constrained decoding; the `$ref`/`oneOf`
result is recorded either way.

### Step 1.3 — Generic-model baselines

Run Phase 0 evals over **generic, untrained** Qwen3.5 4B and 9B via Ollama.

These two numbers are what the fine-tune must beat. Expect the generic 4B to do poorly — a 4B is too
small to absorb a 2.4k-token `PLAN_GUIDE` from context. That is the gap the fine-tune exists to close
(§16.7.4), so a weak result here is information, not a reason to stop.

---

## 4. Phase 2 — Retrieval  *(4 days)*

Built **before** training, because it shares the trace corpus and ships value immediately (§16.9.3).

The closest published analogue is NL→DSL generation over ~700 custom function names **[5]**, which
found optimised RAG *matched* a fine-tuned model on similarity and **beat it by 2 points on
compilation rate**. DAIL-SQL **[1]** establishes the retrieval design: select examples by similarity
on **both question and query**, and organise them to preserve question→output mappings.

### Step 2.1 — Trace store

New table + repository module. **Do not extend `observability.py`** — its hash-only discipline
([observability.py:63-73](../backend/src/autoviz/observability.py#L63)) is deliberate and must stay
intact (§16.1.6).

Schema: `request_text`, `task_text`, `dataset_schema` (JSON), `profile_summary`, `plan` (JSON),
`plan_attempts`, `validation_errors`, `executed_ok`, `row_count`, `created_at`, `consent_version`.

**Opt-in, off by default.** Column names and sample values are user data.

### Step 2.2 — Embedding index

Local `sentence-transformers` (`all-MiniLM-L6-v2`, ~80 MB) — runs on CPU, no GPU contention, no
external service. At a few thousand rows, cosine similarity over a NumPy array is sufficient;
**no vector database is needed.**

### Step 2.3 — Three retrieval paths

| Path | Retrieve | Injected into |
|---|---|---|
| **Few-shot plans** | top-k=3 nearest `(task → validated plan)` | `_PLAN_SYSTEM` |
| **Schema narrowing** | columns relevant to the task | replaces the full schema dump at [client.py:236-244](../backend/src/autoviz/llm/client.py#L236) |
| **Repair examples** | past `(validation_error → corrected plan)` | repair-attempt prompt only |

Schema narrowing matters more than it looks: `generate_plan` currently sends **every** column, so a
150-column CSV is both expensive and actively harmful — more plausible-looking wrong columns to choose
between.

### Step 2.4 — Measure

Run Phase 0 against Gemini **with** retrieval. **[1]** reports that similarity-selected examples beat
*randomly* selected ones — so also run a random-selection arm. If random matches similarity, the
retrieval is not working and the embedding or the `k` is wrong.

**Acceptance:** semantic-valid rate improves over the §0.4 baseline; similarity beats random.

---

## 5. Phase 3 — Training data  *(5 days — the long pole)*

Target: **1,500–2,500 examples**, consistent with the 1,000–5,000 band for domain specialisation
(§16.2). Two generators, because neither alone gives both realism and coverage.

### Step 3.1 — Generator A: Gemini teacher + rejection sampling

For each input task, sample **k = 4** candidate plans from Gemini at `temperature=0.7` (not 0 — the
point is diversity), then keep only candidates that **both** validate and execute.

This is Rejection sampling Fine-Tuning **[6]**, the same mechanism as STaR **[7]**: generate many
candidates, keep the verified ones, train on those. DART-Math **[8]** adds the refinement that
sampling should be **difficulty-aware** — allocate more samples to inputs where the teacher fails
more often, rather than uniformly, since uniform sampling over-represents easy cases.

**Why this is unusually cheap here:** most projects must build a verifier or pay a judge model.
This repo already has a deterministic one — `services/validation.py` plus an executor that either
returns a result table or does not. The filter costs nothing and cannot be gamed.

> **Label with the repaired plan, never the first attempt.** Where the repair loop corrected a plan,
> the training label is the *corrected* version. Training on first attempts teaches the model to
> reproduce exactly the mistakes the repair loop exists to fix.

### Step 3.2 — Input tasks for Generator A

Sourced from: the natural-language requests in `tests/`, paraphrases of the golden set's *themes*
(never the golden cases themselves), and real opt-in traces from §2.1 once any exist.

Profile against the real CSVs in `test-data/` so schemas are genuine, not invented.

### Step 3.3 — The filter

```
candidate → AnalysisPlan.model_validate()   → reject on ValidationError
          → services/validation.py           → reject on semantic error
          → execute against the real dataset → reject on failure or 0 rows
          → keep
```

Record the rejection reason for every discard. The rejection *distribution* is itself a finding for
the project report — it quantifies how often a state-of-the-art model gets this DSL wrong.

### Step 3.4 — Generator B: back-translation for coverage

Generator A inherits whatever biases the input tasks have. Back-translation fixes coverage by
running the pipeline **backwards**:

1. Enumerate valid `AnalysisPlan`s programmatically against real schemas — the Pydantic model and
   `Literal` allow-lists define exactly what is legal.
2. **Execute them.** Anything producing a result table is correct *by construction*.
3. Ask Gemini for the natural-language question that plan answers — a far easier task than
   generating the plan, and therefore a much weaker dependency.

Back-translation is standard in text-to-SQL synthesis precisely because it guarantees pair quality
**[2][9]**; OmniSQL **[9]** demonstrates it at scale.

Use this to fill the coverage matrix from §0.2 — every chart type, intent and operator, including
the ones nobody happened to ask for.

### Step 3.5 — Dataset assembly

- **Split 80/20 train/validation.** The Phase 0 golden set is the *test* set and stays disjoint from both.
- **Deduplicate** by `preprocessing_version`-style canonical hashing — near-duplicate plans inflate
  apparent dataset size without adding signal.
- **Quality pass:** score a random 5–10% sample with a judge model, discard below threshold. Current
  standard practice for synthetic corpora.
- **Drop `PLAN_GUIDE` from the training prompt.** This is deliberate: the guide moves *into the
  weights*. It is the mechanism behind the token reduction measured in §6, and the reason a 4B becomes
  viable at all.
- Write a **dataset card**: counts, coverage matrix, generator split, rejection statistics.

**Acceptance:** ≥1,500 examples; every coverage cell non-empty; card committed.

---

## 6. Phase 4 — Training  *(3 days)*

Unsloth on Kaggle. QLoRA **[11]** over LoRA **[10]**.

### Step 4.1 — Configuration

| Knob | Value | Basis |
|---|---|---|
| Rank `r` | **16** | Standard for narrow domain adaptation |
| Alpha | **32** (α = 2r) | The 2:1 ratio; scaling-factor analysis **[12]** |
| Target modules | **all linear** — `q,k,v,o,gate,up,down` | 2026 practice; attention-only is outdated |
| Learning rate | sweep **1e-5 → 5e-4**, take highest stable | High LR overfits short runs |
| Epochs | **2** | 1–3 band; stop early |
| Precision | **fp16** | T4 is Turing — no bf16 |
| Quantisation | 4-bit base (QLoRA) **[11]** | Fits 9B in one T4 |

### Step 4.2 — Two runs

**Qwen3.5 4B and 9B, identical dataset, identical hyperparameters, identical split.** Any difference
between the runs invalidates the comparison that §7 depends on.

Kaggle practicalities: 30 GPU-h/week, sessions capped ~12 h and killed on timeout — **checkpoint to
`/kaggle/working` as you go** rather than betting on one long run completing.

### Step 4.3 — Do not train for self-correction

RetrySQL **[13]** teaches models to catch their own errors mid-generation (+4 points on BIRD:
54.71% → 58.70%). Skip it, for two independent reasons:

1. **LoRA cannot learn it.** The paper reports parameter-efficient tuning was entirely ineffective for
   retry data — **50.07% against a 54.71% baseline, worse than not training at all.** It required
   full-parameter continued pre-training, far outside a free-Kaggle budget.
2. **The repair loop already does this**, deterministically, in the graph, where it is testable
   (§16.1.2).

Relatedly, **[14]** frames the general expectation: LoRA installs less new capability than full
fine-tuning but preserves base capability better. Favourable for a narrow task — but it means a LoRA
will not rescue a base model that fundamentally cannot do the job. That is the argument for evaluating
9B alongside 4B, not for training longer.

### Step 4.4 — Export

Merge to 16-bit, export GGUF, import to Ollama. **Merge rather than shipping base + QLoRA adapter** —
Ollama's import guidance warns that frameworks quantize differently and recommends non-quantized
adapters; a mismatched pair degrades quality silently, with no error to catch it (§16.7.3).

---

## 7. Phase 5 — Evaluation and ablation  *(2 days)*

Run the Phase 0 harness across the full grid. **This table is the project's headline result.**

| Configuration | Semantic-valid | Execution success | Repair rate | p95 latency | Tokens/req |
|---|---|---|---|---|---|
| Gemini 3.5 Flash (baseline) | | | | | |
| Gemini + retrieval | | | | | |
| Qwen3.5 4B generic | | | | | |
| Qwen3.5 4B fine-tuned | | | | | |
| Qwen3.5 4B fine-tuned + retrieval | | | | | |
| Qwen3.5 9B generic | | | | | |
| Qwen3.5 9B fine-tuned | | | | | |
| Qwen3.5 9B fine-tuned + retrieval | | | | | |

The 2×2 over {generic, fine-tuned} × {no-RAG, RAG} is what separates the contribution of each
technique — the same ablation structure as **[5]**, which is why that paper could conclude RAG
*matched* fine-tuning rather than merely that both helped.

**Ship gate:** the 4B fine-tuned configuration must beat both the generic 4B **and** come within
5 points of the Gemini baseline on semantic-valid rate, with p95 latency no worse.

---

## 8. Phase 6 — Serving decision

Answer [§16.7.7](16-Planner-Model-Strategy.md) using the §7 numbers rather than by guessing:

- **Small 4B↔9B gap** → laptop/local path. Ship the 4B. Free, offline, private.
- **Large gap** → the GPU case is now evidence rather than a budget request. Note that
  `g4dn.xlarge` at ~$384/mo breaks even against Gemini only at ~750 requests/day, so the
  justification must be privacy/offline/independence — not cost (§16.7.7).

---

## 9. Timeline

| Phase | Days | Blocking? |
|---|---|---|
| 0 — Eval harness | 3 | **Blocks everything** |
| 1 — Plumbing + constrained decoding | 2 | Step 1.2 gates the §5 budget |
| 2 — Retrieval | 4 | Ships value independently |
| 3 — Training data | 5 | The long pole |
| 4 — Training | 3 | Needs Phase 3 complete |
| 5 — Ablation | 2 | |
| 6 — Serving decision | — | Decision, not work |
| **Total** | **~19 working days** | ~4 weeks |

Phases 0→1 are the defensible minimum: even if everything after stalls, a measured comparison of
planner models is a real result.

---

## 10. Risk register

| Risk | Impact | Mitigation |
|---|---|---|
| Ollama cannot enforce `$ref`/`oneOf` | Training budget rises; shape errors persist | Step 1.2 on day one; fall back to a flattened decode-only schema |
| Golden set leaks into training data | **Every number in §7 becomes meaningless** | Freeze in Step 0.2; assert disjointness in the assembly script |
| Gemini teacher inherits Gemini's blind spots | Model cannot exceed its teacher | Generator B (§5.4) is teacher-independent for coverage |
| Traces generated on the free tier | User CSV data enters Google's training pipeline | §0.1 condition 1 — paid tier, verified before any generation |
| <1,500 usable examples after filtering | Under-trained adapter | Generator B is unbounded — enumerate more |
| 9B wins big, no GPU budget | A result that cannot ship | The 4B still ships; the gap is itself a finding |
| Kaggle session killed mid-run | Lost GPU hours against a 30 h/week cap | Checkpoint to `/kaggle/working` (Step 4.2) |
| `compose` regresses unnoticed | Hallucinated numbers reach users | Out of scope by design; §0.5 rubric is the floor |

---

## 11. Bibliography

arXiv identifiers verified 2026-08-04. Confirm author lists and venues from the arXiv pages before
formal citation.

**Text-to-SQL / semantic parsing — evaluation and example selection**

1. *Text-to-SQL Empowered by Large Language Models: A Benchmark Evaluation* (DAIL-SQL), Gao et al.,
   2023. [arXiv:2308.15363](https://arxiv.org/abs/2308.15363) — systematic study of question
   representation, **example selection** and example organisation; 86.6% execution accuracy on
   Spider. Basis for §4 retrieval design and §2 execution-accuracy metrics.
2. *Large Language Model Enhanced Text-to-SQL Generation: A Survey*, 2024.
   [arXiv:2410.06011](https://arxiv.org/html/2410.06011v1) — survey; back-translation and synthesis practice.

**Constrained decoding**

3. *XGrammar: Flexible and Efficient Structured Generation Engine for Large Language Models*,
   Dong et al., 2024. [arXiv:2411.15100](https://arxiv.org/abs/2411.15100) — the default grammar
   backend in vLLM; basis for Step 1.2.
4. *XGrammar-2: Efficient Dynamic Structured Generation Engine for Agentic LLMs*, 2026.
   [arXiv:2601.04426](https://arxiv.org/abs/2601.04426)

**Fine-tuning vs retrieval**

5. *A Comparative Study of DSL Code Generation: Fine-Tuning vs. Optimized Retrieval Augmentation*,
   2024. [arXiv:2407.02742](https://arxiv.org/abs/2407.02742) — **the closest analogue to this
   project.** NL→DSL over ~700 custom APIs; RAG reached parity on similarity, +2 pts on compilation
   rate, −1/−2 pts on hallucination. Basis for §4 and the §7 ablation design.

**Rejection sampling and self-training**

6. *Scaling Relationship on Learning Mathematical Reasoning with Large Language Models*, Yuan et al.,
   2023. [arXiv:2308.01825](https://arxiv.org/abs/2308.01825) — introduces **Rejection sampling
   Fine-Tuning (RFT)**. Basis for §5.1.
7. *STaR: Bootstrapping Reasoning With Reasoning*, Zelikman et al., 2022.
   [arXiv:2203.14465](https://arxiv.org/abs/2203.14465) — generate-verify-retrain loop.
8. *DART-Math: Difficulty-Aware Rejection Tuning for Mathematical Problem-Solving*, 2024.
   [arXiv:2407.13690](https://arxiv.org/abs/2407.13690) — difficulty-aware sample allocation (§5.1).
9. *OmniSQL: Synthesizing High-quality Text-to-SQL Data at Scale*, Li et al., VLDB vol. 18.
   [PDF](https://www.vldb.org/pvldb/vol18/p4695-li.pdf) — large-scale synthesis; basis for §5.4.

**Parameter-efficient fine-tuning**

10. *LoRA: Low-Rank Adaptation of Large Language Models*, Hu et al., 2021.
    [arXiv:2106.09685](https://arxiv.org/abs/2106.09685)
11. *QLoRA: Efficient Finetuning of Quantized LLMs*, Dettmers et al., 2023.
    [arXiv:2305.14314](https://arxiv.org/abs/2305.14314) — 4-bit base + adapter; what makes 9B fit a T4.
12. *The Hidden Power of the Scaling Factor in LoRA Optimization*, 2026.
    [arXiv:2606.12883](https://arxiv.org/abs/2606.12883) — basis for α = 2r (§6.1).
13. *RetrySQL: Text-to-SQL Training with Retry Data for Self-Correcting Query Generation*, 2025.
    [arXiv:2507.02529](https://arxiv.org/html/2507.02529v1) — **cited as a negative result**: LoRA was
    ineffective for retry data (50.07% vs 54.71% baseline). Basis for §6.3.
14. *LoRA Learns Less and Forgets Less*, Biderman et al., 2024.
    [arXiv:2405.09673](https://arxiv.org/pdf/2405.09673) — capability/retention trade-off (§6.3).

**Primary sources**

15. *Gemini API Additional Terms of Service*, Google.
    [ai.google.dev/gemini-api/terms](https://ai.google.dev/gemini-api/terms) — clauses quoted in
    §16.10.1–10.2; basis for the §0.1 paid-tier condition.
16. *LoRA Hyperparameters Guide*, Unsloth.
    [unsloth.ai](https://unsloth.ai/docs/get-started/fine-tuning-llms-guide/lora-hyperparameters-guide) — §6.1.
17. *Importing a Model*, Ollama. [docs.ollama.com/import](https://docs.ollama.com/import) — the
    merged-GGUF-over-adapter guidance in §6.4.
