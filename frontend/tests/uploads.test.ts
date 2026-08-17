/**
 * Which files the app accepts, and what name it sends them under.
 *
 * The backend picks its reader from the **file extension**
 * (`ingest.py:_READERS`), so both halves matter and neither is cosmetic. The UI
 * used to accept only `.csv` while the engine read eight formats, and — worse —
 * renamed every upload to `.csv`, which would have handed binary workbook bytes
 * to the CSV parser had anything else ever got through.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  ACCEPTED_EXTENSIONS,
  UPLOAD_ACCEPT,
  extensionOf,
  isAcceptedFile,
  rejectionMessage,
  shouldInspect,
  uploadFilename,
} from '../src/lib/uploads.ts';

const file = (name: string, type = '') => new File(['x'], name, { type });

/** A File that claims to be `bytes` long, without allocating that many. */
function sized(name: string, bytes: number): File {
  return Object.defineProperty(new File([''], name), 'size', { value: bytes });
}

// --- what the engine can read ------------------------------------------------

test('every format the backend has a reader for is accepted', () => {
  // Mirrors ingest.py:_READERS. If that map grows, this fails until both move.
  for (const ext of ['.csv', '.tsv', '.txt', '.xlsx', '.xlsm', '.parquet', '.json', '.jsonl']) {
    assert.ok(
      (ACCEPTED_EXTENSIONS as readonly string[]).includes(ext),
      `${ext} is readable by the backend but not offered by the UI`,
    );
    assert.equal(isAcceptedFile(file(`data${ext}`)), true, ext);
  }
});

test('case does not matter', () => {
  assert.equal(isAcceptedFile(file('REPORT.XLSX')), true);
  assert.equal(isAcceptedFile(file('Data.Csv')), true);
});

test('a file with no usable type still passes on its extension', () => {
  // Windows reports an empty MIME type for .parquet and .jsonl, so a
  // type-based check would reject them.
  assert.equal(isAcceptedFile(file('events.jsonl', '')), true);
  assert.equal(isAcceptedFile(file('facts.parquet', '')), true);
});

test('unsupported files are rejected', () => {
  for (const name of ['notes.pdf', 'photo.png', 'archive.zip', 'noextension']) {
    assert.equal(isAcceptedFile(file(name)), false, name);
  }
});

test('the accept attribute offers every extension', () => {
  for (const ext of ACCEPTED_EXTENSIONS) {
    assert.ok(UPLOAD_ACCEPT.includes(ext), `${ext} missing from accept`);
  }
});

// --- rejection copy ----------------------------------------------------------

test('legacy .xls gets its own message with a way forward', () => {
  // The format people most often have and the engine deliberately will not
  // read. "Unsupported" alone leaves them with no next step.
  const msg = rejectionMessage(file('budget.xls'));
  assert.match(msg, /\.xlsx/);
  assert.match(msg, /budget\.xls/);
});

test('a rejection names the file, so a multi-file drop is diagnosable', () => {
  assert.match(rejectionMessage(file('holiday.png')), /holiday\.png/);
});

// --- the name we upload under ------------------------------------------------

test('the real extension survives a rename', () => {
  // The bug this exists to prevent: an .xlsx sent as .csv is read as text.
  assert.equal(uploadFilename('Q3 sales', 'export.xlsx'), 'Q3 sales.xlsx');
  assert.equal(uploadFilename('events', 'raw.jsonl'), 'events.jsonl');
  assert.equal(uploadFilename('facts', 'part-0.parquet'), 'facts.parquet');
});

test('a typed name that already has the right extension is not doubled', () => {
  assert.equal(uploadFilename('sales.csv', 'sales.csv'), 'sales.csv');
  assert.equal(uploadFilename('report.xlsx', 'report.xlsx'), 'report.xlsx');
});

test('a blank name falls back rather than producing a bare extension', () => {
  assert.equal(uploadFilename('   ', 'source.tsv'), 'dataset.tsv');
});

test('a source with no extension defaults to .csv', () => {
  // The backend also falls back to its delimited-text reader for unknown
  // suffixes, so this stays consistent with what it will actually attempt.
  assert.equal(uploadFilename('mydata', 'export'), 'mydata.csv');
});

test('extensionOf handles dots in the stem', () => {
  assert.equal(extensionOf('2026.q3.sales.csv'), '.csv');
  assert.equal(extensionOf('noextension'), '');
});

// --- when to ask what tables are in the file ---------------------------------
//
// Inspecting sends the file twice: once to ask, once to upload what was chosen.
// So the question is not "could this have several tables" but "is finding out
// worth another copy over the wire".

test('a workbook is always inspected, however big', () => {
  // Several sheets is the norm for a workbook, and reading the wrong one is
  // silent — no error, just numbers from a table nobody meant.
  assert.equal(shouldInspect(sized('quarter.xlsx', 40 * 1024 * 1024)), true);
  assert.equal(shouldInspect(sized('macro.xlsm', 1024)), true);
});

test('formats that hold exactly one table are never inspected', () => {
  // There is nothing to pick, so a round trip could only ever confirm that.
  assert.equal(shouldInspect(sized('facts.parquet', 1024)), false);
  assert.equal(shouldInspect(sized('events.jsonl', 1024)), false);
  assert.equal(shouldInspect(sized('records.json', 1024)), false);
});

test('a small delimited file is inspected, a large one is assumed to be one table', () => {
  // Stacked tables are a report-export habit, and those files are small. At
  // 40 MB the odds do not justify sending it twice — and the upload discloses
  // the stacking anyway if it turns out to be there.
  assert.equal(shouldInspect(sized('report.csv', 200 * 1024)), true);
  assert.equal(shouldInspect(sized('events.csv', 40 * 1024 * 1024)), false);
});
