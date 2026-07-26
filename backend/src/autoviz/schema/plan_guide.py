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
    {"op": "drop_nulls", "columns": ["col", ...], "how": "any"|"all"},
    {"op": "fill_nulls", "column": "col", "strategy": "constant"|"median"|"mode", "value": <scalar for constant>},
    {"op": "drop_exact_duplicates"}
  ],
  "select": ["col", ...],
  "filters": [{"column": "col",
               "op": "eq"|"neq"|"gt"|"gte"|"lt"|"lte"|"in"|"between"|"contains"|"is_null"|"is_not_null",
               "value": <scalar; omit for is_null/is_not_null>}],
  "derive": [{"name": "new_col", "from": "source_col",
              "fn": "month"|"year"|"day"|"weekday"|"lower"|"upper"|"trim"|"round"|"abs"}],
  "group_by": ["col1", "col2"],
  "aggregations": [{"column": "col", "fn": "sum"|"mean"|"min"|"max"|"count"|"median"|"count_distinct",
                    "as": "alias"}],
  "sort": [{"by": "col", "dir": "asc"|"desc"}],
  "limit": <int, optional>,
  "chart": {"type": "bar"|"line"|"scatter"|"pie"|"area"|"histogram", "x": "col", "y": "col",
            "color": "col"}
}
Preprocessing (explicit, never silent — the source CSV is never modified):
- Order of execution: preprocessing -> filters -> derive -> group/aggregate. Preprocessing
  operates on real dataset columns only (not derived names).
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
- Do NOT impute unless the user asks. Missing-value heuristic (percent of a column used by the
  analysis): 0% no action; <5% exclude affected rows and report; 5-30% offer remove-or-impute;
  >30% removing rows needs user confirmation (run_analysis_pipeline returns confirmation_required —
  re-call with approved_preprocessing_hash to proceed); 100% the column is unusable, do not select it.

Rules: group_by max 2 columns; limit max 1000; no other fields or op/fn values are accepted.
is_null/is_not_null take no value and work on any column type.
Omit limit for distribution/relationship plans — the full column is needed to bin the
histogram / plot every point; a limit truncates the data. Use limit only to cap ranking/top-N.
Filter values are scalars, except: "in" takes a list of 1-20 scalars, "between" takes
[low, high] (2 values) — both work on numeric/datetime columns ("in" on any type).
Some number columns are really coded categories (e.g. pclass 1/2/3, survived 0/1); the
profile lists them as categorical_numeric_columns. Treat these as categories — group_by
or chart.color them to compare classes — not as continuous measures to aggregate.
Every column must exist in the dataset schema (call get_dataset_schema first).
sum/mean/min/max/median need a numeric column; month/year/day/weekday derives need a
datetime column. chart is optional (omit it to auto-recommend); chart.x/y/color may only
reference columns the query produces: group_by columns and aggregation "as" aliases (or
select/derive names when there is no grouping). "histogram" bins one numeric x column and
takes NO y (y is the count).

Example — average sepal length per species, largest first:
{"dataset_id": "ds_abc123", "intent": "comparison", "group_by": ["species"],
 "aggregations": [{"column": "sepal_length", "fn": "mean", "as": "avg_sepal_length"}],
 "sort": [{"by": "avg_sepal_length", "dir": "desc"}]}

Example — average fare by class, dropping rows missing class or fare (explicit cleaning):
{"dataset_id": "ds_ghi789", "intent": "comparison",
 "preprocessing": [{"op": "drop_nulls", "columns": ["class", "fare"], "how": "any"}],
 "group_by": ["class"],
 "aggregations": [{"column": "fare", "fn": "mean", "as": "average_fare"}]}

Example — summer 2015 rainfall by month (date-range filter):
{"dataset_id": "ds_def456", "intent": "trend",
 "filters": [{"column": "date", "op": "between", "value": ["2015-06-01", "2015-08-31"]}],
 "derive": [{"name": "month", "from": "date", "fn": "month"}],
 "group_by": ["month"],
 "aggregations": [{"column": "precipitation", "fn": "sum", "as": "total_precip"}],
 "chart": {"type": "line", "x": "month", "y": "total_precip"}}
"""
