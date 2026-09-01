"""Day 1: schemas + deterministic answer binding for ambiguity resolution."""

import pytest

from autoviz.schema.clarification import (
    Ambiguity,
    ClarificationOption,
    ClarificationState,
    Resolution,
    bind_answer,
)


def _time_ambiguity() -> Ambiguity:
    return Ambiguity(
        type="time_column",
        slot="time_column",
        question="Which date column should I use for the trend?",
        options=[
            ClarificationOption(label="Signup date", resolves_to={"column": "signup_date"}),
            ClarificationOption(label="Order date", resolves_to={"column": "order_date"}),
        ],
        detail={"candidates": ["signup_date", "order_date"]},
    )


def _metric_ambiguity() -> Ambiguity:
    return Ambiguity(
        type="missing_metric",
        slot="metric",
        question="What does 'best' mean here?",
        options=[
            ClarificationOption(label="Highest average fare",
                                resolves_to={"aggregation": {"column": "fare", "fn": "mean"}}),
            ClarificationOption(label="Most passengers",
                                resolves_to={"aggregation": {"column": "*", "fn": "count"}}),
        ],
    )


# --- binding: option matches -------------------------------------------------

def test_bind_exact_label_match():
    amb = _time_ambiguity()
    r = bind_answer(amb, "Order date")
    assert r.source == "option"
    assert r.slot == "time_column"
    assert r.value == {"column": "order_date"}
    assert r.matched_label == "Order date"
    assert r.resolved is True


def test_bind_is_case_and_space_insensitive():
    r = bind_answer(_time_ambiguity(), "  ORDER   DATE ")
    assert r.source == "option"
    assert r.value == {"column": "order_date"}


def test_bind_matches_typed_column_name_inside_resolves_to():
    # User types the real column name, not the pretty label.
    r = bind_answer(_time_ambiguity(), "signup_date")
    assert r.source == "option"
    assert r.matched_label == "Signup date"
    assert r.value == {"column": "signup_date"}


def test_bind_substring_match():
    r = bind_answer(_metric_ambiguity(), "highest average")
    assert r.source == "option"
    assert r.matched_label == "Highest average fare"


def test_bind_nested_resolves_to_is_preserved():
    r = bind_answer(_metric_ambiguity(), "Most passengers")
    assert r.value == {"aggregation": {"column": "*", "fn": "count"}}


# --- binding: free text / unmatched ------------------------------------------

def test_bind_falls_back_to_free_text():
    r = bind_answer(_time_ambiguity(), "the fiscal year column please")
    assert r.source == "free_text"
    assert r.value == {"text": "the fiscal year column please"}
    assert r.matched_label is None
    assert r.resolved is True


def test_bind_unmatched_when_free_text_disallowed():
    amb = _time_ambiguity()
    amb.allow_free_text = False
    r = bind_answer(amb, "something unrelated xyz")
    assert r.source == "unmatched"
    assert r.resolved is False


def test_bind_short_answer_does_not_trigger_substring():
    # A 2-char answer must not loosely substring-match an option.
    amb = Ambiguity(
        type="column_reference", slot="dimension", question="Which column?",
        options=[ClarificationOption(label="Age", resolves_to={"column": "age"})],
        allow_free_text=False,
    )
    r = bind_answer(amb, "zz")
    assert r.source == "unmatched"


# --- wire shape --------------------------------------------------------------

def test_to_wire_reduces_to_question_labels_and_slot():
    wire = _time_ambiguity().to_wire()
    assert wire == {
        "question": "Which date column should I use for the trend?",
        "options": ["Signup date", "Order date"],
        # The binding itself stays server-side, but the slot travels: it is what
        # service._group_key dedupes concurrent pauses on, and the only way a
        # host can say what is being decided rather than just quoting the prose.
        "slot": "time_column",
    }


# --- state machine -----------------------------------------------------------

def test_state_records_resolution_and_advances_queue():
    st = ClarificationState(pending=[_time_ambiguity(), _metric_ambiguity()])
    assert st.next_ambiguity().slot == "time_column"

    st.record(bind_answer(st.next_ambiguity(), "Order date"))
    assert st.rounds == 1
    assert st.resolved == {"time_column": {"column": "order_date"}}
    assert st.next_ambiguity().slot == "metric"  # front dropped, next surfaces

    st.record(bind_answer(st.next_ambiguity(), "Most passengers"))
    assert st.rounds == 2
    assert st.next_ambiguity() is None
    assert st.resolved["metric"] == {"aggregation": {"column": "*", "fn": "count"}}


def test_state_record_only_pops_when_slot_matches_front():
    st = ClarificationState(pending=[_time_ambiguity()])
    # A resolution for a different slot must not pop the time_column ambiguity.
    st.record(Resolution(slot="metric", source="free_text", value={"text": "x"}))
    assert st.next_ambiguity().slot == "time_column"
    assert st.resolved["metric"] == {"text": "x"}


def test_models_forbid_extra_fields():
    with pytest.raises(Exception):
        ClarificationOption(label="x", resolves_to={}, bogus=1)  # type: ignore[call-arg]
