"""Generate the synthetic ingestion fixtures.

Like `synthetic-quality/`, these files are deliberately not real data. Each one
is a well-formed table wrapped in exactly one reading hazard — a codec, a
separator, a title row, a decimal convention — so a test can assert that
`services/ingest.probe` recovers the *same* table from all of them. The payload
is held constant on purpose: if the reader is right, every fixture here yields
the same rows, and any difference is the hazard leaking into the data.

One file (`clean.csv`) carries no hazard at all. It is the control, and the
property it guards is the one most easily lost: a probe that reports assumptions
about a perfectly ordinary CSV has made its own disclosure worthless.

Deterministic — no RNG here at all, the tables are written out literally, so a
regenerated file is byte-identical and a diff means a real change.

    python test-data/synthetic-ingest/generate.py
"""

import csv
from pathlib import Path

HERE = Path(__file__).parent

# The shared payload. Small enough to read at a glance and assert on by hand.
#
# Namibia is deliberately NOT in here. One hazard per fixture is the whole design,
# and a country_code column containing "NA" is its own hazard — it would fire on
# every file and make the control fixture untestable. It lives in namibia.csv.
HEADER = ["city", "country_code", "orders", "revenue"]
ROWS = [
    ["Windhoek", "WH", 12, "1234.50"],
    ["Cape Town", "ZA", 34, "2200.00"],
    ["Nairobi", "KE", 7, "845.25"],
    ["Cairo", "EG", 21, "1990.75"],
    ["Lagos", "NG", 15, "1102.40"],
]


def _write_delimited(
    path: Path,
    delimiter: str,
    encoding: str = "utf-8",
    preamble: list[str] | None = None,
    decimal_comma: bool = False,
    newline_bom: bool = False,
) -> None:
    lines: list[str] = list(preamble or [])
    lines.append(delimiter.join(HEADER))
    for city, code, orders, revenue in ROWS:
        value = revenue.replace(".", ",") if decimal_comma else revenue
        lines.append(delimiter.join([city, code, str(orders), value]))
    text = "\n".join(lines) + "\n"
    data = text.encode(encoding)
    if newline_bom:
        data = b"\xef\xbb\xbf" + data
    path.write_bytes(data)
    print(f"{path.name}: {path.stat().st_size} bytes, {encoding}, delimiter={delimiter!r}")


def main() -> None:
    """Write one fixture per reading hazard, plus the no-hazard control."""
    # The control. UTF-8, comma, header on line 0 — probe() must report nothing.
    _write_delimited(HERE / "clean.csv", ",")

    # "NA" as a real value. pandas' default NA set turns it into null, deleting
    # Namibia from the analysis and saying nothing; the column shape (two-letter
    # uppercase codes) is what lets the probe tell data from absence here.
    namibia = HERE / "namibia.csv"
    lines = [",".join(HEADER)]
    codes = ["NA", "ZA", "KE", "EG", "NG"]
    for (city, _code, orders, revenue), code in zip(ROWS, codes):
        lines.append(",".join([city, code, str(orders), revenue]))
    namibia.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"namibia.csv: {namibia.stat().st_size} bytes")

    # cp1252: the single most common way a spreadsheet export fails to load. The
    # accented city name is the only byte that distinguishes it from ASCII, which
    # is exactly the situation the strict-decode ladder has to get right.
    accented = [list(r) for r in ROWS]
    accented[0][0] = "Windhoek Süd"
    lines = [",".join(HEADER)]
    lines += [",".join([c, k, str(o), r]) for c, k, o, r in accented]
    (HERE / "cp1252.csv").write_bytes(("\n".join(lines) + "\n").encode("cp1252"))
    print(f"cp1252.csv: {(HERE / 'cp1252.csv').stat().st_size} bytes, cp1252")

    # UTF-8 with a BOM — Excel writes these constantly, and an unhandled BOM
    # corrupts the *first column name*, which then fails every later lookup.
    _write_delimited(HERE / "utf8_bom.csv", ",", newline_bom=True)

    # The European convention: semicolon separator because the comma is taken by
    # the decimal point.
    _write_delimited(HERE / "eu_semicolon.csv", ";", decimal_comma=True)

    # Spreadsheet furniture above the table: a title, a provenance line, and a
    # blank spacer. None of it has the table's field count or is free of empty
    # cells, which is what lets the header search step over it.
    _write_delimited(
        HERE / "title_rows.csv",
        ",",
        preamble=["Quarterly City Report", "Generated 2026-02-01 by Finance", ""],
    )

    # Tab-separated under a .csv name, because that is how they arrive.
    _write_delimited(HERE / "tab_separated.csv", "\t")

    # Unambiguous day-first dates. A reader that assumes month-first cannot parse
    # 25/12/2026 at all, so this is the fixture that proves dayfirst is detected
    # rather than guessed.
    header = HEADER + ["order_date"]
    dates = ["25/12/2026", "13/01/2026", "07/03/2026", "30/06/2026", "19/11/2026"]
    lines = [",".join(header)]
    for (city, code, orders, revenue), when in zip(ROWS, dates):
        lines.append(",".join([city, code, str(orders), revenue, when]))
    (HERE / "dayfirst_dates.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"dayfirst_dates.csv: {(HERE / 'dayfirst_dates.csv').stat().st_size} bytes")

    # A quoted field containing the delimiter. The consistency heuristic must
    # parse through csv rather than splitting, or it picks the wrong separator.
    quoted = HERE / "quoted_commas.csv"
    with quoted.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, quoting=csv.QUOTE_MINIMAL)
        w.writerow(["name", "address", "amount"])
        w.writerow(["Ada", "12 High Street, Windhoek", "100.00"])
        w.writerow(["Grace", "9 Long Road, Nairobi", "250.50"])
        w.writerow(["Alan", "3 Short Lane, Cairo", "75.25"])
    print(f"quoted_commas.csv: {quoted.stat().st_size} bytes")


if __name__ == "__main__":
    main()
