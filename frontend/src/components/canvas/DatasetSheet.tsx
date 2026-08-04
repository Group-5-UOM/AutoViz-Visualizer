import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  ArrowUpDown,
  Columns3,
  CopyMinus,
  Download,
  Eraser,
  FileSpreadsheet,
  Plus,
  Save,
  Scissors,
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
type RibbonTab = 'File' | 'Data' | 'View';

interface RibbonItem {
  label: string;
  icon: typeof Save;
  onClick: () => void;
  disabled?: boolean;
  hover: string;
  active?: boolean;
}

interface RibbonGroup {
  group: string;
  items: RibbonItem[];
}

const RIBBON_TABS: RibbonTab[] = ['File', 'Data', 'View'];

const TAB_DESCRIPTIONS: Record<RibbonTab, string> = {
  File: 'Save, export, discard edits, or close the spreadsheet.',
  Data: 'Add or remove rows and clean values in the sheet.',
  View: 'Inspect columns and sheet status.',
};

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

function RibbonButton({ item }: { item: RibbonItem }) {
  const Icon = item.icon;
  return (
    <button
      type="button"
      className={`dataset-ribbon-btn ${item.active ? 'is-active' : ''}`}
      title={item.hover}
      onClick={item.onClick}
      disabled={item.disabled}
      data-testid={`toolbar-${item.label.toLowerCase().replace(/\s+/g, '-')}`}
    >
      <Icon size={20} strokeWidth={1.75} />
      <span>{item.label}</span>
    </button>
  );
}

function RibbonGroups({ groups }: { groups: RibbonGroup[] }) {
  return (
    <div className="dataset-ribbon-groups">
      {groups.map((section, sectionIdx) => (
        <div key={section.group} className="dataset-ribbon-section">
          {sectionIdx > 0 && <div className="dataset-ribbon-divider" aria-hidden />}
          <div className="dataset-ribbon-group">
            <div className="dataset-ribbon-group-items">
              {section.items.map((item) => (
                <RibbonButton key={item.label} item={item} />
              ))}
            </div>
            <span className="dataset-ribbon-group-label">{section.group}</span>
          </div>
        </div>
      ))}
    </div>
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
  const [selectedCol, setSelectedCol] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [activeTab, setActiveTab] = useState<RibbonTab>('File');
  const [showColumns, setShowColumns] = useState(false);

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
        setSelectedCol(null);
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

  const busy = loading || saving;
  const sheetReady = !loading && columns.length > 0;

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

  const discardEdits = () => {
    setRows(baseline.map((r) => [...r]));
    setDirty(false);
    setSelectedRow(null);
    setSelectedCol(null);
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

  const sortBySelectedColumn = () => {
    if (selectedCol === null) return;
    setRows((prev) => {
      const indexed = prev.map((row, i) => ({ row, i }));
      indexed.sort((a, b) => {
        const left = a.row[selectedCol] ?? '';
        const right = b.row[selectedCol] ?? '';
        const leftNum = Number(left);
        const rightNum = Number(right);
        if (left !== '' && right !== '' && Number.isFinite(leftNum) && Number.isFinite(rightNum)) {
          return leftNum - rightNum;
        }
        return left.localeCompare(right, undefined, { sensitivity: 'base', numeric: true });
      });
      return indexed.map((entry) => entry.row);
    });
    setDirty(true);
  };

  const dropDuplicateRows = () => {
    setRows((prev) => {
      const seen = new Set<string>();
      const next: CellMatrix = [];
      for (const row of prev) {
        const key = row.join('\u0001');
        if (seen.has(key)) continue;
        seen.add(key);
        next.push(row);
      }
      return next;
    });
    setSelectedRow(null);
    setDirty(true);
  };

  const trimWhitespace = () => {
    setRows((prev) => prev.map((row) => row.map((cell) => cell.trim())));
    setDirty(true);
  };

  const clearSelectedRow = () => {
    if (selectedRow === null) return;
    setRows((prev) =>
      prev.map((row, i) => (i === selectedRow ? columns.map(() => '') : row)),
    );
    setDirty(true);
  };

  const ribbonByTab: Record<RibbonTab, RibbonGroup[]> = {
    File: [
      {
        group: 'Save',
        items: [
          {
            label: 'Save',
            icon: Save,
            onClick: () => void saveChanges(),
            disabled: !dirty || busy || !sheetReady,
            hover: dirty
              ? 'Save edits by uploading a new CSV version to AutoViz.'
              : 'No unsaved edits.',
          },
          {
            label: 'Export',
            icon: Download,
            onClick: downloadCsv,
            disabled: !sheetReady || busy,
            hover: 'Download the current sheet as a CSV file.',
          },
          {
            label: 'Discard',
            icon: Undo2,
            onClick: discardEdits,
            disabled: !dirty || busy,
            hover: 'Discard unsaved edits and restore the last loaded sheet.',
          },
        ],
      },
      {
        group: 'Workspace',
        items: [
          {
            label: 'Close',
            icon: X,
            onClick: onClose,
            hover: 'Return to the dashboard canvas.',
          },
        ],
      },
    ],
    Data: [
      {
        group: 'Rows',
        items: [
          {
            label: 'Add Row',
            icon: Plus,
            onClick: addRow,
            disabled: !sheetReady || busy,
            hover: 'Append an empty row to the bottom of the sheet.',
          },
          {
            label: 'Delete Row',
            icon: Trash2,
            onClick: deleteSelectedRow,
            disabled: selectedRow === null || busy,
            hover:
              selectedRow === null
                ? 'Select a row first, then delete it.'
                : 'Delete the selected row.',
          },
          {
            label: 'Clear Row',
            icon: Eraser,
            onClick: clearSelectedRow,
            disabled: selectedRow === null || busy,
            hover:
              selectedRow === null
                ? 'Select a row first, then clear its cells.'
                : 'Clear all cells in the selected row.',
          },
        ],
      },
      {
        group: 'Transform',
        items: [
          {
            label: 'Sort',
            icon: ArrowUpDown,
            onClick: sortBySelectedColumn,
            disabled: selectedCol === null || busy || !sheetReady,
            hover:
              selectedCol === null
                ? 'Click a column header or cell to choose the sort column.'
                : `Sort rows by “${columns[selectedCol]}”.`,
          },
          {
            label: 'Drop Dup',
            icon: CopyMinus,
            onClick: dropDuplicateRows,
            disabled: !sheetReady || busy,
            hover: 'Remove duplicate rows from the sheet.',
          },
          {
            label: 'Trim',
            icon: Scissors,
            onClick: trimWhitespace,
            disabled: !sheetReady || busy,
            hover: 'Trim leading and trailing spaces from every cell.',
          },
        ],
      },
    ],
    View: [
      {
        group: 'Inspect',
        items: [
          {
            label: 'Columns',
            icon: Columns3,
            onClick: () => setShowColumns((v) => !v),
            active: showColumns,
            disabled: !sheetReady,
            hover: 'Show or hide the column list for this dataset.',
          },
          {
            label: 'Sheet',
            icon: FileSpreadsheet,
            onClick: () => setShowColumns(false),
            active: !showColumns,
            hover: 'Show the editable spreadsheet grid.',
          },
        ],
      },
    ],
  };

  let body: ReactNode;
  if (loading) {
    body = <div className="dataset-sheet-status">Loading spreadsheet…</div>;
  } else if (error) {
    body = (
      <div className="dataset-sheet-status is-error" role="alert">
        {error}
      </div>
    );
  } else if (columns.length === 0) {
    body = <div className="dataset-sheet-status">This dataset has no columns.</div>;
  } else if (showColumns) {
    body = (
      <div className="dataset-sheet-columns-panel">
        <h3>Columns ({columns.length})</h3>
        <ul>
          {columns.map((col, idx) => (
            <li key={col}>
              <button
                type="button"
                className={selectedCol === idx ? 'is-active' : undefined}
                onClick={() => setSelectedCol(idx)}
              >
                <span>{col}</span>
                <em>col {idx + 1}</em>
              </button>
            </li>
          ))}
        </ul>
      </div>
    );
  } else {
    body = (
      <div className="dataset-sheet-scroll">
        <table className="dataset-sheet-table">
          <thead>
            <tr>
              <th className="dataset-sheet-rownum" scope="col">
                #
              </th>
              {columns.map((col, cIdx) => (
                <th
                  key={col}
                  scope="col"
                  title={col}
                  className={selectedCol === cIdx ? 'is-selected-col' : undefined}
                  onClick={() => setSelectedCol(cIdx)}
                >
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
                  <td
                    key={`${rIdx}-${cIdx}`}
                    className={selectedCol === cIdx ? 'is-selected-col' : undefined}
                  >
                    <input
                      type="text"
                      value={cell}
                      aria-label={`${columns[cIdx]} row ${rIdx + 1}`}
                      onChange={(e) => updateCell(rIdx, cIdx, e.target.value)}
                      onFocus={() => {
                        setSelectedRow(rIdx);
                        setSelectedCol(cIdx);
                      }}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <section className="dataset-sheet" aria-label="Dataset spreadsheet">
      <header className="dataset-ribbon">
        <div className="dataset-ribbon-tabs">
          <div className="dataset-ribbon-tablist" role="tablist" aria-label="Dataset editor">
            {RIBBON_TABS.map((tabName) => (
              <button
                key={tabName}
                type="button"
                role="tab"
                aria-selected={activeTab === tabName}
                data-testid={`tab-${tabName.toLowerCase()}`}
                title={TAB_DESCRIPTIONS[tabName]}
                className={`dataset-ribbon-tab ${activeTab === tabName ? 'is-active' : ''}`}
                onClick={() => setActiveTab(tabName)}
              >
                {tabName}
              </button>
            ))}
          </div>
          <div className="dataset-ribbon-meta" title={fileName}>
            <FileSpreadsheet size={14} />
            <strong>{fileName}</strong>
            <span>
              {rows.length.toLocaleString()} × {columns.length || columnCount}
              {dirty ? ' · Unsaved' : ''}
              {truncated ? ` · first ${rows.length.toLocaleString()} of ${rowCount.toLocaleString()}` : ''}
            </span>
          </div>
        </div>

        <div className="dataset-ribbon-body" role="tabpanel">
          <RibbonGroups groups={ribbonByTab[activeTab]} />
        </div>
      </header>

      <div className="dataset-sheet-body">{body}</div>

      <footer className="dataset-sheet-footer">
        <span>
          {selectedCol !== null
            ? `Column “${columns[selectedCol]}” selected.`
            : 'Click a cell to edit. Use the ribbon to save, transform, or close.'}
        </span>
        {dirty && <span className="dataset-sheet-dirty">Changes not saved</span>}
      </footer>
    </section>
  );
}
