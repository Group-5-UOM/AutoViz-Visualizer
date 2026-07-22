# AutoViz Test Datasets

Real, public, permissively-licensed CSV datasets organized by domain, for testing AutoViz's upload, profiling, NL-query, and chart-generation pipeline against realistic tabular data. Pulled from `seaborn-data` (BSD-3), `vega-datasets` (BSD-3), and `plotly/datasets` (MIT) — all directly citable, stable GitHub-hosted sources.

## Index

### `sales-retail/`
| File | Rows | Columns | Notes |
|---|---|---|---|
| `tips.csv` | 244 | 7 | Restaurant bills/tips — mixed numeric + categorical, small, ideal for first smoke tests |
| `diamonds.csv` | 53,940 | 10 | Diamond pricing — large-scale test (~2.7MB), good for performance/limit testing |

### `finance/`
| File | Rows | Columns | Notes |
|---|---|---|---|
| `stocks.csv` | 559 | 3 | Multi-symbol stock prices over time (AAPL, MSFT, IBM, GOOG, AMZN) — time series + categorical grouping |
| `sp500.csv` | 123 | 2 | S&P 500 monthly price — simple time series, good for trend-chart tests |

### `healthcare/`
| File | Rows | Columns | Notes |
|---|---|---|---|
| `healthexp.csv` | 274 | 4 | Health spending vs. life expectancy by country/year — good for correlation/scatter tasks |

### `weather-climate/`
| File | Rows | Columns | Notes |
|---|---|---|---|
| `seattle-weather.csv` | 1,461 | 6 | Daily weather (precip, temp, wind, condition) — date parsing + categorical weather type |
| `disasters.csv` | 802 | 3 | Natural disaster deaths by type/year — long-format, good for filter+aggregate tasks |

### `education/`
| File | Rows | Columns | Notes |
|---|---|---|---|
| `school_earnings.csv` | 21 | 4 | Median earnings by school and gender — tiny, good for quick bar-chart/gender-gap tests |

### `public-open-data/`
| File | Rows | Columns | Notes |
|---|---|---|---|
| `population_engineers_hurricanes.csv` | 52 | 5 | US state population/engineers/hurricanes — classic multi-metric choropleth test |
| `gapminderDataFiveYear.csv` | 1,704 | 6 | Global development indicators (pop, life expectancy, GDP) by country/year — rich time-series + categorical |
| `2011_us_ag_exports.csv` | 50 | 9 | US agricultural exports by state and category — wide numeric table |
| `2010_alcohol_consumption_by_country.csv` | 191 | 2 | Alcohol consumption by country — simple ranking/bar-chart test |

### `transportation/`
| File | Rows | Columns | Notes |
|---|---|---|---|
| `mpg.csv` | 398 | 9 | Classic auto dataset (mpg, cylinders, origin, etc.) — good numeric+categorical mix, some missing values |
| `car_crashes.csv` | 51 | 8 | US state-level crash statistics — wide numeric table |
| `taxis.csv` | 6,433 | 14 | NYC taxi trips — larger dataset (~870KB), datetime + categorical + numeric |
| `flights.csv` | 144 | 3 | Classic airline passengers time series (1949–1960) — simple monthly trend |

### `general-testing/`
Classic ML/stats datasets — small, clean, well-known; useful as quick sanity-check baselines and for edge cases (missing values, mixed types).
| File | Rows | Columns | Notes |
|---|---|---|---|
| `titanic.csv` | 891 | 15 | Passenger survival data — **has missing values (age, embarked, deck)**, good for null-handling tests |
| `penguins.csv` | 344 | 7 | Species measurements — **has missing values**, good for data-quality profiling tests |
| `iris.csv` | 150 | 5 | Classic flower measurements — clean, no missing values, simplest baseline |

## Suggested use

- **Smoke-testing upload/profiling:** start with `iris.csv`, `tips.csv`, `school_earnings.csv` (small, clean).
- **Null-handling / data-quality checks:** `titanic.csv`, `penguins.csv`, `mpg.csv` (all contain real missing values).
- **Scale / performance testing:** `diamonds.csv` (53.9K rows), `taxis.csv` (6.4K rows).
- **Time-series / trend charts:** `stocks.csv`, `sp500.csv`, `flights.csv`, `seattle-weather.csv`, `gapminderDataFiveYear.csv`.
- **Benchmark task authoring** (per [`Docs/04-Improvement-Plan.md`](../Docs/04-Improvement-Plan.md)): this set already spans the domains named in the project proposal (sales, finance, healthcare, weather, education, public data) — pick 1–2 per folder and hand-author 5–10 NL tasks each to reach the ~100–150 task benchmark target.

## Sources

- [mwaskom/seaborn-data](https://github.com/mwaskom/seaborn-data) (BSD-3)
- [vega/vega-datasets](https://github.com/vega/vega-datasets) (BSD-3)
- [plotly/datasets](https://github.com/plotly/datasets) (MIT)
