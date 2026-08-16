# 15 — In-Place Chart Editing & Arbitrary Colours

How a chart that already exists gets changed, as **implemented** in `backend/` and `frontend/` on
branch `feat/cleaning-disclosure` (commit `9e44b46`). This is FR-15 — *"user can apply basic chart
edits (title, labels, legend, colors, presentation)"* — and the Week-4 roadmap line *"chart
editing; save/reopen"*.

Three problems that look separate and are not:

1. **A refinement produced a second chart.** "Make it a line chart" left the bar chart where it
   was and put a line chart beside it.
2. **A card had no edit affordance**, and the theme's eight slots were the only colours a chart
   could have.
3. **The persistence layer assumed specs never change**, so both fixes would have saved nothing.

And one found while fixing them: with several charts on the canvas, a refinement was grounded in
the **wrong chart's plan** — §2.3.

Every behaviour below is enforced in code and covered by tests. Suite: **515 → 548 passing**.

---

## 1. The problem each piece solves

### 1.1 A refinement had no identity to carry

The graph already understood refinements. `agent/routing.py::route_after_classify` walked
`history` backwards for the most recent plan and handed it to the worker as `prior_plan`, so the
planner produced *a modified version of that chart* rather than a fresh analysis. That half worked.

What came back did not. `ChartResult` carried `task`, `status`, `plan`, `vega_lite_spec` — and no
way to say **which chart this is**. On the canvas, `widgetsFromAgent` therefore did the only thing
it could:

```ts
return charts.filter((chart) => chart.vega_lite_spec).map((chart, i) => ({
  id: makeId(),          // always a new id
  ...placement(existingCount + i),   // always a new slot
}));
```

The user asked to change one chart and got two. The information needed to do better — *this result
supersedes that one* — existed in the graph and was thrown away at the boundary.

### 1.2 Colour had one source and no override path

`services/chart_theme.py` is deliberately not configurable: eight categorical slots in a fixed
order, validated offline for CVD separation (worst ΔE 9.1 against a target of 8) and for the
normal-vision floor (worst ΔE 19.6 against a floor of 15). The slot *ordering* is the safety
mechanism.

That is right for a chart nobody has opinions about, and wrong for a user with a brand colour.
`ChartSpec` looks like it has a colour field:

```python
class ChartSpec(_StrictModel):
    type: ChartType
    x: str
    y: str | None = None
    color: str | None = None    # a COLUMN NAME, not a colour
```

`color` names the column that drives the colour channel. `_StrictModel` forbids extra fields, so
there was nowhere to put `#7d3cff` even if you wanted to.

### 1.3 Autosave was correct only while nothing edited a spec

`persistSignature` decides "the canvas differs from what the server has". It hashed six fields per
widget and documented why the spec was not among them:

> Widget `id` stands in for the spec: `widgetsFromAgent` mints a fresh id per chart and never
> rewrites an existing one's spec, so equal ids mean equal specs.

A sound argument from a true premise — and both features above falsify the premise. `ensureCharts`
had the matching assumption (`if (widget.backendChartId) continue;`), and `routes/charts.py` had no
`PUT`. An edited chart would have marked nothing dirty, uploaded nothing, and reverted on reload.

---

## 2. Chart identity — the agent half

### 2.1 One field, inherited rather than minted

`ChartResult` gains `chart_id`. `finalize_worker` decides where it comes from:

```python
"chart_id": state.get("refines_chart_id") or f"ch_{uuid.uuid4().hex[:12]}",
```

A refinement **inherits** the id of the chart it refined; everything else mints a new one. There is
no separate `replaces` field — sameness of id *is* the claim.

### 2.2 Routing carries an id alongside a plan it already carried

`compose_response` writes a richer history entry pairing each plan with the chart it produced:

```python
entry = {
    "request": state["user_request"],
    "plans":  [c["plan"] for c in produced],   # kept in step, see below
    "charts": produced,                        # [{chart_id, plan}, ...]
}
```

and `route_after_classify` reads the id from the same entry it was already reading the plan from:

```python
if state.get("intent") == "refinement":
    for entry in reversed(state.get("history", [])):
        if entry.get("plans"):
            prior_plan = entry["plans"][-1]
            last = (entry.get("charts") or [{}])[-1]
            if len(tasks) == 1:
                refines_chart_id = last.get("chart_id")
            break
```

Two constraints are deliberate:

- **`plans` is kept alongside `charts`.** Threads outlive a deploy under the Postgres checkpointer,
  so an entry written before this change has `plans` and no `charts`. Reading falls back to
  `[{}]`, the id comes out `None`, and that thread keeps the old append-only behaviour instead of
  crashing.
- **`len(tasks) == 1`.** A refinement that fans out to several charts has no single thing to
  supersede — the planner read it as new analysis. It appends.

This adds **no new heuristic**. "A refinement refines the most recent chart" was already the
graph's assumption, encoded in the `prior_plan` walk; this carries an identity along the path that
assumption already travelled.

### 2.3 Pointing at a chart beats guessing at one

The guess above is only right while the canvas holds one chart. With four, refining the second
picked up the *fourth* chart's id — and, worse, the fourth chart's **plan**, because
`prior_plan = entry["plans"][-1]` reads the same way. The planner was then asked to modify a chart
the user was not looking at. That was a correctness bug, not a cosmetic one.

So a caller can name the chart: `POST /agent/analyze` and the MCP `analyze` tool both accept a
`chart_id`, taken from the `chart_id` on a previous response. `route_after_classify` treats it as
authoritative:

```python
targeted = _chart_in_history(state.get("history", []), target) if target else None
if targeted is not None:
    prior_plan = targeted.get("plan")          # THAT chart's plan, not the newest
    if len(tasks) == 1:
        refines_chart_id = target
elif state.get("intent") == "refinement":
    ...most-recent fallback...
```

Three properties, each tested:

- **The classifier does not get a vote.** Pointing at a chart *is* the statement of intent, so an
  explicit target refines it even when the words were read as fresh analysis.
- **`_chart_in_history` searches every entry**, not just the newest — a chart worth pointing at may
  be several requests old, which is the whole reason for pointing at it.
- **An unknown id falls back rather than failing.** A chart from a dashboard reopened without its
  conversation is not in this thread's history; that is a reason to append, not to error.
- **The target is per-run state**, reset on every `run()`. Carrying it forward would silently
  overwrite that chart with the answer to an unrelated question.

On the canvas the attachment is held in `useDashboard` — the gesture happens on a card, and sending
is what consumes it. Two ways to attach, one mechanism: an `@` button on the card header, and `@`
in the composer opening a picker of the charts on the canvas. The chip above the composer shows
what is attached, the placeholder changes to `Change "Fare by class"…`, and the message keeps a
`referencedTitle` so the transcript still says which chart was being edited after the attachment is
gone. Deleting a widget clears an attachment pointing at it.

### 2.4 The canvas half

`widgetsFromAgent` is replaced by `applyAgentCharts(existing, charts, existingCount, makeId)`,
which returns `{widgets, focusId, placed}`. For each result:

| Condition | Outcome |
|---|---|
| `chart_id` matches a widget's `agentChartId` | Update that widget in place |
| No match (new chart, or the card was deleted) | Place a new widget |
| No `vega_lite_spec` (plan failed before charting) | Skipped — the error reaches the chat answer |

A replacement swaps `vegaLiteSpec`, `title` and `explanation`, and **keeps** the widget's `id`,
position, size, `backendChartId` and `style`. A card the user deleted matches nothing and
reappends, which is the correct way to fail: the chart the user asked for still arrives.

`focusId` points at the first chart produced whether it landed on an existing card or a new one, so
the chat reply's "view on canvas" link goes to what actually changed.

---

## 3. Styling — `schema/chart_style.py` + `services/chart_style.py`

### 3.1 Why a separate block rather than fields on `ChartSpec`

`ChartSpec` is part of the analysis plan: a description of *what to compute*, written by the
planner and executed as SQL. Presentation is neither planned nor executed. Folding a colour into
it would mean every style tweak re-ran the query.

So `ChartStyle` travels beside the spec and is applied to the **finished Vega-Lite output**. A
style edit cannot change a number, because it never touches the path that produces numbers.

### 3.2 The grammar

| Field | Effect |
|---|---|
| `title` | Chart title text |
| `x_title`, `y_title` | Axis titles |
| `legend` | `false` hides the colour legend |
| `mark_color` | Single-series mark colour |
| `series_colors` | `{series value: hex}` |
| `color_scheme` | Ordered hex list replacing the categorical range |

Colours are `#rgb` or `#rrggbb`, enforced by pattern. Vega-Lite would also accept named CSS
colours, but a free-text colour field is exactly where a planner hallucinates something
unrenderable — a closed syntax fails loudly instead of silently drawing nothing.

### 3.3 Cumulative, not incremental — and why that matters

The block is the widget's **whole styling state**, not a diff. An edit merges into it and the
entire block is re-applied to the chart. This is what makes repeated edits converge:

```
apply(apply(spec, block), block) == apply(spec, block)
```

Every field is nullable because `None` is the only way to express *revert this to the theme*; an
absent field cannot say that. So every branch in `apply` has an `else` that actively restores the
default rather than leaving the previous override standing.

### 3.4 Two things `apply` must not break

**The subtitle is load-bearing.** `generate_chart` parks the log-axis and skew disclosures in
`title.subtitle` precisely so they survive into a saved dashboard, where no chat exists to carry
them (Doc 14 §2.4). Setting a user title writes `title.text` and leaves `subtitle` alone.

**Reverting a colour deletes only `domain` and `range`.** `services/skew.py` writes a log `scale`
onto the very same colour encoding for a skewed heatmap. Clearing the whole `scale` object to reset
a colour would quietly un-disclose a log axis — turning a presentation edit into a correctness bug.

A third, smaller one: `mark_color` is set on the data layer's own mark definition, not
`config.mark.color`, which would also repaint the direct-label layer drawn above it.

### 3.5 Overrides land above the theme for free

`chart_theme.attach` merges with `config.setdefault`, so anything already set wins. The style layer
did not have to fight the theme or be inserted before it — it only had to write somewhere the theme
had already yielded.

---

## 4. Two authoring surfaces, one block

`POST /charts/style` is the only way styling is applied:

```
{vega_lite_spec, style?, request?} -> {vega_lite_spec, style, valid, warnings}
```

| Surface | Sends | Reaches the planner? |
|---|---|---|
| Style panel (swatches, hex field, toggles) | `style` | **No** |
| Card edit bar ("make the bars orange") | `style` + `request` | Yes |

The natural-language path is *only a second way to author the same block*: the planner returns a
patch, it merges over the current style, and both paths end at the same `apply`. A test asserts the
two produce byte-identical specs.

This split matches what each is good for. "Make it orange" is a fine way to say the easy 80%;
`#7d3cff` is not. Typing a hex into a chat box is a bad way to pick a colour, and a colour picker
is a bad way to say "drop the legend and retitle this".

The route is authenticated (`Depends(get_current_user)`), unlike the other stateless chart routes,
because one of its two paths spends tokens.

### 4.1 A patch outside the grammar renders nothing

The planner's output is validated against `ChartStyle` before it is applied. A hallucinated field
(`drop_outliers`) or a colour that is not a colour (`"burnt sienna"`) fails validation, and the
response is a refusal with a readable sentence:

> I can only change how this chart looks — try naming a colour, a title, an axis label, or the
> legend.

The chart on screen is left exactly as it was. Partial application is never possible, because
`apply` works on a deep copy and the copy is discarded on any failure.

---

## 5. Persistence

| Change | File | Why |
|---|---|---|
| `specVersion` counter on `ChartWidget` | `types/dashboard.ts` | Bumped on every in-place spec change |
| `syncedSpecVersion` | `types/dashboard.ts` | What the server holds; an outcome of saving, like `backendChartId` |
| `persistSignature` watches `specVersion` | `lib/dashboardSync.ts` | Style edits and refinements now mark the board dirty |
| `ensureCharts` gains an update branch | `lib/dashboardSync.ts` | POST when unsaved, PUT when versions differ, skip otherwise |
| `PUT /charts/{chart_id}` | `api/routes/charts.py` | Overwrite rather than append a second row |
| `repository.update_chart` | `storage/repository.py` | Partial overwrite via `exclude_unset` |

**The spec itself is not hashed.** `spec.data.values` holds every result row, and
`persistSignature` is recomputed on every render and every pointer frame of a drag. A counter
covers both mutation paths at constant cost.

**Versions are compared, not assumed.** Dragging a chart changes the layout signature but not
`specVersion`, so a drag writes the layout and does not re-upload any spec.

**The bump is counted off `prev` inside the state updater**, not off a widget read before the
request. Two colour clicks in quick succession would otherwise both compute version 1, and the
second edit would never be saved — the failure mode is silent, which is why it is worth the
awkwardness.

The block is stored in the existing `SavedChart.chart_spec` JSON column as `{"style": {...}}` — no
migration, since the canvas never populated that column. `BoardPage` restores it on load, so
reopening a board and opening the panel shows what was actually chosen rather than defaults over an
already-styled render.

---

## 6. Design decisions

### 6.1 No colour-accessibility checker was built

Considered and rejected for this batch. Any hex is accepted; nothing measures WCAG contrast or
colour-vision separation, and no warning is appended.

The theme's palette carries those guarantees for charts nobody has styled, which is the great
majority. A colour a user deliberately typed is theirs to choose, and the honest options were a
real check or none — a contrast-ratio number without CVD simulation would have looked like a
safety guarantee while missing the failure it is usually invoked for (two colours that separate
fine on white and collide under deuteranopia).

`chart_theme.py`'s standing note about the three low-contrast slots (aqua, yellow, magenta) is
unchanged and still outstanding.

**Follow-up if this is revisited:** the module would be ~180 lines of pure Python
(sRGB → linear → XYZ → LMS, Viénot/Brettel simulation, Lab, ΔE) with no new dependencies, and it
would also let the palette's ΔE 9.1 / 19.6 claims — computed offline, enforced by nothing — become
a regression test.

### 6.2 The raw Vega-Lite editor stays disabled

`vega-embed` is configured with `source: false, editor: false`. A JSON escape hatch would cover
everything the block does not, and would also let a user produce a spec no other surface can read
back — the panel could not show its state and the planner could not patch it. The closed grammar is
what keeps both authoring surfaces honest about the same object.

### 6.3 Style edits stay off the agent thread

A style edit does not go through `/agent/analyze`. It has no dataset, no plan, no thread and no
pause states, and putting it there would mean a colour change competing with clarification and
cleaning-choice interrupts for the same conversation. Targeting the selected card also removes the
"which chart did that mean?" problem entirely.

### 6.4 Strict MCP models caught a real contract break — again

Same trap as Doc 14 §4.4. `mcp/results.ChartResult` uses `extra="forbid"`, so adding `chart_id` to
the agent's result would have made `unwrap()` raise on the whole envelope.

Declaring it surfaced a **pre-existing bug**: `notices` had never been declared either. Any MCP
`analyze` run over cleaned data — the ordinary case, and the entire subject of Doc 14 — was failing
validation and taking the disclosure with it. Both fields are now declared, with a regression test
that exercises a completed run rather than only the pause paths the previous test covered.

---

## 7. Known limitations & follow-ups

- **Referencing needs a live conversation.** A board reopened from `DashboardsPanel` clears
  `threadId` and its widgets have no `agentChartId`, so its charts cannot be attached — there is no
  history for a request to refine against. The `@` button is hidden for them rather than offered
  and then failing. Making it work means rehydrating a thread from each chart's saved `chart_spec`.
- **A refinement's style block is kept but not re-applied.** The widget retains its `style`, and
  `series_colors` entries that no longer resolve are dropped by `apply` — but the new spec comes
  back unstyled from the agent. Re-posting it through `/charts/style` after a replacement is one
  call and is not yet wired.
- **No direct manipulation.** Clicking a bar or a legend swatch does nothing. The mechanism exists
  (`ChartWidget.tsx` already attaches a Vega signal listener for brushing); the popover would be
  the panel's own colour control.
- **The frontend has no test runner.** `applyAgentCharts` was verified with a 12-assertion `tsx`
  script during development, but nothing guards it in CI. Adding Vitest is the obvious next step
  and is the only untested logic of consequence in this change.
- **`color_scheme` has no UI.** It is in the grammar and reachable through natural language
  ("use these colours"), but the panel exposes per-series colours only.

---

## 8. File map

| File | Status | Role |
|---|---|---|
| `schema/chart_style.py` | **new** | `ChartStyle` grammar, hex validation, `merged_with` |
| `services/chart_style.py` | **new** | `apply`, `context_for` |
| `api/routes/charts.py` | modified | `POST /style`, `PUT /{chart_id}` |
| `api/deps.py` | modified | `get_planner` — the model without the graph around it |
| `llm/client.py` | modified | `style_patch` on the protocol + `GeminiPlanner`, `_STYLE_SYSTEM` |
| `storage/repository.py` | modified | `update_chart` |
| `agent/state.py` | modified | `ChartResult.chart_id`, `WorkerState.refines_chart_id` |
| `agent/nodes.py` | modified | Id minted/inherited in `finalize_worker`; `charts` in the history entry |
| `agent/routing.py` | modified | Explicit target beats the most-recent walk; `_chart_in_history` |
| `agent/service.py` | modified | `run(chart_id=...)`, reset per run |
| `api/schemas.py`, `routes/agent.py` | modified | `chart_id` on `AnalyzeRequest` |
| `mcp/server.py` | modified | `chart_id` on the `analyze` tool |
| `mcp/results.py` | modified | `chart_id` **and** `notices` on `ChartResult` |
| `frontend/lib/chartWidgets.ts` | modified | `applyAgentCharts` replaces `widgetsFromAgent` |
| `frontend/lib/dashboardSync.ts` | modified | `specVersion` in the signature; update branch in `ensureCharts` |
| `frontend/lib/chartStyle.ts` | **new** | `styleChart` client |
| `frontend/lib/specData.ts` | modified | `specSeries` — the series a picker can list |
| `frontend/hooks/useDashboard.ts` | modified | `editWidgetStyle`; attachment state; `applyResponse` folds instead of appending |
| `frontend/components/chat/ChatPanel.tsx` | modified | Attachment chip, `@` picker, transcript reference |
| `frontend/components/canvas/StylePanel.tsx` | **new** | Direct controls |
| `frontend/components/canvas/ChartWidget.tsx` | modified | Palette + wand buttons, inline edit bar |
| `frontend/types/dashboard.ts` | modified | `ChartStyle`, `agentChartId`, `specVersion`, `syncedSpecVersion` |

---

## 9. Test coverage

`tests/test_chart_style.py` — 14 tests. Hex syntax accepted and non-colours rejected; an unreadable
colour permitted on purpose; mark colour on the layer and not the config; subtitle preserved
through a title change and through clearing it; title dropped when nothing remains; axis titles set
and reverted; every series covered when only one is named; a `series_colors` key matching no
current series ignored; `color_scheme` setting `range` without a `domain`; a foreign log `scale`
surviving a colour revert; legend hidden and restored; idempotence plus the input left unmutated;
a layered spec targeting the data layer; `merged_with` keeping unmentioned fields and honouring an
explicit null; `context_for` naming the series.

`tests/test_api_chart_style.py` — 7 tests. Style-only applying with zero planner calls; a patch
merging over an existing block without discarding it; **both surfaces reaching a byte-identical
spec**; an out-of-grammar colour and an invented field both refused with the spec untouched; a
`PlannerError` returning structured content rather than a 500; auth required.

`tests/test_agent.py` — 8 added. A refinement keeping its `chart_id` across two chained
refinements; a new analysis minting a fresh one; a multi-task refinement replacing nothing; a
legacy history entry with `plans` and no `charts` still refining; and, for explicit targets, a
named chart refined instead of the newest **with the planner grounded in its plan**, a named chart
winning even when the classifier read the words as new analysis, an unknown id falling back rather
than failing, and a target not persisting into the next request.

`tests/test_api_agent.py` — 1 added. `chart_id` carried through the route, returning the same chart
and the right `prior_plan`.

`tests/test_api_dashboards.py` — 2 added. `PUT` overwriting in place with unsent fields untouched
and no second row; ownership 403 and unknown-id 404.

`tests/test_mcp_envelope.py` — 1 added. A completed run with `chart_id` and `notices` surviving
`AnalyzeOutput`.
