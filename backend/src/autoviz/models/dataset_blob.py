"""Durable dataset payload — the parsed rows plus their computed metadata.

One row per registered dataset. The rows are stored as **Parquet bytes** rather
than the original CSV so a reload round-trips dtypes exactly: re-parsing a CSV
would re-run ``services.dataset._coerce_datetimes``, whose heuristics could in
principle yield a different schema than the one a plan was validated against.

``schema_json`` / ``profile_json`` cache the output of ``_build_profile`` so a
cache miss never re-profiles (``nunique``/``describe``/``duplicated`` over every
column is the expensive part of registration, not the parse).

Kept in its own table, not as columns on ``UserDataset``: ``list_dataset_meta``
does ``select(UserDataset)``, which would otherwise drag every blob into memory
just to list dataset names.
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, LargeBinary, String

from autoviz.core.database import Base


class DatasetBlob(Base):
    __tablename__ = "dataset_blobs"

    # Shares the registry's durable id. FK to datasets.dataset_id (unique there),
    # so deleting the metadata cascades the payload on Postgres.
    dataset_id = Column(
        String,
        ForeignKey("datasets.dataset_id", ondelete="CASCADE"),
        primary_key=True,
    )
    # BYTEA on PostgreSQL, BLOB on SQLite — portable, like the JSON columns, so
    # the offline SQLite test DB runs the identical schema.
    parquet = Column(LargeBinary, nullable=False)
    schema_json = Column(JSON, nullable=False)
    profile_json = Column(JSON, nullable=False)
    categorical_numeric = Column(JSON, nullable=False)
    # Logical name shown in execution provenance (`provenance.source`).
    source = Column(String, nullable=False)
    byte_size = Column(Integer, nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
