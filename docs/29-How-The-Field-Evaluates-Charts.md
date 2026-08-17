# 29 — How Everyone Else Evaluates Chart Quality

**And how AutoViz compares.** Companion to [`Docs/28`](28-Testing-Chart-Quality.md), which
describes what we do. This one describes what the field does, so you can see which parts of
our evaluation are normal, which are unusually strong, and which are genuinely behind.

> **Read this first:** [`Docs/05 §3`](05-Research-Findings-for-AutoViz.md) already contains
> most of the research below — it was written early in the project and then **not acted
> on**. Section 5 of this document is about that gap. If you only read one thing, read
> section 4.

---

## 1. There are three traditions, not one

People have been trying to score charts automatically for forty years. The work splits into
three families, and they answer three different questions.

| Tradition | The question it asks | Started |
|---|---|---|
| **A. Perceptual rules** | Which encoding can a human read most accurately? | 1984 |
| **B. Benchmark + ground truth** | Did you produce the chart the question asked for? | 2021 |
| **C. Model-as-judge** | Would an expert say this chart is any good? | 2024 |

Almost every modern tool uses some mixture. AutoViz uses A and B, and none of C.

---

## 2. Tradition A — perceptual rules

**The founding idea:** some ways of showing a number are simply easier for a human eye to
read than others. This isn't opinion — it was measured.

**Cleveland & McGill (1984)** ran experiments asking people to compare values shown
different ways, and produced a ranking of accuracy:

> position on a common scale → position on unaligned scales → length → angle → area →
> colour saturation

That ranking is why a bar chart beats a pie chart for comparing values, and it is the
reason almost every recommender prefers bars. **Mackinlay (1986)** turned it into an
algorithm: a chart must be *expressive* (shows the data and nothing false) and *effective*
(uses the highest-ranked encoding available).

**Draco** ([Moritz et al., IEEE TVCG](https://idl.uw.edu/draco)) is the modern version, and
it's the most sophisticated tool in this family. It works like this:

- Visualization knowledge is written as **constraints** in a logic language.
- **Hard constraints** rule out impossible or dishonest charts.
- **Soft constraints** are preferences, each with a **cost** when violated.
- A solver searches the whole design space and returns the chart with the lowest total cost.

The clever part: **the costs are learned from graphical-perception experiments**, not
guessed. So "this chart is worse" becomes a number backed by human studies rather than
someone's taste.

### How AutoViz compares

Our recommender is in this family, but it is much simpler: hand-written rules that read the
result's shape and pick a family. No solver, no costs, no learned weights.

**That is a reasonable choice for this project** — a rule you can read is a rule you can
explain to an evaluator, and Draco needs a logic solver as a dependency. But be honest
about what it means: *our chart choices are defensible by argument, not by measurement.*

Worth knowing if asked: [DracoGPT (2024)](https://arxiv.org/pdf/2408.06845) tested whether
LLMs' visualization preferences match Draco's perceptual rules. They partly do, and partly
don't — which is a good argument for our design, where an LLM never chooses the chart type
at all. **A deterministic recommender is the safer half of that finding.**

---

## 3. Tradition B — benchmarks with ground truth

This is where the NL-to-chart field actually lives, and it's the family AutoViz's own
benchmark belongs to.

### nvBench (2021) — the original

The standard dataset: **~25,750 natural-language / visualization pairs** across 153
databases. It made the field measurable for the first time. Its known weakness is noisy and
ambiguous labels — some questions have more than one right answer, but only one is marked
correct, so a good system gets scored wrong.

### VisEval (2024, Microsoft) — the one to copy

[VisEval](https://arxiv.org/abs/2407.00981) cleaned nvBench up (**2,524 queries, 146
databases**) and, more importantly, defined **three evaluation axes** that have become the
default framing:

| Axis | Means | How they check it |
|---|---|---|
| **Validity** | Does it produce a chart at all? | Run it, see if anything renders |
| **Legality** | Does the chart match what was asked? | Right columns, right chart type, right sort order, right channels |
| **Readability** | Is it visually clear? | Rule checks **plus a vision-model judge** |

Two of their findings matter to us:

**Ground truth should be a *feasible region*, not one answer.** "Count by rank and gender"
can legitimately put gender on the colour channel *or* the x-axis. Marking one wrong is a
false negative. So they label a **set** of acceptable configurations.

**Automated readability judging works.** Their vision-model judge agreed with human raters
at **SRCC 0.843**, against **0.782** agreement between two human experts. In other words:
*the automated judge was about as reliable as a second expert.* That is the single most
useful number in this entire literature for a small team, because it means you do not need
a large human study to score readability.

### nvBench 2.0 (2025, NeurIPS) — the one built for our feature

[nvBench 2.0](https://nvbench2.github.io/) is the most directly relevant thing in this
document, and it did not exist when `Docs/05` was written.

It exists because of one observation: **many natural-language questions are genuinely
ambiguous**, and a benchmark that pretends they aren't will punish a system for noticing.
So nvBench 2.0:

- supports **one-to-many** mapping from a question to several valid charts,
- **explicitly models the ambiguity** in the question,
- provides **reasoning paths** showing how the ambiguity should be resolved.

**Read that list against AutoViz's clarification gate.** Our whole argument on slide 12 of
the mid-eval deck is that *asking a clarifying question is the product working, not
failing* — and we currently support that claim with 7 hand-written prompts. nvBench 2.0 is
a public, peer-reviewed benchmark built specifically to measure that behaviour.

---

## 4. Tradition C — the model as judge

The newest family, and the one AutoViz uses **not at all**.

The idea: show a rendered chart image to a vision-capable model and ask it to score the
chart, the way you'd ask a human. Used by VisEval for readability, and by
**PandasPlotBench** for overall quality.

PandasPlotBench found two things worth remembering:

**Score the task, not the picture.** They scored charts two ways — *visual similarity* to a
reference chart, and *task adherence* (does it answer what was asked). These agreed only at
**r = 0.58**, so they measure different things. Against human judgement, task adherence
scored **r = 0.85** and visual similarity only **r = 0.66**. **So task adherence is the
better primary metric.**

**Never score by comparing code or JSON.** They tested string-similarity metrics on
generated plotting code and found **no correlation with actual quality** — two correct
charts often differ only in irrelevant details. This is a direct warning for us: *do not
score AutoViz by diffing Vega-Lite specs against reference specs.* We don't, and we should
keep not doing it.

---

## 5. Where AutoViz actually stands

Mapping our four layers onto VisEval's three axes:

| VisEval axis | What VisEval does | What AutoViz does | Verdict |
|---|---|---|---|
| **Validity** | Renders the chart, checks it isn't blank | Validates against Vega-Lite's **official JSON schema**, then renders through the **real Vega runtime** and asserts the scenegraph | **We are ahead** |
| **Legality** | Checks columns, chart type, sort order, channels — over 2,524 pairs | Checks **chart type only**, over 14 shapes + 39 NL prompts | **Well behind** |
| **Readability** | Rule checks **+ vision-model judge**, SRCC 0.843 vs humans | **3 rule-based ceilings.** No judge, no human scoring | **Far behind** |

### The one place we are genuinely stronger

**Nobody else checks the scenegraph.** VisEval renders a chart to an image and asks whether
something appeared. We compile through the real Vega-Lite compiler and then assert on the
drawing instructions: *are these bars grouped or stacked? does this donut have an inner
radius? did the theme colour actually reach the marks?*

That catches a specific class of bug — a chart that renders happily and is quietly wrong —
that an image-based check will miss and a JSON check cannot see. It is worth saying out
loud in the evaluation, because it is a real methodological contribution rather than a
borrowed one.

### The three places we are behind

**1. Scale.** 14 chart shapes and 39 NL prompts against VisEval's 2,524 pairs. Ours are
hand-written by us, theirs are peer-reviewed and public.

**2. Legality is only chart type.** We never check that the chart used the *right columns*,
the *right sort order*, or the *right channels*. A chart could pick the correct type and
still plot the wrong column, and every test we have would pass.

**3. No readability judging at all.** Our three ceilings catch gross overcrowding. Nothing
catches a chart that is merely *bad* — overlapping labels, a squashed axis, an unreadable
scale.

### And the thing that stings

[`Docs/05 §3.6`](05-Research-Findings-for-AutoViz.md) — written by us, early in the project
— prescribed a concrete recipe: *15–20 datasets × 5–10 tasks (~100–150 total), feasible-
region labels, validity/legality/readability scoring, an LLM judge, and a human-correlation
sanity check.*

**We built about a quarter of that.** The research was done and then not acted on. That is
worth owning in the evaluation before somebody finds it, in exactly the way we owned the
prose-grounding hole.

---

## 6. What to do about it, ranked by value per hour

**1. Run VisEval's evaluation code against our system.** *(Highest value.)*
It is [open source](https://github.com/microsoft/VisEval) and the checkers are reusable.
This converts "we tested it ourselves" into "we scored against a published Microsoft
benchmark", which is a completely different sentence in a final report. Even a partial run
on a subset is worth more than another 50 hand-written cases.

**2. Add a vision-model judge for readability.**
We already render charts to SVG in `verify:specs` and throw the image away. Rasterise it,
send it to a vision model with VisEval's readability rubric, and score. Their SRCC 0.843
result says this is reliable enough to report. **Then sanity-check the judge against a few
human ratings and publish that correlation** — that step is what makes the number credible
rather than circular.

**3. Extend legality beyond chart type.**
Add assertions for the right columns on the right channels, and the right sort order. Our
39-prompt suite already carries `must_columns` for the plan — extending the same idea to
the chart's encodings is a small change to `nl_suite.py`.

**4. Evaluate the clarification gate against nvBench 2.0.**
The ambiguity behaviour is the most distinctive thing in the product and the least measured
— 7 hand-written prompts. nvBench 2.0 was built for exactly this. Bigger job than the
others because of the data-loading, but it would let us make a claim nobody else in the
cohort can.

**5. Adopt "feasible region" labelling everywhere.**
We already do this informally — `chart_family` in `nl_suite.py` accepts a *set*. Say so
explicitly and cite VisEval for it, because it is the correct methodology and we arrived at
it independently.

---

## 7. Answers to have ready

**"How do other systems evaluate this?"**
> Three ways. Perceptual rules from graphical-perception experiments — Cleveland & McGill
> through to Draco. Benchmarks with labelled ground truth — nvBench and VisEval. And
> vision-model judges scoring rendered charts, which is the newest and is now about as
> reliable as a second human expert.

**"Which do you use?"**
> The first two. Our recommender is rule-based in the Draco tradition but hand-written, and
> our benchmark follows VisEval's structure — we independently arrived at the same three
> axes and the same feasible-region labelling. We use no model judge, which is our clearest
> gap.

**"Is your evaluation as good as theirs?"**
> On validity, ours is stricter — we assert on the rendered scenegraph, so we catch grouped
> bars silently stacking, which an image check misses. On scale and on readability, no:
> 14 shapes against VisEval's 2,524, and three ceilings against a calibrated judge. We know
> the fix, it's open source, and it's in the plan.

---

## 8. Sources

- Cleveland, W.S. & McGill, R. (1984). *Graphical Perception.* JASA — the accuracy ranking everything else rests on.
- Mackinlay, J. (1986). *Automating the Design of Graphical Presentations.* — expressiveness and effectiveness.
- [Moritz, D. et al. *Formalizing Visualization Design Knowledge as Constraints: Actionable and Extensible Models in Draco.*](https://idl.cs.washington.edu/files/2019-Draco-InfoVis.pdf) IEEE TVCG.
- [Chen, N. et al. (2024). *VisEval: A Benchmark for Data Visualization in the Era of Large Language Models.*](https://arxiv.org/abs/2407.00981) IEEE TVCG — the three axes, and the 0.843 judge correlation. [Code](https://github.com/microsoft/VisEval).
- [nvBench 2.0: Resolving Ambiguity in Text-to-Visualization through Stepwise Reasoning](https://nvbench2.github.io/) — NeurIPS 2025. [Code](https://github.com/HKUSTDial/nvBench-2.0).
- Luo, Y., Tang, J., Li, G. (2021). *nvBench.* arXiv:2112.12926.
- [Wang, H. et al. (2024). *DracoGPT: Extracting Visualization Design Preferences from Large Language Models.*](https://arxiv.org/pdf/2408.06845) IEEE TVCG.
- Galimzyanov, T. et al. (2025). *Drawing Pandas (PandasPlotBench).* arXiv:2412.02764 — task adherence beats visual similarity; code similarity is worthless.

*Already in the project bibliography via [`Docs/05 §5`](05-Research-Findings-for-AutoViz.md).*
