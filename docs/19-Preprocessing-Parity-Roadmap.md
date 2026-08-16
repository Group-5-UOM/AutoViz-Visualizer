# 19 — Preprocessing Parity: Ingestion, Correctness, Disclosure

Where AutoViz's data preparation stands against Tableau Desktop/Prep, Power Query and Alteryx —
what was missing, what is **implemented** on `feat/preprocessing-hardening`, and what is
deliberately still open.

Six commits, one per problem class. Every behaviour below is enforced in code and covered by
tests. Suite: **600 → 738 passing**.

---

## 1. What the comparison actually found

The incumbents split preparation across four layers:

| Layer | Tableau / Power Query | AutoViz before |
|---|---|---|
| Connect-time interpretation | Data Interpreter: finds the real table under titles, footers and blank rows; encoding/delimiter/locale controls on the connection | `pd.read_csv(path)`, stock defaults |
| Profile-first UI | Column quality / distribution / profile panes; click a bar to act on it | profile JSON, no interactive pane |
| A recorded, replayable step list | Power Query M, Prep flows; join, union, **pivot**, split, aggregate, script | the analysis plan (comparable), minus reshape and joins |
| Semantic validation | Data roles (email, URL, geography), fuzzy grouping with a strictness slider | none |

We had layer three and half of layer two. **Layer one was one line of code.**

But the comparison also found the reverse. On the axis the incumbents ignore, we were already
ahead, and nothing here was traded away to close the gap:

| | Tableau / Power Query | AutoViz |
|---|---|---|
| Consent | steps just run | risk-tiered, hash-bound approval (`preprocessing_version`) |
| Disclosure | read the flow yourself | sentences composed in Python, unparaphrasable by the LLM |
| Nulls skipped by an aggregate | silent | measured pre-cleaning and stated ([`Docs/14`](14-Disclosure-and-Outlier-Handling.md)) |
| Top-N ranking | by row frequency | by the measure the chart plots (`rank_by`) |
| A lossy cast | silently nulls the values | refused, with the count |

The strategy follows from that split: **fix layer one and the correctness bugs; do not soften the
consent model to do it.**

---

## 2. Reading a file (`services/ingest.py`)

`pd.read_csv(path)` assumed UTF-8, a comma, a header on row 0, a full stop for the decimal point,
and that `NA` means missing rather than Namibia. Each assumption is right most of the time and
silently destructive the rest of it, and none of them were recorded.

Reading is now two steps. `probe` inspects a bounded 256 KiB sample and decides how the file
should be read; `read_table` reads it with every decision passed **explicitly** and returns the
decisions alongside the frame.

| Hazard | How it is settled |
|---|---|
| Encoding | BOM first (definitive), then a strict-decode ladder: UTF-8 → cp1252 → latin-1 |
| Delimiter | Field-count consistency across the sample, parsed through `csv` so a quoted comma is not a separator. `csv.Sniffer` only breaks ties |
| Header position | First row with the table's field count, no empty cells, and a same-width row beneath it |
| European decimals | `1.234,56` behind a `;` delimiter — the comma is only free to be a decimal point when it is not the separator |
| `NA` = Namibia | A column ≥90% two-letter uppercase codes opts out of that one token, per-column |
| Day-first dates | Read off the data (`25/12` proves it) and threaded into `_coerce_datetimes` |
| Other formats | `.xlsx` (naming the sheets it did *not* read), `.parquet`, `.json` |

### The property that makes it worth having

`IngestReport.assumptions` lists only the choices a reader could dispute, and it is **empty for a
well-formed UTF-8 comma CSV**. Verified against all 40 real files in `test-data/`, which produce
zero assumptions between them. A disclosure that fires on every upload is one nobody reads by the
time it matters.

Anything non-empty becomes an `ADVISORY` notice on every answer the file produces — a semicolon
read as a decimal point is as wrong on the tenth chart as the first.

### Two bugs the fixtures caught

Both were found by checking the output rather than the exit code, which is the whole reason
`test-data/synthetic-ingest/` holds the *same table* nine times:

1. **pandas counts `header=N` after dropping blank lines.** A blank spacer above a table shifted
   the index and promoted the first data row to column names. Now `skiprows` + `header=0`, which
   counts raw lines — the thing the probe actually measured.
2. **A byte sample cut mid-character** made a strict UTF-8 decode raise, demoting a good UTF-8
   file to cp1252 on the strength of where the 256 KiB boundary landed. The sample is now trimmed
   to its last newline first.

---

## 3. Two answers that were wrong, not absent

### 3.1 Trends collapsed across years

`_DERIVE_SQL["month"]` was `date_part`, a bare 1–12, and there was no `date_trunc` in the grammar
at all. A monthly revenue line over two years therefore plotted **twelve** points, adding January
2025 to January 2026. Nothing raised; the chart looked entirely reasonable.

Added `month_start` / `quarter_start` / `week_start` / `year_start`, which truncate and stay
datetimes. They needed a new `DATETIME_DERIVE_FNS` branch in validation — the existing line typed
every date derive as a number, which would have admitted `mean(month_start)` and put a period on
a quantitative axis.

Both kinds are kept, because both are right for different questions, and the plan guide now says
which is which: **truncate for a trend, extract for seasonality.**

```
month        -> 12 points; first = {m: 1,            total: 1202}   # 2025 + 2026
month_start  -> 24 points; first = {m: 2025-01-01,   total: 101}
```

### 3.2 Money columns could not be analysed at all

`TRY_CAST('$1,234.50' AS DOUBLE)` is null, so `cast_column` refused — correctly — and there was no
other route. The commonest financial CSV in existence could not be summed.

`parse_number` handles currency marks, thousands separators and European notation. It is SAFE
because of *how* it strips, not how little: only a **closed set** of decoration is removed, and
whatever remains must convert in full.

```
'$1,234.50'  -> 1234.50        '1.234,50' (decimal=',') -> 1234.50
'12 apples'  -> refused        '45%'                    -> refused
```

`12 apples` becoming `12` and being reported as a successful repair is exactly the failure a
permissive "strip everything non-numeric" would produce. Percentages are refused because `45%` is
either 45 or 0.45 and the column does not say which.

### 3.3 A question that could never be asked

`quality.scan` tested cardinality in an `elif` after case variants, so a column with **both** only
ever reported the first. `normalize_case` then repaired the spellings silently, the grouping
proposal was never raised, and the user got 300 unreadable categories with nothing appearing to
have gone wrong.

The findings are now independent, and cardinality is judged on the **folded** count — the number
of bars the chart actually has to draw.

---

## 4. Disclosing the work that did not happen

Three paths dropped work in silence. Each limit is defensible; being invisible was not.

| Path | Now |
|---|---|
| Repairs cut by `MAX_PREPROCESSING_STEPS` | `merge_auto_ops` returns `(merged, dropped)`; the cut ones are named |
| Questions cut by `MAX_CLEANING_PROMPTS` | reported, with what happened instead ("nothing was changed") |
| Rows cut by `HARD_ROW_CEILING` | reported, so totals are known to describe the rows shown |

The first two have no preprocessing report to ride on — nothing ran — so they travel out of
`assess_quality` on `WorkerState.cleaning_notices` and are attached in `finalize_worker` on
**every** branch: a run that failed at the chart step still skipped those repairs.

### `normalize_case` stopped shouting

It was SAFE in meaning and wrong in presentation. `lower()` merged the variants and rewrote every
label with them, so a country axis read `usa` and `canada` — a defect introduced by a repair the
user never asked for.

It now folds to the column's **commonest spelling**, which is what Tableau's grouping does. Ties
break toward the spelling that reads as a label (`Male` over `MALE`, which is what value order
alone picked) and then on value order, so nothing depends on scan order.

Six tests changed their expected labels. The values were identical in every one.

---

## 5. Reshape: the shape of the file was itself a limit

A file with one column per month could not answer "revenue by month" **at all**. `group_by` takes
values; in a wide file the month is a header. That is the commonest real spreadsheet export, and
the grammar had no way to express it.

`pivot_longer` folds repeated columns into rows; `split_column` splits text into parts and keeps
the source. Both are SAFE — neither alters, invents nor discards a value — but neither is ever
proposed automatically, because whether twelve columns are one repeated measurement is a question
about what the data *means*, which the data cannot answer.

The real work was underneath. These are the first ops that change the table's **shape**, and
`preprocessing_type_overrides` could only express retyping. It is replaced by `op.apply_schema`,
declared per-op exactly as `risk` and `removes_rows` already are, and folded into
`AnalysisPlan.preprocessing_schema`. Validation now walks the ops evolving the schema as it goes,
so each op is checked against the table the previous ones left: a filter on a pivoted column
validates, and a trim of a column already cast to a number is rejected at plan time instead of
failing at execution.

### Two more bugs, neither of which raised anything

- The **chart encoder kept its own copy** of the derive-type mapping, so §3.1's `month_start`
  arrived as `quantitative` and put an ISO timestamp on a linear axis. Validation had been fixed;
  this had not. Only a `run_pipeline` test could see it.
- `_coerce_datetimes` promoted anything pandas could parse, so `"2026-Q3"` became a datetime —
  discovered by a `split_column` test. Bare years, product codes and version strings did the same.
  A value must now **look** like a date before it is allowed to be one; all six real datetime
  columns in `test-data/` still promote.

---

## 6. Semantic validation, our way

The layer Tableau calls data roles — done as **detection**, with a repair offered only where one
honestly exists.

| Finding | Offered |
|---|---|
| Numeric placeholder (`999`, `-1`) | A question, recommending "treat as missing" (`nullify_values`) |
| Text placeholder (`"unknown"`, `"-"`, `"?"`) | The same question |
| Malformed value in a mostly-valid email/URL column | An **advisory only** — nothing can invent the right address |

**A sentinel is worse than a null.** A null is skipped by every aggregate and disclosed when it
matters; a 999 meaning "not recorded" is averaged in and the answer is wrong with nothing to show
for it. Nothing in the grammar could turn one into the other — `drop_nulls` and `fill_nulls` both
need the value to already be null — hence `nullify_values`.

Detection needs **two** conditions and neither is sufficient alone: the value must be a known code
**and** sit far outside the column's own distribution. 999 is a placeholder among ages and an
ordinary reading among prices, so the code list cannot decide; plenty of genuine outliers are not
codes, so distance cannot either. Most of the tests in `test_semantic_quality.py` are about what
must *not* be flagged, because a detector that fires on real data trains the user to dismiss the
question — which costs more than never asking.

The proposal **recommends** treating a code as missing, unusually for a value-changing op. The
asymmetry is the point: counting a code as a measurement corrupts every average over the column,
while treating a genuine 999 as missing costs a few rows from an aggregate that already discloses
its exclusions. The cheap mistake is the one to default to.

**Group-wise imputation.** `fill_nulls` grows a `by`. A global median flattens exactly the variance
a grouped chart exists to show — in the test fixture it pulled Sales from 520 to 447. Median only:
a deterministic per-group mode needs a second window pass, and an arbitrary tie-break is what this
codebase refuses everywhere else, so it is rejected rather than silently falling back to a global
fill. A group with no recorded values has no median, so those rows stay null and the notice says so.

---

## 7. Reuse: the recipe can now be re-pointed

`preprocessing_version` already made cleaning reproducible, but there was no way to point an
existing block at *different rows* — which is the actual recurring task. `apply_cleaning_recipe`
reads the block out of a materialised dataset's lineage and reapplies it to a new upload
(`POST /datasets/{id}/apply-recipe`, and an MCP tool).

Two refusals carry the weight:

- **Column compatibility is checked first, by name.** A recipe run against a renamed file fails
  loudly, because cleaning nothing hands back a dataset that looks prepared and is raw.
- **Consent does not transfer.** The token is bound to `(dataset_id, ops)`, so a removal that took
  1 of 5 rows last month re-gates against a file where the same rule takes 4 of 5. That falls out
  of `preprocessing_version` rather than being re-implemented — exactly the kind of inherited
  safety that quietly stops holding, so a test pins it.

`quality.scan` is also memoized per column scope on the record: it was re-reading the frame on
every call (0.27s on 200k rows) and the agent scans once per pass plus once per question it asks.
Sound because the frame is immutable. The cache lives on the record, so eviction discards it —
a reloaded frame re-derives rather than trusting an answer computed against something else.

---

## 8. Still open, deliberately

| Gap | Why not yet |
|---|---|
| **Joins and unions** | The biggest remaining capability gap and the biggest surface-area increase: key validation, fan-out row explosion, ambiguous column names. Deferred throughout because single-table correctness was where every live bug turned out to be — and §3 and §5 each found two |
| **DuckDB-native ingestion** | **Cut from this branch on purpose.** It conflicts with the DataFrame contract every other phase preserved (`registry` eviction, Parquet blobs, `con.register("df_raw", …)` all assume a pandas frame), and it buys scale rather than correctness — the 50 MiB cap is not currently binding. It deserves its own branch and its own re-validation of typing across the suite, not a rushed sixth commit |
| **Reference-list data roles** (countries, currencies) | The two implemented domains are decidable from the value alone. A country list is a judgement about the world, not about the string, and belongs to a user-supplied reference list — which is a feature, not a regex |
| **Fuzzy auto-grouping** | **Not planned.** `Risk.AMBIGUOUS` already encodes the stance: a Levenshtein merge that silently combines two real categories is precisely what the consent model exists to prevent. If ever added it must be a reviewable diff of every proposed merge, never a slider |

---

## 9. Files

| Path | Role |
|---|---|
| [`services/ingest.py`](../backend/src/autoviz/services/ingest.py) | probe + readers + the resource ceilings that bound them |
| [`services/notices.py`](../backend/src/autoviz/services/notices.py) | `from_ingest`, `from_dropped_repairs`, `from_unasked_proposals`, `from_row_ceiling` |
| [`services/quality.py`](../backend/src/autoviz/services/quality.py) | independent cardinality finding; `merge_auto_ops` reports what it cut |
| [`services/execution.py`](../backend/src/autoviz/services/execution.py) | `date_trunc` derives, `parse_number`, canonical-spelling folding |
| [`schema/analysis_plan.py`](../backend/src/autoviz/schema/analysis_plan.py) | `ParseNumber`, `PivotLonger`, `SplitColumn`, `NullifyValues`, `op.apply_schema`, the truncating derive fns |
| [`test-data/synthetic-ingest/`](../test-data/synthetic-ingest/) | one table, nine reading hazards |

Reading order for the tests, which double as the specification:
[`test_ingest.py`](../backend/tests/test_ingest.py) →
[`test_date_truncation.py`](../backend/tests/test_date_truncation.py) →
[`test_reshape.py`](../backend/tests/test_reshape.py) →
[`test_semantic_quality.py`](../backend/tests/test_semantic_quality.py) →
[`test_recipe_replay.py`](../backend/tests/test_recipe_replay.py).
