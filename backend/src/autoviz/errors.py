"""Typed error taxonomy for the analysis pipeline.

The old behaviour treated *every* execution failure as plan-repairable, so a
missing dataset or an internal DuckDB fault would burn the whole replan budget
regenerating a plan that was never the problem. This module gives each failure
a stable ``error_code`` and classifies it into one of three response classes so
the agent (and any MCP host) can react correctly:

* **plan-repairable** (``INVALID_PLAN``, ``TYPE_MISMATCH``) — the plan is wrong;
  regenerating it can fix the failure.
* **retryable** (``EXECUTION_ERROR``, ``TIMEOUT``) — the plan is fine, the
  environment faulted transiently; retry with backoff, do *not* replan.
* **terminal** (``UNKNOWN_DATASET``, ``RESOURCE_LIMIT``, ``CHART_ERROR``) —
  neither replanning nor retrying helps; surface an actionable message.

Structured errors keep the existing ``error`` message key so current callers
and tests are unaffected; the ``error_code`` / ``retryable`` / ``user_action``
fields are additive.
"""

from typing import Any

# Plan-repairable: regenerating the analysis plan can fix it.
INVALID_PLAN = "INVALID_PLAN"  # structural / schema violation
TYPE_MISMATCH = "TYPE_MISMATCH"  # op or fn applied to an incompatible column type

# Retryable: the plan is valid; the environment faulted. Retry with backoff.
EXECUTION_ERROR = "EXECUTION_ERROR"  # DuckDB raised on an already-validated plan
TIMEOUT = "TIMEOUT"  # execution exceeded the time budget

# Terminal: neither replanning nor retrying helps.
UNKNOWN_DATASET = "UNKNOWN_DATASET"  # dataset_id not registered
RESOURCE_LIMIT = "RESOURCE_LIMIT"  # file / row / column / memory ceiling exceeded
CHART_ERROR = "CHART_ERROR"  # chart step failed after a successful execution
FILE_ERROR = "FILE_ERROR"  # source file missing, unreadable, or empty
FORBIDDEN_PATH = "FORBIDDEN_PATH"  # a write target escaped its allowed directory
NO_CHART_FIT = "NO_CHART_FIT"  # no column in the result can carry the requested chart
INVALID_SPEC = "INVALID_SPEC"  # a caller-supplied Vega-Lite spec is malformed
CANCELLED = "CANCELLED"  # the caller cancelled the request mid-execution

PLAN_REPAIRABLE = frozenset({INVALID_PLAN, TYPE_MISMATCH})
RETRYABLE = frozenset({EXECUTION_ERROR, TIMEOUT})
TERMINAL = frozenset(
    {
        UNKNOWN_DATASET,
        RESOURCE_LIMIT,
        CHART_ERROR,
        FILE_ERROR,
        FORBIDDEN_PATH,
        NO_CHART_FIT,
        INVALID_SPEC,
        CANCELLED,
    }
)

_USER_ACTION: dict[str, str] = {
    INVALID_PLAN: "The analysis plan was malformed; it will be regenerated.",
    TYPE_MISMATCH: (
        "A column was used with an incompatible operation; the plan will be corrected."
    ),
    EXECUTION_ERROR: "The query engine failed unexpectedly; retrying.",
    TIMEOUT: "The query took too long; narrow the request (fewer rows or groups) and retry.",
    UNKNOWN_DATASET: "Register the dataset first, then reference the dataset_id it returns.",
    RESOURCE_LIMIT: "The dataset or result is too large; reduce its size and try again.",
    CHART_ERROR: "The result is available, but a chart could not be built for it.",
    FILE_ERROR: "Check the file path and that the file is a readable, non-empty CSV.",
    FORBIDDEN_PATH: "Choose a filename without path separators or parent references.",
    NO_CHART_FIT: "The result has no plottable measure; aggregate a numeric column first.",
    INVALID_SPEC: "Pass a Vega-Lite spec dict, such as the one generate_chart returns.",
    CANCELLED: "The request was cancelled before it finished; no results were produced.",
}


def user_action_for(code: str | None) -> str:
    """The one-line remediation for an error code, or "" if there isn't one."""
    return _USER_ACTION.get(code or "", "")


def is_retryable(code: str | None) -> bool:
    return code in RETRYABLE


def is_plan_repairable(code: str | None) -> bool:
    return code in PLAN_REPAIRABLE


def is_failure(result: Any) -> bool:
    """True if a service result encodes a failure rather than a value.

    The single detection predicate for the three failure shapes the services
    produce: ``{error, ...}`` (make_error), ``{valid: false, errors}``
    (validation), and ``{status: "error", failed_step, ...}`` (orchestrator).
    Shared by the HTTP layer (autoviz.api.errors), the observability decorator,
    and the MCP envelope so all three cannot drift apart.

    Note this is *not* the same question as "should MCP set isError" — a
    validation rejection is a failure here but a successful tool call over the
    wire. See autoviz.mcp.envelope for that policy.
    """
    return isinstance(result, dict) and (
        "error" in result
        or result.get("valid") is False
        or result.get("status") == "error"
    )


def make_error(code: str, message: str, **extra: Any) -> dict[str, Any]:
    """Build a structured error dict.

    Always carries ``error`` (human message, unchanged contract), ``error_code``,
    ``retryable``, and ``user_action``. ``extra`` merges in call-site context
    such as ``validation_errors`` or ``sql``.
    """
    return {
        "error": message,
        "error_code": code,
        "retryable": code in RETRYABLE,
        "user_action": _USER_ACTION.get(code, ""),
        **extra,
    }
