"""Dataset routes: upload, ownership, profile/preview (SQLite-backed, offline)."""

from fastapi.testclient import TestClient

import autoviz.services.dataset as dataset_service
import autoviz.services.ingest as ingest_service
from autoviz.api.deps import get_registry
from autoviz.api.main import create_app
from autoviz.services.registry import DatasetRegistry
from autoviz.storage import blobs
from tests.conftest import data_path


def _titanic_bytes() -> bytes:
    with open(data_path("general-testing", "titanic.csv"), "rb") as fh:
        return fh.read()


def _app_with_registry():
    """App whose registry is empty on every request — a cold cache each time.

    This is the restart/eviction case in miniature: nothing survives in memory
    between calls, so every read after the upload has to come back from the
    stored Parquet blob via the loader.
    """
    app = create_app()
    app.dependency_overrides[get_registry] = lambda: DatasetRegistry(
        loader=blobs.make_loader()
    )
    return app


def _token(client: TestClient, email: str) -> str:
    creds = {
        "email": email,
        "password": "pw12345678",
        "username": f"user-{email.split('@', 1)[0]}",
    }
    client.post("/auth/register", json=creds)
    return client.post("/auth/login", json=creds).json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_upload_then_profile_and_preview(api_db):
    client = TestClient(_app_with_registry())
    token = _token(client, "owner@example.com")

    up = client.post(
        "/datasets/upload",
        files={"file": ("titanic.csv", _titanic_bytes(), "text/csv")},
        headers=_auth(token),
    )
    assert up.status_code == 201, up.text
    ds = up.json()["dataset_id"]
    assert up.json()["row_count"] == 891

    listing = client.get("/datasets", headers=_auth(token)).json()["datasets"]
    assert any(d["dataset_id"] == ds for d in listing)

    prof = client.get(f"/datasets/{ds}/profile", headers=_auth(token))
    assert prof.status_code == 200
    assert prof.json()["null_counts"]["age"] > 0

    prev = client.get(f"/datasets/{ds}/preview?limit=5", headers=_auth(token))
    assert prev.status_code == 200
    assert len(prev.json()["rows"]) == 5


def test_upload_requires_auth(api_db):
    client = TestClient(_app_with_registry())
    r = client.post("/datasets/upload", files={"file": ("t.csv", b"a,b\n1,2\n", "text/csv")})
    assert r.status_code == 401


def test_other_user_cannot_access_dataset(api_db):
    client = TestClient(_app_with_registry())
    owner = _token(client, "a@example.com")
    ds = client.post(
        "/datasets/upload",
        files={"file": ("titanic.csv", _titanic_bytes(), "text/csv")},
        headers=_auth(owner),
    ).json()["dataset_id"]

    intruder = _token(client, "b@example.com")
    r = client.get(f"/datasets/{ds}/profile", headers=_auth(intruder))
    assert r.status_code == 403


def test_unknown_dataset_404(api_db):
    client = TestClient(_app_with_registry())
    token = _token(client, "c@example.com")
    r = client.get("/datasets/ds_nope/schema", headers=_auth(token))
    assert r.status_code == 404


def test_oversized_upload_413(api_db, monkeypatch):
    monkeypatch.setattr(ingest_service, "MAX_FILE_BYTES", 8)
    client = TestClient(_app_with_registry())
    token = _token(client, "d@example.com")
    r = client.post(
        "/datasets/upload",
        files={"file": ("titanic.csv", _titanic_bytes(), "text/csv")},
        headers=_auth(token),
    )
    assert r.status_code == 413
    assert r.json()["error_code"] == "RESOURCE_LIMIT"


def test_delete_dataset(api_db):
    client = TestClient(_app_with_registry())
    token = _token(client, "e@example.com")
    ds = client.post(
        "/datasets/upload",
        files={"file": ("titanic.csv", _titanic_bytes(), "text/csv")},
        headers=_auth(token),
    ).json()["dataset_id"]
    d = client.delete(f"/datasets/{ds}", headers=_auth(token))
    assert d.status_code == 200 and d.json()["removed"] is True
    assert client.get(f"/datasets/{ds}/schema", headers=_auth(token)).status_code == 404


def test_materialize_cleaned_dataset_survives_a_cold_registry(api_db):
    """A cleaned copy is persisted like an upload, not left in memory.

    `_app_with_registry` gives every request an empty registry, so the reads after
    the POST can only succeed if the derived frame reached the Parquet blob. A
    dataset the user now owns that vanished on eviction would be worse than one
    that was never offered.
    """
    client = TestClient(_app_with_registry())
    token = _token(client, "cleaner@example.com")

    csv = b"dept,salary\n Eng ,100\neng,200\nENG,300\nSales,400\n"
    up = client.post(
        "/datasets/upload",
        files={"file": ("staff.csv", csv, "text/csv")},
        headers=_auth(token),
    )
    parent = up.json()["dataset_id"]

    res = client.post(
        f"/datasets/{parent}/cleaned",
        json={
            "preprocessing": [
                {"op": "trim_whitespace", "columns": ["dept"]},
                {"op": "normalize_case", "column": "dept"},
            ]
        },
        headers=_auth(token),
    )
    assert res.status_code == 201, res.json()
    body = res.json()
    assert body["parent_id"] == parent
    assert body["version_id"].startswith("pp_")
    cleaned = body["dataset_id"]

    # Both datasets are listed, and the parent still has its original values.
    names = {d["dataset_id"] for d in client.get("/datasets", headers=_auth(token)).json()["datasets"]}
    assert {parent, cleaned} <= names

    rows = client.get(f"/datasets/{cleaned}/preview", headers=_auth(token)).json()["rows"]
    assert {r["dept"] for r in rows} == {"Eng", "Sales"}

    original = client.get(f"/datasets/{parent}/preview", headers=_auth(token)).json()["rows"]
    assert " Eng " in {r["dept"] for r in original}


def test_cannot_clean_someone_elses_dataset(api_db):
    client = TestClient(_app_with_registry())
    owner = _token(client, "owner2@example.com")
    intruder = _token(client, "intruder2@example.com")

    up = client.post(
        "/datasets/upload",
        files={"file": ("titanic.csv", _titanic_bytes(), "text/csv")},
        headers=_auth(owner),
    )
    ds = up.json()["dataset_id"]
    res = client.post(
        f"/datasets/{ds}/cleaned",
        json={"preprocessing": [{"op": "drop_empty_rows"}]},
        headers=_auth(intruder),
    )
    assert res.status_code == 403
