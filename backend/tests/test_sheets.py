"""Files that hold more than one table.

A file is not a table. A workbook has sheets; an exported "report" stacks several
tables in one CSV with blank lines between them. Both used to collapse into a
single frame — the workbook by reading sheet 0 and dropping the rest, the report
by feeding pandas rows of two different shapes and passing on whatever it said.

So these tests come in three kinds:

* **enumeration** — the tables are found, named, and described without reading
  their data;
* **selection** — asking for one gets *that* one, and asking for a name that is
  not there fails loudly rather than falling back to the first;
* **restraint** — the far more important half. A blank line inside one table must
  not split it, an ordinary CSV must behave exactly as it did before, and a
  quoted line break must make block detection give up rather than mis-slice.
"""

import pandas as pd
import pytest

from autoviz.errors import FILE_ERROR
from autoviz.services import dataset as ds
from autoviz.services import ingest, notices


@pytest.fixture
def workbook(tmp_path):
    """A blank cover sheet, then two real ones — the shape of a real export."""
    path = tmp_path / "quarter.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame().to_excel(writer, sheet_name="Cover", index=False)
        pd.DataFrame({"region": ["North", "South"], "revenue": [100, 250]}).to_excel(
            writer, sheet_name="Q3 Actuals", index=False
        )
        pd.DataFrame({"sku": ["a", "b", "c"], "units": [3, 4, 5]}).to_excel(
            writer, sheet_name="Units", index=False
        )
    return path


@pytest.fixture
def report_csv(tmp_path):
    """Two tables of different widths, each under its own title."""
    path = tmp_path / "report.csv"
    path.write_text(
        "Q3 Revenue\n"
        "\n"
        "region,revenue\n"
        "North,100\n"
        "South,250\n"
        "\n"
        "Q3 Units\n"
        "\n"
        "sku,units,price\n"
        "a,3,1.5\n"
        "b,4,2.0\n"
    )
    return path


# --- enumeration -------------------------------------------------------------


def test_a_workbooks_sheets_are_listed_with_their_columns(workbook):
    sheets = ingest.list_sheets(workbook)
    assert [s.name for s in sheets] == ["Cover", "Q3 Actuals", "Units"]
    assert sheets[0].is_empty
    assert sheets[1].columns == ["region", "revenue"]
    assert sheets[2].approx_rows == 3


def test_a_stacked_csv_reports_one_block_per_table(report_csv):
    sheets = ingest.list_sheets(report_csv)
    assert [(s.name, s.kind) for s in sheets] == [
        ("Q3 Revenue", "block"),
        ("Q3 Units", "block"),
    ]
    assert sheets[1].columns == ["sku", "units", "price"]


def test_a_block_takes_its_name_from_the_title_above_it(report_csv):
    """A lone line above a table is its title, and a far better label than
    "Table 2" for someone deciding which one they meant."""
    assert ingest.list_sheets(report_csv)[0].name == "Q3 Revenue"


def test_an_untitled_block_still_gets_a_usable_name(tmp_path):
    path = tmp_path / "untitled.csv"
    path.write_text("region,revenue\nN,1\n\nsku,units,price\na,2,3\n")
    assert [s.name for s in ingest.list_sheets(path)] == ["Table 1", "Table 2"]


def test_list_sheets_never_returns_nothing(tmp_path):
    """Callers should not have to special-case "this format has no sheets" — for
    Parquet and JSON the file simply is the table."""
    frame = pd.DataFrame({"a": [1, 2]})
    for name in ("one.parquet", "one.json", "one.csv"):
        path = tmp_path / name
        if path.suffix == ".parquet":
            frame.to_parquet(path)
        elif path.suffix == ".json":
            frame.to_json(path, orient="records")
        else:
            frame.to_csv(path, index=False)
        sheets = ingest.list_sheets(path)
        assert len(sheets) == 1, name
        assert sheets[0].kind == "table", name


def test_needs_choice_is_the_signal_to_draw_a_picker(workbook, tmp_path):
    plain = tmp_path / "plain.csv"
    pd.DataFrame({"a": [1]}).to_csv(plain, index=False)
    assert ds.list_file_sheets(str(workbook))["needs_choice"] is True
    assert ds.list_file_sheets(str(plain))["needs_choice"] is False


# --- selection ---------------------------------------------------------------


def test_naming_a_sheet_reads_that_sheet(workbook):
    df, report = ingest.read_table(workbook, "Units")
    assert list(df.columns) == ["sku", "units"]
    assert report.sheet == "Units"


def test_a_sheet_can_be_chosen_by_position(report_csv):
    df, report = ingest.read_table(report_csv, 0)
    assert report.sheet == "Q3 Revenue"
    assert df["revenue"].tolist() == [100, 250]


def test_a_chosen_block_is_read_without_its_neighbours(report_csv):
    df, _ = ingest.read_table(report_csv, "Q3 Units")
    assert list(df.columns) == ["sku", "units", "price"]
    assert len(df) == 2


def test_an_unknown_sheet_name_fails_and_says_what_is_there(workbook):
    """Never fall back to the first sheet. A caller who asked for "Q3 Actuals"
    and silently received "Cover" would attribute every later number to the
    wrong table with nothing on screen to say so."""
    with pytest.raises(ingest.IngestError) as excinfo:
        ingest.read_table(workbook, "Q4 Actuals")
    assert excinfo.value.code == FILE_ERROR
    assert "Q3 Actuals" in (excinfo.value.hint or "")


def test_a_blank_first_sheet_does_not_fail_the_upload(workbook):
    """The default is the first sheet *with data in it*. Reading position 0 and
    reporting "no data rows" is a dead end for a workbook that plainly has some."""
    df, report = ingest.read_table(workbook)
    assert report.sheet == "Q3 Actuals"
    assert len(df) == 2


def test_a_title_row_above_a_sheets_table_is_skipped(tmp_path):
    """Worksheets carry titles far more often than CSVs do, and until now the
    Excel path had no header detection at all — the table arrived with columns
    called "Unnamed: 1"."""
    path = tmp_path / "titled.xlsx"
    pd.DataFrame(
        [["Q3 Sales Report", None], [None, None], ["region", "revenue"], ["North", 100]]
    ).to_excel(path, sheet_name="Sheet1", index=False, header=False)
    df, report = ingest.read_table(path)
    assert list(df.columns) == ["region", "revenue"]
    assert report.header_row == 2
    assert ingest.HEADER_ROW in report.assumptions


# --- restraint ---------------------------------------------------------------


def test_a_blank_line_inside_one_table_does_not_split_it(tmp_path):
    """Splitting one table in half is far worse than leaving two joined: the
    second half disappears, and nothing on screen says a row count is short."""
    path = tmp_path / "gappy.csv"
    path.write_text("a,b\n1,2\n\n3,4\n5,6\n")
    assert len(ingest.list_sheets(path)) == 1
    df, report = ingest.read_table(path)
    assert len(df) == 3
    assert report.assumptions == []


def test_a_quoted_line_break_makes_block_detection_give_up(tmp_path):
    """Row numbers only match line numbers while no field spans a line, and
    skiprows counts lines. Offsets that cannot be trusted are not offered."""
    path = tmp_path / "quoted.csv"
    path.write_text('a,b\n"line one\nline two",2\n\nc,d\n3,4\n')
    sheets = ingest.list_sheets(path)
    assert len(sheets) == 1 and sheets[0].kind == "table"


def test_an_ordinary_csv_is_read_exactly_as_before(tmp_path):
    path = tmp_path / "plain.csv"
    path.write_text("city,revenue\nLagos,10\nCairo,20\n")
    df, report = ingest.read_table(path)
    assert df["revenue"].tolist() == [10, 20]
    assert report.assumptions == []
    assert report.sheet is None
    assert report.other_sheets == []


# --- disclosure --------------------------------------------------------------


def test_a_stacked_file_that_cannot_be_read_whole_says_why(report_csv):
    """We know exactly what is wrong, so say that rather than passing on
    "Expected 2 fields in line 9, saw 3" — true, unreadable, and unactionable."""
    with pytest.raises(ingest.IngestError) as excinfo:
        ingest.read_table(report_csv)
    assert "2 separate tables" in excinfo.value.message
    assert "Q3 Units" in excinfo.value.message


def test_a_stacked_file_that_does_parse_whole_is_disclosed_not_refused(tmp_path):
    """Same widths, so pandas reads it happily and produces a frame with another
    table's header sitting in it as data. Nothing else would ever mention that."""
    path = tmp_path / "same.csv"
    path.write_text("region,revenue\nN,1\n\nregion,revenue\nE,3\n")
    df, report = ingest.read_table(path)
    assert len(df) == 3
    assert ingest.MULTIPLE_TABLES in report.assumptions
    kinds = [n.kind for n in notices.from_ingest(report.to_wire())]
    assert "ingest_multiple_tables" in kinds


def test_choosing_a_sheet_silences_the_advisory_about_the_others(workbook):
    """Disclosure once the user has decided is nagging, not disclosure."""
    _, default = ingest.read_table(workbook)
    _, chosen = ingest.read_table(workbook, "Units")
    assert ingest.EXTRA_SHEETS in default.assumptions
    assert chosen.assumptions == []
    # Still recorded as provenance, just not raised as a question again.
    assert "Q3 Actuals" in chosen.other_sheets


def test_the_extra_sheets_notice_tells_the_user_what_to_do(workbook):
    _, report = ingest.read_table(workbook)
    note = notices.from_ingest(report.to_wire())[0].note
    assert "Units" in note and "pick a sheet" in note


def test_the_sheet_that_was_read_is_recorded_on_the_dataset(workbook, registry):
    """Long after the upload, the profile is the only record of which of three
    sheets these numbers came from."""
    out = ds.register_dataset(str(workbook), registry, sheet="Units")
    assert out["ingest"]["sheet"] == "Units"
    assert registry.get(out["dataset_id"]).profile["ingest"]["sheet"] == "Units"
