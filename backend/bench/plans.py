"""The query shapes the latency curve is measured over.

Each entry is a real `analysis_plan` — the same dict an LLM emits and
`validate_analysis_plan` accepts — so what is timed is the shipped path, not a
hand-written SQL string that happens to resemble it.

The shapes are chosen to separate costs that a single "query latency" number
would blend together: a scan that returns rows, an aggregate that collapses
them, a group-by whose output grows with cardinality, an aggregate that has to
hold state (median, count_distinct), a derive that computes before it groups,
and a cleaning block that walks the table several extra times before the
analysis starts.
"""

from __future__ import annotations

from typing import Any

# `label` is what appears in the report; `note` says what the shape isolates.
SHAPES: list[dict[str, Any]] = [
    {
        "id": "scan_limit",
        "label": "Projection + limit (1k rows out)",
        "note": "Row delivery with no aggregation — the floor for any query.",
        "plan": {
            "intent": "distribution",
            "select": ["order_date", "region", "category", "revenue"],
            "limit": 1000,
        },
    },
    {
        "id": "filter_scan",
        "label": "Filter + projection (1k rows out)",
        "note": "Adds a predicate over the full table to the scan above.",
        "plan": {
            "intent": "distribution",
            "select": ["order_date", "region", "revenue"],
            "filters": [{"column": "region", "op": "eq", "value": "North"}],
            "limit": 1000,
        },
    },
    {
        "id": "agg_1key",
        "label": "Group by 1 key, sum (5 groups)",
        "note": "The commonest shape in the product: full scan, tiny output.",
        "plan": {
            "intent": "comparison",
            "group_by": ["region"],
            "aggregations": [{"column": "revenue", "fn": "sum", "as": "total_revenue"}],
        },
    },
    {
        "id": "agg_2key",
        "label": "Group by 2 keys, 2 aggregates (60 groups)",
        "note": "MAX_GROUP_BY=2 — the widest grouping the grammar allows.",
        "plan": {
            "intent": "comparison",
            "group_by": ["region", "category"],
            "aggregations": [
                {"column": "revenue", "fn": "sum", "as": "total_revenue"},
                {"column": "quantity", "fn": "mean", "as": "avg_quantity"},
            ],
        },
    },
    {
        "id": "agg_highcard",
        "label": "Group by high-cardinality key (n/8 groups)",
        "note": "Output grows with the table — the worst case for a group-by.",
        "plan": {
            "intent": "ranking",
            "group_by": ["customer_id"],
            "aggregations": [{"column": "revenue", "fn": "sum", "as": "total_revenue"}],
        },
    },
    {
        "id": "agg_median",
        "label": "Group by 1 key, median",
        "note": "A holistic aggregate: cannot stream, must materialise per group.",
        "plan": {
            "intent": "comparison",
            "group_by": ["region"],
            "aggregations": [{"column": "revenue", "fn": "median", "as": "median_revenue"}],
        },
    },
    {
        "id": "agg_count_distinct",
        "label": "Group by 1 key, count_distinct",
        "note": "Hash-set state per group over a high-cardinality column.",
        "plan": {
            "intent": "comparison",
            "group_by": ["region"],
            "aggregations": [
                {"column": "customer_id", "fn": "count_distinct", "as": "customers"}
            ],
        },
    },
    {
        "id": "derive_trend",
        "label": "Derive month_start + group + sum (36 points)",
        "note": "The trend shape: a computed key, then a group-by over it.",
        "plan": {
            "intent": "trend",
            "derive": [{"name": "month", "from": "order_date", "fn": "month_start"}],
            "group_by": ["month"],
            "aggregations": [{"column": "revenue", "fn": "sum", "as": "total_revenue"}],
            "sort": [{"by": "month", "dir": "asc"}],
        },
    },
    {
        "id": "top_n",
        "label": "Filter + group + sort + limit 10 (“top 10”)",
        "note": "The full ranking pipeline end to end.",
        "plan": {
            "intent": "ranking",
            "filters": [{"column": "revenue", "op": "gt", "value": 50}],
            "group_by": ["product"],
            "aggregations": [{"column": "revenue", "fn": "sum", "as": "total_revenue"}],
            "sort": [{"by": "total_revenue", "dir": "desc"}],
            "limit": 10,
        },
    },
    {
        "id": "clean_agg",
        "label": "Cleaning block (3 ops) + group + sum",
        "note": (
            "Median imputation, whitespace trim and exact-duplicate removal ahead "
            "of the same aggregate as agg_1key — so the difference is the cleaning."
        ),
        "plan": {
            "intent": "comparison",
            "preprocessing": [
                {"op": "trim_whitespace", "columns": ["region", "category"]},
                {"op": "fill_nulls", "column": "discount_pct", "strategy": "median"},
                {"op": "drop_exact_duplicates"},
            ],
            "group_by": ["region"],
            "aggregations": [{"column": "revenue", "fn": "sum", "as": "total_revenue"}],
        },
    },
]


def plan_for(shape: dict[str, Any], dataset_id: str) -> dict[str, Any]:
    return {"dataset_id": dataset_id, **shape["plan"]}
