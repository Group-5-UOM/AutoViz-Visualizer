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

# Superlatives that imply a ranking metric the user may not have named.
#
# Split by how the word is actually used, because treating them alike produced a
# false positive that blocked ordinary requests. "How did the maximum
# temperature change over the years?" is not a ranking question — "maximum" is
# an adjective naming a column (`temp_max`), and stopping to ask "which measure
# should rank them?" is wrong twice over: nothing is being ranked, and the
# measure was named.
#
# _RANKING_WORDS are superlatives that ask for an ordering however they are
# phrased: "best passengers", "top products", "most sales".
_RANKING_WORDS = (
    "best", "worst", "top", "bottom", "most", "least",
    "greatest", "largest", "smallest", "biggest",
)
# _MEASURE_ADJECTIVES far more often name a quantity than request an ordering —
# "maximum temperature", "minimum wage", "highest recorded rainfall". They count
# as a ranking request only when used substantively ("show me the highest"),
# which _used_substantively decides.
_MEASURE_ADJECTIVES = ("highest", "lowest", "maximum", "minimum", "max", "min")

_SUPERLATIVES = _RANKING_WORDS + _MEASURE_ADJECTIVES

# Explicit aggregation words: if one appears the metric is likely already stated.
_AGG_WORDS = ("average", "avg", "mean", "median", "sum", "total", "count", "number of")

# Things the closed grammar cannot express at all, grouped by what to say instead.
#
# This exists because the alternative is worse than a refusal: asked to "forecast
# next year's rainfall", the planner produced a perfectly valid *historical* trend
# and presented it as the answer. Silently substituting a different question is
# the exact failure mode this project is built to prevent, and no amount of
# prompt wording reliably stops it — so the check is deterministic and runs
# before the planner, like every other detector here.
#
# The lists are deliberately short. A false positive blocks legitimate work, so a
# term earns its place only when no supported reading of it exists:
#
#   * "relationship"/"related"/"correlation" are NOT here — a scatter plot is a
#     legitimate, supported answer to "is X related to Y".
#   * "trend", "growth", "over time" are NOT here — all are supported.
#   * "model", "project", "significant" are NOT here — far too common in ordinary
#     English to read as a request for statistical modelling.
_UNSUPPORTED: tuple[tuple[str, tuple[str, ...], str, str], ...] = (
    (
        "forecast",
        ("forecast", "forecasts", "forecasting", "forecasted",
         "predict", "predicts", "predicted", "prediction", "predictions",
         "predictive", "extrapolate", "extrapolation"),
        "AutoViz describes data that already exists — it cannot forecast or predict.",
        "Show what the data does say, over time",
    ),
    (
        "statistical_model",
        ("regression", "p-value", "p value", "confidence interval",
         "hypothesis test", "t-test", "chi-square", "chi square",
         "r-squared", "r squared", "statistical significance",
         "cluster", "clustering", "k-means", "kmeans"),
        "AutoViz computes descriptive statistics only — it does not fit models "
        "or run significance tests.",
        "Show the underlying values instead",
    ),
    (
        "join",
        ("join", "joins", "joined", "joining"),
        "AutoViz analyses one table at a time — it cannot join datasets.",
        "Analyse this dataset on its own",
    ),
)

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
    resolved = resolved or {}

    # Checked first and on its own. If the request asks for something that does
    # not exist, "which date column did you mean?" is not the question worth
    # asking — and answering it would walk the user further into a request that
    # cannot be honoured. Once the slot is resolved this falls through and the
    # ordinary detectors run against whatever the user agreed to instead.
    if "capability" not in resolved:
        unsupported = _detect_unsupported_capability(request, schema)
        if unsupported is not None:
            return [unsupported]

    found: list[Ambiguity] = []
    for detector in (
        _detect_time_column(request, schema),
        _detect_column_reference(request, schema),
        _detect_value_reference(request, profile),
        _detect_missing_metric(request, schema, profile),
    ):
        if detector is not None:
            found.append(detector)

    return [a for a in found if a.slot not in resolved]


# What the planner is told once the user has accepted the supported alternative.
# Keyed by the `fallback` recorded on the chosen option.
_CAPABILITY_CLAUSE = {
    "forecast": (
        "describe only the values present in the dataset — do NOT forecast, "
        "predict or extend beyond the last observation"
    ),
    "statistical_model": (
        "report the observed values only — do NOT fit a model, estimate a "
        "coefficient, or report a significance test"
    ),
    "join": (
        "use only the columns of this one dataset — there is no second table to "
        "join to"
    ),
    "cancel": "",
}


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
        if not val:  # a cancelled capability leaves nothing to fold in
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
        elif slot == "capability":
            # Spelled out as a prohibition, not just a substitution. The planner
            # has already shown it will answer a forecast with a trend if left to
            # infer; saying what must NOT happen is the half that was missing.
            clauses.append(_CAPABILITY_CLAUSE.get(val.get("fallback", ""), ""))
    if not clauses:
        return task
    return f"{task}  [Resolved constraints: {'; '.join(clauses)}]"


# --- capability detector ------------------------------------------------------


def _detect_unsupported_capability(
    request: str, schema: list[dict[str, str]]
) -> Ambiguity | None:
    """The request asks for a capability the closed grammar does not have.

    Returns an ``Ambiguity`` rather than a hard failure, because a dead end is
    rarely the most useful true answer. Declining *and* offering the nearest
    supported thing lets the user get value from the same turn — and, crucially,
    makes the substitution **their** choice rather than a silent one. The defect
    this fixes was never that a historical trend is a bad chart; it was that the
    user asked for a forecast and was handed a trend without being told.
    """
    for kind, terms, refusal, alternative in _UNSUPPORTED:
        term = _first_match(request, terms)
        if term is None:
            continue
        # A dataset with a column like `join_date` or `cluster_id` will have the
        # word in ordinary circulation, and the user naming their own column is
        # not a request for a capability. Schema beats vocabulary.
        if _names_a_column(term, schema):
            continue
        return Ambiguity(
            type="unsupported_capability",
            slot="capability",
            question=f"{refusal} What would you like instead?",
            options=[
                ClarificationOption(
                    label=alternative, resolves_to={"fallback": kind}
                ),
                ClarificationOption(
                    label="Nothing — cancel this request",
                    resolves_to={"fallback": "cancel"},
                ),
            ],
            detail={"capability": kind, "matched": term},
        )
    return None


def _names_a_column(term: str, schema: list[dict[str, str]]) -> bool:
    """Is `term` part of a real column name, rather than a request for a feature?"""
    return any(term in _norm(c.get("name", "")) for c in schema)


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
    trigger = _first_match(request, _RANKING_WORDS)
    if trigger is None:
        # A measure adjective only asks for a ranking when it is not modifying
        # the thing being measured — see _MEASURE_ADJECTIVES.
        trigger = next(
            (
                w
                for w in _MEASURE_ADJECTIVES
                if _used_substantively(request, w)
            ),
            None,
        )
    if trigger is None:
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
        # Quote the word that actually fired. A fixed "best"/"most" text sent
        # the user looking for words their request did not contain.
        question=f'Which measure should rank them? "{trigger}" isn\'t a column.',
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


def _first_match(text: str, needles: tuple[str, ...]) -> str | None:
    """The first needle present as a whole word, or None."""
    hay = _norm(text)
    for n in needles:
        if re.search(rf"\b{re.escape(n)}\b", hay):
            return n
    return None


def _used_substantively(text: str, word: str) -> bool:
    """Is `word` standing on its own rather than modifying the noun after it?

    "the highest" and "which is the maximum?" ask for an ordering. "maximum
    temperature" and "highest recorded rainfall" name a quantity, and treating
    them as ranking requests stops an ordinary question to ask an irrelevant one.

    Adjectives attach to the right, so the test is what follows: another word
    means the superlative is modifying it. Adverbs between the two ("highest
    *ever* recorded") are rare enough to leave on the adjectival side, where the
    cost of being wrong is a missed clarification rather than a blocked query.
    """
    hay = _norm(text)
    match = re.search(rf"\b{re.escape(word)}\b(?P<rest>.*)$", hay, flags=re.DOTALL)
    if match is None:
        return False
    rest = match.group("rest").lstrip()
    if not rest:
        return True  # ends the request: "show me the highest"
    # A following word makes it a modifier — unless that word is punctuation or
    # a preposition, which detach it again ("the maximum of fare", "the top 5").
    head = re.match(r"[a-z0-9]+", rest)
    if head is None:
        return True  # punctuation: "which is the maximum?"
    return head.group(0) in ("of", "in", "for", "by", "per", "among", "across")


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
