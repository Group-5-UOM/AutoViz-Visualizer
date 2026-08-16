# 16 — Planner Model Strategy: Replacing Gemini

Options for running AutoViz's planner on something other than the Gemini API — an open-weight
model, a fine-tuned model, or a tuned Gemini — with a phased plan and the evidence behind the
recommendation.

Grounded in `backend/src/autoviz/llm/client.py` and `backend/src/autoviz/agent/` on branch
`feat/cleaning-disclosure` (commit `0d5d080`). Market facts checked August 2026.

**Headline:** the model swap is nearly free and worth doing. The fine-tune is a separate, much
larger project that is currently **blocked on two prerequisites the repo does not have** — an
evaluation harness and a single line of training data. Build those first; they are worth having
even if the fine-tune never happens.

> **Decision (2026-08-03): Option C — fine-tune an open-weight model.** Train **both Qwen3.5 4B
> and 9B** with QLoRA on free Kaggle GPU, from one shared dataset, and let the eval harness decide.
> **The serving home is deliberately deferred** — see §7.7, which is the decision that actually
> constrains the model size. Toolchain and hardware reasoning in **§7**.
>
> **Superseded on §10 only (2026-08-04): Gemini *is* the teacher model**, contrary to the
> recommendation below, subject to three mandatory conditions (paid tier, validator-as-labeller,
> documented reading). See [17 — Fine-Tuning Execution Plan](17-Fine-Tuning-Execution-Plan.md) §0.1.
> **Doc 17 is the step-by-step plan; this doc remains the options analysis and evidence base.**

---

## 1. What the planner actually is

### 1.1 Four jobs, not one

`PlannerLLM` ([client.py:49](../backend/src/autoviz/llm/client.py#L49)) is a four-method protocol.
Treating it as "the LLM" hides that these are four different problems with different difficulty and
different tolerance for a weaker model:

| Method | Job | Output | Failure caught by | Hard for a small model? |
|---|---|---|---|---|
| `classify` | Route intent, split into ≤6 tasks | `IntentDecision` JSON | Pydantic validation | **No** — short output, closed label set |
| `generate_plan` | Task → `AnalysisPlan` | Plan JSON | `services/validation.py` + repair loop | **Partly** — schema is easy to enforce, *column choice* is judgement |
| `style_patch` | NL → style diff | Partial `ChartStyle` | `ChartStyle` validation | **No** — smallest, most constrained job |
| `compose` | Results → prose answer | Free text | `services/grounding.py` *(added 16 Aug — see below)* | **Yes** — ungrounded prose is where small models hallucinate |

This table is the single most important input to the decision. Three of the four jobs emit
**validated JSON**, and every one of those is checked before it can affect the user. `compose`
**was** the odd one out: free text, with nothing downstream verifying it — which meant the one
output the user actually reads was the one output nobody checked.

> ### Closed, 16 August 2026 — `services/grounding.py`
>
> The asymmetry is gone. Every figure in a composed answer is now traced back to the results
> before the answer is served: cell values and their rounded and percent-converted forms, the
> row-accounting integers, the literals the user's own filters named, figures inside notices the
> system wrote itself, and small integers that can only be counts or ordinals of what is on
> screen. **A number matching none of those has no visible source, and the fluent answer is
> discarded in favour of the deterministic template summary** — which is grounded by
> construction because it is read straight off the result.
>
> Fluency lost, correctness kept. For a data tool that is the right way round, and it is the same
> trade the rest of the architecture already makes.
>
> The check is deliberately built to **under-report**: a false positive throws away a good
> answer, so the grounded set is generous and only a figure with no traceable source is acted on.
> Measured at **0 false positives** across the 39-prompt benchmark (`Docs/24 §4.4`), and every
> rejection is logged as an `ungrounded_answer` event, so the rate is observable rather than
> assumed.
>
> **This changes the fine-tune calculus below.** §1.1 argued against fine-tuning `compose`
> because "nothing downstream would catch it". Something does now — so the residual risk of a
> weaker composer is a *terser* answer, not a wrong one. That does not make fine-tuning `compose`
> attractive, but it stops it being unsafe, and §3's Option C reasoning should be re-read with
> that in mind.

That asymmetry means the right answer is almost certainly **not** one model for all four.

### 1.2 The safety net already exists

`generate_plan` output never reaches execution unvalidated. `routing.route_after_plan`
([routing.py:113](../backend/src/autoviz/agent/routing.py#L113)) re-plans while
`plan_attempts < 1 + MAX_PLAN_ATTEMPTS`, feeding the rejected plan and its validation errors back
in ([client.py:246-249](../backend/src/autoviz/llm/client.py#L246)).

**This is what makes a weaker model viable.** A wrong plan is not a wrong answer — it is a retry.
A weaker model raises the repair rate (cost, latency) long before it degrades correctness. Any
option below inherits that net for free.

`compose` inherits nothing. It is the one place a weaker model produces a wrong answer that ships.

### 1.3 Call and token profile

Per user request: **1 `classify` + N `generate_plan` (N ≤ 6 tasks, each up to 1 + `MAX_PLAN_ATTEMPTS`
attempts) + 1 `compose`.** So 3 calls for a simple question, up to ~15 for a six-task request that
repairs twice.

The prompts are not small. `_PLAN_SYSTEM` embeds the whole of `PLAN_GUIDE` — 10 KB of source,
roughly 2.4k tokens — and it is re-sent on **every** plan call and **every** repair attempt.

| Request shape | Calls | ≈ input tokens | ≈ output tokens |
|---|---|---|---|
| Single question, clean plan | 3 | ~6k | ~600 |
| Six tasks, two repairs | ~10 | ~25k | ~2k |

At Gemini 3.5 Flash list pricing (**$1.50 / $9.00 per 1M** in/out, cached input $0.15) that is
roughly **$0.017–$0.055 per user request**. Context caching would cut the dominant term — the
repeated `PLAN_GUIDE` — by up to 90%, and is currently not used.

### 1.4 What the free tier actually buys

Free-tier Gemini limits run ~5–15 RPM and ~1,000 requests/day. **One AutoViz request costs 3–15
model calls**, so the free tier is worth roughly **70–300 AutoViz requests per day**, shared across
everyone using the deployment. That is fine for development and thin for a demo with an audience.

Also relevant: on the free tier, **prompts may be used to improve Google's products**. `compose`
sends up to 25 result rows per task ([client.py:286](../backend/src/autoviz/llm/client.py#L286)),
and `classify`/`generate_plan` send the full column schema. That is user data from uploaded CSVs
leaving the machine — the aggregate, not the raw file, but real values nonetheless. For a tool whose
pitch is "upload your CSV", this is a genuine argument for local inference independent of cost.

### 1.5 What is already swappable, and what is not

Good news, mostly:

- The graph depends on the **protocol**, not the provider ([graph.py:18](../backend/src/autoviz/agent/graph.py#L18)).
  Tests already run offline against `FakePlanner`, so a second implementation is a supported shape.
- The model id is env-driven: `AUTOVIZ_PLANNER_MODEL`, any `init_chat_model` id
  ([client.py:180](../backend/src/autoviz/llm/client.py#L180)).

Three things block a local endpoint today:

1. **No `base_url` / `api_key` passthrough.** `init_chat_model(self._model_id, temperature=0)`
   ([client.py:188](../backend/src/autoviz/llm/client.py#L188)) takes no connection kwargs. Pointing
   at vLLM/Ollama needs `model_provider="openai"`, `base_url=...`, `api_key="EMPTY"`.
2. **No OpenAI-compatible client installed.** `pyproject.toml` has `langchain-google-genai` only;
   `langchain-openai` is needed.
3. **`GeminiPlanner` is named for one provider** ([client.py:172](../backend/src/autoviz/llm/client.py#L172),
   referenced in [deps.py:59](../backend/src/autoviz/api/deps.py#L59) and
   [graph.py:27](../backend/src/autoviz/agent/graph.py#L27)). Cosmetic, but it should not survive
   the swap.

All three are under an hour's work.

### 1.6 The two blockers for fine-tuning

**There is no evaluation harness.** Nothing in `backend/tests/` measures plan quality — the suite
uses `FakePlanner` and tests deterministic code. So today there is **no way to tell whether any
model change helped or hurt**. Every option below is unmeasurable until this exists, which is why
it is Phase 0 and not an afterthought.

**There is no training data, and the logging is designed to prevent it.**
`observability._input_hash` ([observability.py:63-73](../backend/src/autoviz/observability.py#L63))
logs a SHA-256 prefix and explicitly documents: *"Only the hash is logged, never raw argument
values."* That is correct privacy engineering and it means **zero** usable `(prompt → plan) `pairs
exist. Collecting them is a deliberate, separately-consented feature, not a config flag.

---

## 2. The options

### Option A — Stay on Gemini, optimise it

The do-nothing-structural baseline, and not a bad one.

- **Enable context caching** on the ~2.4k-token `PLAN_GUIDE` prefix: up to 90% off the dominant
  input cost.
- **Drop to Flash-Lite for `classify` and `style_patch`** — both are trivially constrained.
- Keep 3.5 Flash for `generate_plan` and `compose`.

**Cost:** ~1 day. **Risk:** none. **Solves:** cost. **Does not solve:** free-tier ceiling,
offline operation, data leaving the machine, vendor dependence.

### Option B — Swap to an open-weight instruct model (no fine-tune)

Run a 7–14B instruct model behind an OpenAI-compatible endpoint, either self-hosted (vLLM, Ollama)
or on a serverless provider.

Candidates as of Aug 2026, for this specific workload:

| Model | Why it's a candidate | Watch out for |
|---|---|---|
| **Qwen3.5 9B** | The general default at this size; ~6.6 GB on Ollama, leaves room for the 6k-token context | Largest of the three |
| **Hermes 2 Pro 7B** | Purpose-built for function calling / JSON mode (~84% JSON-mode accuracy reported) | Older base; weaker general reasoning |
| **Phi-4-mini** | Notably stable structured output under aggressive quantisation | Smallest capacity for column-choice judgement |

The decisive addition is **constrained decoding**. `AnalysisPlan` is Pydantic, so
`AnalysisPlan.model_json_schema()` is free, and vLLM's `guided_json` (XGrammar backend — the 2026
default, JIT-compiled grammars that cache well across reuse) makes **schema-invalid output
impossible by construction**. Ollama exposes the same via its structured-output `format` field.

That matters more here than the model choice does. A large share of a small model's failures on
this task are *shape* failures — a missing field, a hallucinated operator outside the `Literal`
allow-lists in [analysis_plan.py:22-49](../backend/src/autoviz/schema/analysis_plan.py#L22) — and
grammar-constrained decoding eliminates that entire class. What remains is judgement: *is this the
right column?* Constrained decoding does nothing for that; the repair loop and
`services/validation.py` catch a good deal of it anyway.

> ⚠️ **Verify before committing:** `AnalysisPlan` uses a discriminated union for `preprocessing`
> and field aliases (`from`, `as`). The generated JSON Schema uses `$ref` + `oneOf`. Confirm the
> chosen grammar backend handles that nesting — this is the single most likely technical
> surprise in Option B, and it is cheap to test in an afternoon.

**Cost:** ~2–3 days plus hardware. **Risk:** medium, and *measurable* once Phase 0 exists.
**Solves:** cost, ceiling, offline, privacy, vendor dependence. **Does not solve:** `compose`
quality — recommend keeping `compose` on a hosted model initially and moving it last, if at all.

### Option C — Fine-tune an open-weight model (LoRA/QLoRA)

Option B plus a distillation step: log real traffic, use Gemini's outputs as labels, LoRA-tune the
open model on `(task, schema) → plan`.

Tooling is mature and cheap. **Unsloth** leads on single-GPU (2× faster, ~70% less VRAM; a 14B
QLoRA fits a free Colab T4); **Axolotl** is better for multi-GPU. Adapters are interoperable
between them, so this is not a lock-in choice. Consensus on data volume: **~500 curated examples
for format/style adaptation, 1,000–5,000 for genuine domain specialisation**, with sharp diminishing
returns past 5k — and 200 hand-checked examples beating 2,000 scraped ones.

What a fine-tune buys that Option B does not:

- **Prompt compression.** `PLAN_GUIDE` gets baked into the weights instead of re-sent on every call
  and every repair. On a 6k-token request that is most of the input.
- **Better column judgement** — the one failure mode constrained decoding cannot touch.
- A lower repair rate, which compounds into latency and cost.

The blocking cost is not GPU time; it is **the trace-capture feature** (§1.6), which is a privacy
decision requiring user consent, not a training run. Budget that honestly.

Scope it to **`generate_plan` only.** It is the highest-volume, most constrained, most repair-prone
call. `classify` and `style_patch` are already easy; `compose` is the job where a small fine-tune
is most likely to make things *worse*, because fluent-but-ungrounded prose is exactly the failure
LoRA on a small base tends to produce, and §1.1 established nothing downstream would catch it.

**Cost:** ~2–3 weeks realistically, dominated by data collection. **Risk:** high.
**Prerequisites:** Phase 0 *and* Option B shipped.

### Option D — Fine-tune Gemini itself (Vertex AI SFT)

Supervised tuning on Vertex, same distilled dataset, no serving infrastructure.

**This has a specific trap:** Vertex SFT supports `gemini-2.5-pro`, `gemini-2.5-flash`, and
`gemini-2.5-flash-lite`. It does **not** support the 3.5 family the code currently defaults to
([client.py:25](../backend/src/autoviz/llm/client.py#L25)). Tuning Gemini therefore means
**downgrading the base model by a generation** and betting the tuning gain exceeds the generation
loss. It also needs a billed GCP project with tuning quota.

And it solves none of the non-cost motivations: still hosted, still online, still sending user data
off-machine, still Google.

**Verdict: not recommended.** It carries Option C's entire data-collection cost while keeping every
drawback of Option A.

---

## 3. Comparison

| | A: Optimise Gemini | B: Open-weight swap | C: Fine-tune open | D: Tune Gemini |
|---|---|---|---|---|
| Effort | ~1 day | 2–3 days | 2–3 weeks | 1–2 weeks |
| Needs training data | No | No | **Yes (~1–5k)** | **Yes (~1–5k)** |
| Needs eval harness | Yes | Yes | Yes | Yes |
| Cuts cost | Yes (caching) | Yes | Yes | Partly |
| Removes free-tier ceiling | No | Yes | Yes | Yes (billed) |
| Runs offline | No | Yes | Yes | No |
| Keeps user data local | No | Yes | Yes | No |
| Base model generation | Current | Current | Current | **One behind** |
| Risk | None | Medium | High | High |

---

## 4. Recommendation

**Do Phase 0 and Phase 1. Treat Phase 2 as conditional and Option D as rejected.**

The reasoning: three of the four planner jobs emit validated JSON behind a repair loop, so the
marginal value of a *smarter* model on those is low and the marginal value of a *cheaper, local,
schema-constrained* one is high. Constrained decoding plus the existing validator plausibly closes
most of the gap for `generate_plan` with no training data at all. Fine-tuning is the right tool for
the residue — but only once there is a number proving a residue exists.

Sequencing also matters for a project already past its Week-3 integration window: Phase 0 and 1 are
days and produce a demonstrable, defensible result ("we measured N models on M tasks"). Phase 2 is
weeks, gated on a privacy feature, and could easily consume the remaining schedule without
producing anything demo-able.

---

## 5. Plan

### Phase 0 — Make it measurable (2–3 days) · *prerequisite for everything*

| # | Work | Acceptance |
|---|---|---|
| 0.1 | Build `backend/evals/` with 40–60 golden `(request, dataset, expected plan properties)` cases across the chart types and intents. Assert *properties* — right columns, right agg, right chart family — not byte equality; many plans are correct. | Suite runs against any `PlannerLLM` |
| 0.2 | Metrics: **schema-valid rate**, **semantic-valid rate** (passes `services/validation.py`), **repair rate**, **task-success rate**, p50/p95 latency, tokens/request | One command emits a comparison table |
| 0.3 | Baseline current Gemini 3.5 Flash | Numbers committed to the repo as the bar to beat |
| 0.4 | A `compose` rubric — a hallucinated number or a dropped `disclosed` notice is a **failure**, per the disclosure rules in Docs 14 | Manual scoring sheet, ~20 cases |

Deliverable: a table saying what the current system scores. Nothing after this is guesswork.

### Phase 1 — Provider swap (2–3 days)

| # | Work | Acceptance |
|---|---|---|
| 1.1 | Add `base_url` / `api_key` passthrough to the planner; add `langchain-openai`; rename `GeminiPlanner` → `Planner` (keep an alias) | Points at any OpenAI-compatible endpoint via env |
| 1.2 | New env: `AUTOVIZ_PLANNER_BASE_URL`, `AUTOVIZ_PLANNER_API_KEY` — documented in `.env.example` and `README.md` | Gemini path unchanged when unset |
| 1.3 | Constrained decoding: emit `AnalysisPlan.model_json_schema()` as `guided_json`; **verify the `$ref`/`oneOf` discriminated union works** (§2.2 warning) | Malformed-shape rate → 0 |
| 1.4 | Run Phase 0 evals over Qwen3.5 9B, Hermes 2 Pro 7B, Phi-4-mini | Comparison table vs the Gemini baseline |
| 1.5 | **Decide per method, not globally.** Expect to keep `compose` hosted. | `AUTOVIZ_PLANNER_MODEL` documented per-role if they differ |

**Bar to ship:** semantic-valid rate within 5 points of Gemini, repair rate under 1.5× Gemini's, p95
latency no worse. Miss the bar → Phase 2. Meet it → **Phase 2 is unnecessary; stop.**

### Phase 2 — Fine-tune (conditional, 2–3 weeks)

Only if Phase 1 misses the bar, and only for `generate_plan`.

| # | Work | Acceptance |
|---|---|---|
| 2.1 | **Opt-in trace capture** — a separate store, never the observability log, whose hash-only discipline stays intact. Explicit consent; column names and sample values are user data. | Off by default; documented |
| 2.2 | Collect 1,000–2,000 `(task, schema, profile) → validated plan`. Keep only plans that **passed validation and executed**, and label with the *repaired* plan where a repair happened — training on first attempts teaches the model to make the mistakes. | Dataset card with counts and coverage |
| 2.3 | Augment from the golden set + synthetic schemas so coverage is not skewed to whatever CSVs got uploaded | Every chart type and intent represented |
| 2.4 | QLoRA (rank 16) via Unsloth on the Phase 1 winner; hold out 20% | Trained adapter |
| 2.5 | Re-run Phase 0 evals. Ship only on a **measured** win. | Beats both baselines, or is discarded |

Hosted alternatives if no GPU is available: Together (~$0.48/M tokens LoRA SFT on a 16B base),
Fireworks ($0.50/M under 16B; note serverless LoRA serving was unsupported as of Feb 2026 —
re-check), Predibase (per-token training + per-second serving, $25 trial, LoRAX multi-adapter
serving).

---

## 6. Risks

| Risk | Mitigation |
|---|---|
| `$ref`/`oneOf` discriminated union breaks grammar-constrained decoding | Test in Phase 1.3 before committing; fall back to a flattened schema for decoding only |
| Small model picks wrong columns — invisible to schema validation | Semantic-valid rate in Phase 0.2 is exactly this measurement |
| `compose` hallucinates numbers or drops a `disclosed` notice | Keep `compose` hosted; Phase 0.4 rubric treats it as a failure, not a style issue |
| Self-hosting adds an ops burden the team cannot carry | Hosted OpenAI-compatible endpoint keeps Option B's benefits minus offline/privacy |
| Trace capture leaks user data | Opt-in, separate store, never the hash-only observability log |
| Phase 2 consumes the schedule with nothing shippable | It is explicitly gated on Phase 1 missing a numeric bar |

---

## 7. Option C toolchain — what runs where

Option C is the committed direction. This section fixes the model, the training venue, and the
serving runtime, because the available hardware decides all three.

### 7.1 The hardware constraint

Development machine: **NVIDIA GeForce RTX 3050 Ti Laptop GPU, 4 GB VRAM** (driver 610.74),
**7.7 GB system RAM**, Windows 11.

Two separate ceilings, and the second is the one that gets missed:

**Training.** Published QLoRA sizing puts a **7B at ~8 GB** (batch 1, seq 512, rank 64, before the
15–20% headroom real runs need). A 4B lands ~5–6 GB. AutoViz's training sequences are not short — a
schema plus a plan runs ~800–1,500 tokens — which pushes activation memory up, not down.
**No training happens on this laptop**, at any size. That is a venue problem, not a blocker.

**Serving.** 4 GB VRAM fits Qwen3.5 4B at Q4 (~2.5 GB) with context room. It does not fit the 9B
(~6 GB at Q4) — and **7.7 GB of system RAM rules out CPU offload as a fallback**, because that 6 GB
would compete with Windows, Postgres, the FastAPI backend and the frontend. For the 9B on this
machine the failure mode is "won't load", not "runs slowly".

### 7.2 Train off-machine; serving home is deferred

| Stage | Where | Why |
|---|---|---|
| **Train** (QLoRA) | Free **Kaggle** (T4 16 GB, 30 h/week) or **Colab T4** | 9B QLoRA ≈ ~10 GB, inside one T4; Unsloth fits even 14B |
| **Merge + export** | Same notebook | One GGUF artifact per model |
| **Serve** | **Deferred — see §7.7** | The 4B runs locally under Ollama; the 9B needs a home that does not exist yet |

### 7.3 Ollama does not fine-tune

Worth stating plainly because the naming invites the confusion: **Ollama has no training path.**
Its `Modelfile` changes how a model is *prompted*; fine-tuning changes what the weights encode.
Ollama's role here is strictly serving, via the `ADAPTER` directive (LoRA adapter over a base) or a
merged GGUF.

> ⚠️ **Prefer a merged GGUF over shipping the adapter.** Ollama's own import guidance warns that
> frameworks quantize differently and recommends **non-quantized adapters**. Since this plan uses
> QLoRA, merge to 16-bit and export a single GGUF from the training notebook rather than pairing a
> QLoRA adapter with a separately-quantized base — mismatched quantization degrades quality
> silently, with no error to catch it.

### 7.4 Which Qwen — train both

The Qwen3.5 dense lineup (released 2026-03-02, Apache 2.0, 262K context) is **9B / 4B / 2B / 0.8B**.
Apache 2.0 matters for a university project — no usage restrictions on the trained artifact.

| | Trains on free Kaggle? | Serves on the laptop? | Role |
|---|---|---|---|
| **9B** | Yes (~10 GB QLoRA, fits one T4) | **No** (§7.1) | The quality ceiling — measures what is being given up |
| **4B** | Yes (~5–6 GB) | Yes (~2.5 GB at Q4) | The one that definitely ships |
| 2B | Yes | Yes, comfortably | Fallback if 4B latency disappoints |

**Train 4B and 9B from the same dataset and evaluate both.** The reasoning:

- **The dataset is the asset, and it is model-agnostic.** The weeks of work in Option C go into
  collecting 1,000–2,000 validated `(task, schema) → plan` pairs. That JSONL trains any of these
  sizes, so deferring the model choice costs nothing on the only expensive axis.
- **A QLoRA run is hours of free GPU.** Once the data exists, training a second size is nearly free.
  Picking one in advance buys nothing and forecloses the comparison.
- **The comparison is itself the deliverable.** "The 9B scores N points higher" is what turns the
  §7.7 serving decision from a budget guess into an evidence-backed one.
- **The 4B is insurance.** Whatever the 9B scores, there is still a model that runs on the
  available hardware.

Note that a generic 4B is too weak to plan analyses off a 2.4k-token `PLAN_GUIDE` — the fine-tune is
what makes that size viable at all, by baking the guide into the weights (§2.3). So the 4B result
is not "the small model result"; it is the result the whole approach exists to produce.

### 7.5 Serving-runtime consequence

§2.2 recommended vLLM's `guided_json` (XGrammar). **vLLM has no native Windows support** — it needs
WSL2 or Linux — so on this machine the practical runtime is Ollama, which supports structured output
via a JSON-schema `format` field but with a less battle-tested grammar implementation.

This makes the risk already flagged in §6 **more** likely, not less: `AnalysisPlan.model_json_schema()`
emits `$ref` + `oneOf` for the `preprocessing` discriminated union, and Ollama is the likelier of
the two runtimes to mishandle it. **Test this in the first day of work**, before any training
happens — if constrained decoding cannot enforce the plan schema, the fine-tune has to carry the
entire load of producing valid shapes, which changes how much training data is needed.

### 7.6 Revised Phase 2 sequence

Phase 0 (§5) still comes first — without the eval harness there is no way to know whether the
trained model is better than what it replaces, and a fine-tune with no measurement is not a result.

| # | Work | Note |
|---|---|---|
| 7.a | Verify Ollama structured output against `AnalysisPlan.model_json_schema()` | **Day 1.** Gates everything; see §7.5 |
| 7.b | Baseline **generic** Qwen3.5 4B on the Phase 0 evals | The number the fine-tune must beat |
| 7.c | Opt-in trace capture → 1,000–2,000 validated `(task, schema) → plan` pairs (§5, 2.1–2.3) | **The long pole.** A privacy feature, not a config flag. Model-agnostic — this is the asset |
| 7.d | QLoRA rank 16 via Unsloth on Kaggle, `PLAN_GUIDE` dropped from the prompt — **two runs, 4B and 9B, same dataset, same hyperparameters** | Hold out 20%; keep the split identical across runs or the comparison is meaningless |
| 7.e | Merge each to 16-bit, export GGUF | Per §7.3 warning |
| 7.f | Evaluate both against Phase 0. Import the 4B to Ollama; the 9B is measured, not yet served | Produces the 4B-vs-9B gap |
| 7.g | **Decide §7.7 using the 7.f numbers.** Ship the 4B on a measured win over 7.b and the Gemini baseline | A small gap → laptop path; a large gap → the GPU case is now evidence, not a guess |

Scope stays `generate_plan` **only**, for the reasons in §1.1 — `compose` remains on a hosted model.

Kaggle practicalities for 7.d: 30 GPU-hours/week, sessions capped at ~12 h and killed on timeout, so
**checkpoint to `/kaggle/working` as you go** rather than relying on one long run finishing. T4 is
Turing — no bf16, use fp16 (Unsloth handles this).

### 7.7 The deferred decision: where the model serves

**Open as of 2026-08-03**, by choice. It does not block any of §7.6 up to 7.f, and it must be
answered before the fine-tuned planner replaces Gemini in a deployment.

The current deploy target is **CPU-only EC2** via CodeDeploy ([appspec.yml](../appspec.yml),
[buildspec.yml](../buildspec.yml)) — Docker on `ec2-user`, no GPU instance anywhere in the config.
A 4B on CPU runs roughly 5–15 tok/s, so a ~300-token plan is 20–60 s per call, and one AutoViz
request is 3–15 calls. **Neither model can serve from the current infrastructure.**

| Option | 9B viable | Cost | Keeps the privacy/offline win |
|---|---|---|---|
| Laptop only (demo runs locally) | No — 4B only | Free | Yes |
| GPU EC2 (`g4dn.xlarge`, T4 16 GB) | Yes | **$0.526/hr ≈ $384/mo** | Yes |
| Hosted adapter serving (Predibase LoRAX, Together) | Yes | Per-token | **No** — data leaves again |

The cost comparison is uncomfortable and worth stating plainly: against Gemini at ~$0.017/request
(§1.3), $384/month breaks even at roughly **750 requests per day, every day**. This project will not
reach that. **If cost was the motivation, a GPU instance inverts it.** The GPU path is justified by
privacy, offline operation and vendor independence — §1.4 — or not at all.

Deferring is safe because §7.4 trains a model for *each* answer. The risk it carries is narrow and
worth naming: if the 9B wins by a wide margin and no GPU budget materialises, the outcome is a
measured result the project cannot ship. That is still a finding, and the 4B still ships.

---


## 8. Training strategies

Researched 2026-08-03. What the current literature says about *how* to run §7.6's training, and two
things not to bother with.

### 8.1 LoRA hyperparameters — the 2026 consensus

| Knob | Value | Note |
|---|---|---|
| Rank `r` | **16–32** | Industry standard for instruction-tuning and domain adaptation. `r=16` is the right start here; the task is narrow |
| Alpha | **α = 2r** | So α=32 at r=16. The 2:1 ratio matters increasingly at higher rank |
| Target modules | **All linear layers** — `q_proj`, `k_proj`, `v_proj`, `o_proj`, `gate_proj`, `up_proj`, `down_proj` | 2026 practice has moved off attention-only. This is a change from older tutorials |
| Learning rate | Sweep **1e-5 → 5e-4**, take the highest that trains stably | High LR overfits on short runs, which this will be |
| Epochs | **1–3, then stop** | With ~1–2k examples, more is overfitting |

`r=16` was already in §7.6 (7.d); the α and target-module choices are the ones most likely to be got
wrong from an out-of-date notebook.

### 8.2 Rejection sampling — nearly free here, and the reason data quality is a solved problem

Standard 2026 practice: sample several candidate outputs per input, keep only those that pass a
correctness check, train on the survivors.

**AutoViz is unusually well set up for this.** Most projects have to build a verifier or pay a judge
model. This repo already has one: `services/validation.py` plus an executor that either produces a
result table or does not. So the filter is *deterministic and free* — sample k plans per task, keep
the ones that validate **and execute**, discard the rest.

That has a consequence worth stating plainly: **the training labels' authority comes from the
validator, not from whichever model generated the candidates.** A weak teacher that produces one
good plan in five is still a perfectly good data source, because the bad four are thrown away. This
is what makes §10 tractable.

Related, already in §5 (2.2): **label with the repaired plan, never the first attempt.** Training on
first attempts teaches the model to reproduce the mistakes the repair loop exists to fix.

### 8.3 Two techniques to skip

**Retry / self-correction training.** RetrySQL trains a model to recognise its own errors mid-generation
(corrupt a reasoning step, emit a `[BACK]` token, correct it) and gains ~4 points execution accuracy
on BIRD (54.71% → 58.70%). Tempting — and wrong for this project, twice over:

1. **LoRA cannot learn it.** The paper reports parameter-efficient tuning was *entirely ineffective*
   for retry data — 50.07% against a 54.71% baseline, i.e. **worse than not training at all**. It
   required full-parameter continued pre-training, which is far outside a free-Kaggle budget.
2. **The repair loop already does this, architecturally.** `routing.route_after_plan` re-plans with
   the validation errors fed back (§1.2). Self-correction is handled in the graph, deterministically,
   where it can be tested. Teaching the weights to duplicate it buys nothing.

**Chasing base-model capability.** "LoRA Learns Less and Forgets Less" is the relevant framing: LoRA
is weaker than full fine-tuning at installing genuinely new knowledge, and better at preserving what
the base model already does. For a narrow schema-constrained task that trade is favourable — but it
means a LoRA will not rescue a base model that fundamentally cannot reason about the task. That is
the real argument for evaluating 9B alongside 4B (§7.4), not an argument for a longer training run.

---

## 9. Retrieval (RAG) — and why it should come first

**Short answer: yes, and this is probably the highest value-per-day item in this entire document.**

### 9.1 The closest published analogue

The nearest match in the literature is DSL code generation — natural language to a domain-specific
language with a large set of custom function names, which is structurally what `AnalysisPlan`
generation is. [Comparative Study of DSL Code Generation: Fine-Tuning vs. Optimized Retrieval
Augmentation](https://arxiv.org/abs/2407.02742) built a DSL over ~700 APIs and compared a fine-tuned
Codex against an optimised RAG pipeline:

| Metric | Winner |
|---|---|
| Code similarity | Fine-tuned best; **RAG achieved parity** |
| **Compilation rate** | **RAG better by 2 pts** |
| Hallucinated function names | Fine-tuned better by 1 pt |
| Hallucinated parameter keys | Fine-tuned better by 2 pts |

Their conclusion: *"an optimized RAG model can match the quality of fine-tuned models and offer
advantages for new, unseen APIs."*

Separately, dynamic few-shot retrieval is well established for text-to-SQL — retrieving the top-k
most similar `(question, query)` pairs and injecting them as examples, reported up to 96.6% execution
accuracy and consistently beating both zero-shot and *random* example selection. The "beating random
selection" part is the load-bearing bit: the gain comes from similarity, not from merely having
examples.

### 9.2 Three places retrieval applies to AutoViz

1. **Dynamic few-shot plan retrieval.** Embed the task, retrieve the k nearest past
   `(task, schema) → validated plan` pairs, inject as examples in `_PLAN_SYSTEM`. Directly targets
   the failure mode neither constrained decoding nor the validator can catch — *column choice*
   (§2.2).
2. **Schema retrieval for wide datasets.** `generate_plan` currently sends the **entire** column
   schema ([client.py:236-244](../backend/src/autoviz/llm/client.py#L236)). On a 150-column CSV that
   is both expensive and actively harmful — more plausible-looking wrong columns to choose from.
   Retrieve the columns relevant to the task instead.
3. **Repair-example retrieval.** On a repair attempt, retrieve past
   `(validation_error → corrected plan)` pairs. The repair path is the most expensive one (§1.3);
   making it succeed on the first retry is a direct latency and cost win.

### 9.3 Why this reorders the plan

**RAG and the fine-tune consume the same asset.** The store of validated
`(task, schema) → plan` traces that §7.c spends weeks collecting *is* the retrieval index. Building
retrieval first is therefore not a detour from Option C — it is the same work, with three advantages:

- **It ships in days, not weeks.** Retrieval gets better with every trace collected; the fine-tune
  needs the full 1–2k before it produces anything at all.
- **It works against the current Gemini setup**, with no serving infrastructure, no GPU, and no
  answer to §7.7 required.
- **It de-risks the fine-tune.** If retrieval closes most of the gap — which the DSL paper says is
  plausible — then the fine-tune's remaining job is prompt compression and cost, a much smaller
  claim to have to prove.

The two also compose: a fine-tuned model with retrieval is the strongest configuration, and the
ablation (base / +RAG / +FT / +both) is a genuinely publishable result for the project write-up.

> **Note:** [Docs/03](03-Schedule-Report.md)-era scoping listed embeddings as out of scope for the
> 3-week individual track. This reopens that deliberately — the justification is that the embedding
> index is a byproduct of trace collection, which Option C requires regardless.

**Recommended insertion: a Phase 1.5, between the provider swap and the fine-tune.** Cheap
implementation — the traces are already JSON, so a local sentence-transformer plus cosine similarity
over a few thousand rows needs no vector database.

---

## 10. Where the training labels come from — can Gemini be the teacher?

**It is a legal grey area, and there is a better option on the technical merits anyway. Do not
build the plan around Gemini as teacher.**

### 10.1 What the terms actually say

From the [Gemini API Additional Terms of Service](https://ai.google.dev/gemini-api/terms), verbatim:

> "You may not use the Services to develop models that compete with the Services (e.g., Gemini API
> or Google AI Studio)."

> "You also may not attempt to reverse engineer, extract or replicate any component of the Services,
> including the underlying data or models (e.g., parameter weights)."

Two honest observations. There is **no explicit clause forbidding training on outputs** — the
prohibition is scoped to *competing* models and to *replicating the Services*. A narrow CSV-analysis
planner that emits a validated `AnalysisPlan` is not a plausible competitor to a general-purpose LLM
API, so a good-faith reading permits it.

But "develop models that compete with the Services" is undefined and interpreted by the party that
wrote it. **For a university project that will be graded, written up, and possibly published, a
grey area is a poor place to build the foundation of the method.** The exposure is not a lawsuit; it
is a reviewer or examiner asking a question with no clean answer.

### 10.2 The free tier has a separate, worse problem

> "Google uses the content you submit to the Services and any generated responses to provide,
> improve, and develop Google products and services and machine learning technologies."

That applies to **unpaid** use. Trace collection would be sending user CSV schemas, column names and
result rows (§1.4) to a tier that explicitly trains on them — while building a privacy-motivated
feature. That combination is hard to defend in a write-up regardless of the ToS question.

### 10.3 Three clean alternatives, best first

**A. Back-translation — generate plans first, questions second.** The strongest option, and it is
available *because of* what this repo already has. Instead of asking a model for a plan and hoping
it is right, go the other way:

1. Enumerate valid `AnalysisPlan`s programmatically against real dataset schemas — the Pydantic
   model, the `Literal` allow-lists and `services/validation.py` define exactly what is legal.
2. **Execute them.** Anything that produces a result table is correct *by construction*, not by a
   teacher model's say-so.
3. Generate the natural-language question that plan answers — the one LLM step, and a much easier,
   weaker dependency than plan generation.

Back-translation is standard practice in text-to-SQL data synthesis precisely because it
"guarantees the quality of synthetic question–query pairs." Here it yields unlimited, guaranteed-valid
training data with **no teacher-model licence question at all**, and it fixes a coverage problem
§5 (2.3) already flagged: real traffic will be skewed toward whatever CSVs happen to get uploaded,
while enumeration can cover every chart type, intent and operator deliberately.

**B. An openly-licensed teacher.** Qwen3.5's larger variants are Apache 2.0 — no restriction on
training from outputs. Combined with rejection sampling (§8.2), teacher quality matters far less
than usual, because the validator discards bad candidates regardless of who produced them.

**C. Real traffic, self-labelled.** The §7.c trace store, kept only where the plan validated and
executed. Cleanest signal of what users actually ask — but it is the slowest to accumulate, and if
the plans were generated by Gemini it inherits §10.1. Best used as the *evaluation* and retrieval
corpus rather than the training set.

**Recommended mix: A for training volume, C for retrieval and evaluation, B if a teacher is wanted
for hard cases.** Gemini stays what it is today — the production planner and the quality baseline to
beat — and never becomes the source of the weights.

---

## 11. Sources

- [Structured Outputs — vLLM](https://docs.vllm.ai/en/v0.8.2/features/structured_outputs.html) ·
  [Structured outputs in vLLM (Red Hat)](https://developers.redhat.com/articles/2025/06/03/structured-outputs-vllm-guiding-ai-responses) ·
  [Guided decoding performance, vLLM vs SGLang](https://blog.squeezebits.com/guided-decoding-performance-vllm-sglang)
- [Best small language models under 10B (2026)](https://www.labellerr.com/blog/best-small-language-models-under-10b-parameters/) ·
  [awesome-llm-json](https://github.com/imaurer/awesome-llm-json) ·
  [Best local LLMs by VRAM (2026)](https://www.mayhemcode.com/2026/06/best-local-llms-for-4gb-6gb-and-8gb.html)
- [Unsloth vs Axolotl vs TRL vs LLaMA-Factory (MarkTechPost, Jul 2026)](https://www.marktechpost.com/2026/07/22/unsloth-vs-axolotl-vs-trl-vs-llama-factory-a-fine-tuning-framework-comparison-on-speed-vram-and-multi-gpu/) ·
  [Qwen3.5 fine-tuning guide (Unsloth)](https://unsloth.ai/docs/models/qwen3.5/fine-tune) ·
  [Fine-tuning LLMs in 2026: LoRA, QLoRA, Unsloth, MLX](https://codersera.com/blog/fine-tuning-llms-complete-guide-2026/)
- [Together AI pricing 2026](https://www.eesel.ai/blog/together-ai-pricing) ·
  [Fireworks SFT with LoRA](https://fireworks.ai/blog/supervised-fine-tuning-tutorial) ·
  [LoRAX + Outlines (Predibase)](https://predibase.com/blog/lorax-outlines-better-json-extraction-with-structured-generation-and-lora)
- [Gemini API pricing guide 2026](https://curlscape.com/blog/google-gemini-api-pricing-guide-2026) ·
  [Gemini API free tier limits 2026](https://yingtu.ai/en/blog/gemini-api-free-tier) ·
  [About supervised fine-tuning for Gemini models (Google Cloud)](https://cloud.google.com/vertex-ai/generative-ai/docs/models/gemini-supervised-tuning?hl=en)
- [LangChain models docs — OpenAI-compatible providers](https://docs.langchain.com/oss/python/langchain/models)
- [Ollama — Importing a model (GGUF + `ADAPTER`)](https://docs.ollama.com/import) ·
  [Use an Unsloth LoRA adapter with Ollama](https://sarinsuriyakoon.medium.com/unsloth-lora-with-ollama-lightweight-solution-to-full-cycle-llm-development-edadb6d9e0f0)
- [Qwen3.5 small models (Artificial Analysis)](https://artificialanalysis.ai/articles/qwen3-5-small-models) ·
  [Qwen 3 & 3.5 GPU requirements by variant](https://willitrunai.com/blog/qwen-3-gpu-requirements)
- [GPU VRAM requirements to fine-tune LLMs in 2026 (Spheron)](https://www.spheron.network/blog/gpu-vram-requirements-fine-tune-llm-2026/) ·
  [Unsloth requirements](https://unsloth.ai/docs/get-started/fine-tuning-for-beginners/unsloth-requirements)

**§8 Training strategies** ·
[Unsloth LoRA hyperparameters guide](https://unsloth.ai/docs/get-started/fine-tuning-llms-guide/lora-hyperparameters-guide) ·
[The Hidden Power of the Scaling Factor in LoRA (α = 2r)](https://arxiv.org/abs/2606.12883) ·
[LoRA Learns Less and Forgets Less](https://arxiv.org/pdf/2405.09673) ·
[RetrySQL: text-to-SQL training with retry data](https://arxiv.org/html/2507.02529v1) — source of the
**LoRA-cannot-learn-retry** result (50.07% vs 54.71% baseline) ·
[Synthetic data for LLM fine-tuning in 2026](https://futureagi.com/blog/synthetic-data-fine-tuning-llms/)

**§9 Retrieval** ·
[A Comparative Study of DSL Code Generation: Fine-Tuning vs. Optimized Retrieval Augmentation](https://arxiv.org/abs/2407.02742)
— the closest published analogue; RAG reached parity with a fine-tune and beat it on compilation rate ·
[Evaluating RAG variants for NL-based SQL and API call generation](https://arxiv.org/html/2602.07086v1) ·
[LLM-enhanced text-to-SQL generation: a survey](https://arxiv.org/html/2410.06011v1) ·
[OmniSQL: synthesizing high-quality text-to-SQL data at scale (VLDB)](https://www.vldb.org/pvldb/vol18/p4695-li.pdf)

**§10 Teacher licensing** ·
[Gemini API Additional Terms of Service](https://ai.google.dev/gemini-api/terms) — clauses quoted
verbatim in §10.1–10.2
