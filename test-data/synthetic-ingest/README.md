# Synthetic ingestion fixtures

Everything else in `test-data/` is real, unmodified public data. **These files are not.** Each one
is the *same five-row table* wrapped in exactly one reading hazard, so the test suite can assert a
single property from nine angles: whatever the file did to disguise itself, the table that comes
out is the one that went in.

That shared payload is the design. If a reader is wrong, the fixture that exposes it produces a
*different table* from its neighbours — which is a far sharper signal than a parse error, because
the failures that matter here do not raise. A mis-sniffed delimiter, a swapped date order, or a
`NA` read as null all succeed quietly and corrupt every number downstream.

```bash
python test-data/synthetic-ingest/generate.py
```

No RNG at all — the tables are written out literally, so a regenerated file is byte-identical and
a diff means a real change.

## The fixtures

| File | Hazard | What breaks without it |
|---|---|---|
| `clean.csv` | **none — the control** | A probe that reports assumptions here has made its own disclosure worthless |
| `cp1252.csv` | Windows-1252 encoding | `UnicodeDecodeError` on upload, or mojibake in every label |
| `utf8_bom.csv` | UTF-8 byte-order mark | The BOM prefixes the *first column name*, so every later lookup of it fails |
| `eu_semicolon.csv` | `;` separator, `1234,50` decimals | Loads as one text column; revenue can never be summed |
| `title_rows.csv` | Title + provenance + blank line above the header | Column names become `Quarterly City Report`; the real header becomes data |
| `tab_separated.csv` | Tabs, under a `.csv` name | One column containing the whole row |
| `quoted_commas.csv` | A comma inside a quoted address | Naive sniffing picks the wrong separator and splits the address in two |
| `dayfirst_dates.csv` | Unambiguous `25/12/2026` dates | Month-first parsing cannot read them at all |
| `namibia.csv` | `country_code` = `NA` | pandas' default NA set deletes Namibia and says nothing |

## Shared payload

`city`, `country_code`, `orders`, `revenue` — five rows, five African cities. `namibia.csv` and
`dayfirst_dates.csv` vary one column each; `quoted_commas.csv` has its own schema because the
hazard it carries needs a field with a comma in it.

Namibia is deliberately **absent** from the shared payload. One hazard per fixture is the point,
and a `NA` country code would otherwise fire on every file and leave the control untestable.

See [`backend/tests/test_ingest.py`](../../backend/tests/test_ingest.py) and
[`backend/src/autoviz/services/ingest.py`](../../backend/src/autoviz/services/ingest.py).
