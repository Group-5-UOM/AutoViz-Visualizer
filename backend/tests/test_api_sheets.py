"""Choosing which table to import, over HTTP.

The picker is a two-call flow — inspect to see the tables, upload to register the
ones the user picked — so what these tests pin down is the seam between them: the
names that come back from the first call have to be accepted by the second, one
bad sheet must not cost the user the good ones, and a client written before any
of this existed has to keep working byte-for-byte.
"""

import io
import json

import pandas as pd
from fastapi.testclient import TestClient

from autoviz.api.deps import get_registry
from autoviz.api.main import create_app
from autoviz.services.registry import DatasetRegistry
from autoviz.storage import blobs


def _app():
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


def _workbook_bytes() -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame({"region": ["N", "S"], "revenue": [100, 250]}).to_excel(
            writer, sheet_name="Q3 Actuals", index=False
        )
        pd.DataFrame({"sku": ["a", "b", "c"], "units": [3, 4, 5]}).to_excel(
            writer, sheet_name="Units", index=False
        )
    return buffer.getvalue()


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _file(name="quarter.xlsx"):
    return {"file": (name, _workbook_bytes(), XLSX)}


# --- inspect -----------------------------------------------------------------


def test_inspect_lists_the_sheets_without_registering_anything(api_db):
    client = TestClient(_app())
    token = _token(client, "inspect@example.com")

    res = client.post("/datasets/inspect", files=_file(), headers=_auth(token))
    assert res.status_code == 200
    body = res.json()
    assert [s["name"] for s in body["sheets"]] == ["Q3 Actuals", "Units"]
    assert body["needs_choice"] is True
    assert body["sheets"][0]["columns"] == ["region", "revenue"]

    # Nothing was kept: the user has not chosen yet, and a half-imported workbook
    # cluttering their dataset list would be a side effect of merely looking.
    assert client.get("/datasets", headers=_auth(token)).json()["datasets"] == []


def test_inspect_requires_auth(api_db):
    client = TestClient(_app())
    assert client.post("/datasets/inspect", files=_file()).status_code == 401


def test_a_single_table_file_needs_no_choice(api_db):
    client = TestClient(_app())
    token = _token(client, "single@example.com")
    res = client.post(
        "/datasets/inspect",
        files={"file": ("t.csv", b"a,b\n1,2\n", "text/csv")},
        headers=_auth(token),
    )
    assert res.json()["needs_choice"] is False


# --- upload ------------------------------------------------------------------


def test_uploading_without_a_choice_behaves_exactly_as_before(api_db):
    """A client written before sheet selection sends no `sheets` field, and must
    get back the same single-dataset body at the same status it always did."""
    client = TestClient(_app())
    token = _token(client, "legacy@example.com")
    res = client.post("/datasets/upload", files=_file(), headers=_auth(token))
    assert res.status_code == 201
    body = res.json()
    assert body["row_count"] == 2  # the first sheet, as before
    assert "datasets" not in body


def test_each_chosen_sheet_becomes_its_own_dataset(api_db):
    """Sheets in one workbook rarely share a schema, so merging them would be a
    join nobody asked for — and the join machinery is already there for when
    they do want one."""
    client = TestClient(_app())
    token = _token(client, "multi@example.com")
    res = client.post(
        "/datasets/upload",
        files=_file(),
        data={"sheets": json.dumps(["Q3 Actuals", "Units"])},
        headers=_auth(token),
    )
    assert res.status_code == 201
    imported = res.json()["datasets"]
    assert [d["sheet"] for d in imported] == ["Q3 Actuals", "Units"]
    assert [d["row_count"] for d in imported] == [2, 3]
    assert len({d["dataset_id"] for d in imported}) == 2
    # Named so the two are told apart in a list that shows only logical names.
    assert imported[1]["logical_name"] == "quarter.xlsx — Units"

    listing = client.get("/datasets", headers=_auth(token)).json()["datasets"]
    assert len(listing) == 2


def test_the_top_level_body_still_describes_the_first_dataset(api_db):
    """Additive on purpose: `datasets` is new, everything above it is what a
    caller that has not been updated is already reading."""
    client = TestClient(_app())
    token = _token(client, "shape@example.com")
    body = client.post(
        "/datasets/upload",
        files=_file(),
        data={"sheets": json.dumps(["Units"])},
        headers=_auth(token),
    ).json()
    assert body["dataset_id"] == body["datasets"][0]["dataset_id"]
    assert body["row_count"] == 3


def test_all_imports_every_sheet_with_data_in_it(api_db):
    client = TestClient(_app())
    token = _token(client, "all@example.com")
    body = client.post(
        "/datasets/upload", files=_file(), data={"sheets": "all"}, headers=_auth(token)
    ).json()
    assert {d["sheet"] for d in body["datasets"]} == {"Q3 Actuals", "Units"}


def test_a_sheet_name_containing_a_comma_survives_the_round_trip(api_db):
    """Why the field is a JSON array and not a comma-separated list: "Revenue,
    net" is an entirely ordinary thing to call a worksheet."""
    client = TestClient(_app())
    token = _token(client, "comma@example.com")
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame({"a": [1]}).to_excel(writer, sheet_name="Revenue, net", index=False)
    payload = {"file": ("c.xlsx", buffer.getvalue(), XLSX)}
    body = client.post(
        "/datasets/upload",
        files=payload,
        data={"sheets": json.dumps(["Revenue, net"])},
        headers=_auth(token),
    ).json()
    assert body["datasets"][0]["sheet"] == "Revenue, net"


def test_one_unreadable_sheet_does_not_cost_the_others(api_db):
    """Workbooks collect junk tabs. Failing the whole import because one of them
    is a note to self would make the feature useless on real files."""
    client = TestClient(_app())
    token = _token(client, "partial@example.com")
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame({"region": ["N"], "revenue": [1]}).to_excel(
            writer, sheet_name="Data", index=False
        )
        pd.DataFrame().to_excel(writer, sheet_name="Notes", index=False)
    res = client.post(
        "/datasets/upload",
        files={"file": ("j.xlsx", buffer.getvalue(), XLSX)},
        data={"sheets": json.dumps(["Data", "Notes"])},
        headers=_auth(token),
    )
    assert res.status_code == 201
    body = res.json()
    assert [d["sheet"] for d in body["datasets"]] == ["Data"]
    assert body["skipped"][0]["sheet"] == "Notes"


def test_an_unknown_sheet_name_is_a_400_naming_what_is_there(api_db):
    client = TestClient(_app())
    token = _token(client, "unknown@example.com")
    res = client.post(
        "/datasets/upload",
        files=_file(),
        data={"sheets": json.dumps(["Q4 Actuals"])},
        headers=_auth(token),
    )
    assert res.status_code == 400
    assert "Q3 Actuals" in json.dumps(res.json())


def test_too_many_sheets_is_refused_before_any_are_read(api_db, monkeypatch):
    client = TestClient(_app())
    token = _token(client, "cap@example.com")
    monkeypatch.setattr("autoviz.services.ingest.MAX_SHEETS", 1)
    res = client.post(
        "/datasets/upload",
        files=_file(),
        data={"sheets": json.dumps(["Q3 Actuals", "Units"])},
        headers=_auth(token),
    )
    assert res.status_code == 413
    assert client.get("/datasets", headers=_auth(token)).json()["datasets"] == []
