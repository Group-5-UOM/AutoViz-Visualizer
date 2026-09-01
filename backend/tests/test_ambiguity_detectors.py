"""Day 2: ambiguous-time-column and superlative-without-metric detectors."""

from autoviz.agent.ambiguity import apply_resolutions, detect_ambiguities
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


# --- unsupported capability (bench/nl_suite X02) ------------------------------
#
# "Forecast next year's rainfall" produced a valid *historical* trend and
# presented it as the answer. The chart was not wrong; substituting a different
# question without saying so was. The detector declines and offers the nearest
# supported thing, so the substitution becomes the user's choice.

WEATHER_FC = [
    {"name": "date", "type": "datetime"},
    {"name": "precipitation", "type": "number"},
    {"name": "temp_max", "type": "number"},
    {"name": "weather", "type": "string"},
]


def _capability(request, schema=WEATHER_FC, **kw):
    return [
        a for a in _detect(request, schema, **kw) if a.type == "unsupported_capability"
    ]


def test_forecast_is_declined_with_an_alternative():
    amb = _capability("Forecast next year's rainfall.")[0]
    assert amb.slot == "capability"
    assert "cannot forecast" in amb.question
    assert amb.detail["capability"] == "forecast"
    # Declining is only half of it — the nearest supported thing is offered too.
    assert amb.options[0].resolves_to == {"fallback": "forecast"}
    assert amb.options[-1].resolves_to == {"fallback": "cancel"}


def test_statistical_modelling_is_declined():
    amb = _capability("Run a regression of precipitation on temp_max")[0]
    assert amb.detail["capability"] == "statistical_model"


def test_join_is_declined():
    amb = _capability("Join this with the station metadata")[0]
    assert amb.detail["capability"] == "join"


def test_capability_check_preempts_every_other_question():
    """Asking which date column to use for a forecast walks the user further in."""
    ambs = _detect("Forecast revenue over time", TWO_DATES)
    assert [a.type for a in ambs] == ["unsupported_capability"]


def test_ordinary_detectors_resume_once_the_capability_is_resolved():
    ambs = _detect("Forecast revenue over time", TWO_DATES,
                   resolved={"capability": {"fallback": "forecast"}})
    assert [a.type for a in ambs] == ["time_column"]


def test_a_relationship_question_is_not_a_modelling_request():
    """A scatter plot is a legitimate, supported answer — this must not fire."""
    assert _capability("Is wind related to precipitation?") == []
    assert _capability("Is there a correlation worth plotting here?") == []


def test_supported_words_near_the_vocabulary_do_not_fire():
    for request in (
        "Show total precipitation per month over time.",
        "Show the trend of temp_max over the years",
        "What is the average precipitation by weather type?",
    ):
        assert _capability(request) == [], request


def test_a_column_named_after_the_capability_wins_over_the_vocabulary():
    """`join_date` is the user naming their own column, not asking for a join."""
    schema = [
        {"name": "join_date", "type": "datetime"},
        {"name": "revenue", "type": "number"},
    ]
    assert _capability("total revenue by join date", schema) == []


def test_accepting_the_alternative_forbids_the_thing_that_cannot_be_done():
    """The planner already showed it will answer a forecast with a trend."""
    folded = apply_resolutions("Forecast rainfall", {"capability": {"fallback": "forecast"}})
    assert "do NOT forecast" in folded


def test_cancelling_folds_nothing_into_the_task():
    assert apply_resolutions("Forecast rainfall", {"capability": {}}) == "Forecast rainfall"


# --- unknown-reference detector ----------------------------------------------
#
# Every test below has a negative twin, because this detector reads a phrase out
# of free text and the cost of reading it wrong is interrupting a request that
# was perfectly clear. Its first version did exactly that on five ordinary
# benchmark prompts.

TIPS = [
    {"name": "total_bill", "type": "number"},
    {"name": "tip", "type": "number"},
    {"name": "sex", "type": "string"},
    {"name": "smoker", "type": "string"},
    {"name": "day", "type": "string"},
    {"name": "size", "type": "number"},
]
TIPS_PROFILE = {
    "sample_values": {
        "sex": ["Female", "Male"],
        "smoker": ["No", "Yes"],
        "day": ["Fri", "Sat", "Sun", "Thur"],
    },
    "cardinality": {"sex": 2, "smoker": 2, "day": 4, "total_bill": 229, "tip": 123},
}


def _unknown(request, schema=TIPS, profile=None):
    found = detect_ambiguities(request, schema, TIPS_PROFILE if profile is None else profile)
    return next((a for a in found if a.type == "unknown_reference"), None)


def test_unknown_reference_fires_on_a_column_the_dataset_lacks():
    amb = _unknown("show average tip by waiter name")
    assert amb is not None
    assert amb.slot == "dimension"
    assert amb.detail["term"] == "waiter name"
    # Options are real groupable columns, so the answer binds to something.
    assert {"sex", "smoker", "day"} >= {
        o.resolves_to["column"] for o in amb.options if o.resolves_to
    }


def test_unknown_reference_offers_a_way_out_that_is_not_a_column():
    amb = _unknown("show average tip by waiter name")
    assert amb.options[-1].resolves_to == {}
    # And the label says what actually happens, rather than implying a stop.
    assert "without it" in amb.options[-1].label


def test_declining_every_option_leaves_the_task_untouched():
    assert apply_resolutions("tip by waiter", {"dimension": {}}) == "tip by waiter"


def test_a_modifier_before_a_real_column_is_not_an_unknown_column():
    # "for each passenger class" names `class`; "passenger" merely modifies it.
    # Read word-at-a-time this reported `passenger` missing and interrupted one
    # of the most ordinary requests in the benchmark.
    schema = TIPS + [{"name": "class", "type": "string"}]
    assert _unknown("what was the average fare for each passenger class", schema) is None


def test_a_head_noun_after_a_real_column_is_not_an_unknown_column():
    schema = TIPS + [{"name": "payment", "type": "string"}]
    assert _unknown("what is the average bill by payment type", schema) is None


def test_a_trailing_conjunction_is_not_an_unknown_column():
    assert _unknown("show average tip by day, and separately the count by sex") is None


def test_time_units_are_not_unknown_columns():
    # Every dataset with a date supports "by month"; there is no `month` column
    # and there does not need to be one.
    schema = [{"name": "served_at", "type": "datetime"}, {"name": "tip", "type": "number"}]
    assert _unknown("show total tips by month", schema) is None


def test_a_value_the_data_contains_is_not_an_unknown_column():
    # "by Male" is odd phrasing, but `Male` is a value of `sex` and the request
    # is about something the dataset really has.
    assert _unknown("break the tips down by male") is None


def test_unknown_reference_stays_quiet_when_nothing_is_grouped():
    assert _unknown("what is the distribution of tips") is None


def test_ranking_verbs_ask_for_a_measure():
    # "rank" cannot be read as naming a quantity the way "maximum" can, so it
    # needs no substantive test — but it was missing from the list entirely.
    schema = [
        {"name": "deck", "type": "string"},
        {"name": "fare", "type": "number"},
        {"name": "age", "type": "number"},
    ]
    ambs = detect_ambiguities("rank the decks", schema, {})
    assert any(a.type == "missing_metric" for a in ambs)


def test_order_is_not_a_ranking_verb():
    # `order_date` is a column in half the schemas there are, and "in order" is
    # an adverbial. Reading either as a request for a ranking blocks real work.
    schema = [
        {"name": "order_date", "type": "datetime"},
        {"name": "revenue", "type": "number"},
    ]
    assert detect_ambiguities("show revenue by order date", schema, {}) == []


# --- morphology: the same word, written the way people write it ---------------
#
# Both cases below come from the frozen 39. The unknown-reference detector
# interrupted them on its first outing, which is the expensive kind of bug: a
# request that named its column perfectly well, stopped to be asked what it
# meant.

TITANIC = [
    {"name": "survived", "type": "number"},
    {"name": "pclass", "type": "number"},
    {"name": "sex", "type": "string"},
    {"name": "fare", "type": "number"},
    {"name": "class", "type": "string"},
    {"name": "embark_town", "type": "string"},
    {"name": "deck", "type": "string"},
]


def test_a_plural_still_names_its_column():
    # "embarkation towns" is `embark_town`, twice over: a longer derived form of
    # `embark`, and the plural of `town`.
    assert detect_ambiguities(
        "compare average fare across embarkation towns", TITANIC, {}
    ) == []


def test_a_counted_plural_still_names_its_column():
    # "the three classes" is `class`; the count is not part of the name.
    assert detect_ambiguities(
        "how is fare distributed across the three classes", TITANIC, {}
    ) == []


def test_the_prefix_rule_does_not_reach_a_genuinely_absent_column():
    # The liberty taken above has to stop somewhere: no column word is a prefix
    # of "nationality", and titanic records where people boarded, not where they
    # were from. Those are different facts and the difference matters.
    ambs = detect_ambiguities("compare survival by nationality", TITANIC, {})
    assert any(a.type == "unknown_reference" for a in ambs)
