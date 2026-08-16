# 14 — Cleaning Disclosure & Outlier-Robust Axes

Two related pieces of the "a correct number is not enough" problem, as **implemented** in
`backend/` on branch `feat/cleaning-disclosure`:

1. **Disclosure** — the user is told what cleaning did to their numbers, in the answer itself,
   not only in provenance.
2. **Outlier-robust axes** — a single extreme value no longer flattens every other mark, and the
   fix happens at the axis rather than by deleting or capping the value.

They ship as two commits because the second needs the first: an axis that silently stopped being
linear is a trap, so the rendering fix could not land until there was a channel to announce it on.

Every behaviour below is enforced in code and covered by tests. Suite: **475 → 515 passing**.

---

## 1. The problem each half solves

### 1.1 Disclosure: the prose existed and never reached anyone

`services/execution.py` already built a correct, plain-English sentence whenever an imputation
was large enough to move a result:

> `40 of 100 values in 'fare' (40.0%) were filled in, not measured.`

It went into `provenance.imputation_notices` — an audit artefact nobody reads mid-conversation.
Meanwhile `llm/client.py::compose()` condensed each result down to seven fields before handing it
to the composer LLM:

```
task · status · chart_type · rows · row_count · sql · errors
```

None of them mention cleaning. The composer therefore **could not** tell the user that the average
it was reporting sat on a 40%-imputed column, because it was never shown that fact. The same held
for `implicit_null_exclusions`, the preprocessing step report, and `applied_cleaning` — which
`assess_quality` computed, stored in worker state, and which `finalize_worker` then dropped.

### 1.2 Outlier axes: a rendering problem treated as a data problem

One row 500× the others collapses every remaining mark into a hairline at the baseline. The chart
is arithmetically correct and shows nothing.

The instinct is to clean the outlier away. That is the wrong layer. An extreme value is only
*sometimes* an error — the literature splits outliers into **error outliers** (data-entry
mistakes, unit mix-ups, instrument faults) and **genuine extremes**, which carry information and
should be retained — and the data itself cannot say which kind it is holding. A ₹9,000,000 salary
in a table of ₹50k salaries may be a typo for ₹90,000, or it may be the CEO. Dropping it to
improve a chart changes the number the chart reports.

So AutoViz separates four stages that most tutorials merge:

| Stage | Question | Where it lives |
|---|---|---|
| Detect | Which points are extreme? | `services/skew.py` |
| Classify | Error, or genuine extreme? | **Not attempted** — undecidable from the data |
| Treat | Change the value? | Only via an explicit, confirmed preprocessing op |
| Display | How do I render a wide range legibly? | `services/skew.py` → the Vega-Lite scale |

---

## 2. The disclosure channel — `services/notices.py`

### 2.1 One notice type

Before this, four incompatible shapes carried user-relevant facts: `imputation_notices` (dicts
with prose), `implicit_null_exclusions` (a `column → int` map with no prose), the `preprocessing`
step report, and chart `warnings` (bare strings). They collapse into one:

```python
@dataclass(frozen=True)
class Notice:
    kind: str                 # "fill_nulls", "skewed_axis", …
    severity: str             # applied | disclosed | advisory
    note: str                 # the finished, user-facing sentence
    column: str | None
    technique: str | None     # the jargon, kept separate from the prose
    detail: dict[str, Any]    # rows_affected, fraction, min/max/median …
```

`notices.py:65`. `technique` is split from `note` for the same reason
`quality.CleaningOption` does it: the jargon belongs behind a "how this works" disclosure, not in
front of a user who has never heard of median imputation.

**The prose is built in Python, never by the LLM.** This mirrors the stance already taken in
`services/quality.py` (*"it is deliberately not an LLM"*). A disclosure the model paraphrases is a
disclosure that can drift, soften, or vanish; the composer is handed a finished sentence and told
to reuse it.

### 2.2 Severity — derived, never declared twice

Severity decides **how loudly** something is said. It is distinct from `Risk`, which decides
whether consent was needed in the first place.

| Severity | Meaning | Treatment in the answer |
|---|---|---|
| `applied` | Semantics-preserving repair. Nothing means anything different. | Batched into one closing clause, or omitted |
| `disclosed` | The numbers now mean something different from the raw data. | Its own sentence, every time |
| `advisory` | Nothing changed, but the chart is misread without it. | Its own sentence |

Severity is **computed** from two things that already exist, rather than hand-declared per op
(`notices.py:98`):

- the op's declared `Risk` (`SAFE` → `applied`);
- for value-changing ops, the existing `ROW_DROP_NOTICE_FRACTION` (0.05) line — already documented
  in `allowlists.py` as *"small enough to mention rather than ask about"*. Above it, `disclosed`;
  below it, demoted to `applied` — recorded, but not worth a sentence.

The op → risk map is read off the Pydantic models themselves by unwrapping the `PreprocessOp`
discriminated union (`notices.py:45`), so a new op is covered the moment it joins the union rather
than the moment someone remembers to extend a list. A parallel judgement here would be one more
thing to forget when an op changes tier.

A step with `rows_affected == 0` produces **no notice at all** — "trimmed whitespace in 0 rows" is
noise that pushes the real disclosure further down the answer.

### 2.3 Producers

| Builder | Source | Severities emitted |
|---|---|---|
| `from_preprocessing(report, input_rows)` | The cleaning step report | `applied` / `disclosed` |
| `from_null_exclusions(exclusions, input_rows)` | Nulls an aggregate skipped on its own | `disclosed` |
| `skew.assess(values, column, chart_type, channel)` | The plotted values | `advisory` |

All ten preprocessing ops have prose (`drop_nulls`, `fill_nulls`, `drop_exact_duplicates`,
`trim_whitespace`, `empty_string_to_null`, `normalize_case`, `drop_empty_rows`, `cast_column`,
`clean_categories`, `group_rare_categories`), pinned by
`test_every_op_in_the_grammar_can_be_phrased` — an op that falls through to silence still runs and
still changes the data, so the gap would be invisible until someone read the SQL.

`from_null_exclusions` covers the disclosure that is easiest to lose, because nothing "happened":
no step ran, no row was dropped by a plan, the average is simply over fewer rows than the user
thinks.

Column names are passed through `safety.neutralize_text` — headers come from an untrusted CSV and
this prose is bound for both an LLM prompt and the user's screen.

### 2.4 The path to the user

```
execute_analysis ──► provenance.notices                     (execution.py:911)
                          │
generate_chart ──► chart["notices"]                          (charts.py:337)
                          │
                          ▼
run_pipeline ──► out["notices"]  = cleaning + chart, merged  (orchestrator.py:176)
                          │
                          ▼
finalize_worker ──► ChartResult["notices"]                   (nodes.py:444)
                          │
                          ▼
compose() ──► condensed payload + _COMPOSE_SYSTEM rules      (client.py:240)
                          │
                          ▼
compose_response ──► owed disclosures appended if missing    (nodes.py:156)
```

Four properties this path guarantees:

1. **Additive.** `imputation_notices` and `implicit_null_exclusions` are untouched. `notices` is
   the disclosure; those remain the machine-readable evidence.
2. **Survives a partial run.** `finalize_worker`'s `partial`/`error` branch carries notices too — a
   run that failed at the chart step still cleaned data and still returned numbers, so the
   disclosure is owed either way. The fallback bar chart contributes its own axis notices.
3. **Survives a mute or broken composer.** After `compose()` returns, any `disclosed`/`advisory`
   note whose wording is not already in the answer is appended (`nodes.py:156`). "The LLM was told
   to" is not a guarantee, and a caveat lost to a terse model or a failed API call is exactly the
   failure this channel exists to prevent. `applied` notices are never force-appended — a wide
   messy CSV would otherwise bury the answer.
4. **Survives the conversation.** `advisory` notices are also written onto the Vega-Lite spec as a
   `title.subtitle` (`charts.py:327`). A saved dashboard has no chat behind it; an explanation
   living only in the transcript is one the reader will not have tomorrow.

`render_summary()` (`notices.py:248`) provides deterministic prose for callers with no LLM at all:
disclosures and advisories keep their own sentences, safe repairs collapse into one trailing
clause.

### 2.5 Prompt contract

`_COMPOSE_SYSTEM` (`llm/client.py`) was extended with the reuse rule, per-severity handling, and
one guard: *"Notices are not results: never treat a note's numbers as findings about the data."*
`schema/plan_guide.py` gained the matching planner-side rule — see §4.3.

---

## 3. Outlier-robust axes — `services/skew.py`

### 3.1 Skew is measured on the plotted values, not the source column

This is the load-bearing decision. Aggregation both **destroys** and **creates** skew:

- a violently skewed `revenue` column averages into twelve unremarkable regional means;
- a perfectly tame column produces one enormous bar when a single group holds most of the rows.

A source-level check would fire on the wrong distribution in both directions. The distribution that
compresses a chart is the one in the **result table**, which is why detection runs inside
`generate_chart` on the values actually being drawn (`charts.py:287`), not at registration time
against the cached profile.

Channels with no `field` — a histogram's binned count, for example — are skipped: there is no
column of values to judge.

### 3.2 Detection rule

Two complementary tests (`skew.py:90`); either firing marks the axis compressed.

| Test | Formula | Threshold | Catches |
|---|---|---|---|
| **Dominance** | `max / median`, positive data only | ≥ `SKEW_DOMINANCE` = 25.0 | One value swamping the rest |
| **Occupancy** | `(p75 − p25) / (max − min)` | ≤ `SKEW_OCCUPANCY` = 0.03 | Several extremes; data crossing zero |

Dominance is the direct statement of the symptom: at 25, the median mark occupies 4% of the axis;
well below that a chart is merely uneven rather than unreadable, which is not worth interrupting
anyone over. It is only meaningful on strictly positive data, where the baseline is zero and the
ratio genuinely says what share of the axis a typical value receives.

Occupancy covers what dominance misses — a bimodal split where the median sits inside the upper
cluster — and works on data that crosses zero, where a ratio means nothing.

`MIN_POINTS = 4` guards the small-n case: with three marks there is no "typical value" being
crushed, and that the third is larger is a finding about the data, not a defect in the chart.
Constant series and zero-span series return early rather than dividing by zero.

Quantiles are linear-interpolated in pure Python (`skew.py:71`) — no new dependency, and the input
is a result table already capped by `HARD_ROW_CEILING`.

**Deliberately not used:** the classical z-score (`|x−μ|/σ > 3`). Both μ and σ are themselves
wrecked by the outlier being hunted, so it *masks* — the extreme value hides itself. This is the
same reasoning that already excludes `mean` from `FILL_STRATEGIES` in `allowlists.py`.

### 3.3 What may be rescaled — a property of the channel, not the chart type

`assess()` takes the channel as well as the chart type, because the two questions are genuinely
different. Resolution order:

| Test | Applies to | Behaviour |
|---|---|---|
| `EXEMPT_TYPES` = `boxplot` | Any channel | Nothing; extremes are the content |
| `COLOR_CHANNELS` = `color`, `fill` | Any non-exempt chart type | Scale changed **and** disclosed |
| `SCALABLE_TYPES` = `line`, `scatter` | `x` / `y` | Scale changed **and** disclosed |
| `BASELINE_TYPES` = `bar`, `grouped_bar`, `area`, `histogram` | `x` / `y` | Disclosed only; scale left linear |
| anything else | — | Nothing |

The asymmetry is the point. A **position** channel (a line or scatter axis) moves a mark and claims
nothing else. A **colour** channel carries a quantity as hue, and a hue makes no proportionality
claim at all. But a **length-or-area-from-a-baseline** channel — a bar's height, an area's
thickness — does: a log-scaled bar length is no longer proportional to its value.

Keying the policy on the channel is what lets a heatmap's measure be log-scaled while a bar's
height, on the very same chart grammar, may not be — and it means a bar chart with a quantitative
*colour* channel gets the colour rescaled while its heights stay honest
(`test_colour_is_rescaled_even_on_a_mark_whose_axis_is_not`).

Nominal colour channels are never judged: categories have no quantity to compress.

That is the same objection that makes a truncated bar axis misleading, and the experimental result
there is unusually strong: the exaggeration *persists across chart types and designs, and even
when participants correctly report the numbers they read off the axis*. Broken-axis marks and
gradient fills — the usual mitigations — did **not** consistently reduce the misreading. A visual
cue does not rescue a broken encoding, so AutoViz does not break the encoding.

Bars therefore keep their honest linear scale and the user is told what they are looking at:

> `'revenue' is dominated by one value, 9,500 — about 380x the typical 25, so the smaller values
> are compressed near the baseline. The scale is left linear because bar length has to stay
> proportional; a line or scatter of the same data can be log-scaled instead.`

Colour is the opposite case, and the one where the linear version fails **worse** than a squashed
axis. On a heatmap, one dominant cell takes the whole top of the sequential ramp and every other
cell lands on a near-identical shade at the bottom — the chart reads as *uniform*, which is a
stronger false claim than merely cramped. The measure rides `color`, both axes are nominal, and
the notice is a distinct kind (`skewed_color`):

> `'sales' spans 3 to 9,000, so the colour scale is log-scaled — on a linear ramp one value would
> take the whole scale and the rest would be near-identical shades. Equal steps in colour are equal
> ratios, not equal amounts.`

The theme's colour ramp is unaffected: `chart_theme.attach` writes only to `spec["config"]`
(`config.range.heatmap`), so a scale *type* on the encoding composes with it rather than
overriding it.

### 3.4 Scale choice

```
min > 0   →  {"type": "log"}
otherwise →  {"type": "symlog"}
```

A Vega-Lite **log domain must be strictly positive or strictly negative and must not include or
cross zero**, so any series touching zero or going negative would produce an invalid spec.
`symlog` is log-like and defined at and below zero, which makes it the correct default for
measures such as profit or temperature delta.

`assess()` returns `(scale, notice)` and **never returns a scale without a notice** — pinned by
`test_a_scale_is_never_changed_without_saying_so`.

---

## 4. Design decisions

### 4.1 No winsorize / clip / trim preprocessing op was added

Capping a value to improve a chart changes the number the chart reports, and the classification
that would justify it (error vs. genuine extreme) is not derivable from the data. The practical
guidance in the literature is also narrow: **never winsorize more than ~5% of the data** — beyond
that the distribution is heavy-tailed rather than contaminated, and should be analysed as two
populations instead of flattened into one.

Users who genuinely want an extreme excluded can still say so; it becomes an ordinary
`VALUE_CHANGING` filter or `drop_nulls`, gated and disclosed like any other. What AutoViz will not
do is apply one on its own initiative to make a picture look better.

### 4.2 Aggregate choice is the real "treatment"

A single extreme value corrupts `mean` but not `median`, and both are already in `AGG_FNS`.
Switching the aggregate changes zero rows and is fully explainable — strictly better than
winsorizing when the plan is `mean(revenue) by region`. Automatic suggestion of this is listed in
§5 as a follow-up.

### 4.3 The planner is told not to "fix" skew

`schema/plan_guide.py` gained an explicit rule, because the failure mode is an LLM helpfully adding
`revenue < 1000` to tidy a chart:

> *Do NOT try to fix a skewed chart with a plan. An extreme value that flattens the other marks is
> handled at the axis, automatically, and disclosed as an advisory notice. Filtering or capping it
> would change the answer to improve the picture — if the user did not ask to exclude it, keep it.*

### 4.4 Strict MCP models caught a real contract break

Adding `notices` to the `run_pipeline` return initially broke three `test_mcp_envelope.py` tests:
`PipelineOutput` is a `_Strict` model and rejected the unknown key. This is the contract working as
designed — any future field added to a pipeline return fails loudly at the MCP boundary rather
than being silently dropped. `PipelineOutput`, `Provenance` and `GenerateChartOutput` all gained
the field.

---

## 5. Known limitations & follow-ups

- **No frontend rendering.** Notices reach the user through the agent's text answer and the chart
  subtitle. The React client does not yet display them as a distinct UI affordance.
- **Pie / donut.** `theta` is an angle swept from a baseline — the same proportionality objection as
  a bar, so it must not be rescaled. It is currently not assessed at all, meaning a pie dominated by
  one slice gets no advisory either; adding one would be consistent with how bars are handled.
- **No skew-aware aggregate suggestion.** Detecting that a plan uses `mean` on a heavily skewed
  measure and proposing `median` is the obvious next producer of a `disclosed` notice.
- **Thresholds are constants, not configuration.** `SKEW_DOMINANCE` and `SKEW_OCCUPANCY` are not
  env-overridable, unlike the resource ceilings in `allowlists.py`.
- **Medcouple-adjusted fences are not implemented.** For genuinely skewed distributions the
  skewness-adjusted boxplot is the more principled detector; the two cheap rules in §3.2 were
  chosen because they need no new dependency and match the *harm* (wasted axis) rather than a
  distributional definition of "outlier".

---

## 6. File map

| File | Status | Role |
|---|---|---|
| `services/notices.py` | **new** | `Notice` model, severity derivation, prose builders, `render_summary` |
| `services/skew.py` | **new** | Detection, scale choice, mark-class policy |
| `services/execution.py` | modified | Publishes `provenance.notices` |
| `services/charts.py` | modified | Per-channel skew assessment, scale merge, spec subtitle, `notices` in return |
| `services/orchestrator.py` | modified | Merges cleaning + chart notices into one list |
| `agent/nodes.py` | modified | `_notices_of`, carries notices on every `finalize_worker` branch, appends owed disclosures in `compose_response`, fallback chart notices |
| `agent/state.py` | modified | `ChartResult.notices` |
| `llm/client.py` | modified | `notices` in the condensed payload; `_COMPOSE_SYSTEM` rules |
| `mcp/results.py` | modified | `notices` on `Provenance`, `GenerateChartOutput`, `PipelineOutput` |
| `schema/plan_guide.py` | modified | Severity contract + the "do not fix skew with a plan" rule |

## 7. Test coverage

`tests/test_notices.py` — 13 tests. Severity derivation from `Risk`; sub-threshold demotion;
zero-effect steps producing nothing; every grammar op being phraseable; column-name
neutralization; sub-threshold null exclusions; summary ordering; end-to-end publication in
provenance with the legacy records intact; notices surviving a partial run; disclosure reaching the
answer through both a mute composer and a broken one; no duplication when the composer already said
it; `applied` notices not being force-appended.

`tests/test_skew.py` — 27 tests. Dominance and occupancy detection; unremarkable spreads left
alone; small-n and constant-series guards; `log` vs `symlog` selection; every `BASELINE_TYPES`
member disclosed-but-not-rescaled (parametrized); boxplot exemption; the never-silent invariant;
the extreme row still present in the chart data; derived channels skipped; spec subtitle present
and absent as appropriate; neutralization; the channel-over-chart-type rule (a bar's colour
rescaled while its height is not); heatmap colour `log` and `symlog`; boxplot exemption still
winning over the colour rule; heatmap axes left untouched; nominal colour channels not judged; and
a full `run_pipeline` integration asserting that the cleaning half and the rendering half arrive
merged in one list.

## 8. Sources for the design claims

- Correll, Bertini & Franconeri, *Truncating the Y-Axis: Threat or Menace?*, CHI 2020 —
  <https://dl.acm.org/doi/fullHtml/10.1145/3313831.3376222>
- Yang et al., *Truncating Bar Graphs Persistently Misleads Viewers*, JARMAC 2021 —
  <https://www.sciencedirect.com/science/article/abs/pii/S2211368120300978>
- Vega-Lite scale documentation (log/symlog/clamp/domain constraints) —
  <https://vega.github.io/vega-lite/docs/scale.html>
- *Outlier management in data analysis: a checklist for authors and reviewers*, J. For. Res. —
  <https://link.springer.com/article/10.1007/s11676-025-01967-z>
- Wicklin, *Winsorization: The good, the bad, and the ugly*, SAS —
  <https://blogs.sas.com/content/iml/2017/02/08/winsorization-good-bad-and-ugly.html>
- *Univariate Outlier Detection Using SAS*, WUSS 2023 Paper 158 —
  <https://www.wuss.org/proceedings/2023/WUSS-2023-Paper-158.pdf>
- Mahmood, *Outlier Detection Part 2 — Adjusted Boxplot for skewed distributions* —
  <https://towardsdatascience.com/outlier-detection-part-2-6839f6199768/>
