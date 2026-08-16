# Usability session pack

Everything needed to run one session. Print or open alongside the app.
Companion to [`Docs/23`](../23-Usability-Evaluation.md).

**Facilitator:** ______________  **Participant:** P___  **Date:** ______________

---

## Before the day

- [ ] Fix H1, H2, H3 from [`Docs/23 §3`](../23-Usability-Evaluation.md) — otherwise
      five people spend their time rediscovering them
- [ ] Book **5 participants**, 60-minute slots. Students outside Group 5.
      **No group member takes part** — you cannot un-know where the buttons are
- [ ] Decide the environment and keep it identical across all five: deployed
      build if it is confirmed live, otherwise `npm run dev` on one machine
- [ ] Create a throwaway account per participant, signed in before they arrive
- [ ] Copy `test-data/general-testing/tips.csv` and
      `test-data/synthetic-quality/messy_sales.csv` to the desktop, so hunting
      for a file is not part of the test
- [ ] Check screen recording works, and that audio is captured
- [ ] Run through all 8 tasks yourself once, timed, to confirm nothing is broken

## Before each session

- [ ] Reset: sign in as the fresh account, no datasets, no dashboards
- [ ] Browser at a consistent window size, zoom 100%
- [ ] Recording started **after** consent is given
- [ ] This sheet open, timer ready

---

## 1. Brief — read aloud

> Thanks for helping. This will take about 45 minutes.
>
> I want to be clear about one thing: **we are testing the software, not you.**
> There is no way for you to do this wrong. If something is confusing, that is
> the software failing to explain itself, and it is exactly what I need to find
> out — so please do not be polite about it. Being blunt helps me more than
> being kind.
>
> I will give you eight small tasks. Please **think out loud** as you go: say
> what you are looking for, what you expect a thing to do, and what surprises
> you. If you go quiet I will nudge you.
>
> I cannot help you while a task is running, even if you get stuck — that is not
> me being unhelpful, it is that the sticking points are the results. If you are
> completely stuck, say so and we will move on. That is a useful result, not a
> failure.
>
> You can stop at any time, for any reason, without explaining.
>
> Any questions before I start recording?

## 2. Consent

> I would like to record the screen and your voice, so I do not have to rely on
> my notes. The recording is used only by our project group, for this university
> module. It is not published and does not go in the report. Your name is not
> written down anywhere — you are "Participant 3". You can ask me to delete the
> recording afterwards, no reason needed.
>
> Is that all right?

**Consent given:** ☐ verbally, on the recording ☐ signed below
**Recording:** ☐ screen ☐ audio ☐ declined — notes only

Signature (optional): ______________________

*If they decline recording, run the session on notes. Do not press.*

## 3. Warm-up — 2 minutes, not scored

> Before we start: have you used anything like Excel charts, Tableau, Power BI,
> or Google Sheets charts before? Roughly how often?

Answer: ______________________________________________

> Take thirty seconds and just look at the screen. Without clicking, tell me
> what you think this application is for.

Answer (verbatim): ____________________________________

*This is the single cheapest first-impression measure there is. Write what they
say, not what they meant.*

---

## 4. Tasks

**Rules for the facilitator.** Read each task exactly as written. Never name a
button, menu or panel — if the task names the control, it is testing reading
comprehension, not the interface. When asked "what should I do?", reflect it
back: *"What would you try?"* Start the timer when you finish reading; stop it
when they say they are done, or when you call it.

**Recording a result:** ✅ unassisted · 🟡 assisted (you hinted) · ❌ failed
(abandoned, gave up, or believed they had succeeded when they had not).

Log a hint whenever you say anything beyond a nudge to keep talking. Note the
time of each hint — a task completed at 4:30 with a hint at 4:00 is a failure
wearing a hat.

---

### Task 1 — Load a file

> On the desktop there is a file called `tips.csv`. It is a few hundred
> restaurant bills — what the meal cost, what tip was left, which day it was,
> that sort of thing. Get it into this application so you can start asking
> questions about it.

**Done when:** the dataset is loaded and its row/column summary is visible.

Time: ______ Result: ______
Notes:

---

### Task 2 — Ask a first question

> Find out whether people tip differently at lunch than at dinner.

**Done when:** a chart or answer comparing tip by `time` exists.

Time: ______ Result: ______
**Probe after:** *"Do you believe that answer? What would make you more or less
sure?"* — this is the whole trust question for an LLM-driven tool.

Notes:

---

### Task 3 — Change a chart

> You are going to show this to someone else. Make that chart a different type
> of chart, and give it a colour you prefer.

**Done when:** the chart type has changed and a colour has been applied, by any
route (chat, the wand, or the palette panel).

Time: ______ Result: ______
**Watch for:** which of the three routes they find first, and whether they
discover the other two exist.

Notes:

---

### Task 4 — Arrange the canvas

> Add a second chart — anything you find interesting about this data — then
> arrange the two so someone could compare them at a glance.

**Done when:** two charts exist and have been moved or resized deliberately.

Time: ______ Result: ______
Notes:

---

### Task 5 — Keep the work

> You have to stop here and come back to this tomorrow. Do whatever you would do
> to make sure this is all still here when you get back.

**Done when:** they either save deliberately or state that it saves itself.

Time: ______ Result: ______
**This task has no correct answer, and that is the point.** The board autosaves.
What is being measured is whether the interface makes that believable. Record
whether they hunted for a Save control, and whether they trusted the result.

**Probe after:** *"How confident are you that it is saved? What told you?"*

Notes:

---

### Task 6 — The messy file

> Here is a second file, `messy_sales.csv`. A colleague exported it and you have
> not seen it before. Find out which region brought in the most revenue.

**Done when:** a revenue-by-region answer exists.

Time: ______ Result: ______

**Then, before they click anything else, and before you show them anything:**

> Without scrolling back — what, if anything, do you think the system changed
> about that data in order to answer that?

Verbatim answer:

Named the change unprompted? ☐ yes ☐ partly ☐ no

*The file has four real regions spelled thirteen ways, and 15% of the discount
column missing. The disclosure prose exists specifically so this question can be
answered. If five participants cannot answer it, the channel does not work,
however correct its wording is.*

Notes:

---

### Task 7 — Export

> Your supervisor wants this dashboard, and they only ever open PDFs.

**Done when:** a PDF is downloaded.

Time: ______ Result: ______
**Watch for:** whether they find the format menu or expect Export to be a single
button, and whether they check the file afterwards.

Notes:

---

### Task 8 — Recover from a failure

**Set-up: stop the backend before reading this task.** (`Ctrl-C` the API, or
disconnect the network — whichever is quicker to reverse.) Do not tell the
participant anything is wrong.

> Ask it one more question about this data — anything you like.

**Done when:** they have seen the failure and either retried or stated what they
would do.

Time: ______ Result: ______

**Watch for, in order:**
1. Do they understand that it failed, or do they think they are still waiting?
2. Do they blame themselves or the software? (*"Did I type it wrong?"* is a
   finding.)
3. Do they find "Try again"?
4. **Restart the backend without saying so.** Do they press it again? Does it
   work?

Notes:

---

## 5. Debrief — 5 minutes

Ask all four. Write answers verbatim; paraphrase loses the finding.

> **1.** What was the most frustrating moment?

> **2.** Was there anything you expected to be able to do and could not find?

> **3.** If you could change one thing, what would it be?

> **4.** Would you trust a chart from this in something you had to hand in?
> Why, or why not?

---

## 6. System Usability Scale

> Last thing — ten statements. Answer with your immediate reaction rather than
> thinking about them too long. 1 is strongly disagree, 5 is strongly agree.
> Some are worded positively and some negatively, so read each one.

| # | Statement | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|---|
| 1 | I think that I would like to use this system frequently | ☐ | ☐ | ☐ | ☐ | ☐ |
| 2 | I found the system unnecessarily complex | ☐ | ☐ | ☐ | ☐ | ☐ |
| 3 | I thought the system was easy to use | ☐ | ☐ | ☐ | ☐ | ☐ |
| 4 | I think that I would need the support of a technical person to be able to use this system | ☐ | ☐ | ☐ | ☐ | ☐ |
| 5 | I found the various functions in this system were well integrated | ☐ | ☐ | ☐ | ☐ | ☐ |
| 6 | I thought there was too much inconsistency in this system | ☐ | ☐ | ☐ | ☐ | ☐ |
| 7 | I would imagine that most people would learn to use this system very quickly | ☐ | ☐ | ☐ | ☐ | ☐ |
| 8 | I found the system very cumbersome to use | ☐ | ☐ | ☐ | ☐ | ☐ |
| 9 | I felt very confident using the system | ☐ | ☐ | ☐ | ☐ | ☐ |
| 10 | I needed to learn a lot of things before I could get going with this system | ☐ | ☐ | ☐ | ☐ | ☐ |

**Do not reword these.** SUS is comparable across studies only because the
wording is fixed; an edited item makes the score meaningless.

### Scoring

Odd items (1,3,5,7,9): score = **response − 1**
Even items (2,4,6,8,10): score = **5 − response**
SUS = (sum of all ten) **× 2.5**

| Item | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | Sum | ×2.5 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Raw | | | | | | | | | | | — | — |
| Scored | | | | | | | | | | | | |

Range is 0–100 and **is not a percentage**. 68 is the published average.

---

## 7. Close

> That is everything. Thank you — the confusing moments were the useful ones.

- [ ] Recording stopped and saved as `P<n>-YYYY-MM-DD`
- [ ] This sheet completed while the session is fresh — **before the next one**
- [ ] Issues transferred to [`Docs/23 §5.5`](../23-Usability-Evaluation.md)
- [ ] Environment reset for the next participant
