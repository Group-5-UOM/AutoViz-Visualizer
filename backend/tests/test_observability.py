import asyncio
import inspect
import json
import logging
import sys

import pytest

from autoviz import observability
from autoviz.observability import classify_outcome, observed


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture()
def cap():
    """Attach a capture handler directly to the observability logger, so capture
    works regardless of the logger's propagate state / global config."""
    logger = logging.getLogger(observability.LOGGER_NAME)
    handler = _Capture()
    old_level, old_propagate = logger.level, logger.propagate
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    yield handler
    logger.removeHandler(handler)
    logger.setLevel(old_level)
    logger.propagate = old_propagate


def _records(cap: _Capture) -> list[dict]:
    return [json.loads(r.getMessage()) for r in cap.records]


def test_logs_one_record_with_required_fields(cap):
    @observed
    def tool(dataset_id: str) -> dict:
        return {"rows": [1, 2, 3]}

    tool("ds_1")
    (rec,) = _records(cap)
    assert rec["tool"] == "tool"
    assert set(rec) >= {"tool", "input_hash", "ms", "out_bytes", "outcome"}
    assert rec["outcome"] == "ok"
    assert isinstance(rec["ms"], (int, float))
    assert rec["out_bytes"] > 0


def test_outcome_error(cap):
    @observed
    def tool() -> dict:
        return {"error": "boom"}

    tool()
    assert _records(cap)[-1]["outcome"] == "error"


def test_outcome_invalid(cap):
    @observed
    def tool() -> dict:
        return {"valid": False, "errors": ["x"]}

    tool()
    assert _records(cap)[-1]["outcome"] == "invalid"


def test_outcome_failed_captures_failed_step(cap):
    @observed
    def tool() -> dict:
        return {"status": "error", "failed_step": "execute_analysis"}

    tool()
    rec = _records(cap)[-1]
    assert rec["outcome"] == "failed"
    assert rec["failed_step"] == "execute_analysis"


def test_classify_outcome_on_non_dict():
    assert classify_outcome("anything")["outcome"] == "ok"


def test_outcome_error_captures_error_code(cap):
    @observed
    def tool() -> dict:
        return {"error": "no such dataset", "error_code": "UNKNOWN_DATASET", "retryable": False}

    tool()
    rec = _records(cap)[-1]
    assert rec["outcome"] == "error"
    assert rec["error_code"] == "UNKNOWN_DATASET"


def test_outcome_invalid_captures_error_code(cap):
    @observed
    def tool() -> dict:
        return {"valid": False, "errors": ["x"], "error_code": "TYPE_MISMATCH"}

    tool()
    rec = _records(cap)[-1]
    assert rec["outcome"] == "invalid"
    assert rec["error_code"] == "TYPE_MISMATCH"


def test_outcome_failed_captures_error_code(cap):
    @observed
    def tool() -> dict:
        return {"status": "error", "failed_step": "execute_analysis", "error_code": "EXECUTION_ERROR"}

    tool()
    rec = _records(cap)[-1]
    assert rec["outcome"] == "failed"
    assert rec["failed_step"] == "execute_analysis"
    assert rec["error_code"] == "EXECUTION_ERROR"


def test_ok_record_has_no_error_code(cap):
    @observed
    def tool() -> dict:
        return {"rows": []}

    tool()
    assert "error_code" not in _records(cap)[-1]


def test_observes_real_service_success_end_to_end(cap, registry):
    """Full record — name, hash, latency, size, outcome — over a real service."""
    from autoviz.services.dataset import register_dataset
    from tests.conftest import data_path

    wrapped = observed(register_dataset)
    wrapped(data_path("general-testing", "iris.csv"), registry)
    rec = _records(cap)[-1]
    assert rec["tool"] == "register_dataset"
    assert len(rec["input_hash"]) == 12
    assert isinstance(rec["ms"], (int, float)) and rec["ms"] >= 0
    assert rec["out_bytes"] > 0
    assert rec["outcome"] == "ok"


def test_observes_real_service_error_code_end_to_end(cap, registry):
    """A real taxonomy error_code propagates all the way into the log record."""
    from autoviz.services.execution import execute_analysis

    wrapped = observed(execute_analysis)
    wrapped("ds_missing", {"dataset_id": "ds_missing", "intent": "comparison"}, registry)
    rec = _records(cap)[-1]
    assert rec["tool"] == "execute_analysis"
    assert rec["outcome"] == "error"
    assert rec["error_code"] == "UNKNOWN_DATASET"


def test_every_server_tool_is_observed():
    """Guard against a future tool being added without the @observed wrapper.

    Driven off the registration profiles rather than a hardcoded list, so a new
    tool cannot be added in one place and forgotten here.
    """
    import autoviz.mcp.server as server

    registered = [fn for fn, _desc in server.PROFILES["advanced"]]
    assert len(registered) == 19
    for fn in registered:
        # @observed uses functools.wraps, which sets __wrapped__ on the wrapper.
        assert hasattr(fn, "__wrapped__"), f"{fn.__name__} is not wrapped by @observed"


def test_default_profile_is_a_subset_of_advanced():
    import autoviz.mcp.server as server

    default = {fn.__name__ for fn, _ in server.PROFILES["default"]}
    advanced = {fn.__name__ for fn, _ in server.PROFILES["advanced"]}
    assert default < advanced
    # The default profile must still cover a whole workflow on its own.
    assert {"register_dataset", "run_analysis_pipeline", "export_chart"} <= default


def test_every_profile_pairs_analyze_with_its_resume_tool():
    """analyze can return {status: "waiting_for_user"}, and the only way to finish
    such a run is answer_clarification. A profile carrying one without the other
    strands the host on a pause its own tool description told it to answer."""
    import autoviz.mcp.server as server

    for name, tools in server.PROFILES.items():
        exposed = {fn.__name__ for fn, _ in tools}
        assert ("analyze" in exposed) == ("answer_clarification" in exposed), (
            f"profile {name!r} exposes only one of analyze/answer_clarification"
        )


def test_observed_preserves_async_so_fastmcp_awaits_it():
    """A sync wrapper around an async tool makes FastMCP read is_async=False, so
    it never awaits and the coroutine leaks unexecuted. Progress reporting and
    cancellation both depend on this staying true."""
    from mcp.server.fastmcp.tools.base import Tool

    async def sample(dataset_id: str) -> dict:
        return {"ok": True}

    wrapped = observed(sample)
    assert inspect.iscoroutinefunction(wrapped)
    assert Tool.from_function(wrapped).is_async is True
    assert asyncio.run(wrapped("ds_1")) == {"ok": True}


def test_observed_logs_async_calls(cap):
    async def sample(dataset_id: str) -> dict:
        return {"error": "boom", "error_code": "UNKNOWN_DATASET"}

    asyncio.run(observed(sample)("ds_1"))
    rec = _records(cap)[-1]
    assert rec["tool"] == "sample"
    assert rec["outcome"] == "error"
    assert rec["error_code"] == "UNKNOWN_DATASET"


def test_input_is_hashed_not_logged(cap):
    @observed
    def tool(secret: str) -> dict:
        return {"ok": True}

    tool("super-secret-path/leak.csv")
    rec = _records(cap)[-1]
    assert "super-secret-path" not in json.dumps(rec)
    assert len(rec["input_hash"]) == 12


def test_decorator_preserves_signature_for_fastmcp():
    def sample(dataset_id: str, limit: int = 10) -> dict:
        return {}

    assert inspect.signature(observed(sample)) == inspect.signature(sample)
    assert observed(sample).__name__ == "sample"


def test_server_imports_with_decorated_tools():
    # Importing the server runs every @mcp.tool() over an @observed wrapper; a
    # signature-introspection failure in FastMCP would raise here.
    import autoviz.mcp.server  # noqa: F401


def test_configure_logging_never_targets_stdout():
    observability.configure_logging._configured = False  # type: ignore[attr-defined]
    logger = logging.getLogger(observability.LOGGER_NAME)
    logger.handlers.clear()
    observability.configure_logging()
    stream_handlers = [h for h in logger.handlers if isinstance(h, logging.StreamHandler)]
    assert stream_handlers  # at least the stderr handler
    for h in stream_handlers:
        assert h.stream is not sys.stdout
