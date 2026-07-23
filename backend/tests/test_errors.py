"""Unit tests for the typed error taxonomy."""

from autoviz import errors
from autoviz.errors import (
    EXECUTION_ERROR,
    INVALID_PLAN,
    RESOURCE_LIMIT,
    TIMEOUT,
    TYPE_MISMATCH,
    UNKNOWN_DATASET,
    is_plan_repairable,
    is_retryable,
    make_error,
)


def test_make_error_carries_message_and_metadata():
    err = make_error(TIMEOUT, "too slow", sql="SELECT 1")
    assert err["error"] == "too slow"
    assert err["error_code"] == TIMEOUT
    assert err["retryable"] is True
    assert err["user_action"]  # non-empty guidance
    assert err["sql"] == "SELECT 1"  # extra context preserved


def test_retryable_only_for_infrastructure_codes():
    assert is_retryable(EXECUTION_ERROR)
    assert is_retryable(TIMEOUT)
    for code in (INVALID_PLAN, TYPE_MISMATCH, UNKNOWN_DATASET, RESOURCE_LIMIT):
        assert not is_retryable(code)


def test_plan_repairable_only_for_plan_codes():
    assert is_plan_repairable(INVALID_PLAN)
    assert is_plan_repairable(TYPE_MISMATCH)
    for code in (EXECUTION_ERROR, TIMEOUT, UNKNOWN_DATASET, RESOURCE_LIMIT):
        assert not is_plan_repairable(code)


def test_response_classes_are_disjoint():
    assert errors.PLAN_REPAIRABLE.isdisjoint(errors.RETRYABLE)


def test_none_code_is_neither():
    assert not is_retryable(None)
    assert not is_plan_repairable(None)
