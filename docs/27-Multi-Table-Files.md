# 27 — Files That Hold More Than One Table

## 1. The problem

A file is not a table, and AutoViz was built as though it were.

Two shapes break that assumption, and both are ordinary rather than exotic:

**A workbook has sheets.** `_read_excel` read `sheet_names[0]` and dropped the
rest. A three-sheet quarterly workbook produced one dataset from whichever tab
happened to be leftmost — often a cover sheet or a set of notes. An advisory said
so, which is better than nothing, but the user's only recourse was to go back to
Excel, split the workbook by hand, and upload again.

**An exported report stacks tables in one CSV**, separated by blank lines, each
under its own title:

```
Q3 Revenue

region,revenue
North,100
South,250

Q3 Units

sku,units,price
a,3,1.5
```

Read as a single table this either fails with `Error tokenizing data. C error:
Expected 2 fields in line 9, saw 3` — true, unreadable, and giving the user
nothing to do — or, when the widths happen to match, *succeeds*, and produces a
frame with another table's header sitting in it as a data row. The second
outcome is the dangerous one: every number computed afterwards is wrong and
nothing on screen says so.

## 2. One concept for both

`ingest.SheetInfo` describes one table inside one file, with a `kind` that says
which shape it came from:

| kind | what it is | where from |
|---|---|---|
| `sheet` | a worksheet | `.xlsx`, `.xlsm` |
| `block` | a run of rows between blank lines, with its own header | `.csv`, `.tsv`, `.txt` |
| `table` | the file *is* the table | `.parquet`, `.json`, `.jsonl` |

`list_sheets(path)` returns them, always at least one, so no caller has to
special-case "this format has no sheets". `read_table(path, sheet=...)` reads the
one that was named — by name or by position.

Enumeration is deliberately cheap: sheet names, the header row, a row estimate,
and no sheet's data. A picker has to be drawn before the user has decided what
they want, so paying to parse twelve sheets in order to display twelve names
would make choosing slower than not offering the choice at all.

## 3. Detecting a block without breaking a table

This is the part that can do damage, so the rules are conservative in one
specific direction.

**Splitting one table in half is far worse than leaving two joined.** A wrongly
joined pair produces visible nonsense — a header row in the data, a column of
mixed types. A wrongly split table silently loses its second half, and a row
count that is 40% short looks exactly like a row count that is right. So every
rule below is tuned to under-split.

A candidate block must be a run of at least two non-blank rows, with a modal
field count of at least two, whose header row is *entirely* non-numeric labels.
A run failing that last test is absorbed into the block above it rather than
orphaned into one of its own — which is what keeps a stray blank line inside a
table from cutting it in two.

Three further guards:

- **Parsed with `csv.reader`, not `str.split`.** A quoted field containing a line
  break would otherwise invent a boundary.
- **A quoted line break aborts detection entirely.** Row numbers only track raw
  line numbers while no field spans a line, and `skiprows` counts lines. Offsets
  that cannot be trusted are not offered: the file is reported as one table.
- **Streamed, not materialised.** Only the first two rows of each run are kept,
  so scanning a 50 MB file costs no meaningful memory.

A one-line run above a table is read as its **title** and becomes the block's
name — "Q3 Revenue" rather than "Table 1". Those lines are exactly the furniture
that made these files unreadable, and they turn out to be the best labels
available for choosing between them.

## 4. Behaviour, and what changed

| Situation | Before | Now |
|---|---|---|
| Workbook, no choice made | sheet 0, even when blank | first sheet **with data**; others disclosed |
| Workbook, sheet named | not possible | that sheet; no advisory, since they chose |
| Workbook with a title row above the table | columns called `Unnamed: 1` | header detected, `header_row` disclosed |
| Stacked CSV, unequal widths | pandas tokenizer error | refusal naming the tables and how to proceed |
| Stacked CSV, equal widths | silently wrong frame | read, plus a `multiple_tables` advisory |
| Plain CSV | unchanged | unchanged — `assumptions == []` |

The last row is the one under the most test pressure. Disclosure that fires on
every upload is noise, and noise is how a real disclosure gets skipped.

### A latent bug this surfaced

`pd.ExcelFile` was never closed. On Linux the staged upload was unlinked anyway
and the leaked handle was invisible; on Windows `unlink` fails outright, which is
how it was found. Every workbook upload leaked a file descriptor. Fixed by
holding the workbook in a `with` block.

## 5. Interfaces

### HTTP

```
POST /datasets/inspect   multipart  -> {sheets: [...], needs_choice: bool}
POST /datasets/upload    multipart + optional `sheets`
```

`sheets` is a **JSON array** of names, or `"all"`, or absent. A JSON array rather
than a comma-separated list because `Revenue, net` is an entirely ordinary thing
to call a worksheet.

Each chosen sheet becomes a **dataset of its own**. Sheets in one workbook rarely
share a schema, so merging them would be a join nobody asked for — and the join
machinery already exists for when they do want one.

The response's top level always describes the *first* dataset, so a client
written before any of this keeps working unchanged; `datasets` and `skipped` are
additive. One unreadable sheet does not cost the user the other eleven: it lands
in `skipped` and the rest import. Only when *every* chosen sheet fails is the
call an error — and when exactly one was asked for, the reader's own error is
returned untouched, because its hint is what lists the names that do exist.

`/inspect` keeps nothing. The bytes are staged, read for structure alone, and
deleted on the way out.

### MCP

`register_dataset(file_ref, sheet=None)` and a new `list_sheets(file_ref)`.

They ship together in every profile, for the same reason `answer_clarification`
ships with `analyze`: the `sheet` argument is unusable without a way to learn the
names, and a host that cannot see a workbook's other sheets will confidently
analyse the wrong one.

### UI

The picker lives **inside the naming modal**, not in a second dialog. The user is
already answering "what is this?"; "which part of it?" is the same question, and
a separate step would make it feel like a detour. Inspection runs while they type
a name — the one moment in the flow when they are busy anyway, so the round trip
is free.

`shouldInspect` decides when to ask, because inspecting sends the file twice:

- **workbooks, always** — several sheets is the norm and picking wrong is silent;
- **delimited text under 8 MB** — stacked tables are a report-export habit and
  those files are small;
- **never for Parquet/JSON** — there is nothing to pick.

A failed inspection does not block the upload. The file is very likely one plain
table, and the upload discloses whatever it had to assume. Losing the picker is a
smaller harm than losing the upload.

Empty sheets are listed and greyed out rather than hidden: a sheet missing from
the list reads as a bug, whereas an empty one greyed out explains itself.

## 6. Limits

`AUTOVIZ_MAX_SHEETS` (default 20) caps sheets per upload — a workbook with
hundreds of tabs is a database export, and importing it wholesale would bury the
real data in the dataset list. The existing byte, row, and column ceilings apply
per sheet, unchanged.

## 7. Tests

`backend/tests/test_sheets.py` (20) and `backend/tests/test_api_sheets.py` (11),
in three groups: **enumeration**, **selection**, and **restraint** — the last
being the important half, and the one that would catch this feature eating data.

Backend total: 864 → 895. Frontend: 47 → 50.

## 8. Not done

- **Joining sheets on import.** Two sheets that *do* share a key are a common
  case, and the plan grammar already supports joins. Deliberately left out:
  guessing the key is a different kind of decision from reading a file, and one
  the planner should be making with the user in the loop.
- **Named ranges and Excel tables.** A workbook can define these independently of
  sheets; openpyxl exposes them. No evidence yet that anyone's files need it.
- **`.xls`.** Still refused, with the same "re-save as .xlsx" hint.
