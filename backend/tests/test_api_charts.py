"""HTTP chart routes via TestClient."""

from fastapi.testclient import TestClient

from autoviz.api.main import create_app


def _client():
    return TestClient(create_app())


def test_recommend_then_generate():
    client = _client()
    result_schema = [{"name": "species", "type": "string"}, {"name": "avg", "type": "number"}]
    rec = client.post("/charts/recommend", json={"result_schema": result_schema, "intent": "comparison"})
    assert rec.status_code == 200
    assert rec.json()["chart_type"] == "bar"

    table = [{"species": "a", "avg": 1.0}, {"species": "b", "avg": 2.0}]
    gen = client.post(
        "/charts/generate",
        json={"result_table": table, "chart_spec": {"type": "bar", "x": "species", "y": "avg"}},
    )
    assert gen.status_code == 200
    assert gen.json()["valid"] is True


def test_recommend_no_numeric_measure_400():
    client = _client()
    result_schema = [{"name": "species", "type": "string"}]
    r = client.post("/charts/recommend", json={"result_schema": result_schema, "intent": "comparison"})
    assert r.status_code == 400
    assert "error" in r.json()


def test_export_bad_spec_400():
    client = _client()
    r = client.post("/charts/export", json={"vega_lite_spec": {"not": "a spec"}})
    assert r.status_code == 400
    assert "error" in r.json()


def test_export_ok_writes_file():
    client = _client()
    spec = {"mark": "bar", "data": {"values": [{"a": 1}]}, "encoding": {}}
    r = client.post("/charts/export", json={"vega_lite_spec": spec, "filename": "api-test-chart"})
    assert r.status_code == 200
    body = r.json()
    assert body["filename"] == "api-test-chart.html"
