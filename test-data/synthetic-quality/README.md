# Synthetic data-quality & skew fixtures

Everything else in `test-data/` is real, unmodified public data. **These two files are not.** Each
column exists to trip exactly one code path in the cleaning-disclosure and axis-scaling layers
(see [`Docs/14`](../../Docs/14-Disclosure-and-Outlier-Handling.md)), at a size that lands on the
right side of the threshold that path uses.

Real data cannot be relied on to do that. A fixture whose defects are accidental stops testing what
you think it tests the moment someone swaps the file.

| File | Rows | Size | Purpose |
|---|---|---|---|
| `messy_sales.csv` | 246 | 17 KiB | Feature check — every path fires, small enough to read by eye |
| `messy_sales_large.csv` | 205,000 | 14 MiB | Throughput. **Not committed** — run `generate.py` |

```bash
python test-data/synthetic-quality/generate.py
```

Deterministic (seeded), so a regenerated file is byte-identical and a diff means a real change.

## Schema

| Column | Type | Planted defect |
|---|---|---|
| `order_id` | int | — clean |
| `order_date` | date | — clean, 365 days |
| `region` | string | Case variants + leading/trailing spaces ("North", "north", "  North", "NORTH") |
| `channel` | string | — clean, 4 values |
| `product_line` | string | — clean, 6 values |
| `sales_rep` | string | **32 distinct** — over the 25 that makes a chart unreadable |
| `units` | int | — clean |
| `revenue` | float | **1 in 120 rows is ~1000× the rest** — the headline skew |
| `profit_delta` | float | Skewed **and crosses zero** — the case `log` cannot represent |
| `discount_pct` | float | **~14% null** — over 5%, under 30% |
| `customer_note` | string | **~46% missing**, split 34% true blank / 12% whitespace-only |

Plus ~2.5% exact duplicate rows.

## What each defect should produce

Verified against `messy_sales.csv` at 246 rows.

### Applied silently (SAFE — reported, never asked)

```
trim_whitespace       on region, customer_note
empty_string_to_null  on customer_note
normalize_case        on region
```

### Asked about (value-changing — needs an answer)

| Question | Why it is a question |
|---|---|
| 82 of 246 rows (33.3%) have no customer note | Excluding vs. keeping changes the row set |
| 36 of 246 rows (14.6%) have no discount pct | Same, and above the 5% notice line |
| 6 of 246 rows are exact copies | Repeated rows can be genuine repeated events |
| sales rep has 32 different values | Grouping the tail erases whichever rep you wanted |

Note the split in `customer_note`: 34% are true blanks and read as null immediately, while the
whitespace-only 12% only become null **after** `empty_string_to_null` runs. That is deliberate —
it distinguishes a scan of the raw file from a scan of the cleaned view.

### Axis scaling

| Chart | Result |
|---|---|
| `line` — revenue over time | `y` → **log**, advisory notice |
| `scatter` — profit vs revenue | `x` → **log**, `y` → **symlog** (crosses zero), two notices |
| `heatmap` — revenue by channel × product | `color` → **log**, `skewed_color` notice |
| `bar` — revenue by channel | **No scale change.** Bars keep linear heights by design |

`bar` by channel produces no notice at all, and that is correct rather than a gap: summing ~60
orders per channel averages the whales away, so the four bars are genuinely similar. It is a live
demonstration that skew is judged on the **plotted** values, not the source column.

To see the bar-chart advisory (disclosed, never rescaled), group by something narrower —
`sales_rep`, where one rep carries a whale.

### Confirmation gate

`drop_nulls` on `customer_note` alone removes 33.3% of rows, over the 30% ceiling:

```
status: confirmation_required
"This cleaning step would remove 82 of 246 rows (33.3%). Proceed?"
```

Pass `confirmation.preprocessing_hash` back as `approved_preprocessing_hash` to continue.

## Questions to ask the running app

Upload `messy_sales.csv` and try these — each targets one behaviour:

1. *"Show revenue over time"* → log axis + advisory in the reply
2. *"Plot profit delta against revenue"* → log **and** symlog on the two axes
3. *"Heatmap of revenue by channel and product line"* → log colour scale
4. *"Total revenue by channel"* → no scaling; clean bars
5. *"Average discount by channel"* → cleaning disclosure in the answer
6. *"Revenue by sales rep"* → the 32-category question
7. *"Revenue by region"* → case variants merged silently, mentioned as routine tidying

The reply should **say** what it did. If a chart comes back log-scaled with no explanation, or an
average is reported over an imputed column with no caveat, that is the bug this fixture exists to
catch.

## Measured throughput

`messy_sales_large.csv`, 205,000 rows × 11 columns (14 MiB), warm process, local DuckDB:

| Operation | Time |
|---|---|
| Register + profile | ~1.1 s |
| Quality scan, all 11 columns | ~190 ms |
| Aggregate + bar (4 groups) | ~440 ms |
| Aggregate + heatmap (24 cells) | ~410 ms |
| 3 cleaning ops + aggregate | ~850 ms |
| Scatter, 100,000 raw points | ~670 ms |

Two things worth knowing when reading these:

- **First call in a fresh process is not representative** — imports and DuckDB warm-up add ~2 s.
  Measure the second call.
- **The large file does not fire the heatmap advisory**, while the 246-row file does. Not a
  regression: 1-in-120 whales across 205k rows means ~8,500 orders per cell, so every cell is
  similarly large and the skew is genuinely gone. Aggregation destroying skew is the reason
  detection runs on the result table rather than the source column. The large file still fires on
  `scatter`, which plots raw rows.

Limits for context (`services/dataset.py`): 50 MiB file, 1M rows, 512 columns; execution results
are capped at 100,000 rows.
