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
from dataclasses import dataclass, field
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

_TWO_LETTER_CODE = re.compile(r"^[A-Z]{2}$")
# 1.234.567,89 (grouped) or 1234,89 / 12,5 (plain) — the European convention.
_EU_DECIMAL = re.compile(r"^-?\d{1,3}(?:\.\d{3})+,\d+$|^-?\d+,\d{1,2}$")
# Any slash/dash date; which component is the day is the question, not whether it
# is a date at all.
_SLASH_DATE = re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})$")

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


def _read_csv(path: Path) -> tuple[pd.DataFrame, IngestReport]:
    report = probe(path)
    # The probe already parsed the header, so the column cap is free — no second
    # read of the file to count them.
    try:
        with open(path, "rb") as fh:
            sample = _whole_lines(fh.read(SAMPLE_BYTES)).decode(
                report.encoding, errors="replace"
            )
        rows = list(
            csv.reader(sample.splitlines()[:SAMPLE_ROWS], delimiter=report.delimiter or ",")
        )
        header = [c.strip() for c in rows[report.header_row]] if rows else []
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
        "skiprows": report.header_row,
        "header": 0,
        "decimal": report.decimal,
        "keep_default_na": False,
        "na_values": _na_argument(header, report.na_exclusions),
    }
    if report.thousands is not None:
        kwargs["thousands"] = report.thousands
    try:
        df = pd.read_csv(path, **kwargs)
    except Exception as exc:
        raise IngestError(FILE_ERROR, f"Could not read CSV: {exc}") from exc
    _check_frame(df)
    return df, report


def _read_excel(path: Path) -> tuple[pd.DataFrame, IngestReport]:
    try:
        book = pd.ExcelFile(path)
        sheets = list(book.sheet_names)
        head = book.parse(sheets[0], nrows=0)
    except ImportError as exc:  # openpyxl missing
        raise IngestError(
            FILE_ERROR,
            "Reading .xlsx files needs the openpyxl package.",
            hint="Install it, or export the sheet as CSV.",
        ) from exc
    except Exception as exc:
        raise IngestError(FILE_ERROR, f"Could not read workbook: {exc}") from exc
    _check_columns(len(head.columns))
    try:
        df = book.parse(sheets[0])
    except Exception as exc:
        raise IngestError(FILE_ERROR, f"Could not read workbook: {exc}") from exc
    _check_frame(df)
    return df, IngestReport(
        format="excel",
        sheet=sheets[0],
        other_sheets=sheets[1:],
        # A workbook's other sheets are data the user may have meant and did not
        # get. Silence here reads as "your file had one table in it".
        assumptions=[EXTRA_SHEETS] if len(sheets) > 1 else [],
    )


def _read_parquet(path: Path) -> tuple[pd.DataFrame, IngestReport]:
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


def _read_json(path: Path) -> tuple[pd.DataFrame, IngestReport]:
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


def read_table(path: Path) -> tuple[pd.DataFrame, IngestReport]:
    """Read `path` into a frame, with the decisions that produced it.

    Raises ``IngestError`` — the caller maps ``.code`` onto the error taxonomy.
    """
    _check_size(path)
    reader = _READERS.get(path.suffix.lower())
    if reader is None:
        if path.suffix.lower() == ".xls":
            raise IngestError(
                FILE_ERROR,
                "The legacy .xls format is not supported.",
                hint="Re-save the workbook as .xlsx, or export the sheet as CSV.",
            )
        # No suffix, or an unfamiliar one: a great many exports are delimited text
        # under some other name, so try to read it as one rather than refusing on
        # the strength of a file extension.
        reader = _read_csv
    return reader(path)


def sample_lines(path: Path, encoding: str, limit: int = SAMPLE_ROWS) -> list[str]:
    """First `limit` decoded lines — for callers that want to show the raw file."""
    with open(path, "rb") as fh:
        raw = _whole_lines(fh.read(SAMPLE_BYTES))
    return io.StringIO(raw.decode(encoding, errors="replace")).read().splitlines()[:limit]
