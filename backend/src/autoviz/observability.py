"""Per-call observability for the MCP tool surface.

Implements the cross-cutting logging the MCP Server Architecture Patterns paper
(Rodrigues & Vas, ICSME 2026) prescribes and Proposal §4.7 requires: one
structured record per tool call carrying tool name, input hash, latency, output
size, and an outcome/error code.

**stdout is reserved for the MCP stdio JSON-RPC channel**, so log records go only
to stderr and a rotating file — never stdout. A stray stdout write corrupts the
protocol handshake.
"""

import functools
import hashlib
import json
import logging
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable

LOGGER_NAME = "autoviz.observability"
_logger = logging.getLogger(LOGGER_NAME)

# observability.py is at backend/src/autoviz/observability.py -> parents[2] = backend/
LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
LOG_FILE = LOG_DIR / "autoviz.log"


def configure_logging(level: int = logging.INFO) -> None:
    """Attach stderr + rotating-file handlers to the observability logger.

    Idempotent, and never touches stdout. File logging is best-effort — if the
    log directory can't be created, stderr logging still works.
    """
    if getattr(configure_logging, "_configured", False):
        return
    _logger.setLevel(level)
    _logger.propagate = False  # don't leak to the root logger (which may hit stdout)
    formatter = logging.Formatter("%(message)s")

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    _logger.addHandler(stderr_handler)

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        _logger.addHandler(file_handler)
    except OSError:
        pass

    configure_logging._configured = True  # type: ignore[attr-defined]


def _input_hash(args: tuple, kwargs: dict) -> str:
    """SHA-256 (truncated) over the JSON-serialized call arguments.

    Only the hash is logged, never raw argument values, so cell contents / file
    paths never land in the log.
    """
    try:
        payload = json.dumps({"args": args, "kwargs": kwargs}, default=str, sort_keys=True)
    except Exception:
        payload = repr((args, kwargs))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _output_size(result: Any) -> int:
    try:
        return len(json.dumps(result, default=str))
    except Exception:
        return -1


def classify_outcome(result: Any) -> dict[str, Any]:
    """Derive an outcome code from a tool's structured return value.

    Tools never raise to the host — they encode failure in the returned dict, so
    the outcome is read back out of it: ``ok`` | ``error`` (has ``error``) |
    ``invalid`` (``valid is False``) | ``failed`` (``status == "error"``, with
    the ``failed_step``).
    """
    if not isinstance(result, dict):
        return {"outcome": "ok"}
    if "error" in result:
        return {"outcome": "error"}
    if result.get("valid") is False:
        return {"outcome": "invalid"}
    if result.get("status") == "error":
        return {"outcome": "failed", "failed_step": result.get("failed_step")}
    return {"outcome": "ok"}


def observed(fn: Callable) -> Callable:
    """Log one structured record per call. ``functools.wraps`` keeps the original
    signature so FastMCP's schema introspection is unaffected."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        outcome: dict[str, Any] = {"outcome": "exception"}
        result: Any = None
        try:
            result = fn(*args, **kwargs)
            outcome = classify_outcome(result)
            return result
        finally:
            record = {
                "tool": fn.__name__,
                "input_hash": _input_hash(args, kwargs),
                "ms": round((time.perf_counter() - started) * 1000, 2),
                "out_bytes": _output_size(result),
                **outcome,
            }
            _logger.info(json.dumps(record))

    return wrapper
