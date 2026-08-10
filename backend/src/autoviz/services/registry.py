"""Dataset registry — a bounded LRU cache of loaded DataFrames.

``dataset_id -> DataFrame + schema + profile``. Two properties matter beyond the
plain lookup it started as:

**Bounded.** Frames are evicted least-recently-used once the cache exceeds
``AUTOVIZ_REGISTRY_MEMORY_BYTES``. Without this, every dataset any user touched
stayed resident for the life of the process.

**Self-loading.** A miss calls the injected ``loader``, so a dataset evicted here
(or lost to a restart) is transparently restored from durable storage. Every
caller — ``execute_analysis``, ``validate_analysis_plan``, the agent nodes —
already goes through ``get()``, so none of them need to know about any of this.

The loader is *injected*, never imported: ``storage`` depends on ``services``,
and importing back the other way would make the analysis services require a
database. ``loader=None`` (the default) keeps the pure in-memory behaviour used
by the MCP server and the offline tests.
"""

import hashlib
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


# Total resident frame bytes before eviction kicks in. Sized to sit comfortably
# under a typical 1-2GB container while holding several working datasets.
DEFAULT_MEMORY_BYTES = 512 * 1024 * 1024


@dataclass
class DatasetRecord:
    dataset_id: str
    source: str
    df: pd.DataFrame
    # Logical column types: name -> "number" | "boolean" | "datetime" | "string"
    schema: dict[str, str]
    profile: dict[str, Any] = field(default_factory=dict)
    # Numeric columns whose values are coded categories (low-cardinality whole
    # numbers, e.g. pclass 1/2/3, survived 0/1). Dimensions to group and colour
    # by — not measures — even though their stored dtype stays "number".
    categorical_numeric: list[str] = field(default_factory=list)
    # Memoized quality scans, keyed by the column scope asked for. Sound because
    # the frame is immutable: cleaning builds views over it and never writes back,
    # so a finding stays true for as long as the record exists. An evicted record
    # takes its cache with it, which is the correct lifetime — a reloaded frame
    # re-derives rather than trusting a stale answer.
    #
    # compare/repr are off so a DataFrame-bearing record stays comparable and
    # printable, and so this never counts toward the cache's size accounting.
    scan_cache: dict[Any, Any] = field(
        default_factory=dict, compare=False, repr=False
    )

    def nbytes(self) -> int:
        """Resident size of the frame, object columns included (deep=True)."""
        try:
            return int(self.df.memory_usage(deep=True).sum())
        except Exception:  # pragma: no cover - exotic dtypes
            return 0


# Returns the record for a dataset_id, or None if it cannot be restored.
Loader = Callable[[str], "DatasetRecord | None"]


class DatasetRegistry:
    def __init__(self, max_bytes: int | None = None, loader: Loader | None = None) -> None:
        # Ordered most-recently-used last.
        self._records: OrderedDict[str, DatasetRecord] = OrderedDict()
        self._sizes: dict[str, int] = {}
        self._total = 0
        self._max_bytes = (
            max_bytes
            if max_bytes is not None
            else _env_int("AUTOVIZ_REGISTRY_MEMORY_BYTES", DEFAULT_MEMORY_BYTES)
        )
        # Sync routes run in FastAPI's threadpool, so concurrent get/add is real.
        # Reentrant because add() runs inside get() on the miss path.
        self._lock = threading.RLock()
        self.loader = loader

    def new_id(self, source: str) -> str:
        digest = hashlib.sha1(f"{source}:{time.time_ns()}".encode()).hexdigest()[:8]
        return f"ds_{digest}"

    def add(self, record: DatasetRecord) -> None:
        with self._lock:
            self._discard(record.dataset_id)
            size = record.nbytes()
            self._records[record.dataset_id] = record
            self._sizes[record.dataset_id] = size
            self._total += size
            self._evict()

    def get(self, dataset_id: str) -> DatasetRecord | None:
        with self._lock:
            record = self._records.get(dataset_id)
            if record is not None:
                self._records.move_to_end(dataset_id)
                return record
            loader = self.loader

        if loader is None:
            return None
        # Loaded outside the lock: restoring can mean a DB round trip plus a
        # Parquet decode, and holding the lock through that would serialize
        # every other dataset's queries behind it.
        restored = loader(dataset_id)
        if restored is None:
            return None
        with self._lock:
            # Another thread may have restored the same dataset meanwhile; keep
            # the copy already cached so callers never hold divergent frames.
            existing = self._records.get(dataset_id)
            if existing is not None:
                self._records.move_to_end(dataset_id)
                return existing
            self.add(restored)
            return restored

    def remove(self, dataset_id: str) -> bool:
        with self._lock:
            return self._discard(dataset_id)

    def all(self) -> list[DatasetRecord]:
        with self._lock:
            return list(self._records.values())

    # --- internals (call with the lock held) ---------------------------------

    def _discard(self, dataset_id: str) -> bool:
        if self._records.pop(dataset_id, None) is None:
            return False
        self._total -= self._sizes.pop(dataset_id, 0)
        return True

    def _evict(self) -> None:
        """Drop least-recently-used frames until back under budget.

        Never evicts the last remaining record: a single dataset larger than the
        whole budget must still be queryable, and dropping the one just added
        would make add() a no-op.
        """
        while self._total > self._max_bytes and len(self._records) > 1:
            oldest, _ = next(iter(self._records.items()))
            self._discard(oldest)


# Module-level registry shared by the MCP server and the HTTP API.
REGISTRY = DatasetRegistry()
