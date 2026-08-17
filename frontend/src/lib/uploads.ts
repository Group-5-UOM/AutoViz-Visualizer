/**
 * Which files AutoViz will accept, in one place.
 *
 * This list has to match `backend/src/autoviz/services/ingest.py:_READERS`,
 * which picks its reader **by file extension**. That coupling is the reason this
 * module exists rather than an `accept=".csv"` repeated in four components: the
 * lists drifted, the UI offered only CSV, and the eight formats the engine can
 * actually read were unreachable from the app.
 *
 * The extension is not cosmetic. Renaming an `.xlsx` to `.csv` does not make it
 * one — the backend would hand binary workbook bytes to the CSV reader and fail
 * with something unhelpful. So the upload path must preserve whatever the user
 * actually chose.
 */

/** Extensions the backend has a reader for. Keep in step with `_READERS`. */
export const ACCEPTED_EXTENSIONS = [
  '.csv',
  '.tsv',
  '.txt',
  '.xlsx',
  '.xlsm',
  '.parquet',
  '.json',
  '.jsonl',
] as const;

/**
 * The `accept` attribute for a file input.
 *
 * Extensions *and* MIME types: browsers vary on which they honour, and Windows
 * in particular reports an empty `type` for `.parquet` and `.jsonl`, so an
 * extension-only list is what actually keeps those selectable.
 */
export const UPLOAD_ACCEPT = [
  ...ACCEPTED_EXTENSIONS,
  'text/csv',
  'text/tab-separated-values',
  'text/plain',
  'application/json',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/vnd.ms-excel.sheet.macroEnabled.12',
].join(',');

/** Human-facing list, e.g. for a drop zone: "CSV, TSV, Excel, Parquet, JSON". */
export const ACCEPTED_LABEL = 'CSV, TSV, TXT, Excel, Parquet or JSON';

/** The file's extension including the dot, lower-cased. '' when it has none. */
export function extensionOf(filename: string): string {
  const dot = filename.lastIndexOf('.');
  return dot === -1 ? '' : filename.slice(dot).toLowerCase();
}

/** Can AutoViz read this file? */
export function isAcceptedFile(file: File): boolean {
  return (ACCEPTED_EXTENSIONS as readonly string[]).includes(extensionOf(file.name));
}

/**
 * A rejection message that names the file, so the user can see which one of a
 * multi-file drop was the problem.
 */
export function rejectionMessage(file: File): string {
  const ext = extensionOf(file.name);
  if (ext === '.xls') {
    // Worth its own message: .xls is the one format people most often have and
    // the engine deliberately does not read, and "unsupported" alone leaves
    // them with no next step.
    return `${file.name} is a legacy .xls workbook. Re-save it as .xlsx and try again.`;
  }
  return `${file.name} is not a supported file. Upload ${ACCEPTED_LABEL}.`;
}

/**
 * The filename to send for `file`, given a display name the user typed.
 *
 * Preserves the real extension — the backend chooses its reader from it, so a
 * `.xlsx` renamed to `.csv` is read as text and fails. When the typed name
 * already carries the right extension it is left alone.
 */
export function uploadFilename(displayName: string, original: string): string {
  const ext = extensionOf(original) || '.csv';
  const typed = displayName.trim();
  const stem = (extensionOf(typed) === ext ? typed.slice(0, -ext.length) : typed).trim();
  return `${stem || 'dataset'}${ext}`;
}
