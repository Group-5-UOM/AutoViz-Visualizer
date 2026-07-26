"""Durable dataset payloads: Parquet bytes + cached schema/profile in the DB.

This is the storage half of the registry cache. ``store()`` runs once per upload;
``make_loader()`` produces the callback ``DatasetRegistry`` invokes on a miss, so
an evicted (or restarted-away) dataset comes back without the caller noticing.

Why Parquet and not the original CSV: it round-trips dtypes exactly. Re-parsing a
CSV re-runs ``_coerce_datetimes``, so a reloaded frame's schema is only *probably*
the one the plan was validated against. Caching the profile matters just as much —
``_build_profile`` is the expensive part of registration, not the parse.

One normalization survives the round trip: within *object* columns the null
sentinel returns as ``None`` rather than ``nan``. Dtypes, null positions and
non-null values are identical, and DuckDB reads both as SQL NULL, so no query
can observe it (``tests/test_dataset_blobs.py`` pins this).
"""

import logging
from io import BytesIO

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from autoviz.models import DatasetBlob, UserDataset
from autoviz.services.registry import DatasetRecord, Loader

_log = logging.getLogger("autoviz.observability")


def store(session: Session, record: DatasetRecord, *, source: str | None = None) -> DatasetBlob:
    """Persist a registered dataset's rows and computed metadata.

    ``source`` overrides the record's source string (the upload route passes the
    logical filename, so provenance does not leak a server path that is about to
    be deleted). Idempotent: re-storing the same dataset_id overwrites.
    """
    buffer = BytesIO()
    # index=False: register_dataset always produces a fresh RangeIndex, so the
    # index carries no information and storing it would break frame equality.
    record.df.to_parquet(buffer, index=False)
    payload = buffer.getvalue()
    label = source or record.source

    blob = session.get(DatasetBlob, record.dataset_id)
    if blob is None:
        blob = DatasetBlob(dataset_id=record.dataset_id)
        session.add(blob)
    blob.parquet = payload
    blob.schema_json = dict(record.schema)
    blob.profile_json = dict(record.profile)
    blob.categorical_numeric = list(record.categorical_numeric)
    blob.source = label
    blob.byte_size = len(payload)
    session.commit()

    record.source = label
    return blob


def delete(session: Session, dataset_id: str) -> None:
    """Drop a dataset's payload.

    Explicit rather than relying on the FK cascade: SQLite only enforces
    ``ON DELETE CASCADE`` with ``PRAGMA foreign_keys=ON``, which the offline test
    database does not set.
    """
    blob = session.get(DatasetBlob, dataset_id)
    if blob is not None:
        session.delete(blob)
        session.commit()


def _record_from_blob(blob: DatasetBlob) -> DatasetRecord:
    df = pd.read_parquet(BytesIO(blob.parquet))
    return DatasetRecord(
        dataset_id=blob.dataset_id,
        source=blob.source,
        df=df,
        schema=dict(blob.schema_json or {}),
        profile=dict(blob.profile_json or {}),
        categorical_numeric=list(blob.categorical_numeric or []),
    )


def _restore_from_csv(session: Session, dataset_id: str) -> DatasetRecord | None:
    """Fallback for datasets registered before blobs existed.

    Re-registers from the recorded upload path, re-keys the fresh record to its
    durable id, and writes the blob so this happens at most once per dataset.
    """
    meta = session.scalar(select(UserDataset).where(UserDataset.dataset_id == dataset_id))
    if meta is None or not meta.file_path:
        return None

    # A scratch registry keeps the backfill off the shared one — add() below is
    # the caller's job, and register_dataset mints its own id.
    from autoviz.services.dataset import register_dataset
    from autoviz.services.registry import DatasetRegistry

    scratch = DatasetRegistry()
    result = register_dataset(meta.file_path, scratch)
    if "error" in result:
        return None
    record = scratch.get(result["dataset_id"])
    if record is None:  # pragma: no cover - register_dataset just added it
        return None

    record.dataset_id = dataset_id  # keep the durable id the caller asked for
    try:
        store(session, record, source=meta.filename)
    except Exception as exc:  # backfill is best-effort; the record is still good
        session.rollback()
        _log.warning("blob backfill failed for %s: %s", dataset_id, exc)
    return record


def load(dataset_id: str) -> DatasetRecord | None:
    """Restore a dataset from durable storage, or None if it is gone."""
    from autoviz.core.database import get_sessionmaker

    session = get_sessionmaker()()
    try:
        blob = session.get(DatasetBlob, dataset_id)
        if blob is not None:
            return _record_from_blob(blob)
        return _restore_from_csv(session, dataset_id)
    except Exception as exc:
        # A miss must degrade to "unknown dataset" (404), never propagate a DB
        # fault out of the middle of a query.
        _log.warning("dataset reload failed for %s: %s", dataset_id, exc)
        return None
    finally:
        session.close()


def make_loader() -> Loader:
    """The callback wired into ``REGISTRY.loader`` at application startup.

    Opens its own session per call: a cache miss surfaces deep inside
    ``execute_analysis``, far from any request-scoped dependency.
    """
    return load
