import { useEffect, useMemo, useState } from 'react';
import {
  Download,
  FileSpreadsheet,
  Plus,
  Redo2,
  Save,
  Trash2,
  Undo2,
  X,
} from 'lucide-react';
import { ApiError } from '../../lib/api';
import { previewDataset } from '../../lib/datasets';
import './DatasetSheet.css';

interface DatasetSheetProps {
  datasetId: string;
  fileName: string;
  rowCount: number;
  columnCount: number;
  onClose: () => void;
  onSaved: (file: File) => void | Promise<void>;
}

type CellMatrix = string[][];

function escapeCsvCell(value: string): string {
  if (/[",\n\r]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

function toCsv(columns: string[], rows: CellMatrix): string {
  const lines = [
    columns.map(escapeCsvCell).join(','),
    ...rows.map((row) =>
      columns.map((_, i) => escapeCsvCell(row[i] ?? '')).join(','),
    ),
  ];
  return `${lines.join('\n')}\n`;
}

function rowsFromPreview(
  previewRows: Record<string, unknown>[],
  columns: string[],
): CellMatrix {
  return previewRows.map((row) =>
    columns.map((col) => {
      const value = row[col];
      if (value === null || value === undefined) return '';
      return String(value);
    }),
  );
}

export function DatasetSheet({
  datasetId,
  fileName,
  rowCount,
  columnCount,
  onClose,
  onSaved,
}: DatasetSheetProps) {
  const [columns, setColumns] = useState<string[]>([]);
  const [rows, setRows] = useState<CellMatrix>([]);
  const [baseline, setBaseline] = useState<CellMatrix>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedRow, setSelectedRow] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const limit = Math.max(rowCount || 100, 100);
    void previewDataset(datasetId, limit)
      .then((res) => {
        if (cancelled) return;
        const cols =
          res.rows.length > 0
            ? Object.keys(res.rows[0])
            : Array.from({ length: columnCount }, (_, i) => `col_${i + 1}`);
        const matrix = rowsFromPreview(res.rows, cols);
        setColumns(cols);
        setRows(matrix);
        setBaseline(matrix.map((r) => [...r]));
        setDirty(false);
        setSelectedRow(null);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(
          err instanceof ApiError
            ? err.message
            : err instanceof Error
              ? err.message
              : 'Could not load dataset rows.',
        );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [datasetId, rowCount, columnCount]);

  const truncated = useMemo(
    () => rowCount > 0 && rows.length > 0 && rows.length < rowCount,
    [rowCount, rows.length],
  );

  const updateCell = (r: number, c: number, value: string) => {
    setRows((prev) => {
      const next = prev.map((row, i) => (i === r ? [...row] : row));
      next[r][c] = value;
      return next;
    });
    setDirty(true);
  };

  const addRow = () => {
    setRows((prev) => [...prev, columns.map(() => '')]);
    setSelectedRow(rows.length);
    setDirty(true);
  };

  const deleteSelectedRow = () => {
    if (selectedRow === null) return;
    setRows((prev) => prev.filter((_, i) => i !== selectedRow));
    setSelectedRow(null);
    setDirty(true);
  };

  const undoAll = () => {
    setRows(baseline.map((r) => [...r]));
    setDirty(false);
    setSelectedRow(null);
  };

  const downloadCsv = () => {
    const blob = new Blob([toCsv(columns, rows)], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = fileName.endsWith('.csv') ? fileName : `${fileName}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const saveChanges = async () => {
    setSaving(true);
    setError(null);
    try {
      const blob = new Blob([toCsv(columns, rows)], { type: 'text/csv;charset=utf-8' });
      const file = new File([blob], fileName.endsWith('.csv') ? fileName : `${fileName}.csv`, {
        type: 'text/csv',
      });
      await onSaved(file);
      setBaseline(rows.map((r) => [...r]));
      setDirty(false);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Could not save dataset.',
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="dataset-sheet" aria-label="Dataset spreadsheet">
      <header className="dataset-sheet-topbar">
        <div className="dataset-sheet-topbar-left">
          <FileSpreadsheet size={16} />
          <div className="dataset-sheet-title-block">
            <strong title={fileName}>{fileName}</strong>
            <span>
              {rows.length.toLocaleString()} rows × {columns.length} cols
              {dirty ? ' · Unsaved edits' : ''}
              {truncated ? ` · showing first ${rows.length.toLocaleString()} of ${rowCount.toLocaleString()}` : ''}
            </span>
          </div>
        </div>

        <div className="dataset-sheet-topbar-actions">
          <button type="button" className="dataset-sheet-btn" onClick={addRow} disabled={loading || columns.length === 0}>
            <Plus size={14} />
            Add row
          </button>
          <button
            type="button"
            className="dataset-sheet-btn"
            onClick={deleteSelectedRow}
            disabled={selectedRow === null || loading}
            title={selectedRow === null ? 'Select a row first' : 'Delete selected row'}
          >
            <Trash2 size={14} />
            Delete row
          </button>
          <button type="button" className="dataset-sheet-btn" onClick={undoAll} disabled={!dirty || loading}>
            <Undo2 size={14} />
            Discard
          </button>
          <button type="button" className="dataset-sheet-btn" onClick={downloadCsv} disabled={loading || columns.length === 0}>
            <Download size={14} />
            Download
          </button>
          <button
            type="button"
            className="dataset-sheet-btn dataset-sheet-btn--primary"
            onClick={() => void saveChanges()}
            disabled={!dirty || saving || loading}
          >
            <Save size={14} />
            {saving ? 'Saving…' : 'Save'}
          </button>
          <button
            type="button"
            className="dataset-sheet-btn dataset-sheet-btn--icon"
            onClick={onClose}
            aria-label="Close dataset sheet"
            title="Back to canvas"
          >
            <X size={16} />
          </button>
        </div>
      </header>

      <div className="dataset-sheet-body">
        {loading ? (
          <div className="dataset-sheet-status">Loading spreadsheet…</div>
        ) : error ? (
          <div className="dataset-sheet-status is-error" role="alert">
            {error}
          </div>
        ) : columns.length === 0 ? (
          <div className="dataset-sheet-status">This dataset has no columns.</div>
        ) : (
          <div className="dataset-sheet-scroll">
            <table className="dataset-sheet-table">
              <thead>
                <tr>
                  <th className="dataset-sheet-rownum" scope="col">
                    #
                  </th>
                  {columns.map((col) => (
                    <th key={col} scope="col" title={col}>
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, rIdx) => (
                  <tr
                    key={rIdx}
                    className={selectedRow === rIdx ? 'is-selected' : undefined}
                    onClick={() => setSelectedRow(rIdx)}
                  >
                    <th scope="row" className="dataset-sheet-rownum">
                      {rIdx + 1}
                    </th>
                    {row.map((cell, cIdx) => (
                      <td key={`${rIdx}-${cIdx}`}>
                        <input
                          type="text"
                          value={cell}
                          aria-label={`${columns[cIdx]} row ${rIdx + 1}`}
                          onChange={(e) => updateCell(rIdx, cIdx, e.target.value)}
                          onFocus={() => setSelectedRow(rIdx)}
                        />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <footer className="dataset-sheet-footer">
        <span>
          Click a cell to edit. Save uploads a new CSV version to the platform.
        </span>
        {dirty && (
          <span className="dataset-sheet-dirty">
            <Redo2 size={12} />
            Changes not saved
          </span>
        )}
      </footer>
    </section>
  );
}
