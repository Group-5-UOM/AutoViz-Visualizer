# 23 — Usability Evaluation

**15 August 2026.** Milestone criterion 9 asks for *one usability-test cycle, documented*.

## Read this first: what is and is not done

| Part | Status |
|---|---|
| **A — Heuristic evaluation** (expert inspection against Nielsen's ten heuristics) | ✅ **Done.** 14 findings, every one traced to a file and line; **6 fixed the same day** |
| **B — Test protocol, tasks, instruments** | ✅ **Done and ready to run.** [`usability/session-pack.md`](usability/session-pack.md) |
| **C — Sessions with participants** | ❌ **Not run.** Needs five people and about three hours |
| **D — Results and findings** | ❌ **Empty by design.** §5 is the structure; the numbers must come from real sessions |

**Criterion 9 is not met by this document.** A heuristic evaluation is an expert
inspection, not a usability test — it is what one person can conclude by reading
an interface, and it systematically misses what it does not occur to an expert
to try. The criterion says *usability test*, and a usability test requires
users. Part B exists so that running one is an afternoon rather than a project.

**Nothing in §5 may be filled in from expectation.** An invented participant is
fabricated evidence in an assessed report. If the sessions do not happen, the
honest thing is to say so and leave the criterion unmet.

---

## 1. Why the inspection came first

Two reasons, both practical.

Five participants are a scarce resource. Anything an expert can find by reading
the code is a defect a participant would otherwise spend session time
rediscovering — and every minute spent on a known problem is a minute not spent
finding an unknown one. The severity-3 items in §3 should be fixed *before* the
sessions, not confirmed by them.

The second reason is that heuristic evaluation and user testing fail in
different directions, so neither substitutes for the other. Inspection finds
standards violations, missing affordances and accessibility gaps that users
often work around without complaint. Testing finds the things nobody thought to
look for — the label that means something else to a stranger, the step everyone
on the team performs from memory. The findings below are biased towards the
first kind, and that bias is the argument for doing part C.

---

## 2. Method for the inspection

One evaluator, reading `frontend/src` against Nielsen's ten usability heuristics,
on the `main` build as of 15 August 2026 (merge `6e1cb84`). Severity uses
Nielsen's scale:

| | Severity |
|---|---|
| **4** | Catastrophe — must fix before release |
| **3** | Major — users are blocked or lose work; high priority |
| **2** | Minor — users are slowed or briefly confused |
| **1** | Cosmetic — fix if time allows |

A single-evaluator inspection finds roughly a third of the issues a panel of
three to five would. Read the count below as a floor.

---

## 3. Findings

Six were fixed the same day, before any session — marked **[fixed]**. The rest
are left for evidence, because several are the evaluator guessing at what a
stranger will think, which is what part C is for.

### Severity 3 — major

**H1. [fixed] Deleting a chart is one unconfirmed click, with no undo.**
`ChartWidget.tsx:307-318` — the bin icon calls `onDelete()` directly. Deleting a
*dataset* and deleting a *dashboard* both raise a confirmation; deleting a
chart, which destroys work the user may have spent several turns refining,
raises nothing. Autosave then persists the deletion within 1.5 seconds. There is
no undo anywhere in the product.
*Heuristic 3, user control and freedom; heuristic 4, consistency.*
**Fixed** with undo rather than a confirmation: `deleteWidget` now returns a
restore function and the notice channel offers "Undo". A confirmation taxes the
ordinary path, where the user meant it; an undo costs nothing until it is
needed. Safe because `syncDashboard` only rewrites the dashboard's widget list —
the `saved_charts` row survives a delete, so a restore re-links rather than
re-uploads.

**H2. [fixed] Four modals claim `aria-modal="true"` and none traps focus.**
`DashboardsModal.tsx:173`, `DatasetModal.tsx:136`, `NameUploadModal.tsx:47`,
`SaveDashboardModal.tsx:47`. Nothing moves focus into the dialog when it opens,
nothing restores it on close, and Tab walks straight out into the page behind.
`aria-modal="true"` is an assertion to assistive technology that this is
happening — so the markup actively misinforms a screen reader rather than merely
omitting a feature.
*Heuristic 4, consistency and standards. NFR-08 accessibility.*
**Fixed** — `hooks/useFocusTrap.ts`, applied to all five dialogs. Focus moves in
on open, Tab wraps at both ends, and the previously focused element gets focus
back on close. Takes an optional initial-focus ref, because the naming dialogs
want their text field rather than the close button that precedes it in DOM
order.

**H3. [fixed] Destructive confirmations cannot state their blast radius.**
`DatasetModal.tsx:73` warned that deleting a dataset "will also remove
associated charts" without saying how many, or which dashboards lose content. It
was a `window.confirm`, so it *could not* say — the string is fixed before the
facts are known.
*Heuristic 5, error prevention; heuristic 1, visibility of system status.*
**Fixed** — `ConfirmDialog` replaces all three native dialogs and names the
specific thing: the dataset by name with its row and column count, the dashboard
by name with its chart count, and what survives in each case. Cancel takes
initial focus, so a hurried Enter lands on the safe choice.

### Severity 2 — minor

**H4. "Setup" does not name what it does.** `Sidebar.tsx:23` labels the chart
builder "Setup", next to "Add", "Filter" and "AI Chat". "Setup" conventionally
means configuration or first-run. Nothing in the label suggests "build a chart
by picking a type and asking a question".
*Heuristic 2, match between system and the real world.* **This is exactly the
kind of finding a usability test either confirms or kills — do not rename it on
one evaluator's word.**

**H5. Two chart-request surfaces share one conversation.** AI Chat and Setup
both send to the same agent thread, and Setup renders only the last eight
messages (`BoardPage.tsx`, `setupMessages = messages.slice(-8)`). A user who
asks in one and looks in the other sees a transcript that is the same
conversation but a different length. Whether that reads as one conversation or
two broken ones is a question for participants.
*Heuristic 4, consistency.*

**H6. A permanently disabled "Share" button.** `TopBar.tsx` — `disabled` with
the tooltip "Coming soon", occupying prime top-bar space next to the controls
that do work.
*Heuristic 8, aesthetic and minimalist design.*

**H7. Help exists only as four suggestion chips that disappear.**
`ChatPanel.tsx:145` shows them while `messages.length <= 1`. After the first
message the user has no reference for what the system can be asked, and there is
no help, no documentation link, and no examples panel. The product's entire
value rests on the user's ability to phrase a question it can answer.
*Heuristic 10, help and documentation.*

**H8. [fixed] An unsaved-changes prompt appears in exactly one place.**
`BoardPage.tsx:492` guarded "New dashboard" with a `window.confirm`. Opening a
different dashboard from the Dashboards modal called `saveNow()` silently
instead, and switching datasets flushed without asking. Three paths away from
unsaved work, three different behaviours — and the prompt's Cancel button
*discarded* the work rather than cancelling the operation, with no third option.
*Heuristic 4, consistency.*
**Fixed** by removing the prompt. The board autosaves on every other path, so
asking here was the anomaly. `saveNow()` now reports whether the canvas is
safely on the server, and the new dashboard is created only if it is; if the
save fails, the existing save-failure notice carries the retry and a second
notice says why the new board did not appear.

**H9. Filtering the canvas silently changes what Export produces.** The Filter
panel narrows `visibleWidgets`; Export captures the rendered
`.dashboard-canvas`. A user who filters to bar charts and then exports gets a
PDF of the bar charts only, with nothing saying so. Defensible as
what-you-see-is-what-you-get, but it is not signalled.
*Heuristic 1, visibility of system status.*

**H10. [fixed] Nine animations ignore `prefers-reduced-motion`.** Only
`NoticeStack.css:117` honoured it. The modal scale-in, overlay fade, two
spinners and the chat thinking-dots did not.
*NFR-08 accessibility.*
**Fixed** with one global block in `index.css`. Spinners keep a slow turn rather
than stopping dead — a frozen spinner reads as a hung application, which is the
opposite of what a loading indicator is for.

**H11. [fixed] Error and validation chat bubbles are distinguished by colour
alone.** `ChatPanel.css` — the bubbles carried a red or blue inset rule and
nothing else. The notice stack got this right with distinct icons; the chat
bubbles did not. *A finding on code added the day before for criterion 8.*
*Heuristic 4; WCAG 1.4.1 use of colour.*
**Fixed** — each now carries an icon and a text label ("Request not accepted" /
"Something went wrong") above the message.

### Severity 1 — cosmetic

**H12. Save is disabled once it reads "Saved".** `TopBar.tsx` — a user who wants
to force a save for reassurance cannot. Correct behaviour, but it removes the
control precisely when someone anxious about their work reaches for it.

**H13. "Add" and "Datasets" and "Edit Dataset" are three sidebar entries for one
concept.** Whether users can predict which one holds what is a question for §5.

**H14. The `@`-to-reference-a-chart gesture is discoverable only from the
composer placeholder.** The attach button appears only once a referenceable
chart exists, which is correct, but the gesture itself is never taught.

### What was fixed, and what was left

**Fixed on 15 August: H1, H2, H3, H8, H10, H11.** The first three because they
would have cost participant time on problems already known; H8 because the
prompt actively destroyed work; H10 and H11 because they are accessibility
defects with one-line answers, and H11 was a regression introduced the day
before.

**Left for evidence: H4, H5, H6, H7, H9, H12, H13, H14.** Every one of these is
a guess about what a stranger will think — whether "Setup" reads as a chart
builder, whether two chat surfaces confuse anyone, whether the disappearing
suggestion chips are missed. Changing them now on one evaluator's opinion would
destroy the only chance to find out.

**None of these fixes has an automated test.** They are DOM and React behaviour,
and the test runner added for criterion 8 covers pure logic only — there is
still no component test environment ([`Docs/22 §3`](22-Export-and-UI-States.md)).
They were verified by reading and by `tsc -b`, which is weaker than it sounds
and is worth stating plainly.

---

## 4. The test that has not been run

Full protocol, tasks, consent form, observation sheet, SUS instrument and
debrief script: [`usability/session-pack.md`](usability/session-pack.md).

In summary:

| | |
|---|---|
| **Design** | Moderated, think-aloud, single session per participant, ~45 min |
| **Participants** | 5 — Nielsen and Landauer's curve puts that at roughly 85% of findable issues, and it is the defensible number for a course project |
| **Recruitment** | University students outside the group. **No group member is a participant** — the team cannot un-know where the buttons are |
| **Environment** | The deployed build if criterion 10 is confirmed live, otherwise a local run. Same machine and browser for all five |
| **Tasks** | 8, phrased as goals and never naming a control. Two datasets: `test-data/general-testing/tips.csv` (clean, familiar) and `test-data/synthetic-quality/messy_sales.csv` (13 spellings of 4 regions, 15% missing discounts) |
| **Measures** | Completion (unassisted / assisted / failed), time on task, error count, SUS, and three debrief questions |

Two tasks are worth calling out because they test things the rest of this
project has invested in heavily and never checked against a person:

- **Task 6 asks a question of the messy file**, which triggers the cleaning
  consent flow, and then asks the participant — before showing them anything —
  *"what, if anything, did the system change about your data?"* The disclosure
  prose in `services/notices.py` is composed deterministically in Python
  precisely so a model cannot soften it ([`Docs/14`](14-Disclosure-and-Outlier-Handling.md)).
  Whether it actually communicates to a reader has never been tested.
- **Task 8 asks a question with the backend stopped.** The facilitator kills it
  beforehand. This puts the recoverable-error and retry states built for
  criterion 8 ([`Docs/22`](22-Export-and-UI-States.md)) in front of a real
  person, which is the only way to find out whether "Try again" reads as worth
  pressing.

---

## 5. Results

**Empty until the sessions are run.** The structure below is what to fill in;
the numbers are not to be estimated, inferred from the heuristic evaluation, or
supplied from anywhere other than five recorded sessions.

### 5.1 Participants

| # | Background | Data/chart tools used before | Date |
|---|---|---|---|
| P1 | | | |
| P2 | | | |
| P3 | | | |
| P4 | | | |
| P5 | | | |

### 5.2 Task completion

Unassisted ✅ · assisted 🟡 (facilitator hinted) · failed ❌ (abandoned or gave up).

| Task | P1 | P2 | P3 | P4 | P5 | Unassisted rate |
|---|---|---|---|---|---|---|
| 1 Load a file | | | | | | |
| 2 Ask a first question | | | | | | |
| 3 Change a chart | | | | | | |
| 4 Arrange the canvas | | | | | | |
| 5 Keep the work | | | | | | |
| 6 The messy file | | | | | | |
| 7 Export as PDF | | | | | | |
| 8 Recover from a failure | | | | | | |

### 5.3 Time on task (mm:ss)

| Task | P1 | P2 | P3 | P4 | P5 | Median |
|---|---|---|---|---|---|---|
| 1–8 | | | | | | |

### 5.4 SUS

Odd-numbered items score `response − 1`; even-numbered items score `5 − response`;
sum the ten and multiply by 2.5. The result is 0–100 and **is not a percentage**.
A 68 is average; below 50 is a serious problem.

| | P1 | P2 | P3 | P4 | P5 | Mean |
|---|---|---|---|---|---|---|
| SUS | | | | | | |

### 5.5 Issues found

| ID | Issue | Task | Participants affected | Severity | Heuristic | Fix |
|---|---|---|---|---|---|---|
| U1 | | | /5 | | | |

### 5.6 Did the disclosure communicate? (task 6 probe)

Record each participant's *unprompted* answer to "what, if anything, did the
system change about your data?" verbatim. This is the question the whole
disclosure channel exists to pass.

| | Answer | Named the change? |
|---|---|---|
| P1 | | |

### 5.7 What to change, in order

To be written from 5.5, ranked by severity × number of participants affected.

---

## 6. What flipping criterion 9 requires

1. ~~Fix H1, H2, H3~~ — done 15 August, along with H8, H10 and H11.
2. **Book five participants.** This is the long pole and the reason to do it
   today rather than on the 17th.
3. Run five sessions, ~45 minutes each plus reset time.
4. Fill in §5 from the recordings and notes.
5. Write §5.7 and open issues for whatever comes out at severity 3 or 4.

Steps 2 and 3 are the whole criterion, and they are the two things nobody can do
from a keyboard. Everything else in this document is scaffolding around them.

---

*Part A verified against `main` at merge `6e1cb84`, 15 August 2026. Every file
and line reference in §3 was read, not recalled. Parts C and D are unstarted and
are marked as such deliberately.*
