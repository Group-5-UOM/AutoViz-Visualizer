"""Deterministic ambiguity detectors (Direction B, Days 2-3).

These run over ``request × schema × profile`` BEFORE the planner LLM, so the
decision to ask a follow-up question is a computed signal, not a prompt guess.
Each detector returns grounded ``Ambiguity`` objects whose options reference real
columns/values; the LLM's only job downstream is to phrase nicely (Day 4).

Day 2 covers `time_column` and `missing_metric`. Day 3 adds `column_reference` /
`value_reference`. `detect_ambiguities` is the single entry point the graph calls.
"""

import re
from typing import Any

from autoviz.schema.clarification import Ambiguity, ClarificationOption

# Words that signal the user wants something over time — used to decide whether a
# clash of date columns actually matters for this request.
_TEMPORAL_HINTS = (
    "over time", "time series", "timeseries", "trend", "trends", "growth",
    "monthly", "daily", "weekly", "yearly", "annually", "quarterly", "seasonal",
    "by month", "by day", "by year", "by week", "by quarter", "by date",
    "per month", "per day", "per year", "per week", "per quarter",
    "over the years", "over the months", "change over", "across time",
)

# Superlatives/rankings that imply a ranking metric the user may not have named.
_SUPERLATIVES = (
    "best", "worst", "top", "bottom", "most", "least", "highest", "lowest",
    "greatest", "largest", "smallest", "biggest", "maximum", "minimum",
)

# Explicit aggregation words: if one appears the metric is likely already stated.
_AGG_WORDS = ("average", "avg", "mean", "median", "sum", "total", "count", "number of")

# Cap options so a wide table doesn't produce an unusable wall of buttons.
_MAX_METRIC_OPTIONS = 5

# Request words too generic to imply a specific column when matching concept→column.
_CONCEPT_STOPWORDS = frozenset({
    "the", "and", "for", "with", "show", "give", "plot", "chart", "graph", "count",
    "total", "average", "sum", "group", "each", "per", "over", "time", "best", "most",
    "top", "how", "many", "much", "what", "which", "number", "records", "record", "rows",
    "value", "values", "data", "dataset", "column", "columns", "distribution", "compare",
})


def detect_ambiguities(
    request: str,
    schema: list[dict[str, str]],
    profile: dict[str, Any],
    *,
    resolved: dict[str, Any] | None = None,
) -> list[Ambiguity]:
    """Return the ambiguities in `request` against this dataset, most-important first.

    `resolved` is the map of slots already answered this run; their ambiguities are
    suppressed so a bounded loop never re-asks the same slot.
    """
    found: list[Ambiguity] = []
    for detector in (
        _detect_time_column(request, schema),
        _detect_column_reference(request, schema),
        _detect_value_reference(request, profile),
        _detect_missing_metric(request, schema, profile),
    ):
        if detector is not None:
            found.append(detector)

    if resolved:
        found = [a for a in found if a.slot not in resolved]
    return found


def apply_resolutions(task: str, resolved: dict[str, Any]) -> str:
    """Fold bound clarification resolutions into a task as explicit constraints.

    Deterministic: the answer the user chose becomes a spelled-out clause appended
    to the task the worker plans from — so a clicked option actually steers the
    plan, rather than being re-guessed. Free-text answers are carried verbatim.
    """
    clauses: list[str] = []
    for slot, val in resolved.items():
        if not isinstance(val, dict):
            continue
        if "text" in val:  # free-text answer, no structured binding
            clauses.append(f"{slot.replace('_', ' ')}: {val['text']}")
        elif slot == "time_column" and val.get("column"):
            clauses.append(f"use column `{val['column']}` as the time axis")
        elif slot == "metric":
            if val.get("fn") == "count":
                clauses.append("measure by number of records (count)")
            elif val.get("column"):
                clauses.append(f"measure by {val.get('fn', 'mean')} of `{val['column']}`")
        elif slot == "dimension" and val.get("column"):
            clauses.append(f"group by `{val['column']}`")
        elif slot == "filter_value" and val.get("column"):
            clauses.append(f"filter where `{val['column']}` = '{val.get('value')}'")
    if not clauses:
        return task
    return f"{task}  [Resolved constraints: {'; '.join(clauses)}]"


# --- Day 2 detectors ----------------------------------------------------------


def _detect_time_column(request: str, schema: list[dict[str, str]]) -> Ambiguity | None:
    """Temporal request + >1 datetime column => which time axis to use is ambiguous."""
    if not _has_any(request, _TEMPORAL_HINTS):
        return None
    date_cols = _cols_of_type(schema, "datetime")
    if len(date_cols) < 2:
        return None  # 0 or 1 => nothing to disambiguate here
    # If the user already named one of the date columns, it's not ambiguous.
    named = _mentioned_columns(request, date_cols)
    if len(named) == 1:
        return None
    return Ambiguity(
        type="time_column",
        slot="time_column",
        question="Which date column should I use for the time axis?",
        options=[
            ClarificationOption(label=_pretty(c), resolves_to={"column": c}) for c in date_cols
        ],
        detail={"candidates": date_cols},
    )


def _detect_missing_metric(
    request: str, schema: list[dict[str, str]], profile: dict[str, Any]
) -> Ambiguity | None:
    """A superlative ("best", "top") with no measure named => which metric ranks them?"""
    if not _has_any(request, _SUPERLATIVES, word_boundary=True):
        return None
    numeric_cols = _cols_of_type(schema, "number")
    # Metric is already clear if the user named a numeric column, or used an
    # explicit aggregation word (e.g. "highest average fare", "most total sales").
    if _mentioned_columns(request, numeric_cols):
        return None
    if _has_any(request, _AGG_WORDS) and numeric_cols:
        return None

    # Rank candidate measures by cardinality so continuous quantities (fare, age)
    # surface above low-signal integer codes (0/1 flags, small ordinals) when the
    # option list is capped.
    ranked = _rank_by_cardinality(numeric_cols, profile)
    options = [
        ClarificationOption(label=f"Average {_human(c)}", resolves_to={"column": c, "fn": "mean"})
        for c in ranked[:_MAX_METRIC_OPTIONS]
    ]
    # Count of rows is always a valid ranking metric ("most X" often means count).
    options.append(
        ClarificationOption(label="Number of records (count)", resolves_to={"fn": "count"})
    )
    return Ambiguity(
        type="missing_metric",
        slot="metric",
        question="Which measure should rank them? \"best\"/\"most\" isn't a column.",
        options=options,
        detail={"numeric_candidates": numeric_cols},
    )


# --- Day 3 detectors ----------------------------------------------------------


def _detect_column_reference(request: str, schema: list[dict[str, str]]) -> Ambiguity | None:
    """A concept word matching >1 column name (and none exactly) => which column?"""
    words = [
        w
        for w in re.findall(r"[a-z0-9]+", _norm(request))
        if len(w) >= 3 and w not in _CONCEPT_STOPWORDS
    ]
    # Columns the request names in full (e.g. "sepal length" -> sepal_length) are
    # already disambiguated; a bare component word ("sepal") then isn't ambiguous.
    named = set(_mentioned_columns(request, [c["name"] for c in schema]))
    for w in words:
        matches = [c["name"] for c in schema if w in _col_words(c["name"])]
        if len(matches) < 2:
            continue
        if any(_norm(c) == w for c in matches):
            continue  # an exact-name column wins — not ambiguous
        if set(matches) & named:
            continue  # the user named one of the candidates in full
        types = {_type_of(schema, c) for c in matches}
        if types == {"datetime"}:
            continue  # a pure date clash is the time_column detector's job
        return Ambiguity(
            type="column_reference",
            slot="dimension",
            question=f'"{w}" could mean more than one column — which do you mean?',
            options=[
                ClarificationOption(label=_pretty(c), resolves_to={"column": c}) for c in matches
            ],
            detail={"term": w, "candidates": matches},
        )
    return None


def _detect_value_reference(request: str, profile: dict[str, Any]) -> Ambiguity | None:
    """A literal in the request that is a value in >1 column => which column's value?"""
    sample: dict[str, list[str]] = profile.get("sample_values", {})
    if not sample:
        return None
    hay = _norm(request)
    # value (normalized) -> [(column, original_value)], insertion-ordered for determinism.
    val_map: dict[str, list[tuple[str, str]]] = {}
    for col, values in sample.items():
        for v in values:
            nv = _norm(v)
            if len(nv) < 2:
                continue
            entries = val_map.setdefault(nv, [])
            if not any(c == col for c, _ in entries):
                entries.append((col, v))
    for nv, entries in val_map.items():
        if len(entries) >= 2 and re.search(rf"\b{re.escape(nv)}\b", hay):
            return Ambiguity(
                type="value_reference",
                slot="filter_value",
                question=f'"{nv}" appears in more than one column — which did you mean?',
                options=[
                    ClarificationOption(label=f"{_pretty(c)} = {v}", resolves_to={"column": c, "value": v})
                    for c, v in entries
                ],
                detail={"value": nv, "candidates": [c for c, _ in entries]},
            )
    return None


# --- helpers ------------------------------------------------------------------


def _cols_of_type(schema: list[dict[str, str]], logical_type: str) -> list[str]:
    return [c["name"] for c in schema if c.get("type") == logical_type]


def _type_of(schema: list[dict[str, str]], name: str) -> str:
    return next((c.get("type", "") for c in schema if c["name"] == name), "")


def _col_words(col: str) -> set[str]:
    """Component words of a column name: 'embark_town' -> {'embark', 'town'}."""
    return {w for w in re.split(r"[^a-z0-9]+", _norm(col)) if w}


def _rank_by_cardinality(cols: list[str], profile: dict[str, Any]) -> list[str]:
    """Order columns by distinct-value count (desc); stable for unknown/ties."""
    card = profile.get("cardinality", {})
    return sorted(cols, key=lambda c: card.get(c, 0), reverse=True)


def _has_any(text: str, needles: tuple[str, ...], *, word_boundary: bool = False) -> bool:
    hay = _norm(text)
    for n in needles:
        if word_boundary:
            if re.search(rf"\b{re.escape(n)}\b", hay):
                return True
        elif n in hay:
            return True
    return False


def _mentioned_columns(request: str, cols: list[str]) -> list[str]:
    """Columns the request refers to by name (underscores≈spaces, optional plural 's')."""
    hay = _norm(request)
    hit: list[str] = []
    for col in cols:
        variants = (_norm(col), _norm(col).replace("_", " "))
        if any(v and re.search(rf"\b{re.escape(v)}s?\b", hay) for v in variants):
            hit.append(col)
    return hit


def _pretty(col: str) -> str:
    """'signup_date' -> 'Signup date' for a button label."""
    words = col.replace("_", " ").strip()
    return words[:1].upper() + words[1:] if words else col


def _human(col: str) -> str:
    """'embark_town' -> 'embark town' (lower-cased, for inline label use)."""
    return col.replace("_", " ").strip()


def _norm(s: str) -> str:
    return " ".join(s.split()).casefold()
