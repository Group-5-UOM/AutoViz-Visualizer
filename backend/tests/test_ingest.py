"""Ingestion: reading a file correctly, and admitting how it was read.

The fixtures in test-data/synthetic-ingest/ are the same five-row table wrapped in
one reading hazard each, so most of these tests assert the same thing from
different angles: whatever the file did to disguise itself, the table that comes
out is the one that went in. The rest assert the second half of the contract —
that a guess is disclosed, and that a file with nothing to guess about discloses
nothing.
"""

import pandas as pd
import pytest

from autoviz.errors import FILE_ERROR, RESOURCE_LIMIT
from autoviz.services import dataset as ds
from autoviz.services import ingest, notices
from tests.conftest import TEST_DATA

FIXTURES = TEST_DATA / "synthetic-ingest"

# The payload every hazard fixture is hiding, in the order it was written.
EXPECTED_CITIES = ["Windhoek", "Cape Town", "Nairobi", "Cairo", "Lagos"]
EXPECTED_REVENUE = [1234.50, 2200.00, 845.25, 1990.75, 1102.40]

# Fixtures that carry the shared payload verbatim. Three are excluded and checked
# on their own: quoted_commas.csv has a different schema, dayfirst_dates.csv adds a
# column, and cp1252.csv accents the first city — which is the whole point of it.
SHARED_PAYLOAD = [
    "clean.csv",
    "eu_semicolon.csv",
    "namibia.csv",
    "tab_separated.csv",
    "title_rows.csv",
    "utf8_bom.csv",
]


@pytest.mark.parametrize("name", SHARED_PAYLOAD)
def test_every_hazard_yields_the_same_table(name):
    """The point of the whole module: the disguise never reaches the data."""
    df, _report = ingest.read_table(FIXTURES / name)
    assert list(df.columns) == ["city", "country_code", "orders", "revenue"]
    assert df["city"].tolist() == EXPECTED_CITIES
    assert df["orders"].tolist() == [12, 34, 7, 21, 15]
    assert df["revenue"].tolist() == pytest.approx(EXPECTED_REVENUE)


def test_clean_file_makes_no_assumptions():
    """The control. A disclosure that fires on every upload is worthless."""
    report = ingest.probe(FIXTURES / "clean.csv")
    assert report.assumptions == []
    assert report.encoding == "utf-8"
    assert report.delimiter == ","
    assert report.header_row == 0


def test_real_test_data_makes_no_assumptions():
    """No false positives across the whole real corpus.

    The heuristics here are the kind that look right on the file you wrote them
    for. Forty real CSVs from eight domains is the check that they generalise.
    """
    noisy = {
        p.name: ingest.probe(p).assumptions
        for p in sorted((TEST_DATA).rglob("*.csv"))
        if "synthetic-ingest" not in p.parts and ingest.probe(p).assumptions
    }
    assert noisy == {}


# --- encoding -----------------------------------------------------------------


def test_cp1252_is_detected_and_decoded():
    df, report = ingest.read_table(FIXTURES / "cp1252.csv")
    assert report.encoding == "cp1252"
    assert ingest.ENCODING in report.assumptions
    # The whole reason to detect it: the accented character survives.
    assert df["city"].iloc[0] == "Windhoek Süd"


def test_utf8_bom_does_not_corrupt_the_first_column_name():
    """An unhandled BOM prefixes the first header cell, so every later lookup of
    that column fails with a name that looks correct in every error message."""
    df, report = ingest.read_table(FIXTURES / "utf8_bom.csv")
    assert report.encoding == "utf-8-sig"
    assert list(df.columns)[0] == "city"
    # A BOM is unambiguous, so it is handled rather than guessed at.
    assert report.assumptions == []


def test_truncated_multibyte_char_does_not_demote_encoding(tmp_path):
    """A sample cut mid-character must not be read as evidence of non-UTF-8."""
    path = tmp_path / "wide.csv"
    # One long UTF-8 line, so the sample boundary lands inside it.
    body = "".join(f"café{i}," for i in range(200_000))
    path.write_text(f"a\n{body}\n", encoding="utf-8")
    assert ingest._detect_encoding(path.read_bytes()[: ingest.SAMPLE_BYTES]) == "utf-8"


# --- delimiter ----------------------------------------------------------------


def test_semicolon_and_tab_are_detected():
    assert ingest.probe(FIXTURES / "eu_semicolon.csv").delimiter == ";"
    assert ingest.probe(FIXTURES / "tab_separated.csv").delimiter == "\t"


def test_quoted_delimiter_does_not_fool_the_sniffer():
    """A comma inside a quoted address is not a separator. Splitting on raw text
    instead of parsing CSV is what gets this wrong."""
    df, report = ingest.read_table(FIXTURES / "quoted_commas.csv")
    assert report.delimiter == ","
    assert list(df.columns) == ["name", "address", "amount"]
    assert df["address"].iloc[0] == "12 High Street, Windhoek"
    assert report.assumptions == []


def test_single_column_file_defaults_to_comma(tmp_path):
    path = tmp_path / "one.csv"
    path.write_text("value\n1\n2\n3\n", encoding="utf-8")
    report = ingest.probe(path)
    assert report.delimiter == ","
    assert report.assumptions == []


# --- header position ----------------------------------------------------------


def test_title_rows_above_the_table_are_stepped_over():
    df, report = ingest.read_table(FIXTURES / "title_rows.csv")
    assert report.header_row == 3
    assert ingest.HEADER_ROW in report.assumptions
    assert list(df.columns) == ["city", "country_code", "orders", "revenue"]
    # Every data row survives: the furniture was skipped, not the first record.
    assert len(df) == 5


def test_header_offset_uses_raw_line_numbers(tmp_path):
    """pandas counts `header` after dropping blank lines, so a blank spacer above
    the table silently promotes the first data row to column names. The reader
    uses skiprows to keep the probe's line numbers meaningful."""
    path = tmp_path / "spaced.csv"
    path.write_text("Report title\n\n\na,b\n1,2\n3,4\n", encoding="utf-8")
    df, report = ingest.read_table(path)
    assert report.header_row == 3
    assert list(df.columns) == ["a", "b"]
    assert df["a"].tolist() == [1, 3]


# --- numeric locale -----------------------------------------------------------


def test_european_decimals_parse_as_numbers():
    df, report = ingest.read_table(FIXTURES / "eu_semicolon.csv")
    assert report.decimal == "," and report.thousands == "."
    assert ingest.DECIMAL_COMMA in report.assumptions
    # Read as text, "1234,50" is not aggregatable at all; the point is the dtype.
    assert pd.api.types.is_numeric_dtype(df["revenue"])
    assert df["revenue"].iloc[0] == pytest.approx(1234.50)


def test_decimal_comma_is_not_inferred_for_comma_delimited_files(tmp_path):
    """In a comma-delimited file the evidence cannot survive to be detected — a
    bare 1,5 is already two fields — so inferring it would mean reinterpreting
    the delimiter itself."""
    path = tmp_path / "plain.csv"
    path.write_text("a,b\n1.5,2.5\n3.5,4.5\n", encoding="utf-8")
    report = ingest.probe(path)
    assert report.decimal == "."
    assert ingest.DECIMAL_COMMA not in report.assumptions


# --- missing-value tokens -----------------------------------------------------


def test_na_is_kept_as_data_in_a_country_code_column():
    """The Namibia case: pandas' default NA set deletes a country and says nothing."""
    df, report = ingest.read_table(FIXTURES / "namibia.csv")
    assert report.na_exclusions == {"country_code": ["NA"]}
    assert ingest.NA_EXCLUSION in report.assumptions
    assert df["country_code"].iloc[0] == "NA"
    assert df["country_code"].notna().all()


def test_na_still_means_missing_in_an_ordinary_column(tmp_path):
    """The exclusion is scoped to columns that look like code lists. Everywhere
    else NA is still absence, or the rule would trade one silent error for another."""
    path = tmp_path / "notes.csv"
    path.write_text("note,n\nfine,1\nNA,2\nalso fine,3\n", encoding="utf-8")
    df, report = ingest.read_table(path)
    assert report.na_exclusions == {}
    assert df["note"].isna().sum() == 1


def test_ordinary_missing_tokens_still_become_null(tmp_path):
    path = tmp_path / "gaps.csv"
    path.write_text("a,b\n1,\n2,NULL\n3,n/a\n", encoding="utf-8")
    df, _report = ingest.read_table(path)
    assert df["b"].isna().sum() == 3


# --- date order ---------------------------------------------------------------


def test_dayfirst_is_read_off_the_data():
    report = ingest.probe(FIXTURES / "dayfirst_dates.csv")
    assert report.dayfirst is True
    # Detected, not guessed — so there is nothing to disclose.
    assert ingest.AMBIGUOUS_DATES not in report.assumptions


def test_dayfirst_dates_become_real_datetimes(registry):
    """End to end: detection is worthless if the coercion does not use it."""
    out = ds.register_dataset(str(FIXTURES / "dayfirst_dates.csv"), registry)
    record = registry.get(out["dataset_id"])
    assert record.schema["order_date"] == "datetime"
    assert record.df["order_date"].iloc[0] == pd.Timestamp("2026-12-25")


def test_wholly_ambiguous_dates_are_disclosed(tmp_path):
    path = tmp_path / "ambiguous.csv"
    path.write_text("d\n01/02/2026\n03/04/2026\n05/06/2026\n", encoding="utf-8")
    report = ingest.probe(path)
    assert report.dayfirst is False  # month-first is what gets applied
    assert ingest.AMBIGUOUS_DATES in report.assumptions


# --- other formats ------------------------------------------------------------


def test_excel_reads_the_first_sheet_and_names_the_rest(tmp_path):
    path = tmp_path / "book.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({"a": [1, 2], "b": [3, 4]}).to_excel(
            writer, sheet_name="Sales", index=False
        )
        pd.DataFrame({"z": [9]}).to_excel(writer, sheet_name="Notes", index=False)
    df, report = ingest.read_table(path)
    assert report.format == "excel" and report.sheet == "Sales"
    assert report.other_sheets == ["Notes"]
    assert ingest.EXTRA_SHEETS in report.assumptions
    assert list(df.columns) == ["a", "b"]


def test_single_sheet_workbook_says_nothing(tmp_path):
    path = tmp_path / "one.xlsx"
    pd.DataFrame({"a": [1, 2]}).to_excel(path, index=False)
    _df, report = ingest.read_table(path)
    assert report.assumptions == []


def test_parquet_carries_its_own_schema(tmp_path):
    path = tmp_path / "t.parquet"
    pd.DataFrame({"a": [1, 2], "b": ["x", "y"]}).to_parquet(path)
    df, report = ingest.read_table(path)
    assert report.format == "parquet"
    assert report.assumptions == []
    assert list(df.columns) == ["a", "b"]


def test_nested_json_is_refused_rather_than_stringified(tmp_path):
    path = tmp_path / "nested.json"
    path.write_text('[{"a": 1, "b": {"c": 2}}]', encoding="utf-8")
    with pytest.raises(ingest.IngestError) as exc:
        ingest.read_table(path)
    assert exc.value.code == FILE_ERROR
    assert "nested" in exc.value.message


def test_legacy_xls_is_refused_with_a_way_forward(tmp_path):
    path = tmp_path / "old.xls"
    path.write_bytes(b"\xd0\xcf\x11\xe0")
    with pytest.raises(ingest.IngestError) as exc:
        ingest.read_table(path)
    assert exc.value.code == FILE_ERROR
    assert ".xlsx" in (exc.value.hint or "")


def test_unknown_suffix_is_read_as_delimited_text(tmp_path):
    """Plenty of exports are CSVs under another name; refusing on the extension
    alone would reject files we can read perfectly well."""
    path = tmp_path / "export.dat"
    path.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    df, _report = ingest.read_table(path)
    assert list(df.columns) == ["a", "b"]


# --- limits -------------------------------------------------------------------


def test_empty_file_is_a_file_error(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ingest.IngestError) as exc:
        ingest.read_table(path)
    assert exc.value.code == FILE_ERROR


def test_header_only_file_is_a_file_error(tmp_path):
    path = tmp_path / "header.csv"
    path.write_text("a,b\n", encoding="utf-8")
    with pytest.raises(ingest.IngestError) as exc:
        ingest.read_table(path)
    assert exc.value.code == FILE_ERROR


def test_byte_cap_is_checked_before_the_file_is_read(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, "MAX_FILE_BYTES", 8)
    path = tmp_path / "big.csv"
    path.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    with pytest.raises(ingest.IngestError) as exc:
        ingest.read_table(path)
    assert exc.value.code == RESOURCE_LIMIT


# --- the report reaches the user ----------------------------------------------


def test_report_is_stored_on_the_profile(registry):
    out = ds.register_dataset(str(FIXTURES / "eu_semicolon.csv"), registry)
    profile = registry.get(out["dataset_id"]).profile
    assert profile["ingest"]["delimiter"] == ";"
    assert "decimal_comma" in profile["ingest"]["assumptions"]


def test_assumptions_become_advisory_notices(registry):
    out = ds.register_dataset(str(FIXTURES / "eu_semicolon.csv"), registry)
    report = registry.get(out["dataset_id"]).profile["ingest"]
    produced = notices.from_ingest(report)
    kinds = {n.kind for n in produced}
    assert kinds == {"ingest_delimiter", "ingest_decimal_comma"}
    assert all(n.severity == notices.ADVISORY for n in produced)
    # The sentence has to say what happened, not merely that something did.
    assert "semicolon" in next(n.note for n in produced if n.kind == "ingest_delimiter")


def test_a_clean_file_produces_no_notices(registry):
    out = ds.register_dataset(str(FIXTURES / "clean.csv"), registry)
    report = registry.get(out["dataset_id"]).profile["ingest"]
    assert notices.from_ingest(report) == []


def test_notices_survive_a_profile_round_trip():
    """from_ingest reads the wire form, so a dataset restored from a Parquet blob
    discloses exactly what one still in memory does."""
    report = ingest.probe(FIXTURES / "title_rows.csv").to_wire()
    assert [n.kind for n in notices.from_ingest(report)] == ["ingest_header_row"]


def test_ingest_notices_reach_the_analysis_result(registry):
    """The disclosure channel, end to end — provenance is not where a user looks."""
    out = ds.register_dataset(str(FIXTURES / "eu_semicolon.csv"), registry)
    dataset_id = out["dataset_id"]
    from autoviz.services.execution import execute_analysis

    result = execute_analysis(
        dataset_id,
        {
            "dataset_id": dataset_id,
            "intent": "comparison",
            "group_by": ["city"],
            "aggregations": [{"column": "revenue", "fn": "sum", "as": "total"}],
        },
        registry,
    )
    kinds = {n["kind"] for n in result["provenance"]["notices"]}
    assert "ingest_decimal_comma" in kinds
