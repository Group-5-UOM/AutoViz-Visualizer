"""Chart services: rule-based type recommendation + Vega-Lite spec generation.

recommend_chart_type scores intent x column types x cardinality (the hybrid
recommender's rule layer, Proposal §4.6); generate_chart builds and
structurally validates the Vega-Lite spec.
"""

from typing import Any

from autoviz.schema.allowlists import CHART_TYPES

HIGH_CARDINALITY_COLOR = 10

_VEGA_MARK = {
    "bar": "bar",
    "line": "line",
    "scatter": "point",
    "pie": "arc",
    "area": "area",
    "histogram": "bar",  # binned bar over one numeric column
}

_PIE_MAX_CATEGORIES = 6


def _split_columns(result_schema: list[dict[str, str]]):
    numeric = [c["name"] for c in result_schema if c["type"] == "number"]
    temporal = [c["name"] for c in result_schema if c["type"] == "datetime"]
    categorical = [
        c["name"] for c in result_schema if c["type"] not in ("number", "datetime")
    ]
    return numeric, temporal, categorical


def recommend_chart_type(
    result_schema: list[dict[str, str]], intent: str
) -> dict[str, Any]:
    numeric, temporal, categorical = _split_columns(result_schema)

    if not numeric:
        return {"error": "No numeric column in the result to plot as a measure"}

    y = numeric[0]
    color = None

    if intent == "trend" and temporal:
        chart_type, x = "line", temporal[0]
        rationale = f"Trend intent with temporal column '{x}' — line chart shows change over time."
        if categorical:
            color = categorical[0]
    elif intent == "trend" and categorical:
        chart_type, x = "line", categorical[0]
        rationale = f"Trend intent over ordered category '{x}' — line chart."
        if len(categorical) > 1:
            color = categorical[1]
    elif intent == "relationship" and len(numeric) >= 2:
        chart_type, x, y = "scatter", numeric[0], numeric[1]
        rationale = "Relationship intent with two numeric columns — scatter shows correlation."
        if categorical:
            color = categorical[0]
    elif intent == "composition" and categorical:
        chart_type, x = "pie", categorical[0]
        rationale = f"Composition intent over '{x}' — pie shows part-to-whole shares."
    elif intent == "ranking" and categorical:
        chart_type, x = "bar", categorical[0]
        rationale = f"Ranking intent — sorted bar chart over '{x}'."
    elif intent == "distribution" and not categorical:
        chart_type, x = "histogram", numeric[0]
        rationale = f"Distribution intent over numeric '{x}' — histogram of binned counts."
    elif intent == "distribution":
        chart_type = "bar"
        x = categorical[0]
        rationale = f"Distribution intent — bar chart of counts over '{x}'."
    elif categorical:
        chart_type, x = "bar", categorical[0]
        rationale = f"Comparison across categories of '{x}' — bar chart."
        if len(categorical) > 1:
            color = categorical[1]
    elif temporal:
        chart_type, x = "line", temporal[0]
        rationale = f"Temporal column '{x}' available — line chart."
    else:
        chart_type, x = "scatter", numeric[0]
        y = numeric[1] if len(numeric) > 1 else numeric[0]
        rationale = "Only numeric columns available — scatter plot."

    result: dict[str, Any] = {
        "chart_type": chart_type,
        "x": x,
        "rationale": rationale,
    }
    if chart_type != "histogram":  # histogram's y is the binned count, not a column
        result["y"] = y
    if color:
        result["color"] = color
    return result


def _encoding_type(values: list[Any], column_schema: dict[str, str] | None, name: str) -> str:
    if column_schema and name in column_schema:
        return {"number": "quantitative", "datetime": "temporal"}.get(
            column_schema[name], "nominal"
        )
    non_null = [v for v in values if v is not None]
    if non_null and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in non_null):
        return "quantitative"
    return "nominal"


def generate_chart(
    result_table: list[dict[str, Any]], chart_spec: dict[str, Any]
) -> dict[str, Any]:
    chart_type = chart_spec.get("type")
    if chart_type not in CHART_TYPES:
        return {
            "vega_lite_spec": None,
            "valid": False,
            "warnings": [f"chart type '{chart_type}' is not in the allow-list {sorted(CHART_TYPES)}"],
        }

    columns = set(result_table[0].keys()) if result_table else set()
    warnings: list[str] = []
    channels = {k: chart_spec.get(k) for k in ("x", "y", "color") if chart_spec.get(k)}
    missing = [f"{ch} -> '{col}'" for ch, col in channels.items() if columns and col not in columns]
    if missing:
        return {
            "vega_lite_spec": None,
            "valid": False,
            "warnings": [f"chart channel references absent column(s): {', '.join(missing)}"],
        }

    required = ("x",) if chart_type == "histogram" else ("x", "y")
    absent = [ch for ch in required if ch not in channels]
    if absent:
        return {
            "vega_lite_spec": None,
            "valid": False,
            "warnings": [f"chart type '{chart_type}' requires channel(s): {', '.join(absent)}"],
        }

    schema_hint = chart_spec.get("column_types")  # optional {name: logical_type}

    def enc(col: str) -> dict[str, Any]:
        values = [row.get(col) for row in result_table]
        return {"field": col, "type": _encoding_type(values, schema_hint, col)}

    if chart_type == "histogram":
        if "y" in channels:
            return {
                "vega_lite_spec": None,
                "valid": False,
                "warnings": ["histogram takes no y column — y is the binned count"],
            }
        encoding = {
            "x": {"field": channels["x"], "type": "quantitative", "bin": True},
            "y": {"aggregate": "count", "type": "quantitative"},
        }
    elif chart_type == "pie":
        encoding: dict[str, Any] = {
            "theta": {**enc(channels["y"]), "type": "quantitative"},
            "color": {**enc(channels["x"]), "type": "nominal"},
        }
        n_cats = len({row.get(channels["x"]) for row in result_table})
        if n_cats > _PIE_MAX_CATEGORIES:
            warnings.append(
                f"pie has {n_cats} categories (> {_PIE_MAX_CATEGORIES}) — consider a bar chart"
            )
    else:
        encoding = {"x": enc(channels["x"]), "y": enc(channels["y"])}
        if "color" in channels:
            encoding["color"] = enc(channels["color"])
            n_colors = len({row.get(channels["color"]) for row in result_table})
            if n_colors > HIGH_CARDINALITY_COLOR:
                warnings.append(
                    f"color channel has {n_colors} distinct values — legend may be unreadable"
                )

    spec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "data": {"values": result_table},
        "mark": _VEGA_MARK[chart_type],
        "encoding": encoding,
    }
    return {"vega_lite_spec": spec, "valid": True, "warnings": warnings}
