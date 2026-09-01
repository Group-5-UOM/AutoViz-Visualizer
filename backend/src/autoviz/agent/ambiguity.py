"""Deterministic ambiguity detectors (Direction B, Days 2-3).

These run over ``request × schema × profile`` BEFORE the planner LLM, so the
decision to ask a follow-up question is a computed signal, not a prompt guess.
Each detector returns grounded ``Ambiguity`` objects whose options reference real
columns/values; the LLM's only job downstream is to phrase nicely (Day 4).

Day 2 covers `time_column` and `missing_metric`. Day 3 adds `column_reference` /
`value_reference`. `detect_ambiguities` is the single entry point the graph calls.
"""

import re
import unicodedata
from typing import Any, get_args

from autoviz.schema.clarification import (
    Ambiguity,
    AmbiguityType,
    ClarificationOption,
    Slot,
)

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
    # Verbs that request an ordering outright. Unlike the adjectives above these
    # cannot be read as naming a quantity, so they need no substantive test.
    # "order" is deliberately absent: it is a noun in half the schemas there are
    # (`order_date`, `order_id`) and an adverbial in the other half ("in order").
    "rank", "ranked", "ranking",
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
        # First of the ordinary detectors for the same reason the capability
        # check runs before all of them: if the request names something the
        # dataset has not got, "which of these did you mean?" about some other
        # part of the sentence is not the question worth asking.
        _detect_unknown_reference(request, schema, profile),
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
        elif slot == "aggregation" and val.get("fn"):
            if val.get("column"):
                clauses.append(f"aggregate using {val['fn']} of `{val['column']}`")
            else:
                clauses.append(f"aggregate using {val['fn']}")
        elif slot == "time_grain" and val.get("grain"):
            clauses.append(f"group the time axis by {val['grain']}")
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


# --- the LLM proposal gate ----------------------------------------------------
#
# Everything above this line decides *for itself* whether to ask, using only the
# schema and the request. This section handles the other source: an ambiguity
# proposed by the classifier LLM, which can see meaning the lexical rules cannot
# ("revenue" is `total_bill`) and can also invent columns wholesale.
#
# The split is deliberate, and it mirrors how composed prose is already handled
# in `compose_response`: the model writes, and a deterministic check decides
# whether what it wrote survives. A proposal that clears this gate is
# indistinguishable downstream from a detector's — same queue, same
# `bind_answer`, same `apply_resolutions` — so the LLM never gets a weaker path
# to the user than the detectors have.

# Aggregate functions and time grains an option may bind to. Anything else is a
# fabrication, however plausible it reads.
_VALID_FNS = frozenset({"count", "sum", "mean", "median", "min", "max"})
_VALID_GRAINS = frozenset({"day", "month", "year"})

# Long enough for a real question, short enough that a runaway generation cannot
# fill the panel. Question text is model output rendered verbatim to the user.
_MAX_QUESTION_CHARS = 240

_AMBIGUITY_TYPES = frozenset(get_args(AmbiguityType))
_SLOTS = frozenset(get_args(Slot))


def ground_ambiguity(
    proposed: dict[str, Any] | None,
    schema: list[dict[str, str]],
    profile: dict[str, Any],
    *,
    request: str = "",
    resolved: dict[str, Any] | None = None,
) -> Ambiguity | None:
    """Validate an LLM-proposed ambiguity against the real dataset, or drop it.

    Returns a grounded `Ambiguity` whose every option references a column, value,
    function or grain that exists — or None, meaning do not ask. None is the safe
    outcome throughout: the request proceeds to the planner, which is exactly what
    happened before this layer existed.
    """
    if not isinstance(proposed, dict):
        return None
    resolved = resolved or {}

    amb_type = proposed.get("type")
    slot = proposed.get("slot")
    if amb_type not in _AMBIGUITY_TYPES or slot not in _SLOTS:
        return None

    # The loop guard. Without it the classifier re-proposes the slot the user has
    # just answered, and the round budget — not the logic — is what stops it.
    if slot in resolved:
        return None

    question = _clean_text(proposed.get("question"))
    if question is None:
        return None

    options = _ground_options(proposed.get("options"), schema, profile)
    # One option is not a choice, and none is a hallucination. Either way the
    # honest move is to let the planner proceed rather than stage a question.
    if len(options) < 2:
        return None

    if _already_disambiguated(request, options):
        return None

    return Ambiguity(
        type=amb_type,
        slot=slot,
        question=question,
        options=options[:_MAX_METRIC_OPTIONS],
        origin="llm",
        detail={"proposed_options": len(proposed.get("options") or [])},
    )


def _clean_text(raw: Any) -> str | None:
    """Collapse to a single printable line, or None if nothing usable is left.

    Control and format characters go first — the format class includes the bidi
    overrides, which let a string render differently from how it reads in the
    source. Request text reaches this function's inputs, so it is hostile until
    proven otherwise.
    """
    if not isinstance(raw, str):
        return None
    stripped = "".join(c for c in raw if unicodedata.category(c) not in ("Cc", "Cf"))
    collapsed = " ".join(stripped.split())
    if not collapsed:
        return None
    if len(collapsed) > _MAX_QUESTION_CHARS:
        collapsed = collapsed[: _MAX_QUESTION_CHARS - 1].rstrip() + "\u2026"
    return collapsed


def _ground_options(
    raw: Any, schema: list[dict[str, str]], profile: dict[str, Any]
) -> list[ClarificationOption]:
    """Keep the options that bind to something real; drop the rest silently."""
    if not isinstance(raw, list):
        return []
    names = {c.get("name") for c in schema}
    samples: dict[str, list[str]] = profile.get("sample_values", {}) or {}
    kept: list[ClarificationOption] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = _clean_text(item.get("label"))
        if label is None:
            continue
        bound = _ground_resolves_to(item.get("resolves_to"), names, samples)
        # An option bound to nothing cannot steer the plan, so choosing it would
        # change nothing the user could see — the silent no-op this gate exists
        # to catch.
        if not bound:
            continue
        key = repr(sorted(bound.items()))
        if key in seen:  # two labels for one binding is not a choice
            continue
        seen.add(key)
        kept.append(ClarificationOption(label=label, resolves_to=bound))
    return kept


def _ground_resolves_to(
    raw: Any, names: set[Any], samples: dict[str, list[str]]
) -> dict[str, Any]:
    """The subset of a proposed binding that actually exists in this dataset.

    Any single bad key voids the whole option rather than being dropped from it.
    A half-kept binding is the dangerous outcome: "average of `waiter`" with the
    column quietly removed becomes "average", which the planner will happily
    apply to some other column entirely.
    """
    if not isinstance(raw, dict):
        return {}
    bound: dict[str, Any] = {}
    column = raw.get("column")
    if isinstance(column, str):
        if column not in names:
            return {}
        bound["column"] = column
    value = raw.get("value")
    if value is not None:
        # A value with no column cannot be filtered on, and a value the column
        # does not contain filters to an empty chart.
        if "column" not in bound or str(value) not in (samples.get(bound["column"]) or []):
            return {}
        bound["value"] = str(value)
    fn = raw.get("fn")
    if fn is not None:
        if fn not in _VALID_FNS:
            return {}
        bound["fn"] = fn
    grain = raw.get("grain")
    if grain is not None:
        if grain not in _VALID_GRAINS:
            return {}
        bound["grain"] = grain
    fallback = raw.get("fallback")
    if fallback is not None:
        if fallback not in _CAPABILITY_CLAUSE:
            return {}
        bound["fallback"] = fallback
    return bound


def _already_disambiguated(request: str, options: list[ClarificationOption]) -> bool:
    """Did the request already name exactly one of the columns being offered?

    This is the over-ask guard. The classifier sees `pickup_borough` and
    `dropoff_borough` in the schema and can propose the clash even when the user
    wrote "by pickup borough". Deciding that from the request text is cheap and
    certain, and does not need a model's opinion of its own confidence.
    """
    candidates = [
        o.resolves_to["column"] for o in options if isinstance(o.resolves_to.get("column"), str)
    ]
    if len(candidates) < 2:
        return False
    return len(_mentioned_columns(request, candidates)) == 1


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


# --- unknown-reference detector -----------------------------------------------
#
# Added after the first ambiguity benchmark showed the original five detectors
# leaving a whole category untouched: a request that groups by something the
# dataset simply has not got. It belongs here rather than in the LLM layer
# because it is decidable from the request and the schema alone.

# Prepositions that introduce a grouping. Deliberately not "of": "the
# distribution of petal widths" is a measure, not a grouping, and reading it as
# one turns a well-specified request into a question.
_GROUPING_PREPS = ("grouped by", "broken down by", "for each", "across", "by", "per")

# Determiners and quantities, which carry no reference and are passed over.
# "across the three classes" groups by `class`; the count is not part of the name.
_GROUPING_SKIP = frozenset({
    "the", "a", "an", "each", "every", "their", "its", "all", "both",
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "first", "last", "several", "many", "few", "top", "bottom",
})

# Words that END a grouping phrase rather than joining it. Without these, "by
# day, and separately the count by sex" reads "and separately" as the name of a
# column, and "top region by total" reads the aggregate as one.
_PHRASE_STOP = frozenset({
    "and", "or", "but", "then", "also", "plus", "versus", "vs", "while", "where",
    "using", "with", "from", "over", "during", "only", "just", "excluding",
    "including", "sorted", "ordered", "separately",
    # Aggregates name what to compute, never what to group by.
    "average", "avg", "mean", "median", "sum", "total", "count", "number",
})

# Time buckets a date column supports. There is no `month` column in any of these
# datasets and there does not need to be one: "by month" is a grain, and every
# dataset with a date can be grouped by it. Treated as known rather than skipped,
# so that a dataset which *does* have a `day` column still matches it normally.
_TIME_UNITS = frozenset({
    "day", "days", "date", "dates", "week", "weeks", "weekday", "weekdays",
    "month", "months", "quarter", "quarters", "year", "years", "hour", "hours",
    "minute", "minutes", "time", "season", "seasons", "decade", "decades",
})

# How many words after the preposition can belong to the grouping phrase.
# "by pickup borough" is two; "by average fare paid last year" is not a grouping
# phrase at all, and reading further only invents matches.
_GROUPING_PHRASE_WORDS = 2

# Distinct values below which a grouping column is a category rather than a key.
# Used to pick fallback options for an unknown reference: offering `name` as a
# thing to group 900 rows by is not help.
_MAX_GROUPABLE_CARDINALITY = 50


def _grouping_phrases(request: str) -> list[list[str]]:
    """The word groups that follow a grouping preposition, noise removed.

    "show average tip by waiter name" -> [["waiter", "name"]].

    Phrases, not loose words, because the question "is this a column we have?"
    is only answerable about the whole phrase. "for each passenger class" names
    `class` and modifies it with "passenger"; asked word by word, the modifier
    looks like a column the dataset is missing, and five ordinary requests in
    the benchmark were interrupted on exactly that mistake.
    """
    hay = _norm(request)
    phrases: list[list[str]] = []
    for prep in _GROUPING_PREPS:
        for match in re.finditer(rf"\b{re.escape(prep)}\b(?P<rest>.*)", hay):
            phrase: list[str] = []
            for word in re.findall(r"[a-z0-9_]+", match.group("rest")):
                if word in _GROUPING_SKIP:
                    continue
                if word in _PHRASE_STOP or len(word) < 3:
                    break  # a function word or an aggregate ends the phrase
                phrase.append(word)
                if len(phrase) >= _GROUPING_PHRASE_WORDS:
                    break
            if phrase:
                phrases.append(phrase)
    return phrases


def _forms(word: str) -> set[str]:
    """`word` and its plausible singulars: "towns" -> {towns, town}."""
    forms = {word}
    if len(word) > 3:
        if word.endswith("es"):
            forms.add(word[:-2])
        if word.endswith("s"):
            forms.add(word[:-1])
    return forms


def _same_thing(word: str, target: str) -> bool:
    """Do these two words name the same thing, allowing for how people write?

    Two liberties, both earned by a false positive on the frozen benchmark:

    * plurals — "across embarkation *towns*" is `embark_town`;
    * a longer derived form — "*embarkation*" is `embark`.

    Only a prefix counts for the second, and only from four characters, so
    `day`/`daytime` and `tip`/`tipping` stay out of it. Being too generous here
    costs a missed question; being too strict interrupts a request that named
    its column perfectly well, which is what both of these did.
    """
    for w in _forms(word):
        for t in _forms(target):
            if w == t:
                return True
            if len(t) >= 4 and w.startswith(t):
                return True
            if len(w) >= 4 and t.startswith(w):
                return True
    return False


def _is_known(word: str, schema: list[dict[str, str]], profile: dict[str, Any]) -> bool:
    """Does this word name a column, part of one, a value, or a time bucket?"""
    if word in _TIME_UNITS:
        return True
    for col in schema:
        name = col.get("name", "")
        if any(_same_thing(word, part) for part in _col_words(name)):
            return True
        if _same_thing(word, _norm(name)):
            return True
    for values in (profile.get("sample_values") or {}).values():
        if any(_same_thing(word, _norm(v)) for v in values):
            return True
    return False


def _detect_unknown_reference(
    request: str, schema: list[dict[str, str]], profile: dict[str, Any]
) -> Ambiguity | None:
    """The request groups by something this dataset does not have.

    The failure this prevents is not a crash — it is the planner picking the
    nearest column it does have and presenting the result as the answer. Asked
    for "average tip by waiter name", a tool that charts tip by `sex` has not
    answered the question; it has answered a different one silently.
    """
    unknown = [
        phrase
        for phrase in _grouping_phrases(request)
        if not any(_is_known(w, schema, profile) for w in phrase)
    ]
    if not unknown:
        return None
    term = " ".join(unknown[0])
    options = [
        ClarificationOption(label=_pretty(c), resolves_to={"column": c})
        for c in _groupable_columns(schema, profile)
    ]
    if not options:
        return None  # nothing to offer instead; let the planner fail honestly
    options.append(
        ClarificationOption(
            # Says what actually happens, rather than implying the run stops.
            label="None of these — answer without it",
            resolves_to={},
        )
    )
    return Ambiguity(
        type="unknown_reference",
        slot="dimension",
        question=f'There is no "{term}" in this dataset. What should I group by instead?',
        options=options,
        detail={"term": term, "unknown": [" ".join(p) for p in unknown]},
    )


def _groupable_columns(
    schema: list[dict[str, str]], profile: dict[str, Any]
) -> list[str]:
    """Columns worth offering as a grouping: categories, fewest values first."""
    card = profile.get("cardinality", {})
    usable = [
        c["name"]
        for c in schema
        if c.get("type") in ("string", "boolean")
        and card.get(c["name"], 0) <= _MAX_GROUPABLE_CARDINALITY
    ]
    return sorted(usable, key=lambda c: card.get(c, 0))[:_MAX_METRIC_OPTIONS - 1]


# Two further detectors were built here and removed, and the reason is worth
# keeping: **aggregation** ("show the fare by payment type" — total, average or
# count?) and **time granularity** ("show how precipitation changed over time" —
# by day, month or year?). Both are real ambiguities. Neither is decidable from
# the words.
#
# The benchmark is what settled it. Every rule that fired on "show the bill by
# day" also fired on "tips by smoker", and every rule that fired on "how
# precipitation changed over time" also fired on "the trend in wind speed over
# time" — structurally identical requests where asking is friction rather than
# care. Over-asking went from 0% to 25% of the negative set, and no tightening
# of the trigger separated the pairs, because there is nothing lexical to
# separate: the difference lives in how much the phrasing implies a default.
#
# So they are the LLM layer's, not this one's — which is the whole point of
# having two layers. `aggregation` and `time_grain` remain in the Slot taxonomy
# and in `apply_resolutions`, and `ground_ambiguity` validates the `fn` and
# `grain` an LLM proposal binds to, so a question of either kind still arrives
# grounded and still binds.


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
