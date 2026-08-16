# 20 — Preprocessing: Before, After, and What's Left

A complete account of six phases of work on the data-preparation layer: what it did before, what
it does now, what that buys, and what is still missing. Benchmarked throughout against Tableau
Desktop / Prep, Power Query and Alteryx.

Where [`Docs/19`](19-Preprocessing-Parity-Roadmap.md) is the engineering record — how each piece
works and why it was built that way — this is the before/after account for anyone deciding what
the layer is now worth and what to fund next.

**Branch:** `feat/preprocessing-hardening`, six commits off `main`.
**Scale:** 46 files changed, +4,255 / −130.
**All figures below are read out of the code, not estimated.**

| | Before | After |
|---|---|---|
| Tests passing | 600 | **738** |
| Cleaning operations | 10 | **14** |
| File formats read | 1 | **8** |
| Defects it can detect | 7 | **9** |
| Silent-drop paths | 3 | **0** |

---

## 1. Where we started

The comparison that started this work found something lopsided. Measured against the incumbents,
AutoViz was **ahead on the thing nobody else does** — telling the user what happened to their
numbers — and **behind on nearly everything upstream of it**.

Tableau and Power Query split data preparation across four layers. We had one and a half.

| Layer | Tableau / Power Query | AutoViz, before |
|---|---|---|
| Connect-time interpretation | Data Interpreter finds the real table under titles and blank rows; encoding, delimiter and locale controls on the connection | `pd.read_csv(path)` — stock defaults, one line |
| Profile-first inspection | Column quality, distribution and profile panes; click a bar to act on it | Profile JSON and plain-language proposals — no interactive surface |
| A recorded, replayable step list | Power Query M, Prep flows; join, union, pivot, split, aggregate, script | The analysis plan — comparable, minus reshape and joins |
| Semantic validation | Data roles (email, URL, geography); fuzzy grouping with a strictness slider | None |

But the comparison ran the other way too, and nothing in the six phases traded any of this away:

| | Tableau / Power Query | AutoViz |
|---|---|---|
| Consent before a change | Steps just run | Risk-tiered, hash-bound approval |
| Disclosure | Read the flow yourself | Sentences composed in Python, unparaphrasable by the model |
| Nulls an aggregate skipped | Silent | Measured before cleaning and stated |
| Top-N ranking | By row frequency | By the measure the chart actually plots |
| A cast that would lose values | Silently nulls them | Refused, with the count |

**The strategy that followed:** fix the missing layer and the correctness bugs; do not soften the
consent model to do it. Every operation added since declares its own risk tier, and the two
genuinely new capabilities that could have been made automatic — reshaping, and reading
placeholder codes as missing — are not.

---

## 2. What shipped

Six phases in dependency order — each needed the one before it. The numbering is the build
sequence, not a ranking.

### 01 — Reading the file at all (`938b250`)

`pd.read_csv(path)` assumed UTF-8, a comma, a header on row 0, a full stop for the decimal point,
and that `NA` means missing rather than Namibia. Each is right most of the time and silently
destructive the rest of it, and nothing recorded which had happened.

Reading is now two steps. A **probe** inspects a bounded 256 KiB sample and decides how the file
should be read; the **reader** reads it with every decision passed explicitly and hands the
decisions back with the frame.

| Was | Now |
|---|---|
| A Windows-1252 export raised an error on upload. A semicolon-delimited European CSV loaded as one text column. | Encoding detected by BOM then a strict-decode ladder; delimiter by field-count consistency, parsed through `csv` so a quoted comma is not a separator. |
| A title row above the table became the column names, and the real header became data. | Spreadsheet furniture above the table is stepped over — our narrow equivalent of Data Interpreter. |
| `1.234,56` stayed text and could never be summed. `NA` in a country column silently deleted Namibia. | European decimals parse as numbers. A column that is 90% two-letter codes opts out of the `NA` token, and says so. |
| CSV only. | `.csv .tsv .txt .xlsx .xlsm .parquet .json .jsonl` — and a workbook names the sheets it did *not* read. |

**The property that makes it worth having.** The list of assumptions is **empty for a well-formed
UTF-8 comma CSV** — verified against all 40 real files in the test corpus, which produce zero
assumptions between them. Anything non-empty becomes an advisory attached to every answer that
file produces. A disclosure that fires on every upload is one nobody reads by the time it matters.

### 02 — Two answers that were wrong, not absent (`8173424`)

The date function returned a bare month number and there was no truncation in the grammar at all.
A monthly revenue line over two years therefore plotted **twelve** points, adding January 2025 to
January 2026. Nothing raised; the chart looked entirely reasonable.

```
// two years of monthly data, grouped by the derived period
month        → 12 points · first = { m: 1,          total: 1202 }   ← 2025 + 2026
month_start  → 24 points · first = { m: 2026-01-01, total:  101 }
```

Both kinds are kept, because both are right for different questions: **truncate for a trend,
extract for seasonality**. The planner guide now says which is which, because the choice is not
inferable from the column.

Separately, `TRY_CAST('$1,234.50')` is null, so the existing cast refused — correctly — and there
was no other route. The commonest financial CSV in existence could not be summed. `parse_number`
handles currency marks, thousands separators and European notation, and stays safe by stripping a
*closed set* of decoration and then requiring the remainder to convert in full.

| Was | Now |
|---|---|
| `'$1,234.50'` — unanalysable. No op in the grammar could read it. | `'$1,234.50' → 1234.50`, and `'12 apples'` is *refused* rather than quietly returning 12. |
| A column with case variants *and* 300 categories only ever reported the casing. The grouping question was never asked. | The two findings are independent, and cardinality is judged on the folded count — the number of bars the chart actually has to draw. |

### 03 — Disclosing the work that did not happen (`ccb67ba`)

Three paths dropped work in silence. Each limit is defensible; being invisible was not — in a tool
whose whole thesis is disclosure, this was the sharpest internal inconsistency in the codebase.
The user could not tell a decision that had been made from one that had been skipped.

| What got dropped | Before | After |
|---|---|---|
| Repairs cut by the step budget | Silent | Named, with the columns left untouched |
| Cleaning questions cut by the prompt cap | Silent | Reported, with what happened instead |
| Rows cut by the output ceiling | Silent | Reported, so totals are known to describe the rows shown |

The same commit fixed an operation that was safe in meaning and wrong in presentation. Case
folding used `lower()`, which merged the variants and rewrote every label with them — so a country
axis read `usa` and `canada`, a defect introduced by a repair the user never asked for. It now
folds to the column's **commonest spelling**, the way Tableau's grouping does.

### 04 — The shape of the file was itself a limit (`68f0bf8`)

A file with one column per month could not answer *"revenue by month"* at all. Grouping takes
values; in a wide file the month is a header. That is the commonest real spreadsheet export, and
the grammar had no way to express it.

`pivot_longer` folds repeated columns into rows; `split_column` splits text into parts and keeps
the source. Both are safe — neither alters, invents nor discards a value — but neither is ever
proposed automatically, because whether twelve columns are one repeated measurement is a question
about what the data *means*, which the data cannot answer.

**The real work was underneath.** These are the first operations that change the table's *shape*,
and the old mechanism could only express retyping. It was replaced by a per-operation schema
declaration — the same pattern risk and row-behaviour already follow. Validation now walks the
operations evolving the schema as it goes, so each is checked against the table the previous ones
left: a filter on a pivoted column validates, and a trim of a column already cast to a number is
rejected at plan time rather than failing at execution.

### 05 — Semantic validation, our way (`1122d56`)

The layer Tableau calls data roles — done as **detection**, with a repair offered only where one
honestly exists.

| Finding | What the user is given |
|---|---|
| Numeric placeholder (`999`, `-1`) | A question, recommending "treat as missing" |
| Text placeholder (`unknown`, `-`, `?`) | The same question |
| Malformed value in a mostly-valid email column | An advisory only — nothing can invent the right address |

**A sentinel is worse than a null.** A null is skipped by every aggregate and disclosed when it
matters; a `999` meaning "not recorded" is averaged in and the answer is wrong with nothing to
show for it. Nothing in the grammar could turn one into the other, since dropping and filling both
need the value to already be null.

Detection needs **two** conditions and neither is sufficient alone: the value must be a known code
*and* sit far outside the column's own distribution. `999` is a placeholder among ages and an
ordinary reading among prices, so the code list cannot decide; plenty of genuine outliers are not
codes, so distance cannot either.

Imputation also learned to respect groups. A global median flattens exactly the variance a grouped
chart exists to show — in the test fixture it pulled Sales from 520 to 447.

### 06 — The recipe can now be re-pointed (`3c62dbb`)

Cleaning was already reproducible — the plan is the recipe and the source is immutable — but there
was no way to point an existing block at *different rows*, which is the actual recurring task: the
same report arrives monthly and has to be prepared the same way. This is the capability Tableau
sells as Prep Conductor.

Two refusals carry the weight, and both are the point rather than the caveat:

- **Column compatibility is checked first, by name.** A recipe run against a renamed file fails
  loudly, because cleaning nothing would hand back a dataset that looks prepared and is raw.
- **Consent does not transfer.** The approval token is bound to the dataset and the operations
  together, so a removal that took 1 of 5 rows last month re-gates against a file where the same
  rule takes 4 of 5.

The quality scan is also memoized per column scope. It was re-reading the frame on every call —
0.27 s on a 200,000-row file — and the agent scans once per pass plus once per question it asks.

---

## 3. What the work uncovered

Worth separating honestly: defects that were already live in `main`, and mistakes in the new code
caught before shipping. Every one in the first group was found by checking *output* rather than
exit codes — none of them raised an error.

### Latent defects found in existing code

| Defect | What it did |
|---|---|
| Month extraction with no truncation | Collapsed multi-year trends into 12 points, summing across years |
| Over-eager date coercion | `2026-Q3`, bare years, product codes and version strings all became datetimes |
| Cardinality masked behind case variants | The grouping question could never be asked for a column with both problems |
| Case folding rewrote display labels | Chart axes read `usa` instead of `USA` |
| Three silent-drop paths | Skipped repairs, skipped questions and truncated results all went unreported |
| Currency columns unreachable | No operation in the grammar could read `$1,234.50` as a number |

### Caught during development, before shipping

| Mistake | Found by |
|---|---|
| pandas counts `header=N` *after* dropping blank lines, so a blank spacer promoted the first data row to column names | A fixture asserting the recovered table |
| A byte sample cut mid-character demoted a good UTF-8 file to Windows-1252 | Reasoning about the sample boundary, then a test |
| The chart encoder kept its own copy of the type mapping, so a truncated period reached it as a linear axis | A pipeline-level test two phases later |
| A frequency tie picked `MALE` over `Male` because capitals sort first | Reading the failing assertion rather than just updating it |

---

## 4. What this buys

Four kinds of gain, in descending order of how much they matter to someone actually using the tool.

**1 — Files that used to fail now open.** The largest single bucket of "it just didn't work" was
encoding, delimiter, decimal convention and spreadsheet furniture — four failures that all
happened before a single question could be asked. A Windows-1252 export, a European semicolon CSV,
an Excel workbook and a file with a title block above the table are all now ordinary inputs.

**2 — Charts that were confidently wrong are now right.** This is the most valuable class, because
it is the one the user could not have caught. A two-year trend that silently added last January to
this January produced a plausible chart and a wrong number. So did an average over a column where
`999` meant "not recorded". Both are now correct by construction, and both were found by this work
rather than reported by a user.

**3 — Whole categories of file became analysable.** Wide spreadsheet exports and money columns were
not *badly* handled before — they were impossible. Reshaping and number parsing move them from
"unsupported" to "ordinary", which is a larger change than any accuracy improvement.

**4 — The differentiator is now whole.** The consent-and-disclosure model was the strongest thing
about the product and had three holes in it. Closing them matters more than it sounds: a
disclosure system that is silent in some cases teaches users that silence means nothing happened,
which devalues every disclosure it *does* make. It is now the case that if the system did
something to your numbers, or declined to, it says so.

### Capability, before and after

| Capability | Before | After |
|---|---|---|
| Non-UTF-8 file | Error on upload | Detected and disclosed |
| Semicolon / European decimals | One text column | Parsed as numbers |
| Title rows above the table | Corrupted column names | Stepped over |
| Excel, Parquet, JSON | Unsupported | Supported |
| Currency column | Not aggregatable | `parse_number` |
| Multi-year monthly trend | Silently wrong | Correct |
| Wide (one column per period) | Unanalysable | `pivot_longer` |
| Compound text field | Unanalysable | `split_column` |
| Placeholder codes in a measure | Averaged in silently | Detected and offered |
| Malformed values in a typed column | Undetected | Flagged as advisory |
| Imputation inside a grouping | Global only | Group-wise median |
| Reapplying a cleaning recipe | Manual restatement | One call, re-gated |
| Repeated quality scan | Full cost every turn | Memoized |

---

## 5. What is still weak

Stated with the same weight as the wins, because a report that buries its gaps is doing the thing
this whole project exists to stop. Three of these are real limitations a user will hit; the rest
are bounded.

### One table at a time — no joins or unions · **largest gap**

The biggest remaining difference from Tableau. Any question spanning two files is unanswerable.
Deferred at every phase because single-table correctness is where every live bug turned out to be
— and each of the last two phases found two more. The cost of adding it is real: join-key
validation, fan-out row explosion, and ambiguous column names all arrive together.

### Bounded by memory — no streaming, no pushdown · **scale ceiling**

The frame is materialised in pandas before the query engine sees it, capping uploads at 50 MiB and
a million rows. DuckDB-native ingestion was scoped into phase six and **deliberately cut**: it
conflicts with the frame contract every other phase preserved, and it buys scale rather than
correctness. It needs its own branch and its own re-validation of column typing across the suite.

### Files only — no live database connections · **architectural**

Everything is an upload. There is no equivalent of a live connection, no incremental refresh, and
no scheduled run: recipe replay exists but must be triggered by hand. For a genuinely recurring
report this is the difference between a tool and a pipeline.

### No interactive profile pane · **UX**

Power Query's click-a-bar-to-act surface has no counterpart. We compute the profile and ask good
questions about it, but the user cannot explore a column's distribution and act on what they see.
The frontend also does not yet surface the new ingest report or the four new operations — that
work was deferred to avoid colliding with an in-flight branch.

### Detection is pattern-based, not reference-based · **bounded**

Data roles cover email and web addresses — the two domains decidable from the value alone. Country
and currency validation needs a reference list, which is a judgement about the world rather than
about the string. Sentinel detection likewise uses a fixed code list, so an unusual placeholder
such as `-8888` is missed.

### Narrow reshape and imputation · **bounded**

Folding requires the columns to share one type, and there is no reverse operation. Group-wise
imputation is median-only — a deterministic per-group mode needs a second window pass — and there
is no forward-fill for time series. Header detection handles furniture above the table but not
multi-row or merged headers.

### No cross-field or referential validation · **not started**

Nothing checks that an end date follows a start date, or that a foreign key resolves. Every check
is still within a single column.

### No fuzzy grouping · **by design**

`UK` and `United Kingdom` still need an explicit mapping. This is a genuine capability gap against
Tableau's strictness slider and it is **not planned**: a similarity merge that silently combines
two real categories is precisely what the consent model exists to prevent. If it is ever added it
must be a reviewable diff of every proposed merge.

### Percentages are refused outright · **by design**

`45%` is either 45 or 0.45 and the column does not say which, so number parsing rejects it rather
than guessing. Defensible, and still a dead end for a percentage column until an explicit flag is
added.

---

## 6. The order to take these in

If the gaps above are worked through, this is the sequence the current architecture suggests —
cheapest-and-most-visible first, largest-surface-area last.

1. **Surface it in the UI.** The ingest report, the four new operations and the sentinel proposals
   all exist and are invisible to a user of the web client. Highest value per hour of any item here.
2. **Percentage handling and a user-supplied reference list.** Both are small, bounded, and remove
   two named dead ends.
3. **DuckDB-native ingestion.** Its own branch. Lifts the size ceiling and brings streaming and
   projection pushdown, at the cost of re-validating typing everywhere.
4. **Scheduled recipe runs.** Recipe replay plus a trigger is the whole feature; it turns a tool
   into a pipeline.
5. **Joins and unions.** Last, and only once the single-table layer has stopped producing bugs.

---

## Where the detail lives

[`Docs/19`](19-Preprocessing-Parity-Roadmap.md) carries the engineering record. The test modules
double as the specification, and read in this order:

`test_ingest` → `test_date_truncation` → `test_reshape` → `test_semantic_quality` →
`test_recipe_replay`.
