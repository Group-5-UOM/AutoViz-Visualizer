"""Durable dataset payloads: store -> evict -> reload, offline on SQLite.

The claim these tests defend is that a dataset survives losing the in-memory
registry *and* the upload file, and comes back byte-identical — including
dtypes, which is why the payload is Parquet rather than the original CSV.
"""

from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pandas.testing import assert_frame_equal

import autoviz.services.dataset as dataset_service
from autoviz.api.deps import get_registry
from autoviz.api.main import create_app
from autoviz.core.database import get_sessionmaker
from autoviz.models import DatasetBlob
from autoviz.services.registry import DatasetRegistry
from autoviz.storage import blobs, repository
from tests.conftest import data_path

CREDS = {"email": "blob@example.com", "password": "pw12345678"}


def _client(registry: DatasetRegistry | None = None) -> tuple[TestClient, DatasetRegistry]:
    reg = registry if registry is not None else DatasetRegistry(loader=blobs.make_loader())
    app = create_app()
    app.dependency_overrides[get_registry] = lambda: reg
    return TestClient(app), reg


def _auth(client: TestClient) -> dict[str, str]:
    client.post("/auth/register", json=CREDS)
    token = client.post("/auth/login", json=CREDS).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _upload(client: TestClient, headers: dict, name: str, folder: str = "general-testing") -> str:
    with open(data_path(folder, name), "rb") as fh:
        payload = fh.read()
    res = client.post(
        "/datasets/upload",
        files={"file": (name, payload, "text/csv")},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()["dataset_id"]


# --- round trip --------------------------------------------------------------


@pytest.mark.parametrize(
    "folder,name",
    [
        ("general-testing", "titanic.csv"),
        # Has a real date column — the case CSV re-parsing could get wrong.
        ("weather-climate", "seattle-weather.csv"),
    ],
)
def test_reload_is_dtype_exact(api_db, folder, name):
    client, reg = _client()
    headers = _auth(client)
    ds = _upload(client, headers, name, folder)

    original = reg.get(ds)
    assert original is not None
    before = original.df.copy()

    # Evict, exactly as the LRU would under memory pressure.
    reg.remove(ds)
    restored = reg.get(ds)

    assert restored is not None
    assert_frame_equal(restored.df, before, check_dtype=True)
    assert restored.schema == original.schema
    assert restored.profile == original.profile
    assert restored.categorical_numeric == original.categorical_numeric


def test_reload_does_not_reprofile(api_db, monkeypatch):
    """The cached profile is replayed, not recomputed — that is the point of it."""
    client, reg = _client()
    headers = _auth(client)
    ds = _upload(client, headers, "titanic.csv")
    reg.remove(ds)

    def _boom(*args, **kwargs):
        raise AssertionError("_build_profile must not run on a blob reload")

    monkeypatch.setattr(dataset_service, "_build_profile", _boom)

    restored = reg.get(ds)
    assert restored is not None
    assert restored.profile["null_counts"]["age"] > 0


def test_survives_losing_both_the_registry_and_the_file(api_db):
    """The load-bearing case: a restart with no upload file left on disk."""
    client, reg = _client()
    headers = _auth(client)
    ds = _upload(client, headers, "titanic.csv")

    # The upload route already deleted the staged CSV.
    session = get_sessionmaker()()
    try:
        meta = repository.get_dataset_meta(session, ds)
        assert not Path(meta.file_path).exists()
    finally:
        session.close()

    # A brand-new process: fresh registry, nothing cached.
    fresh = DatasetRegistry(loader=blobs.make_loader())
    client2, _ = _client(fresh)
    headers2 = _auth(client2)

    prof = client2.get(f"/datasets/{ds}/profile", headers=headers2)
    assert prof.status_code == 200
    assert prof.json()["null_counts"]["age"] > 0

    pipeline = client2.post(
        "/analysis/pipeline",
        json={
            "dataset_id": ds,
            "analysis_plan": {
                "dataset_id": ds,
                "intent": "comparison",
                "group_by": ["sex"],
                "aggregations": [{"fn": "mean", "column": "age", "as": "avg_age"}],
            },
        },
    )
    assert pipeline.status_code == 200, pipeline.text
    assert pipeline.json()["status"] == "ok"


# --- fallback and cleanup ----------------------------------------------------


def test_falls_back_to_csv_when_no_blob_row(api_db):
    """Datasets registered before this feature reload from their file, once."""
    client, reg = _client()
    headers = _auth(client)
    # /datasets (file_ref) keeps the source file, so there is something to fall back to.
    res = client.post(
        "/datasets",
        json={"file_ref": data_path("general-testing", "iris.csv")},
        headers=headers,
    )
    assert res.status_code == 201
    ds = res.json()["dataset_id"]

    session = get_sessionmaker()()
    try:
        blobs.delete(session, ds)  # simulate a pre-existing dataset
        assert session.get(DatasetBlob, ds) is None
    finally:
        session.close()

    reg.remove(ds)
    restored = reg.get(ds)
    assert restored is not None
    assert len(restored.df) == 150

    # The fallback backfilled the blob, so the next miss is served from the DB.
    session = get_sessionmaker()()
    try:
        assert session.get(DatasetBlob, ds) is not None
    finally:
        session.close()


def test_missing_everything_is_a_clean_404(api_db):
    client, reg = _client()
    headers = _auth(client)
    ds = _upload(client, headers, "titanic.csv")

    session = get_sessionmaker()()
    try:
        blobs.delete(session, ds)
    finally:
        session.close()
    reg.remove(ds)

    r = client.get(f"/datasets/{ds}/profile", headers=headers)
    assert r.status_code == 404


def test_delete_removes_the_blob(api_db):
    client, reg = _client()
    headers = _auth(client)
    ds = _upload(client, headers, "titanic.csv")

    session = get_sessionmaker()()
    try:
        assert session.get(DatasetBlob, ds) is not None
    finally:
        session.close()

    assert client.delete(f"/datasets/{ds}", headers=headers).status_code == 200

    session = get_sessionmaker()()
    try:
        assert session.get(DatasetBlob, ds) is None
    finally:
        session.close()
    # And it does not come back to life through the loader.
    assert reg.get(ds) is None


def test_blob_is_smaller_than_the_csv(api_db):
    """Parquet + compression: storing rows in the DB should not inflate them."""
    client, _ = _client()
    headers = _auth(client)
    csv_bytes = Path(data_path("general-testing", "titanic.csv")).stat().st_size
    ds = _upload(client, headers, "titanic.csv")

    session = get_sessionmaker()()
    try:
        blob = session.get(DatasetBlob, ds)
        assert blob.byte_size == len(blob.parquet)
        assert blob.byte_size < csv_bytes
    finally:
        session.close()


def test_stored_source_is_the_logical_filename(api_db):
    """Provenance must not leak the staged server path, which no longer exists."""
    client, reg = _client()
    headers = _auth(client)
    ds = _upload(client, headers, "titanic.csv")
    reg.remove(ds)

    restored = reg.get(ds)
    assert restored.source == "titanic.csv"


def test_parquet_survives_nulls_and_mixed_types(api_db):
    """Round-trip a frame carrying nulls in every logical type.

    One documented normalization: inside *object* columns the null sentinel comes
    back as ``None`` rather than ``nan``. Dtypes, null positions, and non-null
    values are unchanged, and DuckDB reads both sentinels as SQL NULL, so no
    query can observe the difference — hence the column-wise assertions here
    instead of a flat assert_frame_equal.
    """
    client, reg = _client()
    headers = _auth(client)
    csv = b"n,s,d,b\n1,alpha,2024-01-01,true\n,beta,,false\n3,,2024-03-01,\n"
    res = client.post(
        "/datasets/upload",
        files={"file": ("mixed.csv", csv, "text/csv")},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    ds = res.json()["dataset_id"]

    before = reg.get(ds).df.copy()
    reg.remove(ds)
    after = reg.get(ds).df

    assert list(after.columns) == list(before.columns)
    assert after.dtypes.to_dict() == before.dtypes.to_dict()
    for col in before.columns:
        mask = before[col].isna()
        assert mask.equals(after[col].isna()), f"null positions moved in {col}"
        assert after.loc[~mask, col].tolist() == before.loc[~mask, col].tolist()

    assert after["n"].isna().sum() == 1
    assert pd.api.types.is_datetime64_any_dtype(after["d"])

    # And the whole point: a query over the reloaded frame sees the same NULLs.
    plan = {
        "dataset_id": ds,
        "intent": "comparison",
        "aggregations": [{"fn": "count", "column": "n", "as": "n_count"}],
    }
    out = client.post("/analysis/execute", json={"dataset_id": ds, "analysis_plan": plan})
    assert out.status_code == 200, out.text
    assert out.json()["result_table"][0]["n_count"] == 2  # the null row is excluded
