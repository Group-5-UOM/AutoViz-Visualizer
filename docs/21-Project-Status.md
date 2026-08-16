# 21 — Project Status

**Originally 14 August 2026; criteria 7 and 8 updated 15 August.** Every figure below was read out
of the working tree, the test suite, or `git`/`gh` on those dates — none is carried over from an
earlier document. Where a claim could not be verified from the repository, it says so.

**The milestone is 3 days away.** [`Docs/project-roadmap.md`](project-roadmap.md) commits to *~85%
of the core product demonstrable by 18 August 2026*, against ten named acceptance criteria.

---

## 1. Verdict

**Nine of the ten milestone criteria are met; one is unmet and one of the nine could not be
verified from the repository.** The product works end to end: upload a file, ask a question in
English, get a validated deterministic answer, a chart, a dashboard that saves itself, and a
disclosure of what the system did to the numbers on the way.

What remains missing is not product — it is **evidence**. The one open criterion is a documented
usability cycle. It is not architecturally hard, and it is something an evaluator will look for by
name.

| # | Acceptance criterion | Status | Evidence |
|---|---|---|---|
| 1 | CSV upload, profiling, and preview work | ✅ Met | `POST /datasets/upload`, `/schema`, `/profile`, `/preview`; 8 formats, not just CSV |
| 2 | NL requests trigger typed MCP calls | ✅ Met | 18 MCP tools, typed envelope, `test_mcp_envelope.py` |
| 3 | Calculations are deterministic and validated | ✅ Met | Closed grammar → DuckDB SQL; `test_execution.py`, `test_validation.py` |
| 4 | Supported Vega-Lite charts render correctly | ✅ Met | 10 chart types; `test_chart_types.py`, `test_vega_version.py`, `verify:specs` |
| 5 | Charts can be edited and arranged on a dashboard | ✅ Met | `StylePanel`, in-place editing, `DashboardCanvas` drag/resize/delete |
| 6 | Dashboard layouts can be saved and reopened | ✅ Met | Autosave (`lib/dashboardSync.ts`) + `DashboardsModal`; `test_api_dashboards.py` |
| 7 | Image **and PDF** export work | ✅ Met (15 Aug) | Both, from one Export menu. `lib/pdf.ts` writes the PDF directly — no new dependency; output verified with `pypdf`. [`Docs/22 §1`](22-Export-and-UI-States.md) |
| 8 | Core error/loading states are complete | ✅ Met (15 Aug) | Audited against the six states FR-19 names; typed validation-vs-recoverable classification, a notice channel, and retry everywhere it is honest to offer one. [`Docs/22 §2`](22-Export-and-UI-States.md) |
| 9 | One usability-test cycle is documented | ❌ **Not met** — and cannot be met from a keyboard | Protocol, tasks and instruments are written and ready ([`Docs/23`](23-Usability-Evaluation.md)), and a heuristic evaluation found 14 issues of which 6 are fixed. **But the criterion says *usability test*, and that needs five participants and about three hours.** Nothing in the results section may be filled in from expectation |
| 10 | Deployed build and local fallback available | ✅ Met (deploy pipeline) | CodeBuild → ECR → CodeDeploy → EC2; `docker-compose.local.yml` + README fallback. **A live URL was not checked** — this cannot be verified from the tree |

Two shared deliverables from the roadmap are also outstanding and are easy to miss because they sit
outside the acceptance list: the **≥30 NL benchmark prompts** (Week 3) and the **evaluation
harness** the planner fine-tune track is blocked on.

---

## 2. The numbers

All measured on `feat/preprocessing-hardening`, which is `origin/main` minus one cleanup commit
(`f0be5fc`, −38 lines of dead JWT code) — so these figures describe `main`.

### Delivery

| | Value |
|---|---|
| First commit | 21 July 2026 — **24 days of development** |
| Non-merge commits | 90 |
| Pull requests | 42 · **39 merged, 3 closed unmerged, 0 open** |
| Branches on origin | 15 |

| Member | Commits | PRs opened | PRs merged |
|---|---|---|---|
| Daishika (230112C) | 54 | 15 | 15 |
| Bulagala (230094U) | 20 | 14 | 13 |
| Chandrasiri (230101R) | 16 | 13 | 11 |

> Chandrasiri commits under **two git identities** — `Tenath Dilusha` (15) and `Dilusha
> Chandrasiri` (1). Any contribution count taken naively from `git shortlog` splits them and
> undercounts. Worth fixing with a `.mailmap` before the final submission.

### Build health

| | Value |
|---|---|
| Backend tests | **759 passing**, 0 failing, 69 s (`uv run pytest tests/ -q`) |
| Backend test modules | 54 |
| Frontend typecheck | `tsc -b` clean (exit 0) |
| **Frontend tests** | **25 passing** (`npm test`) as of 15 Aug — was 0 with no runner installed. Pure-logic only; component and e2e tests are still absent |
| CI | CodeBuild only. There is no `.github/` directory; the sole automated test run is the `pre_build` phase of `buildspec.yml`. Whether it gates pull requests is a CodePipeline setting not visible in the repo |

### Surface area

| | Value |
|---|---|
| MCP tools | **18** — 7 in the `default` profile, 11 more under `advanced` (the shipped default) |
| MCP resources / prompts | 4 / 1 |
| HTTP endpoints | **45** across 7 routers — auth 12, charts 9, datasets 9, analysis 5, dashboards 5, conversations 3, agent 2 |
| Chart types | 10 |
| Filter ops / aggregations / derive fns | 11 / 7 / 15 |
| Preprocessing operations | 14, each declaring its own risk tier |
| Input formats | 8 — `.csv .tsv .txt .xlsx .xlsm .parquet .json .jsonl` |
| Test datasets | 49 CSVs — 38 real across 8 domains, 11 synthetic defect fixtures |

---

## 3. Where each track stands

### MCP, LLM orchestration and integration — Daishika

**State: ahead of plan.** Weeks 1–4 of the roadmap are complete for this track, and the work since
29 July has been depth rather than breadth — closing correctness holes the plan never anticipated.

Since the [last progress log](team/member-01-progress-2026-07-22-to-07-29.md) ended (463 tests),
the suite has gone to **759** across three merged branches:

- **Cleaning disclosure and outlier handling** (PR #30) — the notices channel and skew-aware axis
  scaling. [`Docs/14`](14-Disclosure-and-Outlier-Handling.md).
- **In-place chart editing** (PRs #37, #38) — chart identity, a style block, typography, chart-type
  selection, Markdown chat rendering, server-side conversation history.
  [`Docs/15`](15-In-Place-Chart-Editing.md).
- **Preprocessing hardening** (PR #41, six phases, +4,257/−133) — probe-based ingestion, date
  truncation, `parse_number`, schema-evolving reshape ops, sentinel detection, group-wise
  imputation, recipe replay. [`Docs/19`](19-Preprocessing-Parity-Roadmap.md) and
  [`Docs/20`](20-Preprocessing-Before-And-After.md).

That work found and fixed six defects that were **already live in `main` and silently producing
wrong charts** — the multi-year month collapse being the worst. All are covered by regression tests.

**Not done on this track:** the NL benchmark, and the evaluation harness that gates the planner
fine-tune (see §5).

### Frontend, visualization and dashboard canvas — Chandrasiri

**State: on plan for the canvas, behind on evidence.**

Shipped: OAuth sign-in for Google and GitHub (PR #27, +2,754), dataset editing tools (PR #32,
+2,914), a functional sidebar (PR #35), and graph control fixes (PR #36). The canvas does what the
milestone asks — add, drag, resize, delete, edit, save, reopen.

Two deliverables from the role definition were outstanding on 14 August. As of 15 August:

- ~~**PDF export.**~~ **Done.** PNG and PDF both ship from one Export menu, written without adding
  a dependency. [`Docs/22 §1`](22-Export-and-UI-States.md).
- **Component and frontend e2e tests.** *Partly addressed.* A runner now exists and 25 pure-logic
  tests pass, but component and e2e coverage is still zero, and NFR-09 asks for unit, contract,
  integration *and* e2e tests in CI. This remains the largest hole.

The **usability cycle** (criterion 9) also sits here and still has no artifact. It is now the only
unmet acceptance criterion.

### Data engine, backend services and deployment — Bulagala

**State: on plan; deployment is the strongest single contribution.**

The AWS path is real and complete: `buildspec.yml` runs the whole backend suite before it builds,
pushes the API image to ECR in `eu-north-1`, extracts the frontend `dist`, and `scripts/deploy.sh`
pulls on EC2, runs `alembic upgrade head` against the live schema, and drops the static build into
nginx. Postgres is never recreated, so the `pgdata` volume survives deploys.

Also shipped since 29 July: conversations migrated to `dashboard_id` (PR #39, +946/−459), local
docker-compose (PR #29), nginx timeout configuration, and a security fix hardening an intruder test
to expect `403` (PR #40).

---

## 4. The documentation problem worth fixing this week

**`Docs/` is gitignored, and it catches the numbered documents only.** Line 1 of `.gitignore` is
`Docs/`. Five files predate the rule and are therefore still tracked — `project-roadmap.md`,
`requirements.md`, and the three `team/member-0*.md` role documents. **Everything numbered 01–22 is
untracked**: the proposal, the SAD, the architecture and MCP references, the entire preprocessing
record, and this file. No teammate, mentor, TA or evaluator can see any of those through GitHub,
and none is backed up by the repository. For a project whose deliverables include an SRS and
architecture evidence, that is a delivery risk, not a tidiness one.

*(The earlier revision of this section said no documentation at all was in the repository. Five
files are — the ones above.)*

~~**The README overstates export.**~~ Resolved on 15 August: the README promised PDF and the code
produced PNG. The code now produces both, so the sentence is true as written.

A second, smaller one: `AutoViz-Planner-Model/docs/project-status.md` records that
`Docs/16-Planner-Model-Strategy.md` and `Docs/17-Fine-Tuning-Execution-Plan.md` "do not exist."
They do — both were written in early August. They are invisible from that repo *because of the
gitignore above*, which is the same problem seen from the outside.

---

## 5. The planner fine-tune track is prepared and blocked

The companion repo `Group-5-UOM/AutoViz-Planner-Model` holds the QLoRA work aiming to replace the
hosted Gemini planner (`google_genai:gemini-3.5-flash`) with a locally served Qwen3.5.

Its training notebook, frozen 4B/9B configs and 80-paper research review are all complete. **Every
downstream phase is blocked on one thing that lives in *this* repo and does not exist: a frozen
golden set and an evaluation runner.** Without a held-out set and a baseline number, no claim about
the fine-tune is falsifiable.

Estimated cost: days, not weeks — `test-data/` already supplies the tables and `execute_analysis`
already supplies most of the runner. It is not on the critical path for 18 August, and it is on the
critical path for everything after it.

---

## 6. Known product limits

Carried forward from [`Docs/20 §5`](20-Preprocessing-Before-And-After.md), unchanged and stated
plainly:

| Limit | Kind |
|---|---|
| One table at a time — no joins or unions | Largest capability gap |
| Bounded by memory — 50 MiB / 1 M rows, no streaming or pushdown | Scale ceiling |
| Files only — no live database connections or scheduled refresh | Architectural |
| No interactive profile pane | UX |
| **The frontend surfaces none of the six preprocessing phases** — zero references to ingest reports, notices, or the four new operations anywhere in `frontend/src` | Integration debt |

That last row is the highest value-per-hour item in the whole backlog: the capability is built,
tested and invisible to every user of the web client.

---

## 7. What the three days to 18 August should hold

Ordered by what an evaluator will actually check. Struck items were done on 15 August.

| # | Action | Owner | Why now |
|---|---|---|---|
| 1 | **Commit `Docs/`** — remove line 1 of `.gitignore` | Anyone, 5 minutes | Nothing else on this list matters if the evidence is on one laptop |
| 2 | ~~PDF export~~ | — | **Done** — [`Docs/22 §1`](22-Export-and-UI-States.md) |
| 3 | **Book five participants and run the sessions** | Chandrasiri | The last unmet criterion. Everything except the people is written and waiting in [`Docs/23`](23-Usability-Evaluation.md) — booking is the long pole, so it has to happen today |
| 4 | **Component tests on top of the new runner** | Chandrasiri | `npm test` and 25 pure-logic tests exist now; components and e2e do not, and that is what NFR-09 asks for |
| 5 | **Surface the ingest report and the four new operations in the UI** | Daishika | Six phases of merged backend work are currently undemonstrable in the demo |
| 6 | **Freeze ~30 NL benchmark prompts** | Daishika | Week 3 deliverable; also the first half of the eval harness in §5 |
| 7 | **Confirm the deployed build is live and rehearse the demo against it** | Bulagala | Criterion 10 is the only met criterion that cannot be verified from the tree |
| 8 | **Add a `.mailmap`** | Anyone, 5 minutes | So per-member contribution counts are correct in the final report |

Items 1 and 8 cost minutes. Item 3 is the difference between nine criteria met and ten.

---

*Verified against the working tree on 14 August 2026: `pytest` (759 passed), `tsc -b` (clean),
`git`, and `gh pr list`. Criteria 7 and 8 re-verified 15 August: `npm test` (25 passed), `tsc -b`,
`npm run build`, and the generated PDF parsed with `pypdf`. Re-verify before quoting — this
repository changes daily.*
