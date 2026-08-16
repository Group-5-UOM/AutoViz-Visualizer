"""Day 2: ambiguous-time-column and superlative-without-metric detectors."""

from autoviz.agent.ambiguity import detect_ambiguities
from autoviz.services import dataset as dataset_service

TWO_DATES = [
    {"name": "signup_date", "type": "datetime"},
    {"name": "order_date", "type": "datetime"},
    {"name": "revenue", "type": "number"},
    {"name": "units", "type": "number"},
    {"name": "region", "type": "string"},
]
ONE_DATE = [
    {"name": "order_date", "type": "datetime"},
    {"name": "revenue", "type": "number"},
]


def _detect(request, schema, **kw):
    return detect_ambiguities(request, schema, {}, **kw)


# --- time-column detector ----------------------------------------------------

def test_time_column_ambiguous_when_temporal_and_two_dates():
    ambs = _detect("show revenue over time", TWO_DATES)
    amb = next(a for a in ambs if a.type == "time_column")
    assert amb.slot == "time_column"
    assert [o.resolves_to["column"] for o in amb.options] == ["signup_date", "order_date"]
    assert amb.options[0].label == "Signup date"  # grounded, prettified


def test_time_column_not_ambiguous_when_user_names_one():
    # "signup_date" is explicitly named -> no ambiguity.
    assert _detect("monthly trend by signup_date", TWO_DATES) == []


def test_time_column_not_ambiguous_with_single_date():
    assert _detect("revenue over time", ONE_DATE) == []


def test_time_column_not_ambiguous_when_not_temporal():
    # Two date columns, but nothing temporal in the ask.
    assert _detect("total revenue by region", TWO_DATES) == []


# --- missing-metric detector -------------------------------------------------

def test_missing_metric_ambiguous_on_bare_superlative():
    ambs = _detect("which region is best", TWO_DATES)
    amb = next(a for a in ambs if a.type == "missing_metric")
    assert amb.slot == "metric"
    labels = [o.label for o in amb.options]
    assert "Average revenue" in labels and "Average units" in labels
    assert labels[-1] == "Number of records (count)"
    assert amb.options[-1].resolves_to == {"fn": "count"}


def test_missing_metric_clear_when_numeric_named():
    # "revenue" (numeric) is named -> the ranking measure is clear.
    assert _detect("region with the highest revenue", TWO_DATES) == []


def test_missing_metric_clear_with_agg_word_and_numbers():
    # An explicit aggregation word implies the metric even without naming a column.
    assert _detect("top region by total", TWO_DATES) == []


def test_no_superlative_no_metric_ambiguity():
    assert _detect("revenue by region", TWO_DATES) == []


# --- superlative-as-adjective (regression, found by bench/nl_suite W03/W07) ---
#
# "maximum"/"minimum"/"highest"/"lowest" name a quantity far more often than
# they request an ordering. Firing on the adjectival use stopped ordinary
# questions to ask which measure should "rank them" when nothing was being
# ranked and the measure was already named.

WEATHER = [
    {"name": "date", "type": "datetime"},
    {"name": "precipitation", "type": "number"},
    {"name": "temp_max", "type": "number"},
    {"name": "temp_min", "type": "number"},
    {"name": "weather", "type": "string"},
]


def test_measure_adjective_before_a_noun_is_not_a_ranking_request():
    assert [
        a for a in _detect("How did the maximum temperature change over the years?", WEATHER)
        if a.type == "missing_metric"
    ] == []


def test_measure_adjective_in_a_grouped_request_is_not_a_ranking_request():
    assert [
        a for a in _detect("the spread of daily maximum temperatures by weather type", WEATHER)
        if a.type == "missing_metric"
    ] == []


def test_measure_adjective_used_substantively_still_asks():
    amb = next(
        a for a in _detect("show me the highest", WEATHER) if a.type == "missing_metric"
    )
    assert amb.slot == "metric"


def test_measure_adjective_detached_by_a_preposition_still_asks():
    amb = next(
        a for a in _detect("which weather type has the maximum?", WEATHER)
        if a.type == "missing_metric"
    )
    assert amb.slot == "metric"


def test_question_quotes_the_word_that_actually_fired():
    """A fixed "best"/"most" text sent users hunting for words they never typed."""
    amb = next(
        a for a in _detect("which region is largest", TWO_DATES)
        if a.type == "missing_metric"
    )
    assert '"largest"' in amb.question


def test_metric_options_are_capped():
    many = [{"name": f"n{i}", "type": "number"} for i in range(9)] + [
        {"name": "cat", "type": "string"}
    ]
    amb = next(a for a in _detect("best cat", many) if a.type == "missing_metric")
    # 5 average options + the count option.
    assert len(amb.options) == 6


# --- composition & suppression ----------------------------------------------

def test_both_detectors_compose_time_first():
    ambs = _detect("which region trends best over time", TWO_DATES)
    assert [a.type for a in ambs] == ["time_column", "missing_metric"]


def test_resolved_slot_is_suppressed():
    ambs = _detect("region trend over time", TWO_DATES, resolved={"time_column": {"column": "order_date"}})
    assert all(a.slot != "time_column" for a in ambs)


# --- real dataset (schema shape) ---------------------------------------------

def test_missing_metric_on_real_titanic_schema(registry, titanic_id):
    schema = dataset_service.get_dataset_schema(titanic_id, registry)["columns"]
    profile = dataset_service.get_dataset_profile(titanic_id, registry)
    ambs = detect_ambiguities("which passenger class is the best", schema, profile)
    amb = next(a for a in ambs if a.type == "missing_metric")
    # With cardinality ranking, the continuous measures fare/age are offered ahead
    # of the low-cardinality codes (survived 0/1, pclass 1-3) despite the 5-cap.
    cols = [o.resolves_to.get("column") for o in amb.options]
    assert "fare" in cols and "age" in cols
