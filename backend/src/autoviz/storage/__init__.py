"""Persistence layer: PostgreSQL via SQLAlchemy (Proposal §4.2 Storage Layer).

Only durable metadata lives here — user accounts, dataset metadata, saved chart
specs, and dashboard layouts. Loaded DataFrames stay in the in-memory
`services.registry.REGISTRY`; `DatasetMeta` records the upload file path so a
dataset can be lazily re-registered after a restart.
"""
