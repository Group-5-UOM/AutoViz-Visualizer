"""The plan-grammar guide, shared by every LLM that writes analysis plans.

Two consumers: the MCP tool descriptions (so a host's LLM can produce a valid
plan on the first call) and the internal LangGraph planner's system prompt.
Keep it in lockstep with schema/analysis_plan.py + allowlists.py.
"""

PLAN_GUIDE = """
analysis_plan JSON structure (lists may be empty/omitted; dataset_id and intent are required):
{
  "dataset_id": "<from register_dataset>",
  "intent": "comparison" | "trend" | "distribution" | "relationship" | "composition" | "ranking",
  "preprocessing": [  // optional, explicit cleaning applied to a read-only working view first
    // Safe repairs — change how a value is written, not what it means.
    {"op": "trim_whitespace", "columns": ["col", ...]},
    {"op": "empty_string_to_null", "columns": ["col", ...]},
    {"op": "normalize_case", "column": "col"},
    {"op": "drop_empty_rows"},
    {"op": "cast_column", "column": "col", "to": "number"|"datetime"},
    {"op": "parse_number", "columns": ["col", ...], "decimal": "."|",",
     "thousands": ","|"."|" "|"'"|null},
    // Value-changing — alter values or which rows survive.
    {"op": "drop_nulls", "columns": ["col", ...], "how": "any"|"all"},
    {"op": "fill_nulls", "column": "col", "strategy": "constant"|"median"|"mode", "value": <scalar for constant>},
    {"op": "drop_exact_duplicates"},
    {"op": "clean_categories", "column": "col", "mapping": {"old": "new", ...}},
    {"op": "group_rare_categories", "column": "col", "top_n": <int>, "other_label": "Other",
     "rank_by": {"column": "col", "fn": "sum"|"mean"|"min"|"max"|"count"|"median"|"count_distinct"}}
  ],
  "select": ["col", ...],
  "filters": [{"column": "col",
               "op": "eq"|"neq"|"gt"|"gte"|"lt"|"lte"|"in"|"between"|"contains"|"is_null"|"is_not_null",
               "value": <scalar; omit for is_null/is_not_null>}],
  "derive": [{"name": "new_col", "from": "source_col",
              "fn": "month"|"year"|"day"|"weekday"
                    |"month_start"|"quarter_start"|"week_start"|"year_start"
                    |"lower"|"upper"|"trim"|"round"|"abs"}],
  "group_by": ["col1", "col2"],
  "aggregations": [{"column": "col", "fn": "sum"|"mean"|"min"|"max"|"count"|"median"|"count_distinct",
                    "as": "alias"}],
  "sort": [{"by": "col", "dir": "asc"|"desc"}],
  "limit": <int, optional>,
  "chart": {"type": "bar"|"line"|"scatter"|"pie"|"area"|"histogram"|"heatmap"|"boxplot"
                    |"grouped_bar"|"donut",
            "x": "col", "y": "col", "color": "col"}
}
Preprocessing (explicit, never silent — the source CSV is never modified):
- Order of execution: preprocessing -> filters -> derive -> group/aggregate. Preprocessing
  operates on real dataset columns only (not derived names). Ops run in the order you list
  them, and each sees the output of the one before — so null the blanks *before* casting.
- Safe repairs (apply freely; they preserve meaning):
  trim_whitespace and normalize_case fix category spellings that would otherwise split one
  group into several (" a", "a ", "A" and "a" are four bars on a chart). empty_string_to_null
  turns blank text into a real null so aggregates skip it. drop_empty_rows removes rows that
  are null in every column. All four need string columns.
- Category cleaning (string/boolean columns; both merge distinct values, so use them only when
  the user asked or after offering the choice):
  clean_categories applies an explicit {old: new} mapping — use it for "treat UK and U.K. as the
  same", never to guess at similar-looking values yourself. Values not named are left alone.
  group_rare_categories keeps the leading values and folds the rest into other_label — the fix
  for a grouping column with too many categories to read. Give exactly ONE of top_n or
  min_frequency. Nulls are never bucketed (missing is not the same as rare).
  With top_n, set rank_by to the SAME column and fn as the aggregation you are charting, so the
  categories kept are the ones that lead on the plotted measure. Without it the keep-set is row
  frequency, which answers "who has the most rows" — a different question from "who has the
  highest total", and it will bury the top performer in "Other" whenever the two disagree.
  rank_by does not apply to min_frequency (already a frequency rule).
- cast_column reads a text column as the type it already holds — the only way to aggregate a
  numeric column your reader took as text (sum/mean require a numeric column). It refuses if
  any value would fail to convert, so pair it with empty_string_to_null when blanks or
  sentinels are present. After casting, the column IS the new type for filters and aggregations.
- parse_number is cast_column for money and formatted figures: "$1,234.50", "1 234,50", "€99".
  cast_column CANNOT read these — the symbol and the separators make the conversion fail — so
  this is the op for any numeric-looking text column cast_column rejected. Set thousands to the
  grouping character and decimal to the decimal point ("," for European notation); the dataset
  profile's `ingest` block reports what the file used. It removes only currency marks,
  whitespace and the thousands separator and then requires the rest to convert, so it refuses a
  column like "12 apples" rather than returning 12. It also refuses percentages: "45%" is
  either 45 or 0.45 and the column does not say which. After parsing, the column IS a number.
- drop_nulls: how "any" drops a row if ANY listed column is null; "all" only if all are.
- fill_nulls strategy: "median" (numeric columns only), "mode" (categorical/string or boolean
  columns only), "constant" (any type — requires a "value"). Mean imputation is not available.
- drop_exact_duplicates removes fully identical rows. Only ever use it when the user explicitly
  asks — apparently-identical rows can be legitimate repeated events.
- Clean ONLY the columns the current analysis needs. Ignore nulls in unrelated columns.
- Map NL to ops: "remove rows with no fare" -> drop_nulls ["fare"]; "replace missing age with the
  median" -> fill_nulls median on age; "ignore duplicate rows" -> drop_exact_duplicates.
- For a null-bearing GROUP BY column, add drop_nulls / is_not_null on it so there is no spurious
  "null" category. Aggregates (avg/sum/...) already skip nulls in the measured column — you do not
  need to drop those; the result reports the exclusion.
- Do NOT impute unless the user asks. Imputing changes values, so it needs the user's agreement
  regardless of how few rows it touches — a small share of a measure column can still move a total.
- What the system enforces for you (you do not need to reproduce these checks, only to expect them):
  removing more than 30% of rows is refused with CONFIRMATION_REQUIRED until the caller passes the
  returned confirmation.preprocessing_hash back as approved_preprocessing_hash. This applies to
  execute_analysis and run_analysis_pipeline alike. Imputing 5% or more of a column is allowed but
  is disclosed in provenance.imputation_notices, and nulls skipped by an aggregate are always
  reported in provenance.implicit_null_exclusions (measured before cleaning, so filling them in
  does not hide them). A 100%-null column is unusable — do not select, group, or aggregate on it.
- `notices` collects everything the user must be told, already phrased, each with a severity:
  "disclosed" (the numbers now mean something different — always repeat it), "advisory" (nothing
  changed, but the chart is misread without it — e.g. a log-scaled axis), "applied" (routine
  tidying; batch or omit). Reuse the wording; do not restate the counts yourself.
- Do NOT try to fix a skewed chart with a plan. An extreme value that flattens the other marks is
  handled at the axis, automatically, and disclosed as an advisory notice. Filtering or capping it
  would change the answer to improve the picture — if the user did not ask to exclude it, keep it.

Rules: group_by max 2 columns; limit max 100000; no other fields or op/fn values are accepted.
is_null/is_not_null take no value and work on any column type.
Omit limit for distribution/relationship plans — the full column is needed to bin the
histogram / plot every point; a limit truncates the data. Use limit only to cap ranking/top-N.
Filter values are scalars, except: "in" takes a list of 1-20 scalars, "between" takes
[low, high] (2 values) — both work on numeric/datetime columns ("in" on any type).
Some number columns are really coded categories (e.g. pclass 1/2/3, survived 0/1); the
profile lists them as categorical_numeric_columns. Treat these as categories — group_by
or chart.color them to compare classes — not as continuous measures to aggregate.
Every column must exist in the dataset schema (call get_dataset_schema first).
sum/mean/min/max/median need a numeric column; every date derive needs a datetime column.
Two kinds of date derive, and picking the wrong one silently produces a wrong chart:
- month/year/day/weekday EXTRACT a number (month gives a bare 1-12). Use these only for
  seasonality — "which month is busiest?" — where combining every year is the question.
- month_start/quarter_start/week_start/year_start TRUNCATE to the start of the period and
  stay datetimes. Use these for any trend over time. A "monthly revenue" line over two
  years needs month_start; with month it collapses to 12 points that add January 2025 to
  January 2026, which looks plausible and is wrong. chart is optional (omit it to auto-recommend); chart.x/y/color may only
reference columns the query produces: group_by columns and aggregation "as" aliases (or
select/derive names when there is no grouping). Prefer omitting chart unless the user asked
for a specific type by name — the recommender picks from the result shape.
Chart types with extra requirements:
- "histogram" bins one numeric x column and takes NO y (y is the count).
- "heatmap" is a grid of two categories: x and y are both categorical and color is REQUIRED
  and must be the numeric measure (this is the only type whose color is a number, not a series).
- "grouped_bar" puts series side by side and REQUIRES color. Plain "bar" with a color column
  stacks instead — use bar for part-to-whole, grouped_bar to compare series.
- "boxplot" needs the RAW values to compute quartiles from: select the numeric column with NO
  aggregations, x = the category to split by, y = the numeric column.
- "donut" and "pie" are both part-to-whole over one category (x) and a measure (y); donut is
  the better default. Both warn above 6 categories.

Example — average sepal length per species, largest first:
{"dataset_id": "ds_abc123", "intent": "comparison", "group_by": ["species"],
 "aggregations": [{"column": "sepal_length", "fn": "mean", "as": "avg_sepal_length"}],
 "sort": [{"by": "avg_sepal_length", "dir": "desc"}]}

Example — average fare by class, dropping rows missing class or fare (explicit cleaning):
{"dataset_id": "ds_ghi789", "intent": "comparison",
 "preprocessing": [{"op": "drop_nulls", "columns": ["class", "fare"], "how": "any"}],
 "group_by": ["class"],
 "aggregations": [{"column": "fare", "fn": "mean", "as": "average_fare"}]}

Example — summer 2015 rainfall by month (date-range filter). The range sits inside one
year, so month and month_start would agree here; month_start is still the safer default
because it keeps working when the range widens:
{"dataset_id": "ds_def456", "intent": "trend",
 "filters": [{"column": "date", "op": "between", "value": ["2015-06-01", "2015-08-31"]}],
 "derive": [{"name": "month", "from": "date", "fn": "month_start"}],
 "group_by": ["month"],
 "aggregations": [{"column": "precipitation", "fn": "sum", "as": "total_precip"}],
 "chart": {"type": "line", "x": "month", "y": "total_precip"}}

Example — which month of the year is wettest, across all years (seasonality, so extract):
{"dataset_id": "ds_def456", "intent": "comparison",
 "derive": [{"name": "month_of_year", "from": "date", "fn": "month"}],
 "group_by": ["month_of_year"],
 "aggregations": [{"column": "precipitation", "fn": "mean", "as": "avg_precip"}],
 "chart": {"type": "bar", "x": "month_of_year", "y": "avg_precip"}}
"""
