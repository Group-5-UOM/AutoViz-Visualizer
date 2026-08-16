# 13 — Chart Library Expansion & Interactivity Research

Status: **implemented**. Every workstream below has landed; each section records
what was built and the constraints that shaped it.
Scope: making AutoViz charts interactive and visually rich, and widening the
chart library beyond the original six types.

**Jump to:** [§9 Supported chart types](#9-supported-chart-types) ·
[§10 Future work](#10-future-work) ·
[the verification harness](#the-renderer-verification-harness)

---

## 1. Ground truth — the baseline this work started from

> **Historical.** This section describes the state *before* the work below, kept
> because the rest of the document argues against it. For what is supported now,
> jump to **§9 Supported chart types**.

| Thing | Where | Value |
|---|---|---|
| Chart type allow-list | `backend/src/autoviz/schema/allowlists.py:21` | `bar, line, scatter, pie, area, histogram` |
| Plan-level literal | `backend/src/autoviz/schema/analysis_plan.py:23` | same six, as a `Literal` |
| LLM-facing grammar | `backend/src/autoviz/schema/plan_guide.py:29` | same six, restated in prompt text |
| Mark mapping | `backend/src/autoviz/services/charts.py:15-22` | 6 types → 5 distinct Vega marks |
| Spec builder | `charts.py:181-187` | `$schema`, `data`, `mark`, `encoding` |
| Renderer | `frontend/src/components/canvas/ChartWidget.tsx:42-46` | `vega-embed`, `actions:false`, `renderer:'svg'`, `tooltip:true` |

A generated spec is, in full:

```json
{
  "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
  "data": { "values": [ ... ] },
  "mark": "bar",
  "encoding": { "x": {...}, "y": {...}, "color": {...} }
}
```

That is the entire surface. Concretely, **what we do not emit**:

- No `params` / `selection` → no zoom, no pan, no brush, no legend filtering, no hover highlight.
- No `tooltip` encoding → the only tooltip is `vega-embed`'s default, which dumps
  raw field names and unformatted values.
- No `config` → charts render in Vega's stock defaults (tableau10, 10px sans,
  default gridlines). Nothing ties them to the app's visual language.
- No `title`, no axis formatting, no number/date formatting.
- No `width` / `height` → the spec ignores the widget size the user drags
  (`ChartWidget.tsx` re-embeds on resize but the spec has no `"container"` sizing,
  so the chart does not actually reflow).
- No `sort` → a `ranking`-intent bar chart comes back in whatever order DuckDB
  returned. `recommend_chart_type` says "sorted bar chart over 'x'"
  (`charts.py:69`) but nothing sorts it. That rationale string is currently a lie.

So: six chart types is the *stated* limit, but the more binding limit is that
each of those six renders as a static, unthemed default.

---

## 2. Two defects found while surveying

**2.1 Vega-Lite major-version mismatch (real, will bite).** — **fixed**
`frontend/package.json` pins `vega-lite ^6.4.3` / `vega ^6.3.1` / `vega-embed ^7.1.0`,
but the backend stamps `$schema: .../vega-lite/v5.json` (`charts.py:182`) and
`export.py`'s HTML template loads `vega@5` + `vega-lite@5` + `vega-embed@6` from
CDN (`services/export.py:26-28`).

That means **the in-app chart and the exported HTML of the same chart run through
different major versions of the renderer**. Vega-Lite 6 changed the default
continuous size and moved to ESM-only, and Vega-Lite 6 is what actually parses
the spec in the app regardless of the `$schema` string. Exports drift from what
the user saw, and nothing complains — Vega-Lite does not validate the `$schema`
it is handed, which is why this stayed invisible.

**Resolution.** Standardised on the majors the frontend already installs and was
already rendering through: **Vega 6 / Vega-Lite 6 / vega-embed 7**. The versions
had been written out at five sites (`$schema` stamp, export template, agent
playground, frontend mock specs, `package.json`), which is why they drifted at
all; they now live once in `backend/src/autoviz/vega.py` and every other site
interpolates from there.

Checked before switching: Vega 6 is an ESM-only *package*, but all three still
publish a UMD browser bundle via their `jsdelivr` field, so the plain
`<script src>` tags in the export template and playground remain correct — no
ESM rewrite needed.

Guarded by `tests/test_vega_version.py`, which reads `frontend/package.json` and
fails if the npm pins and the backend constants disagree, and separately fails if
any backend source file hardcodes a Vega version again. Both guards were
mutation-tested — bumping the constant with the frontend unchanged does fail the
suite.

**2.2 The high-cardinality colour threshold is far too permissive.**
`charts.py:13` warns only above **10** distinct colour values. Ten categorical
hues cannot be told apart by anyone — the practical ceiling is 8, and for
all-pairs forms (scatter, bubble) where any two series can end up adjacent, the
safe cap is **3**. Today a 9-series scatter renders silently.

---

## 3. Headroom in Vega-Lite (research)

Vega-Lite's mark vocabulary ([mark docs](https://vega.github.io/vega-lite/docs/mark.html)):

- **Primitive:** `area`, `bar`, `circle`, `geoshape`, `line`, `point`, `rect`,
  `rule`, `square`, `text`, `tick`, `arc`
- **Composite** (macros over layered primitives): `boxplot`, `errorband`, `errorbar`

We use **5 of 12 primitives and 0 of 3 composites**. `rect` (heatmaps), `text`
(direct labels), `rule` (reference lines), `tick` (strip plots) and `boxplot` are
all sitting unused, and none of them need new execution capability — `rect`
heatmaps in particular are already executable today because `MAX_GROUP_BY = 2`
lets a plan produce exactly the 2-D grid a heatmap consumes.

Interactivity comes from `params` + `select`
([selection docs](https://vega.github.io/vega-lite/docs/selection.html)):

- **point** selections — click or `pointerover`, `nearest: true` uses Voronoi
  acceleration to snap to the closest mark.
- **interval** selections — drag; `translate` and `zoom` are **on by default**,
  so pan/zoom is close to free once a param exists.
- **`bind: "legend"`** — turns the legend into a series filter. One property.
- Selections drive conditional encodings (highlight), `filter` transforms
  (cross-filter between views), and scale domains (pan/zoom).

The important shape of this: **most of the interactivity win is spec properties
we are not writing, not new infrastructure.**

---

## 4. Workstream A — interactivity (highest value / lowest cost)

Ordered by payoff per unit of work. All of this is additive inside
`generate_chart`; none of it changes the plan grammar or the execution path.

| # | Feature | How | Cost | Status |
|---|---|---|---|---|
| A1 | Real tooltips | explicit `tooltip: [{field, type, format, title}]` per encoded channel | S | **done** |
| A2 | Legend filtering | `params: [{name, select:{type:"point", fields:[color]}, bind:"legend"}]` + conditional opacity | S | **done** |
| A3 | Hover highlight | point param on `pointerover` + `condition` on opacity | S | **done** |
| A4 | Pan / zoom | interval param bound to scales, on continuous axes only | S | **done** |
| A5 | Responsive sizing | `"width": "container"`, `"height": "container"`; drop the re-embed-on-resize dance | S | **done** |
| A6 | Brush-to-select | interval param on dense charts, read by the frontend to narrow the table view | M | **done** |
| A7 | Cross-filter across widgets | shared signal bus in `DashboardCanvas.tsx`; each widget publishes its selection, others apply it as a filter | L | deferred |

### A1–A5 as built

Implemented in `backend/src/autoviz/services/chart_interaction.py`, called from
`generate_chart` once the encoding is already valid. The layer is purely
additive — it never touches the positional encodings, so it cannot turn a valid
spec invalid.

Two Vega-Lite constraints drove the gating, and both are enforced rather than
assumed:

- **Conditional opacity is evaluated per datum.** On a `line`/`area` mark a
  per-point hover condition splits the line into differently-opaque segments, so
  hover dimming is restricted to discrete marks (`bar`, `scatter`, `pie`,
  `histogram`). A *series-level* legend condition is constant within a line and
  stays safe on every mark, so line charts still get legend filtering.
- **`bind: "scales"` needs continuous scales on both axes.** Pan/zoom attaches
  only when x is quantitative/temporal and y is quantitative, and never over a
  binned or aggregated channel — so a nominal-x bar chart and the binned
  histogram correctly get none.

Legend filtering and hover highlighting are mutually exclusive by construction:
both would otherwise drive `opacity` and fight. A colour channel earns the
legend filter; without one, discrete marks get hover instead.

Verified by compiling every chart-type permutation, plus two real pipeline
outputs (titanic grouped bar, seattle-weather trend line), through the actual
Vega-Lite 6 compiler and Vega 6 runtime parser — all compile with no warnings,
all render marks headless, and the emitted signals match the gating table above.

A5 also required fixing the two render sites so the container actually has a
size: `.chart-widget-body` was centring rather than stretching its child, and
`export.py`'s HTML template gave `#chart` no height at all (`height: "container"`
would have resolved to zero pixels there). `ChartWidget.tsx` no longer re-embeds
on resize, which also stops a drag-resize from discarding the view's interaction
state mid-gesture.

### A6 as built — brush-to-select, not focus+context

Drag a region on a **scatter** or **histogram**: unselected marks dim, and the
widget's table view narrows to the selected rows with a count.

**Why those two types.** Both draw many undifferentiated marks, and the reader's
question there is "which rows are those?" rather than "show me a different
range". Everything else keeps what it had, for a stated reason:

- **Time series keep scale-bound zoom.** Panning a range is the natural gesture
  on a time axis, and a brush and a bound zoom both consume the drag.
- **Charts with a series keep legend filtering.** Both would drive `opacity`, and
  isolating a series is worth more on a multi-series chart. At most one param
  drives opacity anywhere: a condition list resolves first-match, so a second
  would be silently dead.
- **Histogram brushes x only.** Its y is a derived count that appears in no row,
  so brushing it would select on a value the table cannot index.

**Why not the focus+context overview strip** the original sketch proposed: it
needs `vconcat`, which cannot carry top-level container sizing — Vega-Lite warns
*"container only works for single views and layered views"* — so it would undo
A5 for exactly the dense charts it targets. It also largely duplicates what
`bind: "scales"` zoom already provides. Selecting a subset and *reading it back*
is the capability zoom does not cover, and it is the natural pairing for the
table view.

The frontend reads the brush signal off the embedded view. The extent arrives as
`{field: [lo, hi]}` keyed by encoded field name, so it indexes rows directly
(`lib/specData.ts`). The harness drives those signals the way a drag does and
asserts the selection dims some marks but not all.

A7 remains the ambitious one, and where the canvas starts to feel like a BI tool
rather than a wall of static images — but it still needs a real design pass: what
does a selection in widget A *mean* to widget B, when they are built from
different plans and different SQL? A6 deliberately does not answer that.

---

## 5. Workstream B — visual richness (a theme block) — **done**

Shipped as `backend/src/autoviz/services/chart_theme.py`, merged into every
spec's `config` by `generate_chart`. Existing config wins, so a host-supplied
spec that themes itself is not overridden.

**Where the theme is applied, and why there.** It is baked in on the *backend*
rather than passed at embed time, because AutoViz is MCP-first: a spec handed to
Claude Desktop or written into an exported HTML file has no frontend to theme it.
The cost is that a saved chart freezes its theme — acceptable, since a saved
chart is a saved render. This also settles how dark mode should arrive: as a
frontend override at embed time (`vegaEmbed(el, spec, {config: DARK})` merges
over the spec's own config), so no stored spec ever needs regenerating. That is
why no dark variant is built here — building one now would be an unused code
path, and the eventual one belongs on the other side of the wire.

**One non-obvious bug this surfaced.** `config.range.category` only feeds a
*colour scale*, and a colour scale only exists when the chart has a colour
encoding. Every single-series chart — plain bar, line, area, histogram, scatter —
therefore ignored the palette entirely and kept rendering in Vega's stock
tableau blue. Caught by inspecting rendered SVG rather than by reading the spec,
which is the argument for checking output and not just structure. Fixed with an
explicit `config.mark.color` set to slot 1; regression test in
`test_chart_theme.py`.

**Palette validation.** The eight categorical slots were re-validated against
*this app's* `#ffffff` chart surface, not the reference `#fcfcfb`: lightness
band, chroma floor, adjacent-pair CVD separation (worst ΔE 9.1, target ≥ 8) and
normal-vision floor (worst ΔE 19.6, floor ≥ 15) all pass. The slot ordering is
the CVD-safety mechanism, not decoration — reordering requires re-validating.

> **Contrast obligation — discharged for most types, see §6.1.** Three slots
> (aqua `#1baf7a` 2.82:1, yellow `#eda100` 2.17:1, magenta `#e87ba4` 2.69:1) sit
> below 3:1 contrast on white. This is a documented property of the palette and
> it carries a standing requirement: those series need a **visible label**, not
> colour alone. Tooltips and the legend are *not* sufficient relief — both
> require the reader to already be able to pick the mark out. Direct labels
> shipped in §6.1 and discharge it for bar, grouped bar, heatmap, line, area,
> pie and donut. **Still unmet for scatter and stacked bar** — see §6.1 for why
> and what would close it.

Also shipped: **ranking bars now sort descending**. `recommend_chart_type` has
always promised "sorted bar chart over 'x'" (`charts.py:69`) while nothing
sorted it. Intent is threaded from the plan into `chart_spec` by the orchestrator
— the same pattern `column_types` already uses — and the sort is scoped to a
discrete axis, since ordering a time axis by value destroys it.

One interaction between the two workstreams needed handling: an `opacity`
encoding overrides the mark's config default outright, so attaching a selection
condition to an **area** chart would have forced overlapping bands to full
opacity and occluded each other. `AREA_FULL_OPACITY` restates the 0.7
translucency in the condition's "selected" value.

**Not done here:** direct labels (needs the layered-spec refactor above) and
global axis number formatting. The latter was deliberately dropped — the obvious
choice, d3's SI format `~s`, renders 0.5 as "500m", which is worse than Vega's
adaptive default. Tooltips already carry precise values from A1.

**Verified** by compiling all eight chart shapes through Vega-Lite 6 and
inspecting the rendered SVG for palette hexes and the app font, plus a QA page
(`backend/scripts/chart_qa_page.py` → `backend/exports/_chart_qa.html`) that
renders six real pipeline outputs over the repo's own test data. Open it to
click through legend filtering, hover dimming, zoom and tooltips.

### The theme, for reference

Palette below is a validated categorical order (adjacent-pair CVD ΔE ≥ 8, normal-vision
Shape of it, as built (full version with rationale in `chart_theme.py`):

```python
THEME = {
    "background": "transparent",             # let the widget surface show through
    "font": "'DM Sans', system-ui, -apple-system, 'Segoe UI', sans-serif",
    "axis":   {...MUTED_INK labels, SECONDARY_INK titles, hairline grid...},
    "legend": {...SECONDARY_INK, circle symbols...},
    "view":   {"stroke": None},              # no default box around the plot
    "range":  {"category": CATEGORICAL, "heatmap": SEQUENTIAL_BLUE,
               "ramp": SEQUENTIAL_BLUE},
    "mark":   {"color": CATEGORICAL[0]},     # single-series default — see above
    "bar":    {"cornerRadiusEnd": 4},        # rounded data-end, square at baseline
    "line":   {"strokeWidth": 2},
    "point":  {"size": 64, "filled": True,   # surface ring keeps dense scatter
               "stroke": SURFACE, "strokeWidth": 1.5},   # points countable
    "arc":    {"stroke": SURFACE, "strokeWidth": 2},     # 2px gap between slices
}
```

Two items from the original sketch were dropped on contact with the code.
`config.axis.grid: True` would have *added* gridlines to nominal axes — Vega-Lite
already defaults to grid on continuous axes only, which is the correct behaviour.
And `arc.innerRadius: 60` (pie → donut) is an absolute pixel value, which breaks
at small widget sizes now that charts size from their container; donut belongs in
§6 as a proper chart type with a radius derived from the view, not in the theme.

The chrome (ink, gridlines, baselines) is taken from the app's own CSS custom
properties in `index.css` rather than from the palette reference, so charts read
as native rather than as embedded images. `'DM Sans'` leads the font stack
because the app loads it; the system fallbacks cover exported HTML and MCP
consumers, where that webfont is absent.

---

## 6. Workstream C — new chart types

Tiered by what each actually costs. Adding a type means touching four places:
`allowlists.CHART_TYPES`, the `ChartType` literal, the `plan_guide` prompt text,
and `charts.py` (`_VEGA_MARK` + a `generate_chart` branch + a
`recommend_chart_type` rule).

### Tier 1 — new mark, no new plan capability, no new encoding channel — **done**

| Type | Mark | Why it earned a slot |
|---|---|---|
| **heatmap** | `rect` | Two categoricals + a measure. `MAX_GROUP_BY = 2` already produced exactly this shape, and it had *no good chart* — it fell through to a bar with a colour channel. |
| **boxplot** | `boxplot` (composite) | Distribution across groups. `intent == "distribution"` with a categorical degraded to a bar of counts, which answers a different question. |
| **grouped bar** | `bar` + `xOffset` | Compare series within a category. |
| **donut** | `arc` + `innerRadius` | The centre hole removes the wedge-area comparison that makes pies hard to read. Now the recommender's default for `composition`; `pie` stays available by name. |
| ~~stacked bar~~ | — | Not added: a plain `bar` with a colour channel **already stacks** in Vega-Lite. Adding a second name for existing behaviour would have been redundant grammar. Documented in `plan_guide.py` instead — bar for part-to-whole, grouped_bar to compare series. |
| **horizontal bar** | `bar`, axes swapped | Still open. Not a new type — an orientation rule when category labels are long or numerous. |

**Four Vega-Lite constraints found by probing before writing any of this**, each
of which would have been a silent or late failure:

1. **Selection params throw on composite marks.** A param over a `boxplot`
   fails to compile with `Unrecognized signal name`. The whole interaction layer
   is therefore skipped for composite marks; the mark's own `tooltip: true`
   surfaces the quartiles it computes instead.
2. **A heatmap's colour is the measure, not a series.** Its legend is a
   continuous gradient with nothing discrete to click, so legend binding is
   meaningless — it falls through to hover. `build_params` now requires a
   non-quantitative colour before binding a legend.
3. **`innerRadius` as a literal pixel count inverts at small sizes**, now that
   charts size from their container. Donut uses
   `{"expr": "min(width, height) / 5"}`, verified to render a real hole.
4. **`config.range.heatmap` does drive the rect colour scale** — the Vega scale
   references the named range, so the theme's blue ramp applies without a
   per-spec `scale.range`.

**Recommender changes** (deterministic, no LLM involvement — the asymmetry §7
argues for):

- `composition` → **donut** instead of pie.
- `distribution` / `relationship` with ≥ 2 categoricals → **heatmap**.
- `comparison` with ≥ 2 categoricals → **grouped_bar** instead of a bar whose
  colour channel silently stacked it. A single categorical still gives a plain bar.
- **boxplot is deliberately not auto-recommended.** `recommend_chart_type` sees
  only `[{name, type}]` and cannot tell raw rows from a pre-aggregated result —
  and a boxplot over one value per group is degenerate. It has to be asked for.

**Per-type plan validation** was added alongside, since widening the grammar
without it just moves the failure later: heatmap requires a numeric colour,
grouped_bar requires a colour, and boxplot is rejected outright over an
aggregating plan with a message that says to drop the aggregations.

**Colour caps (§2.2) tightened** as part of this: `HIGH_CARDINALITY_COLOR = 10`
is replaced by `MAX_SERIES_ADJACENT = 8` for bars/lines/stacks and
`MAX_SERIES_ALL_PAIRS = 3` for scatter, where any two series can land adjacent.

### 6.1 Layered specs and direct labels — **done**

A generated spec is now **layered** (`{layer: [data, labels]}`) whenever the chart
carries direct labels, and stays a unit spec otherwise. `charts.primary_layer()`
is the accessor for the data mark and encoding; anything reading a generated
spec's encoding should go through it rather than assuming a top-level `mark`.

**What gets labelled, and what deliberately does not** (`chart_labels.py`):

| Type | Label | Ceiling |
|---|---|---|
| bar (single series) | value above each bar | 15 bars |
| grouped_bar | value above each bar, carrying the same `xOffset` | 24 bars |
| heatmap | value in each cell, flipped to white past the ramp midpoint | 60 cells |
| line / area (with series) | series name beside its own last point | 4 series |
| pie / donut | category beside its own slice | 6 slices |
| scatter | — one label per point is unreadable at any useful point count |
| histogram | — bins are counts; the y axis already says what a label would |
| boxplot | — composite mark; its own tooltip carries the quartiles |
| bar + colour (stacked) | — labels inside stacked segments collide at realistic sizes |

Labels wear **secondary ink, never the series colour**. A label is identified by
where it sits — at the end of its own line, inside its own cell — and tinting it
by series would re-introduce exactly the colour-alone dependency the labels exist
to remove. Heatmap is the one exception: its label sits on a filled cell and
flips to white over the dark end of the ramp to stay legible at all.

**The Vega-Lite constraint that shaped this.** Selection params must be declared
on the **data layer**, never at the top level of a layered spec: Vega-Lite pushes
a top-level param down into every child unit, instantiating its signal more than
once, and the spec fails to parse with `Duplicate signal name` — *even when only
one layer references it*. A sibling layer can still refer to the param by name,
which is what lets labels dim along with their series under a legend filter.
Without that, filtering to one series would dim the other's marks and leave its
labels floating. This was found by the verification harness, not by review.

**`export.py` now accepts `layer` as well as `mark`** as a renderable top level.

**The types no label can cover** — scatter (a label per point is unreadable) and
stacked bar (labels collide inside segments) — are closed by the table view
below instead.

### 6.2 Table view — **done**

A toggle in the widget header swaps the chart for its result rows as a table.
This is the accessibility counterpart to the chart, not a debug view: it is what
discharges the §5 contrast obligation for scatter and stacked bar, and the
data-viz method wants a table view regardless as part of its accessibility pass.

**No backend change.** The pipeline already inlines the result table as
`data.values`, so the table reads its rows straight off the spec the widget was
handed (`lib/specData.ts`). Numeric columns are right-aligned with tabular
figures, and only when the column is numeric *throughout*, so a mixed column
keeps its text treatment. Rows are capped at 500 with a visible count — the
diamonds histogram alone carries 5,000, and that much DOM janks the canvas.

The harness asserts every generated spec carries its rows inline. Without that a
chart type could quietly stop doing so and take its accessible counterpart with
it, with no error anywhere.

With A6, brushing a chart narrows this table to the selection.

### The renderer verification harness

Structural tests cannot tell you a spec compiles, that the theme reached the
marks, or that grouped bars grouped rather than silently stacked — all
one-property mistakes with no structural symptom, and two of them
(§5's tableau-blue bug, constraint 1 above) actually happened. So that checking
is now a repeatable harness rather than ad-hoc:

```
python backend/scripts/emit_reference_specs.py   # one spec per chart type
npm run verify:specs                              # compile, render, assert geometry
```

It renders each spec through the real Vega-Lite compiler and Vega runtime and
asserts against the **scenegraph**: grouped bars occupy a fraction of the band
and all sit on the baseline, stacked bars do not; donut has a non-zero inner
radius and pie does not; heatmap cells land on the blue ramp and reach its
lightest step; direct labels actually reach the canvas and wear ink rather than a
series hue; nothing anywhere renders a tableau10 colour.

Label checks read only text with scenegraph `role === 'mark'`. An earlier version
compared against *all* rendered text and silently passed a chart whose data
labels had been deleted — the legend was supplying the same strings. Worth
recording, because it is the failure mode of this whole approach: a check that
reads the wrong part of the output looks exactly like a passing check.

Mutation-tested in two rounds, eight injected regressions, each producing a
specific correct failure — deleting `xOffset`, flattening the donut, dropping
`config.mark`, removing the heatmap ramp, deleting slice labels, deleting cell
labels, pointing series labels at the wrong field, and tinting labels with a
series hue.

### Tier 2 — needs a new encoding channel on `ChartSpec`

`ChartSpec` (`analysis_plan.py:94`) currently carries `type, x, y, color`. These
need one more field each, which widens the validated grammar:

| Type | New channel | Notes |
|---|---|---|
| **bubble** | `size` | Scatter + magnitude. Cap series at 3 (all-pairs form). |
| **strip / tick plot** | — (uses `tick`) | Small-n distribution where a boxplot over-summarises. |
| **small multiples** | `facet` (`row`/`column`) | The principled answer to "too many series." Bigger lift: changes the top-level spec shape from unit to faceted, which `export.py`'s `"mark" in spec` validity check (`export.py:47`) would reject as-is. |

### Tier 3 — explicitly not now

- **Choropleth / `geoshape`** — needs TopoJSON assets, a region-name join, and a
  projection choice. Large, self-contained, and not on the critical path.
- **Dual-axis** — do not build. Two y-scales on one frame is the single most
  common chart lie; two charts or an indexed common base is the correct answer.
- **Sankey / chord / network** — not expressible in Vega-Lite; would need raw
  Vega, i.e. abandoning the closed-grammar guarantee. Out of scope.

---

## 7. Risk this creates, and the mitigation we already own

`Docs/05-Research-Findings-for-AutoViz.md:50` records that **3+ visual-channel
charts (stacked bar, grouped line, grouped scatter) are measurably harder for
LLMs** than 2-channel equivalents, and that quality degrades further with query
hardness. Tier 1 and Tier 2 are *mostly 3-channel charts*. Widening
`CHART_TYPES` therefore widens the model's decision space precisely where it is
weakest.

The mitigation is already the project's stated architecture (same doc, lines
35–36): closed grammar, structural validation, retry-on-error. Applied here that
means a deliberate asymmetry:

> **Expand the deterministic recommender and the renderer aggressively.
> Expand what the LLM may explicitly name conservatively.**

In practice: teach `recommend_chart_type` to *choose* heatmap and boxplot from
the result schema (deterministic, no LLM involvement), and only add those names
to `plan_guide.py` once the recommender's choices have proven out. `generate_chart`
already refuses out-of-allow-list types (`charts.py:117`) and already validates
channels against real columns (`charts.py:127`) — the guard rails hold.

---

## 8. Suggested sequencing

1. ~~**A1–A5 interactivity** (§4) — tooltips, legend filter, hover, zoom, responsive.~~ **done**
2. ~~**Theme block** (§5) — one dict, transforms every existing chart.~~ **done**
3. ~~**Fix the version mismatch** (§2.1).~~ **done**
4. ~~**Tier 1 types** (§6): heatmap, boxplot, grouped_bar, donut.~~ **done**
5. ~~Tighten the colour cap (§2.2).~~ **done**
6. ~~**Layered specs + direct labels** (§6.1).~~ **done** — `export.py` now
   accepts `layer`, so A6 brush-filter is unblocked too.
7. ~~**Table view** (§6.2).~~ **done** — closes the §5 contrast obligation.
8. ~~**A6 brush-to-select**, linked to the table view.~~ **done**

Everything scoped in this document has landed. What is left is genuinely new
work, in rough value order:

- **Look at the charts.** Nobody has. `backend/exports/_chart_qa.html` renders
  nine real pipeline outputs and has never been opened. Geometry, colour, labels
  and interaction signals are all verified off the scenegraph, but layout is not:
  label collisions at real widget sizes, the donut's radius at small widths, and
  grouped-bar label crowding are exactly what that verification cannot see.
- **A7 cross-widget cross-filter** — the big one; needs the design pass above.
- **Horizontal bar** orientation for long category labels (§6 Tier 1).
- **Tier 2** — the `size` channel for bubble charts, `facet` for small multiples.
- **Dark mode** — as a frontend embed-time config override (§5), not a second
  baked theme.

---

## 9. Supported chart types

Ten types. The allow-list is `schema/allowlists.py:CHART_TYPES`, mirrored by the
`ChartType` literal in `schema/analysis_plan.py` and described to the model in
`schema/plan_guide.py`. Adding one means touching all three plus `charts.py`.

### Grammar — what each type needs

| Type | Vega mark | Required channels | What `color` means | Auto-picked for |
|---|---|---|---|---|
| `bar` | `bar` | x, y | series (**stacks**) | ranking (sorted desc), distribution or comparison over one category |
| `grouped_bar` | `bar` + `xOffset` | x, y, **color** | series (side by side) | comparison over two categories |
| `line` | `line` | x, y | series | trend; any intent over a datetime |
| `area` | `area` | x, y | series | — explicit only |
| `scatter` | `point` | x, y | series | relationship over two numerics; numeric-only fallback |
| `histogram` | `bar` (binned) | **x only** | — | distribution over a numeric with no category |
| `pie` | `arc` | x = category, y = measure | the category | — explicit only (donut is preferred) |
| `donut` | `arc` + `innerRadius` | x = category, y = measure | the category | composition |
| `heatmap` | `rect` | x, y, **color** | **the measure** (quantitative) | distribution or relationship over two categories |
| `boxplot` | `boxplot` (composite) | x = category, y = numeric | — | — explicit only |

Three types are **explicit only** — the recommender never picks them:

- **`pie`** — `donut` is strictly more readable at the same cost, so composition
  resolves there. `pie` stays available by name.
- **`area`** — a line answers trend more precisely; area is a stylistic choice
  the caller makes.
- **`boxplot`** — `recommend_chart_type` sees only `[{name, type}]` and cannot
  tell raw rows from a pre-aggregated result. A box over one value per group is
  degenerate, so it has to be asked for. Plan validation rejects it over an
  aggregating plan.

### Behaviour — what each type does once rendered

| Type | Interaction | Direct labels | Ceiling |
|---|---|---|---|
| `bar` | hover-dim, or legend filter with a series | values above bars (single series only) | 15 bars |
| `grouped_bar` | legend filter | values above bars, offset with their bar | 24 bars |
| `line` | scale-bound zoom on a continuous x; legend filter with a series | series name at its own line end (needs a series) | 4 series |
| `area` | scale-bound zoom on a continuous x; legend filter with a series | series name at its own line end (needs a series) | 4 series |
| `scatter` | **brush** to select; with a series instead, legend filter **and** zoom | — per-point labels are unreadable | — |
| `histogram` | **brush** to select (x only) | — the y axis already says what a label would | — |
| `pie` / `donut` | legend filter | category beside its own slice | 6 slices |
| `heatmap` | hover-dim (its legend is a gradient, nothing to click) | value in each cell, white over the dark end | 60 cells |
| `boxplot` | none — Vega-Lite rejects params on composite marks | — the mark's own tooltip carries the quartiles | — |

Every type gets a formatted per-channel tooltip (boxplot via its own composite
mark), the theme, container sizing, and its rows inline for the table view. Past
a ceiling, labels are dropped rather than drawn on top of each other.

Two consequences of "at most one param drives opacity" are easy to miss:

- **A colour channel suppresses the brush**, and because the brush is what was
  blocking zoom, a *scatter with a series* ends up with legend filter **and**
  scale-bound zoom — a different gesture set from a plain scatter.
- **A stacked bar (`bar` + colour) carries no labels.** Labels inside stacked
  segments collide, so the table view is its relief instead.

**Colour ceilings** (`allowlists.py`): 8 series for adjacent forms (bars, lines,
stacks), **3** for all-pairs forms (scatter) where any two series can land beside
each other. Pie and donut warn past 6 categories. These emit warnings, not
errors — the chart still renders.

---

## 10. Future work

Everything scoped in this document has landed. What follows is new work.

**Look at the charts first.** `backend/scripts/chart_qa_page.py` renders nine
real pipeline outputs to `backend/exports/_chart_qa.html`, and it has never been
opened. Geometry, colour, labels and interaction signals are all verified off the
scenegraph, but *layout is not*: label collisions at real widget sizes, the
donut's radius at small widths, and grouped-bar label crowding are exactly what
scenegraph assertions cannot see. Nothing below is worth starting before this.

| Item | Shape | Why it is worth doing |
|---|---|---|
| **A7 cross-widget cross-filter** | shared signal bus in `DashboardCanvas.tsx` | The one that makes the canvas a BI tool rather than a wall of images. Blocked on a design question, not on code: what does a selection in widget A *mean* to widget B, when they are built from different plans and different SQL? A6 deliberately does not answer that. |
| **Dark mode** | frontend `config` override at embed time | `vegaEmbed(el, spec, {config: DARK})` merges over the spec's own config, so no stored spec is regenerated. The theme is baked in on the backend precisely so this stays possible — see §5. The app is single-theme today (`index.css` has one `:root`). |
| **Horizontal bar** | orientation rule, not a new type | Swap the axes when category labels are long or numerous. Cheap legibility win; the current vertical bar truncates long labels. |
| **Tier 2: `size` channel** | new channel on `ChartSpec` | Bubble charts. Cap series at 3 — it is an all-pairs form. |
| **Tier 2: `facet`** | `row`/`column` channels | Small multiples: the principled answer to "too many series" that does not involve generating more hues. Changes the top-level spec shape again, the way layering did. |
| **Table view: sort & CSV** | frontend | The table is currently read-only and unsorted. Sorting by column and copying out are the obvious next asks once people use it. |

### Known limits, recorded rather than fixed

- **Saved charts freeze their theme.** The theme is baked into the stored spec
  (§5). A re-theme does not reach charts already saved. Acceptable — a saved
  chart is a saved *render* — but it is a real property, not an oversight.
- **The table view caps at 500 rows.** Enough for the accessibility purpose; not
  a data browser. A large result is truncated with a visible count.
- **No frontend test runner.** `tsc`, `oxlint` and the spec harness cover a lot,
  but `DataTable`, the brush listener and the widget toggle have no unit tests
  because there is nothing to run them with. Adding Vitest would close this.
- **`Docs/` is gitignored** (`.gitignore:1`), so this document and its siblings
  live outside version control.

---

## Sources

- [Vega-Lite — Mark types](https://vega.github.io/vega-lite/docs/mark.html)
- [Vega-Lite — Selection parameters](https://vega.github.io/vega-lite/docs/selection.html)
- [Vega-Lite — Box plot](https://vega.github.io/vega-lite/docs/boxplot.html)
- [Vega-Lite — Config](https://vega.github.io/vega-lite/docs/config.html)
- [Vega-Lite 6.0.0 release notes](https://github.com/vega/vega-lite/releases/tag/v6.0.0)
- `Docs/05-Research-Findings-for-AutoViz.md` (VisEval / DynaVis findings, internal)
