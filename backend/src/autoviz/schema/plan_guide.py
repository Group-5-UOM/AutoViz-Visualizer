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
  "select": ["col", ...],
  "filters": [{"column": "col", "op": "eq"|"neq"|"gt"|"gte"|"lt"|"lte"|"in"|"between"|"contains",
               "value": <scalar>}],
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
Rules: group_by max 2 columns; limit max 1000; no other fields or op/fn values are accepted.
Omit limit for distribution/relationship plans — the full column is needed to bin the
histogram / plot every point; a limit truncates the data. Use limit only to cap ranking/top-N.
Filter values are scalars, except: "in" takes a list of 1-20 scalars, "between" takes
[low, high] (2 values) — both work on numeric/datetime columns ("in" on any type).
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

Example — summer 2015 rainfall by month (date-range filter):
{"dataset_id": "ds_def456", "intent": "trend",
 "filters": [{"column": "date", "op": "between", "value": ["2015-06-01", "2015-08-31"]}],
 "derive": [{"name": "month", "from": "date", "fn": "month"}],
 "group_by": ["month"],
 "aggregations": [{"column": "precipitation", "fn": "sum", "as": "total_precip"}],
 "chart": {"type": "line", "x": "month", "y": "total_precip"}}
"""
