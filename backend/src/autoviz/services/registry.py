"""In-memory dataset registry — dataset_id -> loaded DataFrame + schema + profile."""

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

import pandas as pd


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


class DatasetRegistry:
    def __init__(self) -> None:
        self._records: dict[str, DatasetRecord] = {}

    def new_id(self, source: str) -> str:
        digest = hashlib.sha1(f"{source}:{time.time_ns()}".encode()).hexdigest()[:8]
        return f"ds_{digest}"

    def add(self, record: DatasetRecord) -> None:
        self._records[record.dataset_id] = record

    def get(self, dataset_id: str) -> DatasetRecord | None:
        return self._records.get(dataset_id)

    def remove(self, dataset_id: str) -> bool:
        return self._records.pop(dataset_id, None) is not None

    def all(self) -> list[DatasetRecord]:
        return list(self._records.values())


# Module-level registry shared by the MCP server process.
REGISTRY = DatasetRegistry()
