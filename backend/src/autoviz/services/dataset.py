"""Resource Gateway services: register / schema / profile / preview.

Dataset cell contents are treated strictly as data — values are returned as
inert JSON scalars, never interpreted or executed.
"""

import math
import os
import re
from pathlib import Path
from typing import Any

import pandas as pd

from autoviz.errors import FILE_ERROR, UNKNOWN_DATASET, make_error
from autoviz.services import ingest
from autoviz.services.ingest import IngestError, IngestReport
from autoviz.services.registry import REGISTRY, DatasetRecord, DatasetRegistry
from autoviz.services.safety import neutralize_text

PREVIEW_MAX_ROWS = 5000

# The ingestion ceilings live in services/ingest.py, next to the reads they guard
# (a byte cap that is not checked immediately before opening the file is not a
# memory guard at all).

# Categorical columns at/under this distinct-value count get their values profiled
# (see sample_values below) — enough to disambiguate references, small enough to
# stay cheap and privacy-bounded. Values themselves are capped per column.
SAMPLE_VALUE_MAX_CARDINALITY = 50
SAMPLE_VALUES_PER_COLUMN = 50

# A numeric column whose values are whole numbers and whose distinct-value count
# stays at/under this bound is treated as a *coded category* (pclass 1/2/3,
# survived 0/1, sibsp 0-8) rather than a continuous measure: it is a dimension to
# group and colour by, not a quantity to plot on a continuous scale. Continuous
# measures (fare) are excluded by the whole-number test; wide integer columns
# (age) by the cardinality bound. The source dtype is never changed — this signal
# only informs chart encoding (nominal vs quantitative).
CATEGORICAL_NUMERIC_MAX_CARDINALITY = 20


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


def _categorical_numeric_columns(df: pd.DataFrame, schema: dict[str, str]) -> list[str]:
    """Numeric columns that are really coded categories, not measures.

    A number column qualifies when every non-null value is a whole number and the
    distinct count is at/under CATEGORICAL_NUMERIC_MAX_CARDINALITY. This flags the
    likes of pclass and survived (which should group/colour as discrete classes)
    while leaving continuous measures (fare) and wide integer columns (age) alone.
    """
    coded: list[str] = []
    for col, logical in schema.items():
        if logical != "number":
            continue
        series = df[col].dropna()
        if series.empty:
            continue
        if not (series % 1 == 0).all():  # any fractional value -> a real measure
            continue
        if series.nunique() <= CATEGORICAL_NUMERIC_MAX_CARDINALITY:
            coded.append(col)
    return coded


# A value has to *look* like a date before it is allowed to be parsed as one.
# "Parses successfully" is far too weak a test on its own: pandas reads "2026" as
# a year, "2026-Q3" as a quarter, and a column of four-digit product codes as a
# run of January firsts. Each becomes a datetime column, and every later question
# about it — group by it, filter a range on it, split it — then answers against a
# date nobody put in the file.
_DATE_SHAPES = re.compile(
    r"""^(
        \d{4}[-/]\d{1,2}[-/]\d{1,2}          # 2026-01-15, 2026/01/15
      | \d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}      # 15/01/2026, 15.01.26
      | \d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4}    # 15 January 2026
      | [A-Za-z]{3,9}\s+\d{1,2},?\s+\d{2,4}  # January 15, 2026
    )
    ([\sT].*)?$                              # optional time-of-day tail
    """,
    re.VERBOSE,
)


def _coerce_datetimes(df: pd.DataFrame, dayfirst: bool = False) -> pd.DataFrame:
    """Promote object columns that parse cleanly as dates to datetime.

    Two gates, both required. Every non-null value must **look** like a date
    (``_DATE_SHAPES``) and must then **parse** as one. The shape gate is what
    stops pandas' generosity from inventing date columns out of years, quarters
    and product codes; the parse gate is what rejects the ones that are shaped
    right and impossible, like 2026-13-45.

    ``dayfirst`` comes from the ingest probe, which reads it off the data when the
    data settles it. It has to be threaded through rather than left at pandas'
    default: for a file whose dates run ``25/12/2024`` the default reading is not
    merely different, it is unparseable in half the rows and silently
    month-swapped in the other half.
    """
    for col in df.columns:
        # pandas 3.x infers text as the 'str' dtype, older versions as 'object'.
        if not (df[col].dtype == object or pd.api.types.is_string_dtype(df[col])):
            continue
        sample = df[col].dropna()
        if sample.empty:
            continue
        text = sample.astype(str).str.strip()
        if not text.map(lambda v: bool(_DATE_SHAPES.match(v))).all():
            continue
        parsed = pd.to_datetime(sample, errors="coerce", format="mixed", dayfirst=dayfirst)
        # Require every non-null value to parse — avoids misreading plain strings.
        if parsed.notna().all():
            df[col] = pd.to_datetime(
                df[col], errors="coerce", format="mixed", dayfirst=dayfirst
            )
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
    file_ref: str,
    registry: DatasetRegistry = REGISTRY,
    sheet: str | int | None = None,
) -> dict[str, Any]:
    path = _resolve_file_ref(file_ref)
    if path is None:
        return make_error(
            FILE_ERROR,
            f"File not found: {file_ref}",
            hint="Use an absolute path, or a path relative to an approved data root: "
            + "; ".join(str(r) for r in DATA_ROOTS),
        )

    # Reading, and the ceilings that bound it, both live in services/ingest.py —
    # which also reports how the file had to be read to be read at all.
    try:
        df, report = ingest.read_table(path, sheet)
    except IngestError as exc:
        return make_error(exc.code, exc.message, **({"hint": exc.hint} if exc.hint else {}))

    record = build_record(df, str(path), registry, ingest_report=report)
    registry.add(record)
    return {
        "dataset_id": record.dataset_id,
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "ingest": report.to_wire(),
    }


def list_file_sheets(file_ref: str) -> dict[str, Any]:
    """The tables inside a file, without registering any of them.

    Separate from ``register_dataset`` because it answers a question asked
    *before* the user has decided what they want: a picker has to be drawn before
    there is anything to register, and enumerating must not cost a full read.
    """
    path = _resolve_file_ref(file_ref)
    if path is None:
        return make_error(
            FILE_ERROR,
            f"File not found: {file_ref}",
            hint="Use an absolute path, or a path relative to an approved data root: "
            + "; ".join(str(r) for r in DATA_ROOTS),
        )
    try:
        sheets = ingest.list_sheets(path)
    except IngestError as exc:
        return make_error(exc.code, exc.message, **({"hint": exc.hint} if exc.hint else {}))
    return {
        "sheets": [s.to_wire() for s in sheets],
        # One table means there is nothing to ask the user, and the caller can
        # skip straight to uploading rather than showing a picker with one row.
        "needs_choice": len(sheets) > 1,
    }


def build_record(
    df: pd.DataFrame,
    source: str,
    registry: DatasetRegistry,
    *,
    lineage: dict[str, Any] | None = None,
    ingest_report: IngestReport | None = None,
) -> DatasetRecord:
    """Type, profile, and identify a frame as a registered dataset.

    Shared by ``register_dataset`` and by materialisation so a derived dataset is
    profiled by exactly the same code as an uploaded one — a cleaned copy that
    reported its nulls differently from a fresh upload of the same rows would be
    worse than useless.

    ``lineage`` and ``ingest_report`` are stored inside the profile rather than as
    their own record fields so they survive the existing Parquet-blob round trip
    (``storage/blobs.py`` persists ``profile_json``) without a schema migration.
    """
    df = _coerce_datetimes(df, dayfirst=bool(ingest_report and ingest_report.dayfirst))
    schema = {col: _logical_type(df[col]) for col in df.columns}
    categorical_numeric = _categorical_numeric_columns(df, schema)
    profile = _build_profile(df, schema)
    # Surface the coded-category signal to the planner too (real names untouched
    # in the record; the copy emitted to the LLM is neutralized like the rest).
    profile["categorical_numeric"] = [neutralize_text(c) for c in categorical_numeric]
    if lineage is not None:
        profile["lineage"] = lineage
    if ingest_report is not None:
        profile["ingest"] = ingest_report.to_wire()
    return DatasetRecord(
        dataset_id=registry.new_id(source),
        source=source,
        df=df,
        schema=schema,
        profile=profile,
        categorical_numeric=categorical_numeric,
    )


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
