# 28 — How We Check Our Charts Are Good (and whether that's enough)

**Written in plain language on purpose.** This explains how AutoViz tests the charts it
draws, what each test can and cannot catch, and an honest answer to "is that enough?"

The short answer to that last question is **no** — and section 6 says exactly where the
holes are.

---

## 1. First: what does "a bad chart" actually mean?

This is the question you have to answer before you can test anything. "Quality" sounds
like one thing. It isn't. A chart can fail in **four completely different ways**, and each
one needs a different kind of test.

Imagine you ask *"What were sales by month?"*

| # | What goes wrong | What you'd see | Example |
|---|---|---|---|
| 1 | **Wrong type of chart** | A perfectly drawn chart that answers nothing | A pie chart of 12 months |
| 2 | **Broken recipe** | Nothing appears, or an error | The chart spec is missing a required field |
| 3 | **Draws the wrong thing** | It looks fine but is subtly lying | Bars *stacked* when they should be *side by side* |
| 4 | **Too crowded to read** | Technically correct, practically useless | A pie chart with 40 slices |

Every one of those is a real failure. **None of them is caught by the others.** So we test
each one separately, and we report four numbers instead of one average.

> **Why not just report one score?** Because averaging hides things. If we said "chart
> quality: 92%", nobody could tell whether that meant "one chart is slightly ugly" or
> "one chart in twelve shows the wrong numbers". Those are not the same problem.

---

## 2. Layer 1 — Is it the right *kind* of chart?

**The idea:** give the system a description of a result table and ask it to pick a chart.
Check whether it picked one from the right family.

The user never says "draw me a bar chart". They ask a question, we run a query, and then a
rule-based recommender looks at the **shape of the answer** — how many categories, how many
numbers, is the x-axis a date — and picks.

So we wrote down **14 result shapes** and, for each, which charts would be acceptable:

| The situation | Charts we'd accept |
|---|---|
| A number over time | `line` |
| A ranking across one category | `bar` |
| Two categories crossed with a number | `heatmap` |
| Part-to-whole, few categories | `pie` or `donut` |
| Two numbers, one point per row | `scatter` |
| **Nothing numeric to plot at all** | **a refusal** |

Notice two things.

**We accept a *family*, not one exact answer.** For "part of a whole", both a pie and a
donut are defensible, so both pass. Insisting on one exact answer would be testing our
taste, not the system's correctness. Where only one answer is genuinely right — a trend
over time is a line — we list only one.

**One case must produce a refusal.** If the result has no number in it, there is nothing to
plot, and the *correct* behaviour is to say so. A test suite that only checks "did it draw
something" would score a wrong chart as a pass here.

**Current result: 14 out of 14.**

```bash
uv run python -m bench.chart_quality
```

---

## 3. Layer 2 — Is the chart's recipe valid?

**The idea:** we don't draw pixels in Python. We produce a **Vega-Lite spec** — a JSON
document that describes the chart, which the browser then draws.

Think of it as a recipe. Our backend writes the recipe; the browser is the cook.

So: **is the recipe one the cook can actually follow?**

The naive way to test this is to write our own checks — "does it have an `x`? does it have
a `y`?". We did that first, and it was not enough, for one specific reason:

> **Our own checks can only test the recipe we *think* is required.**
> They cannot test the recipe the browser *actually* requires.

So instead we validate every generated spec against **Vega-Lite's own official JSON
schema** — the file that ships inside `vega-lite` in `node_modules`. That is the renderer's
real contract, written by the people who built the renderer, not our restatement of it.

**This immediately found a bug.** *Every single boxplot spec we had ever produced was
invalid.* Our own tests said they were fine, because they checked the structure we
expected. The official schema said no.

**Current result: 10 out of 10 chart types produce schema-valid specs.**

---

## 4. Layer 3 — Does it actually *draw* what we think?

This is the most interesting layer, and the one most projects skip.

**The problem:** a spec can be perfectly valid and still draw the wrong picture. Consider:

- Grouped bars vs **stacked** bars — a one-property difference. Both are valid. Both draw
  rectangles. Only one answers the question.
- A donut vs a **pie** — a donut is an arc with an inner radius. Forget the inner radius
  and you silently ship a pie.
- Our custom colour theme vs Vega-Lite's **default** colours — if the theme fails to
  apply, the chart still draws, in the wrong colours.

None of these has a *structural* symptom. Checking the JSON will never find them.

**The solution:** actually run the chart. `npm run verify:specs` takes 14 reference specs,
compiles them with the **real Vega-Lite compiler**, runs them through the **real Vega
runtime**, and then inspects the drawing instructions that came out — the *scenegraph*.

Then it asserts things you could only know after drawing:

```js
grouped_bar: ({ byType }) => {
  const bars = byType.rect ?? [];
  const widths = new Set(bars.map((b) => Math.round(b.width)));
  const atBaseline = bars.filter((b) => Math.round(b.y2) === 300).length;
  // Grouped: each series gets a slice of the band, every bar starts at the
  // baseline. Stacked would be full-band width with contiguous segments.
  if (widths.size !== 1 || [...widths][0] >= 100) return 'bars are full-band — not grouped';
  if (atBaseline !== bars.length) return 'not every bar sits on the baseline — stacked';
  return null;
}
```

In plain English: *"every bar should be narrow, and every bar should start at the bottom.
If some bars start halfway up, they're stacked, and that's the bug."*

It also checks:

- **Donuts have an inner radius**, pies do not.
- **Heatmap cells sit on our blue ramp**, so the default colour scheme has not leaked in.
- **Data labels actually reach the canvas.** A text layer that compiles but draws nothing
  looks fine in the JSON and gives a screen-reader user nothing.
- **Labels are not coloured by series.** Direct labels exist so you don't have to match a
  colour to a legend. A label wearing its series' colour defeats the point.
- **Every spec carries its rows inline**, because the accessible table view reads them from
  there. If a chart type stops doing that, its table silently disappears with no error.

**Current result: 14 out of 14 render correctly. Two real bugs were caught here** that no
unit test found.

---

## 5. Layer 4 — Is it actually readable?

A valid chart of the right type can still be unusable.

**A pie chart with 40 slices is a valid spec.** It is also completely useless — nobody can
match 40 legend entries to 40 slivers.

So we set ceilings and then **test that the ceilings actually fire**:

| Guard | Limit | Why that number |
|---|---|---|
| Colours on a bar or line | 8 | These place series next to each other, so similar hues are comparable |
| Colours on a scatter | 3 | Every point can end up beside every other, so any two hues must be separable |
| Slices on a pie | fires at 40 | Long past the point of readability |

The test builds a chart that deliberately breaks each limit and checks a warning came back.

> **This matters more than it sounds.** It is very easy to write a limit into the code and
> never check it works. A guard nobody tested is a guard you *believe* you have.

**Current result: 3 out of 3 guards fire when they should.**

---

## 6. So — is our testing enough?

**No.** Here is the honest version.

### What we have

| Layer | What it proves | Count |
|---|---|---|
| Python unit tests | Chart building logic, types, themes, labels, interaction | **155 tests** |
| Type accuracy | Right chart family for the question's shape | **14/14** |
| Spec validity | Valid against Vega-Lite's own schema | **10/10** |
| Render tests | Draws what we think it draws | **17/17** |
| Legibility guards | Ceilings actually fire | **3/3** |

> ### Update — 17 August 2026: gap 4 is closed, and it found four bugs
>
> Every case in the render set used to be well-formed: several rows, all
> populated, all positive. Real results are not. Adding awkward data found
> **four defects, all silent** — valid specs, `valid: True`, no warning:
>
> | What we fed it | What it drew | Now |
> |---|---|---|
> | A line with one point | An invisible zero-length path | Point marker, so the datum exists |
> | A pie with a negative value | An arc sweeping **backwards** | Refused, pointing at a bar chart |
> | A pie summing to zero | Two arcs of 0.00 radians — blank | Refused, with the reason |
> | A measure that is null everywhere | **Two full-height bars** | Nothing, plus a notice |
>
> The last is the one that matters. It did not look broken — it looked like an
> answer. Two large equal bars, standing in for a result that had no values in
> it at all. A blank panel gets retried; a confident wrong picture gets believed.
>
> Also fixed: a row with a null in a charted column used to vanish silently, so a
> category could disappear from a chart with nothing on screen saying it had ever
> been there. Those rows are now dropped explicitly and the drop is disclosed.
>
> `backend/tests/test_chart_edge_data.py` (15 tests) and three new cases in the
> render harness. **A third of that file is the counterweight** — negative bars,
> zero bars, identical values and single-row charts are all legitimate, and a
> guard that refused them would be worse than the bug it replaced.

That is genuinely strong for the failures it covers. **But here are seven ways a chart
could be bad while every single one of those tests passes.**

### What we cannot catch today

| # | The gap | A chart that would slip through |
|---|---|---|
| 1 | **Nobody checks it looks good.** We check type, validity, structure, crowding. We never check for *ugly*. | Category labels overlapping each other into mush |
| 2 | **We grade our own homework on chart type.** Those 14 "right answers" were written by us. | If our idea of the right chart is wrong, the test agrees with us and passes |
| 3 | **We never compare a picture.** We inspect drawing *instructions*, not pixels. | A bar drawn 1 pixel wide. Every assertion passes |
| 4 | ~~**Only 14 fixed examples are rendered.**~~ **Partly closed** — see the update above. Still no test for very long labels, or for a category column with hundreds of distinct values. | A 60-character category name squashing the plot area |
| 5 | **Nothing tests the chart inside the real app.** All of this runs headless. | The chart breaks when the panel is resized, or in dark mode |
| 6 | **Accessibility is barely tested.** We check label colour and the inline table. Nothing else. | Two series in colours a red-green colour-blind user cannot tell apart |
| 7 | **No human ever scored a chart.** | A chart everyone technically approves of and nobody finds useful |

Gaps **2** and **7** are the same problem wearing two hats: *there is no outside opinion
anywhere in this loop.* Every "correct answer" in our chart tests was written by the same
three people who wrote the code. That is the single biggest weakness, and it is not fixed
by writing more tests.

### The honest one-sentence summary

> **We can prove our charts are structurally correct, correctly typed, and not overcrowded.
> We cannot yet prove anyone finds them useful.**

---

## 7. What we would add, in order of value

Ranked by *how much it would tell us per hour of work*.

**1. Show real charts to five real people.** (Highest value by a wide margin.)
Closes gaps 2 and 7 at once. No amount of code does this. It is also the one open item on
the project's milestone checklist, so it pays twice.

**2. Snapshot the rendered SVG and diff it.**
We already render to SVG in `verify:specs` — we just throw it away. Saving it and comparing
against a stored copy would catch gap 3 (visual breakage) almost for free. When a diff
appears, a human looks once and either accepts the new picture or files a bug.

**3. ~~Add awkward data to the render set.~~ Done — 17 August.**
One row, all-null measures, partial nulls, negatives and zero totals are now in both the
Python tests and the render harness. It found four bugs on the first run. Still missing:
very long labels, and a category column with hundreds of distinct values.

**4. Automated contrast and colour-blindness checks.**
Run the rendered colours through a contrast-ratio check and a colour-blindness simulation.
There are libraries for both. Attacks gap 6.

**5. Component tests in a real browser.**
The biggest job on this list, and the one the project already names as its largest testing
hole. Attacks gap 5.

---

## 8. How to run all of it

```bash
# Layers 1, 2 and 4 — type accuracy, spec validity, legibility guards
cd backend && uv run python -m bench.chart_quality

# The 140 chart unit tests
cd backend && uv run pytest tests/test_chart*.py tests/test_charts.py -q

# Layer 3 — regenerate the reference specs, then render them for real
cd backend && uv run python scripts/emit_reference_specs.py
cd frontend && npm run verify:specs
```

Results are written to `backend/bench/results/chart_quality.json`.

---

## 9. If someone asks about this in the evaluation

**"How do you know the charts are good?"**
> We don't test "good" as one thing, because it isn't one thing. We test four separate
> failures — wrong type, invalid spec, draws the wrong shape, too crowded to read — and
> report four numbers. Averaging them would hide exactly the failure we most want to see.

**"Isn't validating your own output a bit circular?"**
> For spec validity, no — we validate against Vega-Lite's *own published schema*, not our
> checks. That is what caught every boxplot spec being invalid while our own tests said
> they were fine. For chart *type*, yes, it is partly circular, and that is why five
> usability participants are the top item on our remaining work.

**"Your tests passed but you still shipped bugs."**
> Yes — that is the argument for measurement, not against tests. Tests check what you
> thought to check. The render layer exists precisely because the Python suite checks spec
> *structure*, which can never tell you a spec compiles, that the theme reached the marks,
> or that grouped bars grouped rather than silently stacked.

---

*Related: [`Docs/13`](13-Chart-Library-Expansion-Research.md) for the chart-type research,
[`Docs/24`](24-Performance-and-Evaluation.md) for the full measurement account.*
