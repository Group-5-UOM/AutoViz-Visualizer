"""Resource Gateway services: register / schema / profile / preview.

Dataset cell contents are treated strictly as data — values are returned as
inert JSON scalars, never interpreted or executed.
"""

import math
import os
from pathlib import Path
from typing import Any

import pandas as pd

from autoviz.errors import RESOURCE_LIMIT, UNKNOWN_DATASET, make_error
from autoviz.services.registry import REGISTRY, DatasetRecord, DatasetRegistry
from autoviz.services.safety import neutralize_text

PREVIEW_MAX_ROWS = 50


def _env_int(name: str, default: int) -> int:
    """Read a positive int limit from the environment, falling back on default."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


# Ingestion ceilings enforced *before* a CSV is trusted into memory. pd.read_csv
# would otherwise load the whole file before any check, so the byte cap is the
# real memory guard; the row/column caps bound downstream work. All overridable.
MAX_FILE_BYTES = _env_int("AUTOVIZ_MAX_FILE_BYTES", 50 * 1024 * 1024)  # 50 MiB
MAX_ROWS = _env_int("AUTOVIZ_MAX_ROWS", 1_000_000)
MAX_COLUMNS = _env_int("AUTOVIZ_MAX_COLUMNS", 512)

# Categorical columns at/under this distinct-value count get their values profiled
# (see sample_values below) — enough to disambiguate references, small enough to
# stay cheap and privacy-bounded. Values themselves are capped per column.
SAMPLE_VALUE_MAX_CARDINALITY = 50
SAMPLE_VALUES_PER_COLUMN = 50


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
    if isinstance(value, str):
        # Untrusted cell text reaching an LLM: defang instruction-injection.
        return neutralize_text(value)
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
    # Distinct values of low-cardinality categorical columns — grounding for the
    # ambiguity detectors (a literal in a request that matches values in >1
    # column). Neutralized like every other user-string copied out of the frame.
    sample_values: dict[str, list[str]] = {}
    for col, logical in schema.items():
        if logical in ("string", "boolean") and df[col].nunique(dropna=True) <= SAMPLE_VALUE_MAX_CARDINALITY:
            vals = df[col].dropna().unique().tolist()[:SAMPLE_VALUES_PER_COLUMN]
            sample_values[neutralize_text(col)] = sorted(neutralize_text(str(v)) for v in vals)

    # Per-column null counts and percentages (of total rows). A column that is
    # entirely null is "unusable": the planner must not select/group/aggregate on
    # it, and it cannot supply a median/mode fill value (enforced in validation).
    row_count = len(df)
    null_counts = {c: int(df[c].isna().sum()) for c in df.columns}
    null_percentage = {
        neutralize_text(c): (round(100 * n / row_count, 2) if row_count else 0.0)
        for c, n in null_counts.items()
    }
    unusable_columns = [
        neutralize_text(c) for c in df.columns if row_count and null_counts[c] == row_count
    ]

    # Column names are also untrusted; neutralize the copies emitted to the LLM
    # (the real names remain the DataFrame/SQL identifiers, untouched).
    return {
        "null_counts": {neutralize_text(c): n for c, n in null_counts.items()},
        "null_percentage": null_percentage,
        "unusable_columns": unusable_columns,
        "duplicate_count": int(df.duplicated().sum()),
        "cardinality": {neutralize_text(c): int(df[c].nunique(dropna=True)) for c in df.columns},
        "summary_stats": {neutralize_text(c): v for c, v in summary_stats.items()},
        "sample_values": sample_values,
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

    # Pre-read guards: reject oversized files before loading them into memory,
    # and reject too-wide files from the header alone (a cheap read).
    try:
        size = path.stat().st_size
    except OSError as exc:
        return {"error": f"Could not stat file: {exc}"}
    if size > MAX_FILE_BYTES:
        return make_error(
            RESOURCE_LIMIT,
            f"File is {size} bytes; the limit is {MAX_FILE_BYTES} bytes.",
        )
    try:
        column_count = len(pd.read_csv(path, nrows=0).columns)
    except Exception as exc:
        return {"error": f"Could not read CSV: {exc}"}
    if column_count > MAX_COLUMNS:
        return make_error(
            RESOURCE_LIMIT,
            f"Dataset has {column_count} columns; the limit is {MAX_COLUMNS}.",
        )

    try:
        df = pd.read_csv(path)
    except Exception as exc:
        return {"error": f"Could not read CSV: {exc}"}
    if df.shape[0] == 0 or df.shape[1] == 0:
        return {"error": "CSV has no data rows (an empty or header-only file is not analysable)."}
    if len(df) > MAX_ROWS:
        return make_error(
            RESOURCE_LIMIT,
            f"Dataset has {len(df)} rows; the limit is {MAX_ROWS}.",
        )

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
        return make_error(UNKNOWN_DATASET, f"Unknown dataset_id: {dataset_id}")
    return {"removed": True, "dataset_id": dataset_id}


def get_dataset_schema(
    dataset_id: str, registry: DatasetRegistry = REGISTRY
) -> dict[str, Any]:
    record = registry.get(dataset_id)
    if record is None:
        return make_error(UNKNOWN_DATASET, f"Unknown dataset_id: {dataset_id}")
    return {"columns": [{"name": neutralize_text(n), "type": t} for n, t in record.schema.items()]}


def get_dataset_profile(
    dataset_id: str, registry: DatasetRegistry = REGISTRY
) -> dict[str, Any]:
    record = registry.get(dataset_id)
    if record is None:
        return make_error(UNKNOWN_DATASET, f"Unknown dataset_id: {dataset_id}")
    return record.profile


def preview_dataset(
    dataset_id: str, limit: int = 10, registry: DatasetRegistry = REGISTRY
) -> dict[str, Any]:
    record = registry.get(dataset_id)
    if record is None:
        return make_error(UNKNOWN_DATASET, f"Unknown dataset_id: {dataset_id}")
    limit = max(1, min(int(limit), PREVIEW_MAX_ROWS))
    return {"rows": sanitize_records(record.df.head(limit))}
