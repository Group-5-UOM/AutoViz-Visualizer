"""Resource Gateway services: register / schema / profile / preview.

Dataset cell contents are treated strictly as data — values are returned as
inert JSON scalars, never interpreted or executed.
"""

import math
import os
from pathlib import Path
from typing import Any

import pandas as pd

from autoviz.services.registry import REGISTRY, DatasetRecord, DatasetRegistry

PREVIEW_MAX_ROWS = 50


def _default_data_roots() -> list[Path]:
    # dataset.py sits at backend/src/autoviz/services/; parents[4] is the repo root.
    repo_root = Path(__file__).resolve().parents[4]
    return [repo_root / "test-data", repo_root]


# Approved roots for resolving relative file_refs. Override with AUTOVIZ_DATA_ROOTS
# (os.pathsep-separated list of directories).
DATA_ROOTS: list[Path] = [
    Path(p).resolve()
    for p in os.environ.get("AUTOVIZ_DATA_ROOTS", "").split(os.pathsep)
    if p.strip()
] or _default_data_roots()


def _resolve_file_ref(file_ref: str) -> Path | None:
    """Resolve a file_ref to a real CSV path.

    Absolute paths are used as-is (host-provided references). Relative paths are
    resolved against the approved DATA_ROOTS only, and the resolved path must
    stay inside its root — traversal out of an approved root is rejected.
    """
    path = Path(file_ref)
    if path.is_absolute():
        return path if path.is_file() else None
    for root in DATA_ROOTS:
        candidate = (root / path).resolve()
        if candidate.is_file() and candidate.is_relative_to(root.resolve()):
            return candidate
    return None


def _logical_type(series: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_numeric_dtype(series):
        return "number"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    return "string"


def _coerce_datetimes(df: pd.DataFrame) -> pd.DataFrame:
    """Promote object columns that parse cleanly as dates to datetime."""
    for col in df.columns:
        # pandas 3.x infers text as the 'str' dtype, older versions as 'object'.
        if not (df[col].dtype == object or pd.api.types.is_string_dtype(df[col])):
            continue
        sample = df[col].dropna()
        if sample.empty:
            continue
        parsed = pd.to_datetime(sample, errors="coerce", format="mixed")
        # Require every non-null value to parse — avoids misreading plain strings.
        if parsed.notna().all():
            df[col] = pd.to_datetime(df[col], errors="coerce", format="mixed")
    return df


def _sanitize_scalar(value: Any) -> Any:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):  # numpy scalar -> python scalar
        value = value.item()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def sanitize_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {col: _sanitize_scalar(val) for col, val in row.items()}
        for row in df.to_dict(orient="records")
    ]


def _build_profile(df: pd.DataFrame, schema: dict[str, str]) -> dict[str, Any]:
    numeric_cols = [c for c, t in schema.items() if t == "number"]
    summary_stats: dict[str, dict[str, Any]] = {}
    if numeric_cols:
        described = df[numeric_cols].describe()
        summary_stats = {
            col: {stat: _sanitize_scalar(described.loc[stat, col]) for stat in described.index}
            for col in numeric_cols
        }
    return {
        "null_counts": {c: int(df[c].isna().sum()) for c in df.columns},
        "duplicate_count": int(df.duplicated().sum()),
        "cardinality": {c: int(df[c].nunique(dropna=True)) for c in df.columns},
        "summary_stats": summary_stats,
    }


def register_dataset(
    file_ref: str, registry: DatasetRegistry = REGISTRY
) -> dict[str, Any]:
    path = _resolve_file_ref(file_ref)
    if path is None:
        return {
            "error": f"File not found: {file_ref}",
            "hint": "Use an absolute path, or a path relative to an approved data root: "
            + "; ".join(str(r) for r in DATA_ROOTS),
        }
    try:
        df = pd.read_csv(path)
    except Exception as exc:
        return {"error": f"Could not read CSV: {exc}"}

    df = _coerce_datetimes(df)
    schema = {col: _logical_type(df[col]) for col in df.columns}
    record = DatasetRecord(
        dataset_id=registry.new_id(str(path)),
        source=str(path),
        df=df,
        schema=schema,
        profile=_build_profile(df, schema),
    )
    registry.add(record)
    return {
        "dataset_id": record.dataset_id,
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
    }


def list_datasets(registry: DatasetRegistry = REGISTRY) -> dict[str, Any]:
    return {
        "datasets": [
            {
                "dataset_id": r.dataset_id,
                "source": r.source,
                "row_count": int(len(r.df)),
                "column_count": int(len(r.df.columns)),
            }
            for r in registry.all()
        ]
    }


def unregister_dataset(
    dataset_id: str, registry: DatasetRegistry = REGISTRY
) -> dict[str, Any]:
    if not registry.remove(dataset_id):
        return {"error": f"Unknown dataset_id: {dataset_id}"}
    return {"removed": True, "dataset_id": dataset_id}


def get_dataset_schema(
    dataset_id: str, registry: DatasetRegistry = REGISTRY
) -> dict[str, Any]:
    record = registry.get(dataset_id)
    if record is None:
        return {"error": f"Unknown dataset_id: {dataset_id}"}
    return {"columns": [{"name": n, "type": t} for n, t in record.schema.items()]}


def get_dataset_profile(
    dataset_id: str, registry: DatasetRegistry = REGISTRY
) -> dict[str, Any]:
    record = registry.get(dataset_id)
    if record is None:
        return {"error": f"Unknown dataset_id: {dataset_id}"}
    return record.profile


def preview_dataset(
    dataset_id: str, limit: int = 10, registry: DatasetRegistry = REGISTRY
) -> dict[str, Any]:
    record = registry.get(dataset_id)
    if record is None:
        return {"error": f"Unknown dataset_id: {dataset_id}"}
    limit = max(1, min(int(limit), PREVIEW_MAX_ROWS))
    return {"rows": sanitize_records(record.df.head(limit))}
