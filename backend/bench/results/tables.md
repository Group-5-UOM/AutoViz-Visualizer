
## Performance

*Measured 2026-08-16T11:02:24 on Windows-11-10.0.26200-SP0, 16 logical cores, Python 3.12.13, DuckDB 1.5.5, pandas 3.0.3. Peak resident set for the whole run: 897.2 MiB.*

### Ingest — file on disk to queryable dataset

| Rows | CSV MiB | In RAM MiB | Read ms | Profile ms | Total ms |
|---|---|---|---|---|---|
| 1,000 | 0.10 | 0.13 | 7.72 | 18.01 | 25.73 |
| 10,000 | 0.95 | 1.33 | 26.50 | 53.80 | 80.30 |
| 100,000 | 9.50 | 13.34 | 213.1 | 424.0 | 637.0 |
| 500,000 | 47.50 | 66.68 | 1,134.4 | 2,137.6 | 3,272.0 |
| 1,000,000 | 94.99 | — | — | — | **refused** (RESOURCE_LIMIT) |

### Query latency by plan shape (median ms, `execute_analysis`)

| Plan shape | 1,000 | 10,000 | 100,000 | 500,000 | 1,000,000 | Rows out (max scale) |
|---|---|---|---|---|---|---|
| Projection + limit (1k rows out) | 28.99 | 27.69 | 33.02 | 31.49 | 36.32 | 1,000 |
| Filter + projection (1k rows out) | 21.90 | 25.67 | 33.70 | 54.04 | 79.53 | 1,000 |
| Group by 1 key, sum (5 groups) | 21.86 | 19.18 | 24.97 | 34.87 | 50.04 | 5 |
| Group by 2 keys, 2 aggregates (60 groups) | 20.89 | 21.68 | 27.72 | 50.15 | 76.13 | 60 |
| Group by high-cardinality key (n/8 groups) | 20.92 | 26.97 | 91.91 | 347.6 | 570.6 | 100,000 |
| Group by 1 key, median | 20.66 | 21.31 | 27.02 | 43.63 | 73.33 | 5 |
| Group by 1 key, count_distinct | 21.36 | 29.42 | 37.09 | 76.59 | 134.3 | 5 |
| Derive month_start + group + sum (36 points) | 21.17 | 25.94 | 25.70 | 43.69 | 68.77 | 36 |
| Filter + group + sort + limit 10 (“top 10”) | 19.93 | 21.71 | 27.00 | 54.21 | 89.35 | 10 |
| Cleaning block (3 ops) + group + sum | 51.84 | 86.07 | 197.8 | 856.9 | 1,830.2 | 5 |

### The scan-source change, on `execute_analysis` itself

| Rows | Shape | pandas scan ms | Arrow scan ms | Speed-up |
|---|---|---|---|---|
| 1,000 | agg_2key | 25.24 | 23.21 | 1.09x |
| 1,000 | derive_trend | 23.47 | 21.02 | 1.12x |
| 1,000 | top_n | 24.04 | 20.83 | 1.15x |
| 10,000 | agg_2key | 37.74 | 21.77 | 1.73x |
| 10,000 | derive_trend | 39.03 | 20.55 | 1.9x |
| 10,000 | top_n | 36.34 | 22.16 | 1.64x |
| 100,000 | agg_2key | 237.0 | 33.99 | 6.97x |
| 100,000 | derive_trend | 187.9 | 24.74 | 7.6x |
| 100,000 | top_n | 188.4 | 27.38 | 6.88x |
| 500,000 | agg_2key | 1,100.0 | 50.10 | 21.96x |
| 500,000 | derive_trend | 1,142.3 | 58.59 | 19.5x |
| 500,000 | top_n | 900.3 | 60.32 | 14.93x |
| 1,000,000 | agg_2key | 2,099.2 | 80.53 | 26.07x |
| 1,000,000 | derive_trend | 2,148.4 | 65.78 | 32.66x |
| 1,000,000 | top_n | 1,909.8 | 83.03 | 23.0x |

### Where a query's time goes

| Rows | New connection ms | Expose frame (pandas) ms | Expose frame (Arrow) ms | Query ms | One-off conversion ms |
|---|---|---|---|---|---|
| 1,000 | 12.95 | 3.75 | 0.70 | 2.51 | 0.69 |
| 10,000 | 12.63 | 10.30 | 0.72 | 2.77 | 2.15 |
| 100,000 | 12.17 | 83.58 | 0.72 | 6.78 | 2.60 |
| 500,000 | 11.79 | 459.6 | 0.70 | 24.73 | 3.47 |
| 1,000,000 | 14.69 | 995.7 | 0.73 | 50.95 | 5.04 |

### Memory

| Rows | Frame MiB | Added RSS for the Arrow view MiB | Its logical size MiB |
|---|---|---|---|
| 1,000 | 0.13 | 0.00 | 0.10 |
| 10,000 | 1.33 | -1.00 | 1.30 |
| 100,000 | 13.34 | 0.00 | 13.30 |
| 500,000 | 66.68 | 0.00 | 66.70 |
| 1,000,000 | 133.4 | 0.20 | 133.5 |

### Delivering the result (`sanitize_records` + JSON)

| Rows out | Cols | Cells | Serialize ms | µs/cell | Payload MiB |
|---|---|---|---|---|---|
| 100 | 11 | 1,100 | 3.61 | 3.28 | 0.03 |
| 100 | 2 | 200 | 0.77 | 3.85 | 0.00 |
| 1,000 | 11 | 11,000 | 24.02 | 2.18 | 0.25 |
| 1,000 | 2 | 2,000 | 4.43 | 2.21 | 0.05 |
| 10,000 | 11 | 110,000 | 257.9 | 2.35 | 2.52 |
| 10,000 | 2 | 20,000 | 49.00 | 2.45 | 0.50 |
| 50,000 | 11 | 550,000 | 1,435.9 | 2.61 | 12.59 |
| 50,000 | 2 | 100,000 | 276.5 | 2.77 | 2.49 |
| 100,000 | 11 | 1,100,000 | 2,718.8 | 2.47 | 25.17 |
| 100,000 | 2 | 200,000 | 512.5 | 2.56 | 4.97 |

### Chart construction

| Rows plotted | Recommend ms | Build spec ms | Spec size | Valid |
|---|---|---|---|---|
| 12 | 0.01 | 0.11 | 3 KiB | yes |
| 100 | 0.01 | 0.18 | 6 KiB | yes |
| 1,000 | 0.01 | 1.03 | 41 KiB | yes |
| 10,000 | 0.01 | 7.56 | 393 KiB | yes |
| 100,000 | 0.01 | 87.26 | 3,920 KiB | yes |

### End to end, no LLM (`run_pipeline`)

| Rows | Shape | Chart | Total ms | Status |
|---|---|---|---|---|
| 10,000 | agg_2key | grouped_bar | 20.41 | ok |
| 10,000 | derive_trend | line | 19.01 | ok |
| 10,000 | top_n | bar | 19.68 | ok |
| 100,000 | agg_2key | grouped_bar | 25.10 | ok |
| 100,000 | derive_trend | line | 24.16 | ok |
| 100,000 | top_n | bar | 25.81 | ok |
| 1,000,000 | agg_2key | grouped_bar | 78.09 | ok |
| 1,000,000 | derive_trend | line | 68.33 | ok |
| 1,000,000 | top_n | bar | 76.68 | ok |

### Join headroom — engine only, **not a shipped capability**

| Fact rows | Dim rows | Case | DuckDB ms |
|---|---|---|---|
| 100,000 | 200 | small_dim | 33.10 |
| 100,000 | 125,000 | large_dim | 42.24 |
| 500,000 | 200 | small_dim | 68.52 |
| 500,000 | 125,000 | large_dim | 77.48 |
| 1,000,000 | 200 | small_dim | 141.6 |
| 1,000,000 | 125,000 | large_dim | 153.5 |

### Shipped ceilings

| Ceiling | Value | Where it bites on this 11-column table |
|---|---|---|
| Upload size | 50.0 MiB | ~526,450 rows (99.6 B/row) |
| Rows per dataset | 1,000,000 | after the byte ceiling, so rarely first |
| Columns | 512 | — |
| Rows returned | 100,000 | caps any single result |
| Query time | 30 s | watchdog interrupts the query |
| Engine memory | 1GB | threads=2 |

## Natural-language accuracy

*39 frozen prompts, planner `AUTOVIZ_PLANNER_MODEL default`, run 2026-08-16T10:52:27.*

| Outcome | Cases | Share | Meaning |
|---|---|---|---|
| Answered correctly | 29 | 74.4% | met every assertion for that prompt |
| Asked a clarifying question | 6 | 15.4% | paused where asking was the right move |
| Declined | 0 | 0.0% | refused an out-of-scope request |
| **Over-asked** | 0 | 0% | paused on a request it could have answered |
| **Wrong** | 1 | 2.6% | answered, and the answer was not the question asked |

End-to-end latency including the planner LLM: median **7.2 s**, p90 10.2 s, max 21.2 s.

**Every case that did not pass:**

| Case | Prompt | Outcome | What happened |
|---|---|---|---|
| X02 | Forecast next year's rainfall. | wrong | produced a chart for an out-of-scope request |

## Chart quality

| Measure | Result | What it checks |
|---|---|---|
| Chart-type accuracy | 14/14 (100.0%) | recommender picks a chart from the family the question calls for |
| Spec validity | 10/10 (100.0%) | every chart type validates against the real Vega-Lite v6 JSON schema |
| Legibility guards | 3/3 | series ceilings, pie category ceiling, empty-result disclosure |