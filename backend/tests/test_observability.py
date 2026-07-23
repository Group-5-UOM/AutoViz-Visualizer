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
