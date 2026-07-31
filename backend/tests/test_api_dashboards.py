"""Saved charts + dashboard CRUD over HTTP (SQLite-backed, offline)."""

from fastapi.testclient import TestClient

from autoviz.api.main import create_app

_SPEC = {"mark": "bar", "data": {"values": [{"a": 1}]}, "encoding": {}}


def _client_with_user(email: str):
    client = TestClient(create_app())
    creds = {"email": email, "password": "pw12345678"}
    client.post("/auth/register", json=creds)
    token = client.post("/auth/login", json=creds).json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def _save_chart(client, name="chart 1"):
    r = client.post("/charts/save", json={"name": name, "vega_lite_spec": _SPEC})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_save_list_get_delete_chart(api_db):
    client = _client_with_user("chart@example.com")
    chart_id = _save_chart(client)

    listed = client.get("/charts").json()["charts"]
    assert any(c["id"] == chart_id for c in listed)

    got = client.get(f"/charts/{chart_id}")
    assert got.status_code == 200
    assert got.json()["vega_lite_spec"]["mark"] == "bar"

    assert client.delete(f"/charts/{chart_id}").status_code == 200
    assert client.get(f"/charts/{chart_id}").status_code == 404


def test_update_chart_overwrites_in_place(api_db):
    """Editing a chart must rewrite its row, not append a second one — otherwise
    a reopened dashboard shows the chart as first generated."""
    client = _client_with_user("edit@example.com")
    chart_id = _save_chart(client, "fare by class")

    edited = {**_SPEC, "mark": "line"}
    r = client.put(
        f"/charts/{chart_id}",
        json={"vega_lite_spec": edited, "chart_spec": {"style": {"mark_color": "#ff8800"}}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["vega_lite_spec"]["mark"] == "line"
    assert r.json()["chart_spec"]["style"]["mark_color"] == "#ff8800"

    # Same row, and the field nobody sent is untouched.
    assert [c["id"] for c in client.get("/charts").json()["charts"]] == [chart_id]
    assert client.get(f"/charts/{chart_id}").json()["name"] == "fare by class"


def test_update_chart_ownership(api_db):
    owner = _client_with_user("chartowner@example.com")
    chart_id = _save_chart(owner, "owned")

    intruder = _client_with_user("chartintruder@example.com")
    assert intruder.put(f"/charts/{chart_id}", json={"name": "mine now"}).status_code == 403
    assert owner.put("/charts/does-not-exist", json={"name": "x"}).status_code == 404
    assert owner.get(f"/charts/{chart_id}").json()["name"] == "owned"


def test_dashboard_crud_with_widgets(api_db):
    client = _client_with_user("dash@example.com")
    chart_id = _save_chart(client, "fare by class")

    created = client.post("/dashboards", json={"name": "My board"})
    assert created.status_code == 201
    dash_id = created.json()["id"]

    updated = client.put(
        f"/dashboards/{dash_id}",
        json={"name": "Sales board", "widgets": [{"chart_id": chart_id, "x": 0, "y": 0, "w": 6, "h": 4}]},
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["name"] == "Sales board"
    assert len(body["widgets"]) == 1
    assert body["widgets"][0]["chart_id"] == chart_id

    fetched = client.get(f"/dashboards/{dash_id}")
    assert fetched.status_code == 200
    assert len(fetched.json()["widgets"]) == 1

    assert client.delete(f"/dashboards/{dash_id}").status_code == 200
    assert client.get(f"/dashboards/{dash_id}").status_code == 404


def test_dashboard_rejects_unowned_chart(api_db):
    owner = _client_with_user("owner2@example.com")
    chart_id = _save_chart(owner, "owned")

    intruder = _client_with_user("intruder2@example.com")
    dash_id = intruder.post("/dashboards", json={"name": "b"}).json()["id"]
    r = intruder.put(f"/dashboards/{dash_id}", json={"widgets": [{"chart_id": chart_id}]})
    assert r.status_code == 400


def test_other_user_cannot_get_dashboard(api_db):
    a = _client_with_user("a3@example.com")
    dash_id = a.post("/dashboards", json={"name": "a board"}).json()["id"]
    b = _client_with_user("b3@example.com")
    assert b.get(f"/dashboards/{dash_id}").status_code == 403
