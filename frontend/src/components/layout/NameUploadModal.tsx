import { useEffect, useMemo, useRef, useState } from 'react';
import { FileSpreadsheet, Loader2, X } from 'lucide-react';
import { useFocusTrap } from '../../hooks/useFocusTrap';
import { shouldInspect, uploadFilename } from '../../lib/uploads';
import { inspectFile, type SheetInfo } from '../../lib/datasets';
import './SaveDashboardModal.css';
import './NameUploadModal.css';

interface NameUploadModalProps {
  /** Original file the user picked (used for size hint / default name). */
  file: File;
  onCancel: () => void;
  /** `sheets` is empty when the file holds a single table. */
  onConfirm: (displayName: string, sheets: string[]) => void;
}

function stemFromFilename(name: string): string {
  return name.replace(/\.[^./\\]+$/, '').trim();
}

function describe(sheet: SheetInfo): string {
  if (sheet.is_empty) return 'empty';
  const columns = sheet.columns.length ? `${sheet.columns.length} columns` : '';
  const rows = sheet.approx_rows === null ? '' : `~${sheet.approx_rows.toLocaleString()} rows`;
  return [rows, columns].filter(Boolean).join(' · ');
}

export function NameUploadModal({ file, onCancel, onConfirm }: NameUploadModalProps) {
  const [name, setName] = useState(stemFromFilename(file.name) || 'dataset');
  const [sheets, setSheets] = useState<SheetInfo[] | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [looking, setLooking] = useState(shouldInspect(file));
  const overlayRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const trimmed = name.trim();

  // The trap focuses the field; this selects the default name in it.
  useFocusTrap(dialogRef, true, inputRef);
  useEffect(() => {
    inputRef.current?.select();
  }, []);

  // Ask what tables are in the file while the user is typing a name — the one
  // moment in this flow when they are busy anyway, so the round trip is free.
  useEffect(() => {
    if (!shouldInspect(file)) return;
    let live = true;
    inspectFile(file)
      .then((result) => {
        if (!live) return;
        if (result.needs_choice) {
          setSheets(result.sheets);
          const first = result.sheets.find((s) => !s.is_empty);
          setSelected(first ? [first.name] : []);
        }
      })
      // A failed inspection must not block the upload: the file is very likely
      // one plain table, and the upload itself reports anything it had to
      // assume. Losing the picker is a smaller harm than losing the upload.
      .catch(() => undefined)
      .finally(() => {
        if (live) setLooking(false);
      });
    return () => {
      live = false;
    };
  }, [file]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onCancel]);

  const handleOverlayClick = (e: React.MouseEvent) => {
    if (e.target === overlayRef.current) onCancel();
  };

  const usable = useMemo(() => (sheets ?? []).filter((s) => !s.is_empty), [sheets]);
  const allChosen = usable.length > 0 && selected.length === usable.length;
  const blocked = !trimmed || (sheets !== null && selected.length === 0);

  const toggle = (sheetName: string) => {
    setSelected((current) =>
      current.includes(sheetName)
        ? current.filter((n) => n !== sheetName)
        : // Kept in file order, so "the first one" means the first in the
          // workbook rather than whichever was clicked first.
          usable.filter((s) => s.name === sheetName || current.includes(s.name)).map((s) => s.name),
    );
  };

  const submit = () => {
    if (!blocked) onConfirm(trimmed, selected);
  };

  const label = () => {
    if (looking) return 'Upload';
    if (selected.length > 1) return `Upload ${selected.length} sheets`;
    return 'Upload';
  };

  return (
    <div className="dashboard-modal-overlay" ref={overlayRef} onClick={handleOverlayClick}>
      <div
        className="dashboard-modal save-dashboard-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="name-upload-title"
        ref={dialogRef}
      >
        <div className="dashboard-modal-header">
          <h2 id="name-upload-title">
            <FileSpreadsheet size={18} />
            Name this dataset
          </h2>
          <button className="modal-close-btn" onClick={onCancel} aria-label="Close">
            <X size={20} />
          </button>
        </div>

        <div className="dashboard-modal-body">
          <label className="save-dashboard-label" htmlFor="name-upload-input">
            Dataset name
          </label>
          <input
            id="name-upload-input"
            ref={inputRef}
            className="save-dashboard-input"
            value={name}
            maxLength={120}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') submit();
            }}
            placeholder="e.g. Sales Q1"
          />
          <p className="save-dashboard-hint">
            This name is saved with the file and shown as the board title
            (AutoViz AI / {trimmed || '…'}).
          </p>

          {looking && (
            <p className="sheet-picker-looking">
              <Loader2 size={14} className="sheet-picker-spin" />
              Checking what’s in this file…
            </p>
          )}

          {sheets && (
            <div className="sheet-picker">
              <div className="sheet-picker-head">
                <span className="save-dashboard-label">
                  This file has {sheets.length} tables in it
                </span>
                {usable.length > 1 && (
                  <button
                    type="button"
                    className="sheet-picker-all"
                    onClick={() => setSelected(allChosen ? [] : usable.map((s) => s.name))}
                  >
                    {allChosen ? 'Clear' : 'Select all'}
                  </button>
                )}
              </div>

              <ul className="sheet-picker-list">
                {sheets.map((sheet) => (
                  <li key={sheet.name}>
                    <label
                      className={`sheet-picker-item${sheet.is_empty ? ' is-empty' : ''}`}
                      title={sheet.columns.join(', ')}
                    >
                      <input
                        type="checkbox"
                        checked={selected.includes(sheet.name)}
                        disabled={sheet.is_empty}
                        onChange={() => toggle(sheet.name)}
                      />
                      <span className="sheet-picker-name">{sheet.name}</span>
                      <span className="sheet-picker-meta">{describe(sheet)}</span>
                    </label>
                  </li>
                ))}
              </ul>

              <p className="save-dashboard-hint">
                {selected.length > 1
                  ? 'Each becomes its own dataset. The first opens on this board; the rest are in Browse.'
                  : 'Each sheet becomes its own dataset. Pick more than one to import several.'}
              </p>
            </div>
          )}
        </div>

        <div className="dashboard-modal-footer save-dashboard-footer">
          <button type="button" className="btn-cancel" onClick={onCancel}>
            Cancel
          </button>
          <button type="button" className="btn-load" onClick={submit} disabled={blocked}>
            {label()}
          </button>
        </div>
      </div>
    </div>
  );
}

/** Build the File that will be uploaded / stored under this display name.
 *
 * Keeps the source extension. The backend chooses its reader from it, so
 * renaming an `.xlsx` to `.csv` hands workbook bytes to the CSV parser.
 */
export function namedCsvFile(source: File, displayName: string): File {
  return new File([source], uploadFilename(displayName, source.name), {
    type: source.type,
    lastModified: source.lastModified,
  });
}
