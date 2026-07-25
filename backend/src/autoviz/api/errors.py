"""Map a service's structured result dict to an HTTP response.

The services never raise — they return structured content (`{error, error_code}`,
`{valid: false, errors}`, `{status: "error", ...}`) or a success dict. The API's
only job on top of that is to choose the HTTP **status code**; the response body
stays byte-for-byte the dict the service returned, so the frontend and MCP hosts
see identical shapes.
"""

from typing import Any

from fastapi.responses import JSONResponse

from autoviz.errors import (
    EXECUTION_ERROR,
    FILE_ERROR,
    FORBIDDEN_PATH,
    INVALID_PLAN,
    INVALID_SPEC,
    NO_CHART_FIT,
    RESOURCE_LIMIT,
    TIMEOUT,
    TYPE_MISMATCH,
    UNKNOWN_DATASET,
    is_failure,
)

# Typed error_code -> HTTP status. Codes not listed fall back to the generic
# rules in status_for() (400 for a plain error, 422 for a validation failure).
# "FORBIDDEN"/"UNAUTHENTICATED" are API-level codes (not service taxonomy codes).
#
# FILE_ERROR / NO_CHART_FIT / INVALID_SPEC are listed explicitly at 400 — the
# status these already returned as uncoded {error} dicts. Giving them codes (so
# the MCP envelope can classify them) must not move the HTTP contract.
# CHART_ERROR stays unlisted and keeps falling through to 400 for the same reason.
_CODE_STATUS: dict[str, int] = {
    UNKNOWN_DATASET: 404,
    RESOURCE_LIMIT: 413,
    INVALID_PLAN: 422,
    TYPE_MISMATCH: 422,
    TIMEOUT: 504,
    EXECUTION_ERROR: 500,
    FILE_ERROR: 400,
    NO_CHART_FIT: 400,
    INVALID_SPEC: 400,
    FORBIDDEN_PATH: 403,
    "FORBIDDEN": 403,
    "UNAUTHENTICATED": 401,
}


def is_error(result: Any) -> bool:
    """True if a service result represents a failure rather than a value.

    Thin alias over the shared predicate in autoviz.errors so the HTTP layer,
    the observability decorator, and the MCP envelope cannot drift apart.
    """
    return is_failure(result)


def status_for(result: dict[str, Any]) -> int:
    """HTTP status for a failed service result."""
    code = result.get("error_code")
    if code in _CODE_STATUS:
        return _CODE_STATUS[code]
    if result.get("valid") is False:
        return 422
    return 400  # plain {error} or an unmapped pipeline {status: "error"}


def respond(result: Any, ok_status: int = 200) -> JSONResponse:
    """Wrap a service result in a JSONResponse with the right status, body intact."""
    status = status_for(result) if is_error(result) else ok_status
    return JSONResponse(status_code=status, content=result)
