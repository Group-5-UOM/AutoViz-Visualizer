# AutoViz Test Datasets

Real, public, permissively-licensed CSV datasets organized by domain, for testing AutoViz's upload, profiling, NL-query, and chart-generation pipeline against realistic tabular data. Pulled from `seaborn-data` (BSD-3), `vega-datasets` (BSD-3), `plotly/datasets` (MIT), and `Rdatasets` (mixed open licenses, see [source repo](https://github.com/vincentarelbundock/Rdatasets)) — all directly citable, stable GitHub-hosted sources. **38 files, ~5.7MB total.**

> Rdatasets files originally include an R `rownames` index column, which was stripped on import — everything here reflects the real, unmodified data columns.

## Index

### `sales-retail/`
| File | Rows | Columns | Notes |
|---|---|---|---|
| `tips.csv` | 244 | 7 | Restaurant bills/tips — mixed numeric + categorical, small, ideal for first smoke tests |
| `diamonds.csv` | 53,940 | 10 | Diamond pricing — large-scale test (~2.7MB), good for performance/limit testing |
| `house_prices.csv` | 546 | 12 | Windsor, Canada house prices — price + numeric/binary features (driveway, aircon, garage, etc.) |
| `fashion_store_sales.csv` | 400 | 13 | Men's fashion store sales, margin, staffing — richer retail-ops dataset |
| `dutch_retail_sales_index.csv` | 425 | 2 | Dutch retail sales index over time — simple long time series |

### `finance/`
| File | Rows | Columns | Notes |
|---|---|---|---|
| `stocks.csv` | 559 | 3 | Multi-symbol stock prices over time (AAPL, MSFT, IBM, GOOG, AMZN) — time series + categorical grouping |
| `sp500.csv` | 123 | 2 | S&P 500 monthly price — simple time series, good for trend-chart tests |
| `eu_stock_markets.csv` | 1,860 | 4 | Daily closing prices, 4 major European stock indices (1991–1998) — dense multi-series time series |
| `credit_card_expenditure.csv` | 1,319 | 12 | Credit card expenditure/default data — mixed numeric + binary, good for classification-style filters |
| `us_macro_economic.csv` | 204 | 12 | US macroeconomic indicators 1950–2000 (GDP, consumption, inflation, unemployment) — wide economic time series |

### `healthcare/`
| File | Rows | Columns | Notes |
|---|---|---|---|
| `healthexp.csv` | 274 | 4 | Health spending vs. life expectancy by country/year — good for correlation/scatter tasks |
| `heart_disease_patients.csv` | 303 | 9 | Clinical heart-disease patient data (age, BP, cholesterol, diagnosis) — classic categorical+numeric clinical mix |
| `medical_care_demand.csv` | 4,406 | 19 | NMES 1988 demand for medical care — large healthcare survey dataset |

### `weather-climate/`
| File | Rows | Columns | Notes |
|---|---|---|---|
| `seattle-weather.csv` | 1,461 | 6 | Daily weather (precip, temp, wind, condition) — date parsing + categorical weather type |
| `disasters.csv` | 802 | 3 | Natural disaster deaths by type/year — long-format, good for filter+aggregate tasks |
| `weather_australia_cities.csv` | 300 | 22 | Daily weather for 3 Australian cities — wide, rich multi-metric weather table |
| `precipitation_innsbruck.csv` | 4,971 | 12 | Precipitation observations & forecasts, Innsbruck — large weather time series |
| `australia_climate_by_region.csv` | 109 | 34 | Australian historical annual climate data by region — very wide table, good stress test for many-column profiling |

### `education/`
| File | Rows | Columns | Notes |
|---|---|---|---|
| `school_earnings.csv` | 21 | 4 | Median earnings by school and gender — tiny, good for quick bar-chart/gender-gap tests |
| `california_test_scores.csv` | 420 | 14 | California school test scores, funding, class size — classic education-economics dataset |
| `massachusetts_test_scores.csv` | 220 | 16 | Massachusetts school test scores — similar structure, cross-region comparison |
| `us_states_education_stats.csv` | 51 | 7 | Education & related statistics by US state — small, state-level rollup |

### `public-open-data/`
| File | Rows | Columns | Notes |
|---|---|---|---|
| `population_engineers_hurricanes.csv` | 52 | 5 | US state population/engineers/hurricanes — classic multi-metric choropleth test |
| `gapminderDataFiveYear.csv` | 1,704 | 6 | Global development indicators (pop, life expectancy, GDP) by country/year — rich time-series + categorical |
| `2011_us_ag_exports.csv` | 50 | 9 | US agricultural exports by state and category — wide numeric table |
| `2010_alcohol_consumption_by_country.csv` | 191 | 2 | Alcohol consumption by country — simple ranking/bar-chart test |
| `british_election_panel_study.csv` | 1,525 | 10 | British Election Panel Study — survey/attitudinal data, mostly categorical |
| `boston_housing.csv` | 506 | 14 | Classic Boston housing dataset (crime, tax, pupil-teacher ratio, price) — dense numeric table |
| `us_population_history.csv` | 22 | 2 | US population by decade, 1790–2000 — tiny, simple long-run time series |

### `transportation/`
| File | Rows | Columns | Notes |
|---|---|---|---|
| `mpg.csv` | 398 | 9 | Classic auto dataset (mpg, cylinders, origin, etc.) — good numeric+categorical mix, some missing values |
| `car_crashes.csv` | 51 | 8 | US state-level crash statistics — wide numeric table |
| `taxis.csv` | 6,433 | 14 | NYC taxi trips — larger dataset (~870KB), datetime + categorical + numeric |
| `flights.csv` | 144 | 3 | Classic airline passengers time series (1949–1960) — simple monthly trend |
| `us_traffic_fatalities.csv` | 336 | 34 | US traffic fatalities by state/year with many covariates — very wide table, good stress test |
| `us_airlines_cost_data.csv` | 90 | 6 | US airline cost/output/price panel data — small panel dataset |

### `general-testing/`
Classic ML/stats datasets — small, clean, well-known; useful as quick sanity-check baselines and for edge cases (missing values, mixed types).
| File | Rows | Columns | Notes |
|---|---|---|---|
| `titanic.csv` | 891 | 15 | Passenger survival data — **has missing values (age, embarked, deck)**, good for null-handling tests |
| `penguins.csv` | 344 | 7 | Species measurements — **has missing values**, good for data-quality profiling tests |
| `iris.csv` | 150 | 5 | Classic flower measurements — clean, no missing values, simplest baseline |

## Suggested use

- **Smoke-testing upload/profiling:** start with `iris.csv`, `tips.csv`, `school_earnings.csv`, `us_population_history.csv` (small, clean).
- **Null-handling / data-quality checks:** `titanic.csv`, `penguins.csv`, `mpg.csv` (all contain real missing values).
- **Scale / performance testing:** `diamonds.csv` (53.9K rows), `taxis.csv` (6.4K rows), `medical_care_demand.csv` (4.4K rows), `precipitation_innsbruck.csv` (4.97K rows).
- **Wide-table / many-column stress testing:** `australia_climate_by_region.csv` (34 cols), `us_traffic_fatalities.csv` (34 cols), `weather_australia_cities.csv` (22 cols).
- **Time-series / trend charts:** `stocks.csv`, `sp500.csv`, `eu_stock_markets.csv`, `flights.csv`, `seattle-weather.csv`, `gapminderDataFiveYear.csv`, `dutch_retail_sales_index.csv`, `us_population_history.csv`.
- **Cross-domain comparison tasks:** `california_test_scores.csv` vs `massachusetts_test_scores.csv` (same schema, different regions) — good for testing consistent NL queries across datasets.
- **Benchmark task authoring** (per [`Docs/04-Improvement-Plan.md`](../Docs/04-Improvement-Plan.md)): this set spans all domains named in the project proposal (sales, finance, healthcare, weather, education, public data) with 3–7 files per domain — pick 2–3 per folder and hand-author 5–10 NL tasks each to comfortably reach the ~100–150 task benchmark target.

## Sources

- [mwaskom/seaborn-data](https://github.com/mwaskom/seaborn-data) (BSD-3)
- [vega/vega-datasets](https://github.com/vega/vega-datasets) (BSD-3)
- [plotly/datasets](https://github.com/plotly/datasets) (MIT)
- [vincentarelbundock/Rdatasets](https://github.com/vincentarelbundock/Rdatasets) (per-dataset licenses; mostly public-domain/open academic data mirrored from R packages — see each package's original documentation for attribution)
