import json

from autoviz.services.export import EXPORT_DIR, export_chart

SPEC = {
    "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
    "data": {"values": [{"species": "setosa", "avg": 5.0}]},
    "mark": "bar",
    "encoding": {
        "x": {"field": "species", "type": "nominal"},
        "y": {"field": "avg", "type": "quantitative"},
    },
}


def test_export_writes_html_with_spec():
    out = export_chart(SPEC, filename="test-iris-bar")
    assert "error" not in out, out
    path = EXPORT_DIR / out["filename"]
    assert path.is_file()
    html = path.read_text(encoding="utf-8")
    assert "vegaEmbed" in html
    assert json.dumps(SPEC) in html
    path.unlink()


def test_export_sanitizes_path_escape():
    out = export_chart(SPEC, filename="../evil")
    assert "error" not in out, out
    path = EXPORT_DIR / out["filename"]
    assert path.is_file()
    assert path.resolve().is_relative_to(EXPORT_DIR)
    assert ".." not in out["filename"]
    path.unlink()


def test_export_rejects_non_spec():
    assert "error" in export_chart({"not": "a spec"})
