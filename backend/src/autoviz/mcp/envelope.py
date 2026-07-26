"""The MCP failure-signalling policy: which service results become isError.

MCP distinguishes two things AutoViz previously collapsed into one. A *protocol*
success with a negative payload ("this plan is invalid", "confirm before I drop
128 rows") is a tool that did its job. A *tool-execution failure* ("that dataset
does not exist", "the query timed out") is a tool that could not. Before this
module every failure came back as an ordinary dict with ``isError: false``, so a
host that branches on ``isError`` — to stop a chain, retry, or record a failure —
would happily feed a failed execution into the chart step.

The rule:

    isError: true  when the tool could not fulfil its contract.
    isError: false when the tool successfully determined that the requested
                   operation was invalid, unsupported, or awaiting confirmation.

Applied to AutoViz's taxonomy (autoviz.errors):

===========================  ==========  =========================================
result                       isError     why
===========================  ==========  =========================================
``valid: false``             false       the validator worked; the plan is wrong
``confirmation_required``    false       nothing failed; the workflow paused
``waiting_for_user``         false       same, one level up in the agent
CHART_ERROR / NO_CHART_FIT   false       the query succeeded and the result is
                                         returned; only the chart step failed, so
                                         this becomes status "partial"
UNKNOWN_DATASET              true        cannot operate on a dataset that is gone
TIMEOUT / EXECUTION_ERROR    true        the engine faulted
RESOURCE_LIMIT               true        a hard ceiling was hit
FILE_ERROR / FORBIDDEN_PATH  true        the input or target is unusable
INVALID_SPEC                 true        the caller's argument is not a spec
agent ``status: "failed"``   true        the workflow produced nothing usable
unexpected exception         true        (FastMCP converts it for us)
===========================  ==========  =========================================

Implementation note — this uses ``raise ToolError`` rather than returning a
``CallToolResult(isError=True, structuredContent=...)``. The two are not
interchangeable here: ``FuncMetadata.convert_result`` validates a returned
CallToolResult's structuredContent against the tool's *success* output model, so
an error-shaped payload fails validation and surfaces as a Pydantic dump instead
of the message. Structured error metadata is therefore folded into the message
text, which both the host and its LLM can read.
"""

from typing import Any, TypeVar

from mcp.server.fastmcp.exceptions import ToolError
from pydantic import BaseModel

from autoviz.errors import (
    CHART_ERROR,
    NO_CHART_FIT,
    user_action_for,
)

M = TypeVar("M", bound=BaseModel)

# Pipeline steps whose failure still leaves a valid, traceable result table.
# run_pipeline reports these as status "error" for backwards compatibility with
# the agent's routing; over MCP they are a partial success.
_CHART_STEPS = frozenset({"recommend_chart_type", "generate_chart"})
_PARTIAL_CODES = frozenset({CHART_ERROR, NO_CHART_FIT})

# Non-terminal workflow states, keyed by the two status vocabularies in play:
# the pipeline's (ok/error/confirmation_required) and the agent's
# (completed/failed/waiting_for_user).
_PAUSE_STATES = frozenset({"confirmation_required", "waiting_for_user"})


def is_partial(result: dict[str, Any]) -> bool:
    """True for a chart-step failure that still carries a usable result."""
    return (
        result.get("status") == "error"
        and result.get("failed_step") in _CHART_STEPS
        and result.get("result") is not None
    )


def is_terminal_failure(result: Any) -> bool:
    """True if this result should be signalled to the host as isError: true."""
    if not isinstance(result, dict):
        return False
    status = result.get("status")
    if status in _PAUSE_STATES:
        return False
    if result.get("valid") is False:
        return False  # a validation rejection is a successful validation
    if is_partial(result):
        return False
    if result.get("error_code") in _PARTIAL_CODES and result.get("result") is not None:
        return False
    return "error" in result or status in ("error", "failed")


def _message(result: dict[str, Any]) -> str:
    """A single human-readable line carrying the code, cause and remedy.

    The host's LLM reads this to decide whether to repair and retry, so it must
    stay self-contained — it is the only channel available on the failure path.
    """
    code = result.get("error_code", "INTERNAL_ERROR")
    detail = result.get("error") or "; ".join(result.get("errors") or []) or "Tool execution failed."
    parts = [f"[{code}]", detail]
    if result.get("failed_step"):
        parts.append(f"(failed at step: {result['failed_step']})")
    action = user_action_for(code)
    if action:
        parts.append(action)
    return " ".join(parts)


def normalize_partial(result: dict[str, Any]) -> dict[str, Any]:
    """Rewrite a chart-step failure from status "error" to status "partial".

    run_pipeline's internal vocabulary marks these as errors so the agent's
    routing can send them to a chart fallback. Over MCP that would misrepresent
    a successful, fully-provenanced query as a failure, so the status is
    translated at the boundary and the service is left alone.
    """
    if not is_partial(result):
        return result
    return {**result, "status": "partial"}


def unwrap(result: dict[str, Any], model: type[M]) -> M:
    """Type a service result, or raise ToolError so MCP reports isError: true."""
    if is_terminal_failure(result):
        raise ToolError(_message(result))
    return model.model_validate(normalize_partial(result))
