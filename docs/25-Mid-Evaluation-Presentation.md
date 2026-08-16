# 25 — Mid-Evaluation Presentation

**What to present, in what order, with which numbers, and who says it.**
Written 16 August 2026 against the working tree of that day. Every figure here is traceable to
[`Docs/21`](21-Project-Status.md) (delivery), [`Docs/24`](24-Performance-and-Evaluation.md)
(measured performance), or a command you can run in front of the panel.

---

## 0. The one-line answer to "how far along are you?"

> **The product works end to end and is measured. Nine of ten milestone criteria are met, the
> tenth needs five people in a room rather than more code, and as of today we can put numbers
> on speed, accuracy and chart quality — which found seven real defects that 759 passing tests
> had not, all now fixed.**

Do not open with a percentage. Open with the demo, then justify the percentage in §7 with the
table. A number asserted before evidence invites "how did you get that?"; a number offered after
evidence answers it.

---

## 1. Deck outline — 18 slides, ~20 minutes

Timings assume a 20-minute slot with 10 for questions. If you are cut to 12 minutes, drop
slides 6, 11, 14 and 16 — they are the "depth on request" ones.

| # | Slide | Owner | Min | The one thing it must land |
|---|---|---|---|---|
| 1 | Title, team, three tracks | Daishika | 0.5 | Who owns what |
| 2 | The problem, in one sentence | Daishika | 1 | Non-technical people cannot get a chart out of a CSV without learning a tool |
| 3 | **Live demo** | Chandrasiri | 4 | It actually works — see §2 for the script |
| 4 | Architecture in one diagram | Daishika | 1.5 | Five layers, and the invariant below |
| 5 | **The invariant: the LLM never computes** | Daishika | 1.5 | The single most defensible design decision in the project |
| 6 | The closed grammar, concretely | Daishika | 1 | *(droppable)* Why "injection is structurally impossible" is a claim, not a hope |
| 7 | What's built — the 10 criteria | Bulagala | 1.5 | 9/10, and why the 10th is honest |
| 8 | How we test | Bulagala | 1.5 | 789 backend + 25 frontend + 14 rendered specs + 39 NL prompts |
| 9 | **Performance: how it scales** | Bulagala | 1.5 | 1000× the data costs 2.3× the time |
| 10 | **Performance: the bottleneck we found and fixed** | Daishika | 2 | 26× faster for 0.2 MiB — the star slide |
| 11 | Where the time actually goes | Bulagala | 1 | *(droppable)* Connection > query below 100k rows |
| 12 | **NL accuracy on a frozen benchmark** | Daishika | 1.5 | And that "asked a question" is a *good* outcome |
| 13 | Chart quality, three ways | Chandrasiri | 1 | Type / spec / legibility scored separately |
| 14 | Bugs the measurement found | Daishika | 1.5 | *(droppable)* Seven real defects the tests missed |
| 15 | **Known limits, stated plainly** | Bulagala | 1 | Joins, scale ceiling, concurrency |
| 16 | Deployment | Bulagala | 1 | *(droppable)* CodeBuild → ECR → CodeDeploy → EC2 |
| 17 | **Where we are: ~80%** | Daishika | 1.5 | The table in §7, not a bare number |
| 18 | Next six weeks + risks | All | 1.5 | Usability cycle, e2e tests, the fine-tune |

---

## 2. The demo script (slide 3) — rehearse this exactly

Four minutes, one dataset, no improvisation. **Run it against the deployed build; keep
`docker-compose.local.yml` running on the presenter's laptop as the fallback and say so if you
switch.** Have the dataset already uploaded in a second tab in case ingestion is slow on the
day.

| Step | Do | Say | Proves |
|---|---|---|---|
| 1 | Upload `test-data/sales-retail/tips.csv` | "No configuration, no schema mapping." | FR-01…05 |
| 2 | Type *"What is the average tip by day of the week?"* | "Plain English. No chart type chosen, no columns named." | FR-06…08 |
| 3 | Point at the chart **and the provenance** | "It picked a bar chart, and it shows the SQL it ran. Every number traces to a query." | FR-10, FR-18 |
| 4 | Type *"Show me the best ones"* | "Deliberately vague — watch it refuse to guess." | The clarification gate |
| 5 | Answer the clarifying question | "It asked which measure. That is the product working, not failing." | Bounded agent |
| 6 | Edit the title, change the colour | "Presentation edits never touch the data." | FR-15 |
| 7 | Add to dashboard, drag, resize | — | FR-14 |
| 8 | Export → PDF | "Written by hand — no jsPDF, no new dependency." | FR-17 |
| 9 | Reload the page | "The dashboard came back. It autosaves." | FR-16 |

**Have ready but do not show unless asked:** the messy-CSV path
(`test-data/synthetic-quality/messy_sales.csv`) with the cleaning disclosure. It is the most
impressive thing in the product and the easiest to run long on.

**If the demo breaks:** do not debug on stage. Say *"we have this recorded, let me show that and
come back to it"* and move on. Record the demo the night before.

---

## 3. The technical story (slides 4–6)

### The invariant — slide 5, the most important one in the deck

> **The LLM only plans. It never computes a number, runs code, or touches the filesystem.**

Say it exactly like that, then show why it is enforceable rather than aspirational:

- The planner emits an `analysis_plan` — a Pydantic model whose allow-lists are `Literal` types,
  so **an invalid plan cannot be constructed**, rather than being caught by a validator someone
  might forget to call.
- That plan compiles to DuckDB SQL as a pure function over a closed grammar: identifiers
  quoted, literals bound as parameters. There is no path from model output to raw SQL.
- 11 filter ops, 7 aggregations, 15 derive functions, 10 chart types, 14 cleaning operations.
  Anything outside those lists is a validation failure, not a warning.

**This is the answer to the question every panel asks: "how do you know the AI isn't making the
numbers up?"** It cannot. It never sees the data values, only the schema and the profile.

Have this ready as the follow-up: *"the request text is also untrusted — cell contents and column
names are neutralised before they reach a prompt, because a CSV is an injection vector."*

---

## 4. How we test (slide 8)

Present it as a pyramid with real counts, and be explicit about the hole.

| Layer | What | Count | Command |
|---|---|---|---|
| Unit + integration | Backend services, agent, API, MCP | **789 passing**, ~55 s | `uv run pytest tests/ -q` |
| Contract | MCP typed envelopes, HTTP error taxonomy | in the 789 | `pytest tests/test_mcp_envelope.py` |
| Render | 14 reference specs compiled and drawn through the **real Vega-Lite compiler and Vega runtime**, asserting the geometry actually produced | **14/14** | `npm run verify:specs` |
| Frontend logic | Pure-logic tests, no new dependency (`node --test`) | **25 passing** | `npm test` |
| Types | TypeScript strict, Python hints | clean | `tsc -b` |
| **Behavioural** | **39 frozen NL prompts against the live planner** | see slide 12 | `uv run python -m bench.nl_run` |
| **Performance** | Latency, memory, ceilings across 5 scales | see slides 9–11 | `uv run python -m bench.perf` |
| CI | CodeBuild runs the full backend suite before every build; **verified gating PRs #43 and #44** | — | `buildspec.yml` |

**State the gap before you are asked:** *"NFR-09 asks for unit, contract, integration and e2e
tests. We have the first three. Component and end-to-end frontend tests are the largest hole in
the project and they are the top item in our next-six-weeks plan."* Owning it costs nothing;
being caught omitting it costs a lot.

Also worth one sentence: the render tests exist because **the Python suite checks spec
*structure*, which cannot tell you a spec compiles, that the theme reached the marks, or that
grouped bars grouped rather than silently stacked.** Two real bugs were caught there.

---

## 5. The performance slides (9–11) — the numbers to put on screen

All from [`Docs/24`](24-Performance-and-Evaluation.md). Do not read the tables aloud; put one
table up and say the one sentence under it.

### Slide 9 — how it scales

> "A thousand times more data costs about twice the time."

| Plan shape | 1k rows | 1M rows | Growth |
|---|---|---|---|
| Group by 1 key, sum | 21.9 ms | 50.0 ms | **2.3×** |
| Group by 2 keys, 2 aggregates | 20.9 ms | 76.1 ms | 3.6× |
| Trend (derive month + group) | 21.2 ms | 68.8 ms | 3.2× |
| Top-10 ranking | 19.9 ms | 89.4 ms | 4.5× |
| High-cardinality group-by | 20.9 ms | 570.6 ms | 27.3× |
| Cleaning block + group | 51.8 ms | 1,830 ms | 35.3× |

**Say:** *"Below 100,000 rows we are effectively constant-time, because the query is cheaper
than opening the database connection. The two shapes that do degrade degrade for reasons we
measured: one returns 100,000 rows and is bound by delivering them, the other runs a counting
query per cleaning step so it can tell the user exactly what it changed."*

Follow with the end-to-end line, which is the one people remember:

> **A full question → validated result → chart on 1,000,000 rows: 68–78 ms.**

### Slide 10 — the bottleneck (the strongest slide in the deck)

Tell it as a story in four beats:

1. **We measured, and something was wrong.** A 500k-row group-by took 613 ms. Only 194 ms was
   the query.
2. **The other 439 ms was handing the data to the engine** — DuckDB re-crossing the pandas
   boundary on *every single query*, for a dataset that never changes.
3. **The fix is one cached conversion.** Convert the frame to Arrow once per dataset, register
   that. Sound only because our frames are immutable — cleaning builds views and never writes
   back, which the registry already guaranteed.
4. **Result:**

| Rows | Before | After | Speed-up |
|---|---|---|---|
| 100,000 | 237 ms | 34 ms | 7.0× |
| 500,000 | 1,100 ms | 50 ms | 22.0× |
| 1,000,000 | 2,099 ms | 81 ms | **26.1×** |

> **"26 times faster, for 0.2 MiB of extra memory, with no behaviour change — the whole suite
> passes either way, and a test asserts both paths return identical results."**

Expect: *"why 0.2 MiB and not 133?"* → *"Arrow-backed pandas shares the buffers, so the
conversion is near-zero-copy. We measured real working set rather than trusting the logical
size, because the logical size would have reported a copy that was never made."*

Expect: *"what if a file won't convert?"* → *"It falls back to the old path. A messy CSV costs
speed, never correctness — and there is an environment variable to force the old path in
production."*

### Slide 11 — where the time goes *(droppable)*

| Rows | New connection | Expose frame | Run query |
|---|---|---|---|
| 1,000 | 13.0 ms | 0.70 ms | 2.5 ms |
| 1,000,000 | 14.7 ms | 0.73 ms | 51.0 ms |

**Say:** *"Below a million rows the connection costs more than the analysis. Pooling connections
is our next optimisation and it is worth about 40% of small-query latency — but we are not doing
it before the milestone, because it is not what the milestone is for."*

---

## 6. Accuracy and quality (slides 12–13)

### Slide 12 — NL accuracy

Lead with the method, because the method is what makes the number credible:

> *"We froze 39 prompts across four real datasets before running any of them. Scoring is
> paraphrase-tolerant — there are several correct plans for most questions, so we assert what
> every right answer must share, never plan equality."*

Then the outcome table, and make the point that **the categories are not equally bad**:

| Outcome | Meaning |
|---|---|
| **correct** | Answered, met every assertion |
| **asked** | Paused for clarification where the request really was ambiguous — *this is the product working* |
| **declined** | Refused something out of scope |
| **over-asked** | Interrupted a question it could have answered — friction |
| **wrong** | Answered confidently, and answered a different question — **the expensive failure** |

> **"We report `wrong` separately and never average it away, because for a data tool a confident
> wrong answer is far worse than a question."**

Then the result, from the run on 16 August:

| Outcome | Cases | |
|---|---|---|
| Answered correctly | **32 / 39** | 82.1% |
| Asked a clarifying question | 7 | 17.9% — every one on a prompt where asking is correct |
| Over-asked | **0** | |
| **Wrong** | **0** | |

**Re-run this the morning of the presentation and use that run's numbers.** The planner is a
hosted model; successive runs of the identical suite gave 29, 31, 32, 33 and 32 correct as the
fixes landed, and the median latency moved between 7.2 s and 11.6 s on API variance alone. If
asked: *"it is not deterministic, so we quote the counts and the shape of the failures rather
than a percentage to one decimal place — and we re-run before we present."*

**Do not claim the planner is 100% accurate.** The honest claim is narrower and stronger:
*"nothing in this set produces a confident wrong answer today, and the set is small enough that
we keep adding to it."*

The last `wrong` was closed on 16 August, and the story is worth telling because it is the one
an evaluator will find persuasive: *"asked to forecast next year's rainfall, we produced a
perfectly good **historical** trend and called it the answer. The chart was right; the question
was not the one asked. We now decline and offer the historical view as a choice."*

Volunteering how you failed, and what you changed, is the single most credibility-positive move
available in a mid-evaluation.

Also say what the benchmark unblocks: it is the **Week-3 shared deliverable** the roadmap has
been carrying, and the **held-out set the planner fine-tune track was blocked on**.

### Slide 13 — chart quality

> *"Quality isn't one number, so we don't report one."*

| Measure | Result | Checks |
|---|---|---|
| Chart-type accuracy | **14/14** | Right chart family for the question's shape — including one case it must refuse |
| Spec validity | **10/10** | Against the **real Vega-Lite v6 JSON schema**, not our own checks |
| Legibility guards | **3/3** | Series ceilings, 40-slice pie, empty-result disclosure |
| Render | **14/14** | Compiled and drawn through the actual Vega-Lite + Vega runtime |

### Slide 14 — what measuring found *(droppable, but your best slide if there is time)*

> *"We had 759 passing tests. Building the harness found seven defects. All seven are fixed, and
> the suite is now 789."*

Put the table up, then tell **one** of them properly:

| Defect | Now |
|---|---|
| `is_null` / `is_not_null` were advertised and never implemented | ✅ Fixed |
| Every query re-crossed the pandas→DuckDB boundary | ✅ Fixed, 26× |
| "maximum" read as a ranking superlative, blocking ordinary questions | ✅ Fixed |
| Every boxplot spec was invalid against the Vega-Lite schema | ✅ Fixed |
| Empty results drew a normal-looking chart and said nothing | ✅ Fixed |
| The system stopped to ask about 2 missing rows in 891 | ✅ Fixed |
| Out-of-scope requests answered instead of declined | ✅ Fixed |

**Tell the first one**, because it shows what a benchmark does that a test suite cannot:

> *"`is_null` and `is_not_null` were in our allow-list from the beginning, and validation accepted
> them — but the SQL builder had no rule for either. So a plan that validated perfectly crashed
> inside the engine, and it crashed as a* retryable *error, which put the agent in a loop
> re-running a plan that could never work. No unit test found it, because nobody thought to write
> it down. The benchmark found it because the planner chose that operator on a real question
> about a real dataset."*

Worth adding, if the room is engaged: *"the over-asking bug was **hiding** it — the system paused
to ask about two missing rows before execution was ever reached. Fixing the friction exposed the
correctness bug underneath."*

If asked why the tests missed it: *"tests check what you thought to check. That is an argument for
adding measurement, not against the suite — and every fix shipped with regression tests, which is
why the suite is now 779."*

---

## 7. Where we are (slide 17) — how to justify ~80%

Do not assert 80%. **Show the arithmetic and let the number fall out.** Weight by deliverable,
mark honestly, total it. Two numbers come out, and they answer different questions — say both,
in this order.

### The product itself (weight 80 of 100)

| Area | Weight | Done | Score | Evidence |
|---|---|---|---|---|
| Ingestion, profiling, preview | 8 | 100% | 8.0 | 8 formats; probe-based ingest; 637 ms per 100k rows |
| NL → validated plan (MCP + agent) | 11 | 95% | 10.5 | 18 MCP tools; 39-prompt benchmark; 1 known `wrong` |
| Deterministic execution | 11 | 100% | 11.0 | Closed grammar → DuckDB; provenance on every result |
| Chart generation | 8 | 100% | 8.0 | 10 types; 10/10 schema-valid; 14/14 render |
| Dashboard, editing, persistence | 8 | 100% | 8.0 | Canvas, autosave, reopen |
| Export (image + PDF) | 4 | 100% | 4.0 | Both, no new dependency |
| Preprocessing / cleaning | 8 | 70% | 5.6 | 14 risk-tiered ops, **not surfaced in the UI** |
| Backend API + persistence | 8 | 100% | 8.0 | 46 endpoints, PostgreSQL, Alembic |
| Deployment | 6 | 90% | 5.4 | CodeBuild → ECR → CodeDeploy → EC2; local fallback |
| Automated testing | 8 | 65% | 5.2 | 789 backend + 25 frontend + 14 render; **no component/e2e** |
| **Subtotal** | **80** | | **73.7** | **92% of the product scope** |

### Everything the remaining six weeks are for (weight 20 of 100)

| Area | Weight | Done | Score | Why it is not 0 |
|---|---|---|---|---|
| Evaluation and error analysis | 8 | 45% | 3.6 | Perf + NL + chart harnesses now exist; **usability sessions not run** |
| Final reports, SAD, documentation | 7 | 70% | 4.9 | 25 numbered documents written; not yet finalised for submission |
| Release: video, GitHub page, tagged build | 5 | 15% | 0.8 | Nothing recorded or tagged |
| **Subtotal** | **20** | | **9.3** | **46%** |

### The number

> **73.7 + 9.3 = 83 of 100 — call it ~80%.**
> **92% of the product. 46% of the evidence and release work around it.**

Three things to say alongside it:

1. **"The gap is deliberately the evidence layer, not the product."** Component and e2e tests,
   five usability participants, a recorded demo. Nothing on that list is architecturally hard —
   which is exactly why it slipped, and exactly why it is our next-six-weeks plan.
2. **"Against the milestone's own acceptance list we are 9 of 10."** The tenth is a usability
   cycle, and it cannot be met from a keyboard.
3. **"We would rather show you an 83 we can defend than a 95 we cannot."** Every row above has
   a command behind it.

---

## 8. Known limits — say these before you are asked (slide 15)

| Limit | Honest framing |
|---|---|
| **One table at a time — no joins** | *"Our biggest capability gap. We measured what it would cost: a million-row join is 154 ms — about the same as a group-by we already ship. The barrier is the plan grammar, not performance, so it is a scoped piece of work rather than an open question. And in the meantime the product **says so**: ask it to join and it declines, rather than quietly answering a narrower question."* |
| **No forecasting or statistical modelling** | *"Descriptive only. We added a deterministic capability check for this after the benchmark caught us answering 'forecast next year's rainfall' with a historical trend — a correct chart for a question nobody asked. It now declines and offers the historical view as a choice."* |
| **~526,000 rows / 50 MiB per upload** | *"A deliberate ceiling, not a bug — and the benchmark demonstrates it firing rather than describing it. Beyond that we would need streaming or pushdown to a real warehouse."* |
| **Files only, no live database connections** | Architectural, and in the proposal's non-requirements |
| **Concurrency is unmeasured** | *"Everything we have measured is single-request. It is the first thing we are adding to the harness."* |
| **Cleaning is invisible in the UI** | *"Six merged phases of backend work that a demo cannot show. Highest value-per-hour item in our backlog."* |
| **Frontend e2e coverage is zero** | Owned in §4 |

The framing that works: **a limit you measured is engineering; a limit you discovered on stage
is a gap.** Every row above has a number or a plan next to it.

---

## 9. Questions to rehearse

| Question | Answer |
|---|---|
| "How do you know the LLM isn't inventing numbers?" | It never sees values — only schema and profile. It emits a plan whose grammar is `Literal`-typed, and the plan compiles to parameterised SQL. Every result carries the SQL that produced it. |
| "What if someone puts a prompt injection in a CSV cell?" | Cell contents and column names are neutralised before reaching any prompt. `services/safety.py`, and it is tested. |
| "Why not just use ChatGPT's data analysis?" | It runs arbitrary generated Python. Ours cannot — that is the whole design. Also: MCP-first, so the same tools serve our web app *and* an external host. |
| "Why is it 7 seconds if the query is 80 ms?" | Over 99% of the wait is the planner LLM. That ratio is exactly why the fine-tune track exists. |
| "Is 39 prompts enough?" | No, and we say so — it is a floor and a frozen baseline, not a sufficiency claim. It is the first version of a set that grows *with new cases only*, never by removing ones that fail. |
| "Your tests passed but you found bugs — what does that say about the tests?" | That tests check what you thought to check. Measurement found seven defects, all now fixed with regression tests — including an operator we advertised and never implemented. That is the argument for adding measurement, not against the suite: it is why the suite is 789 and not 759. |
| "What's your biggest risk?" | The usability cycle. It needs five people and three hours, and no amount of code closes it. |
| "Who did what?" | §1 owner column. Also mention the `.mailmap` fix — one member commits under two git identities, so naive `git shortlog` undercounts them. |

---

## 10. Before the presentation — the checklist

Ordered by what breaks the presentation if skipped.

| # | Action | Owner | Cost | Why it is on this list |
|---|---|---|---|---|
| 1 | **Un-gitignore `Docs/`** — line 1 of `.gitignore` | Anyone | 5 min | 25 numbered documents, including this one, exist on one laptop. If a panel asks for the SAD, you cannot show it. **Nothing else on this list matters more.** |
| 2 | **Record the demo** | Chandrasiri | 30 min | The only defence against a live failure |
| 3 | **Confirm the deployed URL responds** | Bulagala | 15 min | Criterion 10 is the one met criterion nobody has verified from outside the tree |
| 4 | **Rehearse §2 end to end, twice, timed** | All | 1 hr | Demos run long; four minutes is less than it sounds |
| 5 | **Add a `.mailmap`** | Anyone | 5 min | Or per-member contribution counts are wrong on slide 1 |
| 6 | Run all three benchmarks once more and refresh the numbers | Daishika | 20 min | So the slides match the tree on the day |
| 7 | Decide who answers each §9 question | All | 15 min | Silence after a question reads worse than any answer |

---

## 11. What to have open in tabs

1. The deployed app, dataset pre-uploaded
2. The local fallback, running
3. `Docs/24` — for any performance question
4. A terminal on `backend/`, ready to run `uv run pytest tests/ -q` if anyone doubts the count
5. The recorded demo

---

*Sources: [`Docs/21 — Project Status`](21-Project-Status.md),
[`Docs/24 — Performance and Evaluation`](24-Performance-and-Evaluation.md),
[`Docs/23 — Usability Evaluation`](23-Usability-Evaluation.md),
[`Docs/project-roadmap.md`](project-roadmap.md). Re-verify counts before presenting — this
repository changes daily.*
