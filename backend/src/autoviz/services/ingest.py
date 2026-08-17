"""Reading a file into a DataFrame, and recording what had to be assumed to do it.

``pd.read_csv(path)`` with stock defaults is a guess wearing a straight face. It
assumes UTF-8, a comma, a header on row 0, a full stop for the decimal point, and
that ``NA`` means "missing" rather than "Namibia". Each of those is right most of
the time and silently destructive the rest of it, and nothing in the old path told
anyone which had happened.

So this module splits reading into two steps. ``probe`` inspects a bounded byte
sample and decides how the file should be read; ``read_table`` reads it with every
one of those decisions passed explicitly, and hands back the decisions alongside
the frame. Anything a reader could reasonably dispute is listed in
``IngestReport.assumptions``, which becomes an advisory notice — the same channel
cleaning already uses, for the same reason: a number whose meaning depends on a
guess must arrive with the guess attached.

The list stays **empty for a well-formed UTF-8 comma CSV**, which is the common
case. Disclosure that fires on every upload is noise, and noise is how a real
disclosure gets skipped.

A third step sits in front of both for files that hold more than one table.
``list_sheets`` enumerates them — worksheets in a workbook, or blank-line-separated
blocks in a delimited file, which is what exported "reports" are made of — and
``read_table(sheet=...)`` reads the one that was picked. Nothing is picked
automatically beyond the first sheet with data in it; where a choice was made on
the user's behalf, ``assumptions`` says so.

Prose lives in services/notices.py, not here: this module reports facts and the
kinds of assumption it made, and the sentences are composed there with everything
else the user is told.

Division of labour with services/dataset.py: this module is *mechanism* (how to
read bytes, and the ceilings that bound that work, which cannot be checked
separately from the read they guard). ``dataset.py`` keeps *policy* — which paths
are allowed (``DATA_ROOTS``), how a frame is typed and profiled once it exists.
"""

import codecs
import csv
import io
import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pandas as pd

from autoviz.errors import FILE_ERROR, RESOURCE_LIMIT
from autoviz.services.safety import neutralize_text


def _env_int(name: str, default: int) -> int:
    """Read a positive int limit from the environment, falling back on default."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


# Ingestion ceilings, enforced *before* a file is trusted into memory. The byte cap
# is the real memory guard — every reader here would otherwise load the whole file
# before any check could run; the row/column caps bound downstream work. All
# overridable. Tests monkeypatch these module attributes, so they are read through
# the module namespace at call time rather than captured at import.
MAX_FILE_BYTES = _env_int("AUTOVIZ_MAX_FILE_BYTES", 50 * 1024 * 1024)  # 50 MiB
MAX_ROWS = _env_int("AUTOVIZ_MAX_ROWS", 1_000_000)
MAX_COLUMNS = _env_int("AUTOVIZ_MAX_COLUMNS", 512)
# How many tables one file may be split into. A workbook with hundreds of sheets
# is a database export, not a spreadsheet, and importing it wholesale would bury
# the real data in the dataset list.
MAX_SHEETS = _env_int("AUTOVIZ_MAX_SHEETS", 20)

# How much of the file the probe looks at. Big enough that the sniffing heuristics
# see real variety, small enough that probing a 50 MiB file is free.
SAMPLE_BYTES = 256 * 1024
# Rows the probe reasons over once the sample is split into lines.
SAMPLE_ROWS = 200
# How far into the file a header may sit. Past this it is not spreadsheet furniture
# above the table, it is a different kind of file.
MAX_HEADER_SEARCH_ROWS = 20

# Ordered by prior likelihood; ties in the consistency score fall back to this order.
DELIMITER_CANDIDATES = (",", ";", "\t", "|")

# pandas' own default NA set, written out rather than inherited. Inheriting it is
# how "NA" silently became null; naming it is what lets a column opt out below.
DEFAULT_NA_TOKENS = (
    "", "#N/A", "#N/A N/A", "#NA", "-1.#IND", "-1.#QNAN", "-NaN", "-nan",
    "1.#IND", "1.#QNAN", "<NA>", "N/A", "NA", "NULL", "NaN", "None",
    "n/a", "nan", "null",
)

# Assumption kinds. Strings rather than an enum because they cross the wire into
# the profile blob and are matched by name in notices.py.
ENCODING = "encoding"
DELIMITER = "delimiter"
HEADER_ROW = "header_row"
DECIMAL_COMMA = "decimal_comma"
AMBIGUOUS_DATES = "ambiguous_dates"
NA_EXCLUSION = "na_exclusion"
EXTRA_SHEETS = "extra_sheets"
MULTIPLE_TABLES = "multiple_tables"

_TWO_LETTER_CODE = re.compile(r"^[A-Z]{2}$")
# 1.234.567,89 (grouped) or 1234,89 / 12,5 (plain) — the European convention.
_EU_DECIMAL = re.compile(r"^-?\d{1,3}(?:\.\d{3})+,\d+$|^-?\d+,\d{1,2}$")
# Any slash/dash date; which component is the day is the question, not whether it
# is a date at all.
_SLASH_DATE = re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})$")
# A cell that is plainly a measurement rather than a label: a header row does not
# look like this, and a row that does is data continuing, not a new table.
_NUMERIC_CELL = re.compile(r"^[-+]?[\d,. ]*\d[\d,. ]*(?:[eE][-+]?\d+)?%?$")

# Fraction of a column's sampled values that must look like two-letter codes before
# "NA" is read as data rather than as missing. High, because the cost of being
# wrong in this direction (real nulls kept as the string "NA") is a visible odd
# category, while being wrong the other way silently deletes Namibia.
CODE_COLUMN_FRACTION = 0.9


class IngestError(Exception):
    """A file cannot be read. ``code`` is the taxonomy code the caller reports."""

    def __init__(self, code: str, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


@dataclass(frozen=True)
class IngestReport:
    """How a file was read, and which of those choices were guesses.

    Stored on the dataset profile, so it is also the record of *why* a column
    holds what it holds long after the upload.
    """

    format: str
    encoding: str = "utf-8"
    delimiter: str | None = None
    quotechar: str | None = None
    # 0 for a well-formed file; >0 means this many rows of furniture sat above it.
    header_row: int = 0
    decimal: str = "."
    thousands: str | None = None
    na_tokens: tuple[str, ...] = DEFAULT_NA_TOKENS
    # column -> tokens deliberately NOT read as missing in that column.
    na_exclusions: dict[str, list[str]] = field(default_factory=dict)
    sheet: str | None = None
    other_sheets: list[str] = field(default_factory=list)
    # True/False when the data settles it, None when every date is ambiguous.
    dayfirst: bool | None = None
    # Kinds of choice a reader could dispute; empty for a well-formed file.
    assumptions: list[str] = field(default_factory=list)

    def to_wire(self) -> dict[str, Any]:
        """The report as inert JSON. Column and sheet names come from the file, so
        they are untrusted text and are neutralized like every other such copy."""
        out: dict[str, Any] = {
            "format": self.format,
            "encoding": self.encoding,
            "header_row": self.header_row,
            "decimal": self.decimal,
            "assumptions": list(self.assumptions),
        }
        if self.delimiter is not None:
            out["delimiter"] = self.delimiter
        if self.thousands is not None:
            out["thousands"] = self.thousands
        if self.na_exclusions:
            out["na_exclusions"] = {
                neutralize_text(c): list(v) for c, v in self.na_exclusions.items()
            }
        if self.sheet is not None:
            out["sheet"] = neutralize_text(self.sheet)
        if self.other_sheets:
            out["other_sheets"] = [neutralize_text(s) for s in self.other_sheets]
        if self.dayfirst is not None:
            out["dayfirst"] = self.dayfirst
        return out


@dataclass(frozen=True)
class SheetInfo:
    """One table inside one file.

    A file is not the same thing as a table, and pretending otherwise is how a
    workbook's other twelve sheets get dropped without anyone noticing. Three
    shapes reduce to this one description:

    * ``sheet``  — a worksheet in an .xlsx/.xlsm workbook.
    * ``block``  — a run of rows in a delimited file, separated from its
      neighbours by blank lines and carrying its own header. Exported "reports"
      are full of these; read whole, they parse into nonsense.
    * ``table``  — the file *is* one table (Parquet, JSON), so there is nothing
      to choose and exactly one of these is returned.

    ``name`` is what the user picks by and what ``read_table(sheet=...)``
    accepts. It comes from the file, so it is untrusted text and is neutralized
    on the way out — never on the way in, because it has to still match the
    workbook when it is passed back.
    """

    name: str
    index: int
    kind: str
    columns: list[str] = field(default_factory=list)
    # Approximate for a worksheet: read-only openpyxl reports the sheet's
    # declared dimension, which trailing formatting can inflate. Exact for a
    # block, which was counted. None when it could not be established at all.
    approx_rows: int | None = None
    is_empty: bool = False
    # Where the header sits, and how many data rows follow. Relative to the sheet
    # for a worksheet; absolute line numbers for a block.
    header_offset: int = 0
    row_span: int | None = None

    def to_wire(self) -> dict[str, Any]:
        return {
            "name": neutralize_text(self.name),
            "index": self.index,
            "kind": self.kind,
            "columns": [neutralize_text(c) for c in self.columns],
            "approx_rows": self.approx_rows,
            "is_empty": self.is_empty,
        }


# --- encoding -----------------------------------------------------------------


def _whole_lines(raw: bytes) -> bytes:
    """Trim a byte sample back to its last newline.

    A sample sliced mid-character makes a strict UTF-8 decode raise, which would
    demote a perfectly good UTF-8 file to cp1252 on the strength of where the
    256 KiB boundary happened to land.
    """
    cut = raw.rfind(b"\n")
    return raw[: cut + 1] if cut > 0 else raw


def _detect_encoding(raw: bytes) -> str:
    """The narrowest codec that decodes the sample without loss.

    A BOM is definitive. Otherwise strict UTF-8 first (it rejects almost every
    non-UTF-8 byte sequence, so success is strong evidence), then cp1252, then
    latin-1 — which decodes any byte at all and so is the terminating fallback
    rather than a real detection.
    """
    if raw.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if raw.startswith(codecs.BOM_UTF16_LE) or raw.startswith(codecs.BOM_UTF16_BE):
        return "utf-16"
    sample = _whole_lines(raw)
    for codec in ("utf-8", "cp1252"):
        try:
            sample.decode(codec)
            return codec
        except UnicodeDecodeError:
            continue
    return "latin-1"


# --- delimiter ----------------------------------------------------------------


def _score_delimiter(lines: list[str], delimiter: str) -> tuple[int, int]:
    """(rows agreeing with the modal field count, that modal count).

    Parsed through ``csv.reader`` rather than ``str.split`` so a comma inside a
    quoted field does not count as a separator — the case that makes naive
    sniffing pick the wrong character on perfectly ordinary data.
    """
    try:
        counts = [len(row) for row in csv.reader(lines, delimiter=delimiter) if row]
    except csv.Error:
        return (0, 0)
    if not counts:
        return (0, 0)
    modal = max(set(counts), key=counts.count)
    return (counts.count(modal), modal)


def _detect_delimiter(lines: list[str]) -> str:
    """The candidate that splits the sample most consistently into >1 field.

    Field-count consistency leads and ``csv.Sniffer`` is only the tie-break.
    Sniffer guesses from character frequency and is confidently wrong on files
    with prose in them; "every row splits into the same number of columns" is the
    property that actually defines a delimiter.
    """
    best: tuple[int, int, str] | None = None
    for candidate in DELIMITER_CANDIDATES:
        agreement, modal = _score_delimiter(lines, candidate)
        # A modal count of 1 means the character does not appear — every line
        # "agrees" at one field, which would otherwise score perfectly.
        if modal < 2:
            continue
        scored = (agreement, modal, candidate)
        if best is None or scored[:2] > best[:2]:
            best = scored
    if best is None:
        return ","
    # Two candidates splitting equally well: let Sniffer break the tie.
    tied = [
        c
        for c in DELIMITER_CANDIDATES
        if _score_delimiter(lines, c)[:2] == (best[0], best[1])
    ]
    if len(tied) > 1:
        try:
            sniffed = csv.Sniffer().sniff("\n".join(lines), delimiters="".join(tied))
            return sniffed.delimiter
        except csv.Error:
            pass
    return best[2]


# --- header position ----------------------------------------------------------


def _detect_header_row(rows: list[list[str]]) -> int:
    """Index of the row that is actually the header.

    Titles, blank spacer rows, and provenance lines above a table all fail at
    least one of three tests: the row has the table's field count, every cell in
    it is non-empty, and the row after it has the same field count. A header is
    the first row where all three hold.

    Deliberately narrow. This is the one heuristic here that can silently discard
    real data if it overreaches, so it only ever *skips* rows that do not look
    like part of the table, and reports doing so.
    """
    if not rows:
        return 0
    counts = [len(r) for r in rows if r]
    if not counts:
        return 0
    modal = max(set(counts), key=counts.count)
    if modal < 1:
        return 0
    limit = min(len(rows) - 1, MAX_HEADER_SEARCH_ROWS)
    for i in range(limit):
        row = rows[i]
        if len(row) != modal:
            continue
        if any(not cell.strip() for cell in row):
            continue
        if len(rows[i + 1]) != modal:
            continue
        return i
    return 0


# --- numeric locale -----------------------------------------------------------


def _detect_decimal_comma(delimiter: str, data_rows: list[list[str]]) -> bool:
    """Whether numbers in this file use a comma for the decimal point.

    Gated on a semicolon delimiter. In a comma-delimited file a bare ``1,5`` has
    already been split into two fields, so the evidence cannot survive to be
    detected — and treating a comma as a decimal point there would mean
    reinterpreting the delimiter itself. The semicolon exists in these files
    precisely because the comma was taken.
    """
    if delimiter != ";" or not data_rows:
        return False
    hits = sum(
        1
        for row in data_rows
        for cell in row
        if _EU_DECIMAL.match(cell.strip())
    )
    return hits > 0


# --- missing-value tokens -----------------------------------------------------


def _na_exclusions(header: list[str], data_rows: list[list[str]]) -> dict[str, list[str]]:
    """Columns where a default NA token is really data.

    The case this exists for is ``NA`` = Namibia. A country-code column is
    overwhelmingly two-letter uppercase codes, so when one of those codes is
    literally ``NA``, reading it as missing deletes a country from the analysis
    and reports nothing. Detect the shape, keep the value, say so.
    """
    exclusions: dict[str, list[str]] = {}
    for i, name in enumerate(header):
        values = [
            row[i].strip()
            for row in data_rows
            if i < len(row) and row[i].strip()
        ]
        if len(values) < 3 or "NA" not in values:
            continue
        codes = sum(1 for v in values if _TWO_LETTER_CODE.match(v))
        if codes / len(values) >= CODE_COLUMN_FRACTION:
            exclusions[name] = ["NA"]
    return exclusions


# --- date order ---------------------------------------------------------------


def _detect_dayfirst(data_rows: list[list[str]]) -> bool | None:
    """True/False when a slash-date column settles it, None when it cannot.

    A single ``25/12/2024`` proves day-first for the whole column; a single
    ``12/25/2024`` proves month-first. When every value could be read either way
    the file genuinely does not say, and the caller discloses the choice instead
    of pretending to have detected one. None is also returned when there are no
    slash dates at all — nothing to disclose either way.
    """
    saw_ambiguous = False
    for row in data_rows:
        for cell in row:
            m = _SLASH_DATE.match(cell.strip())
            if m is None:
                continue
            first, second = int(m.group(1)), int(m.group(2))
            if first > 12 and second <= 12:
                return True
            if second > 12 and first <= 12:
                return False
            saw_ambiguous = True
    return None if saw_ambiguous else False


# --- several tables in one file -----------------------------------------------


def _looks_like_header(row: list[str]) -> bool:
    """Whether this row names columns rather than holding measurements.

    Used to decide whether a run of rows after a blank line is a *new* table or
    the same one continuing. Requiring every cell to be a non-numeric label is
    strict on purpose: splitting one table in half is a far worse failure than
    leaving two joined, because the second half silently disappears.
    """
    if len(row) < 2:
        return False
    return all(cell.strip() and not _NUMERIC_CELL.match(cell.strip()) for cell in row)


def _scan_blocks(path: Path, report: IngestReport) -> list[SheetInfo]:
    """The separate tables inside a delimited file, in the order they appear.

    Streams the file through ``csv.reader`` rather than splitting on newlines, so
    a quoted field containing a line break does not invent a table boundary. That
    same quoting is the one thing that can put row numbers out of step with raw
    line numbers, which is what ``skiprows`` counts — so if any field turns out to
    span lines, this gives up and reports a single table rather than handing back
    offsets it cannot stand behind.

    Returns one entry for an ordinary file. Two or more only when the evidence is
    unambiguous: blank-line-separated runs that each carry their own header.
    """
    groups: list[tuple[int, list[list[str]]]] = []  # (first line index, rows)
    current: list[list[str]] = []
    start = 0
    try:
        with open(path, "r", encoding=report.encoding, errors="replace", newline="") as fh:
            for index, row in enumerate(csv.reader(fh, delimiter=report.delimiter or ",")):
                if any("\n" in cell for cell in row):
                    return []  # offsets would be wrong; caller falls back
                if not row or all(not cell.strip() for cell in row):
                    if current:
                        groups.append((start, current))
                        current = []
                    continue
                if not current:
                    start = index
                current.append(row)
    except (OSError, csv.Error):
        return []
    if current:
        groups.append((start, current))
    if not groups:
        return []

    blocks: list[SheetInfo] = []
    pending_title: str | None = None
    for first_line, rows in groups:
        # A one-line run above a table is its title, not a table of its own.
        if len(rows) < 2:
            cells = [c.strip() for c in rows[0] if c.strip()]
            pending_title = cells[0] if len(cells) == 1 else None
            continue
        counts = [len(r) for r in rows]
        modal = max(set(counts), key=counts.count)
        if modal < 2:
            pending_title = None
            continue
        header_offset = _detect_header_row(rows)
        header = [c.strip() for c in rows[header_offset]]
        if not _looks_like_header(header) and blocks:
            # Data carrying on after a blank line: absorb it into the table above
            # rather than orphaning it as a headerless block of its own.
            previous = blocks[-1]
            span = (first_line + len(rows)) - (
                previous.header_offset + 1 + (previous.row_span or 0)
            )
            blocks[-1] = replace(previous, row_span=(previous.row_span or 0) + span)
            pending_title = None
            continue
        name = pending_title or f"Table {len(blocks) + 1}"
        blocks.append(
            SheetInfo(
                name=name,
                index=len(blocks),
                kind="block",
                columns=header,
                approx_rows=len(rows) - header_offset - 1,
                header_offset=first_line + header_offset,
                row_span=len(rows) - header_offset - 1,
            )
        )
        pending_title = None
    return blocks


# --- worksheets ---------------------------------------------------------------


def _open_workbook(path: Path) -> pd.ExcelFile:
    try:
        return pd.ExcelFile(path)
    except ImportError as exc:  # openpyxl missing
        raise IngestError(
            FILE_ERROR,
            "Reading .xlsx files needs the openpyxl package.",
            hint="Install it, or export the sheet as CSV.",
        ) from exc
    except Exception as exc:
        raise IngestError(FILE_ERROR, f"Could not read workbook: {exc}") from exc


def _sheet_grid(book: pd.ExcelFile, name: str, rows: int) -> list[list[str]]:
    """The top of a worksheet as trimmed text cells, blank rows kept as ``[]``.

    Blank rows are kept because ``skiprows`` counts them, so dropping them here
    would shift every offset derived from this grid.

    Trailing empty cells are trimmed, which is what makes header detection work
    on a worksheet at all: every row pandas returns is padded to the widest one,
    so a title sitting alone in A1 would otherwise have the same field count as
    the table below it and be mistaken for its header.
    """
    try:
        frame = book.parse(name, header=None, nrows=rows, dtype=str)
    except Exception as exc:
        raise IngestError(FILE_ERROR, f"Could not read sheet '{name}': {exc}") from exc
    grid: list[list[str]] = []
    for values in frame.itertuples(index=False, name=None):
        cells = ["" if v is None or v != v else str(v).strip() for v in values]
        while cells and not cells[-1]:
            cells.pop()
        grid.append(cells)
    return grid


def _sheet_rows(book: pd.ExcelFile, name: str) -> int | None:
    """The worksheet's declared row count, or None.

    pandas opens workbooks read-only, where openpyxl takes this from the sheet's
    stored dimension rather than counting — trailing formatting inflates it. Good
    enough to tell a lookup table from a fact table in a picker, not good enough
    to report as a row count, which is why the field it feeds says ``approx``.

    Must be read **before** the sheet is parsed: pandas calls
    ``reset_dimensions()`` on its way in, precisely because that stored dimension
    is unreliable, and afterwards this reads None.
    """
    try:
        return int(book.book[name].max_row)
    except Exception:
        return None


def _workbook_sheets(book: pd.ExcelFile) -> list[SheetInfo]:
    sheets: list[SheetInfo] = []
    # Excel permits a sheet named "2024", which openpyxl hands back as an int.
    for index, name in enumerate(str(s) for s in book.sheet_names):
        rows = _sheet_rows(book, name)  # before the parse below clears it
        grid = _sheet_grid(book, name, SAMPLE_ROWS)
        if not any(row for row in grid):
            sheets.append(
                SheetInfo(name=name, index=index, kind="sheet", approx_rows=0, is_empty=True)
            )
            continue
        header_offset = _detect_header_row(grid)
        header = [c.strip() for c in grid[header_offset]] if header_offset < len(grid) else []
        sheets.append(
            SheetInfo(
                name=name,
                index=index,
                kind="sheet",
                columns=header,
                # Data rows, not sheet rows: what the picker means by "how big".
                approx_rows=max(rows - header_offset - 1, 0) if rows else None,
                header_offset=header_offset,
            )
        )
    return sheets


def _excel_sheets(path: Path) -> list[SheetInfo]:
    # Closed explicitly: pandas holds the file open until told otherwise, and the
    # upload path deletes what it staged the moment it is done with it. On Linux
    # the delete succeeds anyway and the leaked handle is invisible; on Windows
    # it fails outright, which is how this was found.
    with _open_workbook(path) as book:
        return _workbook_sheets(book)


# --- probe --------------------------------------------------------------------


def probe(path: Path) -> IngestReport:
    """Decide how a delimited text file should be read, from a bounded sample."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read(SAMPLE_BYTES)
    except OSError as exc:
        raise IngestError(FILE_ERROR, f"Could not read file: {exc}") from exc
    if not raw.strip():
        raise IngestError(FILE_ERROR, "File is empty.")

    encoding = _detect_encoding(raw)
    text = _whole_lines(raw).decode(encoding, errors="replace")
    lines = text.splitlines()[:SAMPLE_ROWS]
    if not lines:
        raise IngestError(FILE_ERROR, "File has no readable lines.")

    delimiter = _detect_delimiter(lines)
    rows = [row for row in csv.reader(lines, delimiter=delimiter)]
    header_row = _detect_header_row(rows)
    header = [c.strip() for c in rows[header_row]] if header_row < len(rows) else []
    data_rows = rows[header_row + 1 :]

    decimal_comma = _detect_decimal_comma(delimiter, data_rows)
    exclusions = _na_exclusions(header, data_rows)
    dayfirst = _detect_dayfirst(data_rows)

    assumptions: list[str] = []
    if encoding not in ("utf-8", "utf-8-sig"):
        assumptions.append(ENCODING)
    if delimiter != ",":
        assumptions.append(DELIMITER)
    if header_row > 0:
        assumptions.append(HEADER_ROW)
    if decimal_comma:
        assumptions.append(DECIMAL_COMMA)
    if dayfirst is None:
        assumptions.append(AMBIGUOUS_DATES)
    if exclusions:
        assumptions.append(NA_EXCLUSION)

    return IngestReport(
        format="csv",
        encoding=encoding,
        delimiter=delimiter,
        quotechar='"',
        header_row=header_row,
        decimal="," if decimal_comma else ".",
        thousands="." if decimal_comma else None,
        na_exclusions=exclusions,
        # None means "the file does not say"; month-first is then the applied
        # reading, and the assumption above is what admits it.
        dayfirst=bool(dayfirst),
        assumptions=assumptions,
    )


# --- limits -------------------------------------------------------------------


def _check_size(path: Path) -> None:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise IngestError(FILE_ERROR, f"Could not stat file: {exc}") from exc
    if size > MAX_FILE_BYTES:
        raise IngestError(
            RESOURCE_LIMIT, f"File is {size} bytes; the limit is {MAX_FILE_BYTES} bytes."
        )


def _check_columns(count: int) -> None:
    if count > MAX_COLUMNS:
        raise IngestError(
            RESOURCE_LIMIT, f"Dataset has {count} columns; the limit is {MAX_COLUMNS}."
        )


def _check_frame(df: pd.DataFrame) -> None:
    if df.shape[0] == 0 or df.shape[1] == 0:
        raise IngestError(
            FILE_ERROR,
            "File has no data rows (an empty or header-only file is not analysable).",
        )
    if len(df) > MAX_ROWS:
        raise IngestError(
            RESOURCE_LIMIT, f"Dataset has {len(df)} rows; the limit is {MAX_ROWS}."
        )


# --- readers ------------------------------------------------------------------


def _na_argument(
    header: list[str], exclusions: dict[str, list[str]]
) -> Any:
    """The ``na_values`` argument, per-column when a column opts out of a token.

    pandas has no "everything except here" form: a dict applies only to the
    columns it names, and with ``keep_default_na=False`` the rest would get no NA
    handling at all. So an opt-out is expressed by naming *every* column and
    giving one of them a shorter list.

    Falls back to the flat list when headers repeat, because pandas de-duplicates
    them (``a``, ``a.1``) and the dict keys would then miss.
    """
    if not exclusions:
        return list(DEFAULT_NA_TOKENS)
    if not header or len(set(header)) != len(header):
        return list(DEFAULT_NA_TOKENS)
    return {
        name: [t for t in DEFAULT_NA_TOKENS if t not in exclusions.get(name, [])]
        for name in header
    }


def _resolve_sheet(sheet: str | int, available: list[SheetInfo]) -> SheetInfo:
    """The table the caller named, by name or by position.

    Raises rather than falling back to the first one. A caller who asked for
    "Q3 Actuals" and silently received "Instructions" would have no way to tell,
    and every number after that would be attributed to the wrong table.
    """
    text = str(sheet).strip()
    if isinstance(sheet, int) or text.isdigit():
        index = int(text)
        if 0 <= index < len(available):
            return available[index]
    for info in available:
        if info.name == text:
            return info
    folded = text.casefold()
    for info in available:
        if info.name.strip().casefold() == folded:
            return info
    names = ", ".join(f"'{i.name}'" for i in available)
    raise IngestError(
        FILE_ERROR,
        f"There is no sheet called '{sheet}' in this file.",
        hint=f"This file has: {names}." if names else None,
    )


def _read_csv(path: Path, sheet: str | int | None = None) -> tuple[pd.DataFrame, IngestReport]:
    report = probe(path)
    # Exported "reports" often stack several tables in one file, separated by
    # blank lines. Read whole, they collapse into one nonsense frame — so find
    # them, and either read the one that was asked for or say they are there.
    blocks = _scan_blocks(path, report)
    chosen: SheetInfo | None = None
    if sheet is not None and sheet != "":
        chosen = _resolve_sheet(sheet, blocks or [SheetInfo(path.stem, 0, "table")])
        if chosen.kind != "block":
            chosen = None  # names the file itself: read all of it, as before

    if chosen is not None:
        header, header_row = chosen.columns, chosen.header_offset
    else:
        header_row = report.header_row
        # The probe already parsed the header, so the column cap is free — no
        # second read of the file to count them.
        try:
            with open(path, "rb") as fh:
                sample = _whole_lines(fh.read(SAMPLE_BYTES)).decode(
                    report.encoding, errors="replace"
                )
            rows = list(
                csv.reader(sample.splitlines()[:SAMPLE_ROWS], delimiter=report.delimiter or ",")
            )
            header = [c.strip() for c in rows[header_row]] if rows else []
        except (OSError, csv.Error, IndexError):
            header = []
    _check_columns(len(header))

    kwargs: dict[str, Any] = {
        "encoding": report.encoding,
        "sep": report.delimiter,
        "quotechar": report.quotechar,
        # skiprows + header=0, never header=N. pandas counts `header` *after*
        # dropping blank lines, so a blank spacer above the table shifts the index
        # and the first data row is silently promoted to column names. `skiprows`
        # counts raw lines, which is what the probe measured.
        "skiprows": header_row,
        "header": 0,
        "decimal": report.decimal,
        "keep_default_na": False,
        "na_values": _na_argument(header, report.na_exclusions),
    }
    if report.thousands is not None:
        kwargs["thousands"] = report.thousands
    if chosen is not None and chosen.row_span is not None:
        kwargs["nrows"] = chosen.row_span
    try:
        df = pd.read_csv(path, **kwargs)
    except Exception as exc:
        if chosen is None and len(blocks) > 1:
            # We know exactly why this failed, so say that instead of passing on
            # "Expected 2 fields in line 9, saw 3" — which is true, unreadable,
            # and gives the user nothing to do about it.
            names = ", ".join(f"'{b.name}'" for b in blocks)
            raise IngestError(
                FILE_ERROR,
                f"This file holds {len(blocks)} separate tables ({names}) stacked one "
                "after another, so it cannot be read as a single table.",
                hint="Upload one table at a time, or pick which table to use.",
            ) from exc
        raise IngestError(FILE_ERROR, f"Could not read CSV: {exc}") from exc
    _check_frame(df)

    if len(blocks) < 2:
        return df, report
    assumptions = list(report.assumptions)
    # Only when nobody chose. Having picked a table, being told the others exist
    # on every question afterwards is nagging, not disclosure.
    if chosen is None:
        assumptions.append(MULTIPLE_TABLES)
    else:
        # The rows above a chosen block are the blocks before it, not furniture
        # this module guessed at. Reporting an offset of 7 as "7 rows skipped"
        # would be arithmetic about a decision the user made themselves.
        assumptions = [a for a in assumptions if a != HEADER_ROW]
    return df, replace(
        report,
        header_row=header_row,
        sheet=chosen.name if chosen else None,
        other_sheets=[b.name for b in blocks if chosen is None or b.name != chosen.name],
        assumptions=assumptions,
    )


def _read_excel(path: Path, sheet: str | int | None = None) -> tuple[pd.DataFrame, IngestReport]:
    with _open_workbook(path) as book:  # see _excel_sheets on why this is closed
        sheets = _workbook_sheets(book)
        if not sheets:
            raise IngestError(FILE_ERROR, "This workbook has no sheets in it.")

        asked = sheet is not None and sheet != ""
        if sheet is not None and sheet != "":
            chosen = _resolve_sheet(sheet, sheets)
        else:
            # The first sheet with anything in it, not simply the first. A blank
            # "Sheet1" in front of the data used to fail the whole upload as "no
            # data rows", a dead end for a workbook that plainly has some.
            chosen = next((s for s in sheets if not s.is_empty), sheets[0])
        if chosen.is_empty:
            raise IngestError(
                FILE_ERROR,
                f"Sheet '{chosen.name}' is empty.",
                hint="Pick a sheet that has data in it.",
            )
        _check_columns(len(chosen.columns))
        try:
            df = book.parse(chosen.name, skiprows=chosen.header_offset, header=0)
        except Exception as exc:
            raise IngestError(
                FILE_ERROR, f"Could not read sheet '{chosen.name}': {exc}"
            ) from exc
    _check_frame(df)

    others = [s.name for s in sheets if s.name != chosen.name]
    assumptions: list[str] = []
    if chosen.header_offset > 0:
        assumptions.append(HEADER_ROW)
    # A workbook's other sheets are data the user may have meant and did not get.
    # Silence here reads as "your file had one table in it" — but once they have
    # named a sheet, they know, and repeating it is noise.
    if others and not asked:
        assumptions.append(EXTRA_SHEETS)
    return df, IngestReport(
        format="excel",
        sheet=chosen.name,
        other_sheets=others,
        header_row=chosen.header_offset,
        assumptions=assumptions,
    )


# Parquet and JSON hold exactly one table, so `sheet` has nothing to select and
# is accepted only to keep one signature across the readers.
def _read_parquet(path: Path, sheet: str | int | None = None) -> tuple[pd.DataFrame, IngestReport]:
    try:
        import pyarrow.parquet as pq

        meta = pq.ParquetFile(path).metadata
    except Exception as exc:
        raise IngestError(FILE_ERROR, f"Could not read Parquet file: {exc}") from exc
    _check_columns(meta.num_columns)
    if meta.num_rows > MAX_ROWS:
        raise IngestError(
            RESOURCE_LIMIT,
            f"Dataset has {meta.num_rows} rows; the limit is {MAX_ROWS}.",
        )
    try:
        df = pd.read_parquet(path)
    except Exception as exc:
        raise IngestError(FILE_ERROR, f"Could not read Parquet file: {exc}") from exc
    _check_frame(df)
    # Parquet carries its own schema, so nothing here was guessed.
    return df, IngestReport(format="parquet")


def _read_json(path: Path, sheet: str | int | None = None) -> tuple[pd.DataFrame, IngestReport]:
    lines = path.suffix.lower() == ".jsonl"
    try:
        df = pd.read_json(path, lines=lines)
    except Exception as exc:
        raise IngestError(
            FILE_ERROR,
            f"Could not read JSON: {exc}",
            hint="Only a flat array of records (or one record per line) can be tabulated.",
        ) from exc
    if any(df[c].map(lambda v: isinstance(v, (list, dict))).any() for c in df.columns):
        raise IngestError(
            FILE_ERROR,
            "This JSON has nested objects or arrays in it, which have no table form.",
            hint="Flatten the records before uploading.",
        )
    _check_columns(len(df.columns))
    _check_frame(df)
    return df, IngestReport(format="json")


_READERS = {
    ".csv": _read_csv,
    ".tsv": _read_csv,
    ".txt": _read_csv,
    ".xlsx": _read_excel,
    ".xlsm": _read_excel,
    ".parquet": _read_parquet,
    ".json": _read_json,
    ".jsonl": _read_json,
}


def _reader_for(path: Path):
    reader = _READERS.get(path.suffix.lower())
    if reader is not None:
        return reader
    if path.suffix.lower() == ".xls":
        raise IngestError(
            FILE_ERROR,
            "The legacy .xls format is not supported.",
            hint="Re-save the workbook as .xlsx, or export the sheet as CSV.",
        )
    # No suffix, or an unfamiliar one: a great many exports are delimited text
    # under some other name, so try to read it as one rather than refusing on
    # the strength of a file extension.
    return _read_csv


def read_table(
    path: Path, sheet: str | int | None = None
) -> tuple[pd.DataFrame, IngestReport]:
    """Read `path` into a frame, with the decisions that produced it.

    ``sheet`` names one of the tables ``list_sheets`` found — a worksheet, or a
    block within a delimited file — by name or by position. Omitted, the whole
    file is read as one table exactly as before, and the report says so when
    that meant leaving something out.

    Raises ``IngestError`` — the caller maps ``.code`` onto the error taxonomy.
    """
    _check_size(path)
    return _reader_for(path)(path, sheet)


def list_sheets(path: Path) -> list[SheetInfo]:
    """The separate tables inside `path`, in the order they appear.

    Always at least one entry, so a caller never has to special-case "this format
    has no sheets" — for Parquet and JSON the file simply *is* the table.

    Enumeration is deliberately cheap: sheet names, the header row, and a row
    estimate, without reading any sheet's data. A picker has to open before the
    user has decided what they want, so paying to parse twelve sheets to show a
    list of twelve names would make choosing slower than not offering the choice.
    """
    _check_size(path)
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        return _excel_sheets(path)
    if suffix in (".parquet", ".json", ".jsonl"):
        return [SheetInfo(name=path.stem, index=0, kind="table")]
    if suffix == ".xls":
        _reader_for(path)  # raises the "re-save as .xlsx" error, with its hint
    blocks = _scan_blocks(path, probe(path))
    if len(blocks) > 1:
        return blocks
    # One table, so there is nothing to choose — but keep the columns that were
    # found, because a caller showing "1 table, 11 columns" needs them too.
    columns = blocks[0].columns if blocks else []
    return [SheetInfo(name=path.stem, index=0, kind="table", columns=columns)]


def sample_lines(path: Path, encoding: str, limit: int = SAMPLE_ROWS) -> list[str]:
    """First `limit` decoded lines — for callers that want to show the raw file."""
    with open(path, "rb") as fh:
        raw = _whole_lines(fh.read(SAMPLE_BYTES))
    return io.StringIO(raw.decode(encoding, errors="replace")).read().splitlines()[:limit]
