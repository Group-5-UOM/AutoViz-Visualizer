"""CSV ingestion resource controls: file / column / row ceilings.

The ceilings live on ``services.ingest`` — next to the reads they guard — so that
is what these patch, while the behaviour is still asserted through
``register_dataset``, which is where a caller meets them.
"""

import autoviz.services.dataset as ds
import autoviz.services.ingest as ingest
from autoviz.errors import RESOURCE_LIMIT


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_rejects_oversized_file(registry, tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, "MAX_FILE_BYTES", 8)  # smaller than any real CSV
    ref = _write(tmp_path, "big.csv", "a,b\n1,2\n3,4\n")
    out = ds.register_dataset(ref, registry)
    assert out["error_code"] == RESOURCE_LIMIT
    assert "bytes" in out["error"]


def test_rejects_too_many_columns(registry, tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, "MAX_COLUMNS", 2)
    ref = _write(tmp_path, "wide.csv", "a,b,c\n1,2,3\n")
    out = ds.register_dataset(ref, registry)
    assert out["error_code"] == RESOURCE_LIMIT
    assert "columns" in out["error"]


def test_rejects_too_many_rows(registry, tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, "MAX_ROWS", 2)
    ref = _write(tmp_path, "tall.csv", "a\n1\n2\n3\n4\n")
    out = ds.register_dataset(ref, registry)
    assert out["error_code"] == RESOURCE_LIMIT
    assert "rows" in out["error"]


def test_within_limits_registers_normally(registry, tmp_path):
    ref = _write(tmp_path, "ok.csv", "a,b\n1,2\n3,4\n")
    out = ds.register_dataset(ref, registry)
    assert out.get("row_count") == 2
    assert out.get("column_count") == 2
