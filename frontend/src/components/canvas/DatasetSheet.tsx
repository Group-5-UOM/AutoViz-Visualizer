import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
  type UIEvent,
} from 'react';
import {
  ArrowUpDown,
  Columns3,
  CopyMinus,
  Eraser,
  FileSpreadsheet,
  Filter,
  Pencil,
  Plus,
  Replace,
  Save,
  Scissors,
  Trash2,
  Undo2,
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
type ToolPanel =
  | 'filter'
  | 'replace'
  | 'fill'
  | 'add-row'
  | 'add-column'
  | 'rename-column'
  | 'delete-column'
  | null;
type FilterOp = 'eq' | 'neq' | 'contains' | 'empty' | 'not_empty';
type FillStrategy = 'custom' | 'mean' | 'median' | 'mode' | 'ffill' | 'bfill';

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

const LOAD_LIMIT = 5000;
const ROW_HEIGHT = 32;
const OVERSCAN = 8;

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

function isEmptyCell(value: string): boolean {
  return value.trim() === '';
}

function uniqueColumnName(columns: string[], base: string): string {
  const stem = base.trim() || 'column';
  if (!columns.includes(stem)) return stem;
  let i = 2;
  while (columns.includes(`${stem}_${i}`)) i += 1;
  return `${stem}_${i}`;
}

function columnStats(values: string[]): { mean: string; median: string; mode: string } {
  const nums = values
    .filter((v) => !isEmptyCell(v))
    .map((v) => Number(v))
    .filter((n) => Number.isFinite(n));
  let mean = '';
  let median = '';
  if (nums.length > 0) {
    const sum = nums.reduce((a, b) => a + b, 0);
    mean = String(sum / nums.length);
    const sorted = [...nums].sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    median =
      sorted.length % 2 === 0
        ? String((sorted[mid - 1] + sorted[mid]) / 2)
        : String(sorted[mid]);
  }
  const freq = new Map<string, number>();
  for (const v of values) {
    if (isEmptyCell(v)) continue;
    freq.set(v, (freq.get(v) ?? 0) + 1);
  }
  let mode = '';
  let best = 0;
  for (const [v, count] of freq) {
    if (count > best) {
      best = count;
      mode = v;
    }
  }
  return { mean, median, mode };
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

const SheetCell = memo(function SheetCell({
  value,
  colName,
  rowIndex,
  colIndex,
  colSelected,
  revision,
  onCommit,
  onFocusCell,
}: {
  value: string;
  colName: string;
  rowIndex: number;
  colIndex: number;
  colSelected: boolean;
  revision: number;
  onCommit: (row: number, col: number, value: string) => void;
  onFocusCell: (row: number, col: number) => void;
}) {
  const draftRef = useRef(value);
  const committedRef = useRef(value);

  useEffect(() => {
    draftRef.current = value;
    committedRef.current = value;
  }, [value, revision]);

  useEffect(() => {
    return () => {
      if (draftRef.current !== committedRef.current) {
        onCommit(rowIndex, colIndex, draftRef.current);
      }
    };
  }, [rowIndex, colIndex, onCommit]);

  return (
    <td className={colSelected ? 'is-selected-col' : undefined}>
      <input
        type="text"
        defaultValue={value}
        key={`${revision}:${value}`}
        data-sheet-cell={`${rowIndex}:${colIndex}`}
        aria-label={`${colName} row ${rowIndex + 1}`}
        onChange={(e) => {
          draftRef.current = e.target.value;
        }}
        onBlur={(e) => {
          if (e.target.value !== committedRef.current) {
            onCommit(rowIndex, colIndex, e.target.value);
            committedRef.current = e.target.value;
          }
        }}
        onFocus={() => onFocusCell(rowIndex, colIndex)}
      />
    </td>
  );
});

const SheetRow = memo(function SheetRow({
  row,
  rowIndex,
  columns,
  selected,
  selectedCol,
  revision,
  onCommit,
  onFocusCell,
  onSelectRow,
}: {
  row: string[];
  rowIndex: number;
  columns: string[];
  selected: boolean;
  selectedCol: number | null;
  revision: number;
  onCommit: (row: number, col: number, value: string) => void;
  onFocusCell: (row: number, col: number) => void;
  onSelectRow: (row: number) => void;
}) {
  return (
    <tr
      className={selected ? 'is-selected' : undefined}
      style={{ height: ROW_HEIGHT }}
      onClick={() => onSelectRow(rowIndex)}
    >
      <th scope="row" className="dataset-sheet-rownum">
        {rowIndex + 1}
      </th>
      {row.map((cell, cIdx) => (
        <SheetCell
          key={cIdx}
          value={cell}
          colName={columns[cIdx] ?? `col_${cIdx + 1}`}
          rowIndex={rowIndex}
          colIndex={cIdx}
          colSelected={selectedCol === cIdx}
          revision={revision}
          onCommit={onCommit}
          onFocusCell={onFocusCell}
        />
      ))}
    </tr>
  );
});

export function DatasetSheet({
  datasetId,
  fileName,
  rowCount,
  columnCount,
  onSaved,
}: DatasetSheetProps) {
  const [columns, setColumns] = useState<string[]>([]);
  const [rows, setRows] = useState<CellMatrix>([]);
  const [baselineColumns, setBaselineColumns] = useState<string[]>([]);
  const [baselineRows, setBaselineRows] = useState<CellMatrix>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedRow, setSelectedRow] = useState<number | null>(null);
  const [selectedCol, setSelectedCol] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [revision, setRevision] = useState(0);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(480);
  const [toolPanel, setToolPanel] = useState<ToolPanel>(null);

  const [filterCol, setFilterCol] = useState(0);
  const [filterOp, setFilterOp] = useState<FilterOp>('contains');
  const [filterValue, setFilterValue] = useState('');
  const [replaceCol, setReplaceCol] = useState(0);
  const [replaceFind, setReplaceFind] = useState('');
  const [replaceWith, setReplaceWith] = useState('');
  const [fillCol, setFillCol] = useState<number | 'all'>('all');
  const [fillStrategy, setFillStrategy] = useState<FillStrategy>('custom');
  const [fillValue, setFillValue] = useState('');
  const [addColumnName, setAddColumnName] = useState('column');
  const [addAfterCol, setAddAfterCol] = useState<number | 'end'>('end');
  const [renameCol, setRenameCol] = useState(0);
  const [renameName, setRenameName] = useState('');
  const [deleteCol, setDeleteCol] = useState(0);
  const [addRowPlace, setAddRowPlace] = useState<'before' | 'after'>('after');

  const scrollRef = useRef<HTMLDivElement>(null);
  const sheetRef = useRef<HTMLElement>(null);

  const bump = () => setRevision((v) => v + 1);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const limit = Math.min(Math.max(rowCount || 100, 100), LOAD_LIMIT);
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
        setBaselineColumns([...cols]);
        setBaselineRows(matrix.map((r) => [...r]));
        setDirty(false);
        setSelectedRow(null);
        setSelectedCol(null);
        setScrollTop(0);
        setToolPanel(null);
        bump();
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

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const sync = () => setViewportHeight(el.clientHeight || 480);
    sync();
    const ro = new ResizeObserver(sync);
    ro.observe(el);
    return () => ro.disconnect();
  }, [loading, columns.length]);

  const truncated = useMemo(
    () => rowCount > 0 && rows.length > 0 && rows.length < rowCount,
    [rowCount, rows.length],
  );

  const busy = loading || saving;
  const sheetReady = !loading && columns.length > 0;

  const visibleCount = Math.ceil(viewportHeight / ROW_HEIGHT) + OVERSCAN * 2;
  const startIndex = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN);
  const endIndex = Math.min(rows.length, startIndex + visibleCount);
  const padTop = startIndex * ROW_HEIGHT;
  const padBottom = Math.max(0, (rows.length - endIndex) * ROW_HEIGHT);

  const handleScroll = useCallback((e: UIEvent<HTMLDivElement>) => {
    setScrollTop(e.currentTarget.scrollTop);
  }, []);

  const commitCell = useCallback((r: number, c: number, value: string) => {
    setRows((prev) => {
      if (prev[r]?.[c] === value) return prev;
      const next = prev.slice();
      const row = next[r].slice();
      row[c] = value;
      next[r] = row;
      return next;
    });
    setDirty(true);
  }, []);

  const focusCell = useCallback((r: number, c: number) => {
    setSelectedRow(r);
    setSelectedCol(c);
  }, []);

  const selectRow = useCallback((r: number) => {
    setSelectedRow(r);
  }, []);

  const addRowAt = (index: number) => {
    setRows((prev) => {
      const next = prev.slice();
      next.splice(index, 0, columns.map(() => ''));
      return next;
    });
    setSelectedRow(index);
    setDirty(true);
    bump();
  };

  const applyAddRow = (e: FormEvent) => {
    e.preventDefault();
    if (selectedRow === null) return;
    const insertAt = addRowPlace === 'before' ? selectedRow : selectedRow + 1;
    addRowAt(insertAt);
    setToolPanel(null);
  };

  const deleteRowAt = (index: number | null) => {
    if (index === null) return;
    setRows((prev) => prev.filter((_, i) => i !== index));
    setSelectedRow(null);
    setDirty(true);
    bump();
  };

  const applyAddColumn = (e: FormEvent) => {
    e.preventDefault();
    const insertAt = addAfterCol === 'end' ? columns.length : addAfterCol + 1;
    const colName = uniqueColumnName(columns, addColumnName);
    setColumns((prev) => {
      const next = prev.slice();
      next.splice(insertAt, 0, colName);
      return next;
    });
    setRows((prev) =>
      prev.map((row) => {
        const next = row.slice();
        next.splice(insertAt, 0, '');
        return next;
      }),
    );
    setSelectedCol(insertAt);
    setDirty(true);
    setToolPanel(null);
    bump();
  };

  const applyRenameColumn = (e: FormEvent) => {
    e.preventDefault();
    const trimmed = renameName.trim();
    if (!trimmed) return;
    setColumns((prev) => {
      const next = prev.slice();
      next[renameCol] = uniqueColumnName(
        prev.filter((_, i) => i !== renameCol),
        trimmed,
      );
      return next;
    });
    setSelectedCol(renameCol);
    setDirty(true);
    setToolPanel(null);
    bump();
  };

  const applyDeleteColumn = (e: FormEvent) => {
    e.preventDefault();
    if (columns.length <= 1) return;
    const index = deleteCol;
    setColumns((prev) => prev.filter((_, i) => i !== index));
    setRows((prev) => prev.map((row) => row.filter((_, i) => i !== index)));
    setSelectedCol(null);
    setDirty(true);
    setToolPanel(null);
    bump();
  };

  const discardEdits = () => {
    setColumns([...baselineColumns]);
    setRows(baselineRows.map((r) => [...r]));
    setDirty(false);
    setSelectedRow(null);
    setSelectedCol(null);
    setToolPanel(null);
    bump();
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
      setBaselineColumns([...columns]);
      setBaselineRows(rows.map((r) => [...r]));
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
    bump();
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
    bump();
  };

  const trimWhitespace = () => {
    setRows((prev) => prev.map((row) => row.map((cell) => cell.trim())));
    setDirty(true);
    bump();
  };

  const clearSelectedRow = () => {
    if (selectedRow === null) return;
    setRows((prev) =>
      prev.map((row, i) => (i === selectedRow ? columns.map(() => '') : row)),
    );
    setDirty(true);
    bump();
  };

  const dropEmptyRows = () => {
    setRows((prev) => prev.filter((row) => !row.some((cell) => isEmptyCell(cell))));
    setSelectedRow(null);
    setDirty(true);
    bump();
  };

  const applyFilter = (e: FormEvent) => {
    e.preventDefault();
    setRows((prev) =>
      prev.filter((row) => {
        const cell = row[filterCol] ?? '';
        switch (filterOp) {
          case 'eq':
            return cell === filterValue;
          case 'neq':
            return cell !== filterValue;
          case 'contains':
            return cell.toLowerCase().includes(filterValue.toLowerCase());
          case 'empty':
            return isEmptyCell(cell);
          case 'not_empty':
            return !isEmptyCell(cell);
          default:
            return true;
        }
      }),
    );
    setDirty(true);
    setToolPanel(null);
    bump();
  };

  const applyReplace = (e: FormEvent) => {
    e.preventDefault();
    if (!replaceFind) return;
    setRows((prev) =>
      prev.map((row) => {
        const next = row.slice();
        next[replaceCol] = (next[replaceCol] ?? '').split(replaceFind).join(replaceWith);
        return next;
      }),
    );
    setDirty(true);
    setToolPanel(null);
    bump();
  };

  const applyFillEmpty = (e: FormEvent) => {
    e.preventDefault();
    setRows((prev) => {
      if (fillStrategy === 'ffill' || fillStrategy === 'bfill') {
        const cols =
          fillCol === 'all' ? columns.map((_, i) => i) : [fillCol];
        const next = prev.map((row) => row.slice());
        for (const c of cols) {
          if (fillStrategy === 'ffill') {
            let last = '';
            for (let r = 0; r < next.length; r += 1) {
              if (isEmptyCell(next[r][c] ?? '')) next[r][c] = last;
              else last = next[r][c] ?? '';
            }
          } else {
            let last = '';
            for (let r = next.length - 1; r >= 0; r -= 1) {
              if (isEmptyCell(next[r][c] ?? '')) next[r][c] = last;
              else last = next[r][c] ?? '';
            }
          }
        }
        return next;
      }

      const targetCols =
        fillCol === 'all' ? columns.map((_, i) => i) : [fillCol];
      const fillByCol = new Map<number, string>();
      for (const c of targetCols) {
        if (fillStrategy === 'custom') {
          fillByCol.set(c, fillValue);
          continue;
        }
        const stats = columnStats(prev.map((row) => row[c] ?? ''));
        if (fillStrategy === 'mean') fillByCol.set(c, stats.mean);
        if (fillStrategy === 'median') fillByCol.set(c, stats.median);
        if (fillStrategy === 'mode') fillByCol.set(c, stats.mode);
      }

      return prev.map((row) => {
        const next = row.slice();
        for (const c of targetCols) {
          if (isEmptyCell(next[c] ?? '')) {
            next[c] = fillByCol.get(c) ?? '';
          }
        }
        return next;
      });
    });
    setDirty(true);
    setToolPanel(null);
    bump();
  };

  const toggleTool = (panel: ToolPanel) => {
    setToolPanel((prev) => {
      const next = prev === panel ? null : panel;
      if (next === 'filter' && selectedCol !== null) setFilterCol(selectedCol);
      if (next === 'replace' && selectedCol !== null) setReplaceCol(selectedCol);
      if (next === 'fill' && selectedCol !== null) setFillCol(selectedCol);
      if (next === 'add-row') {
        setAddRowPlace('after');
      }
      if (next === 'add-column') {
        setAddColumnName(uniqueColumnName(columns, 'column'));
        setAddAfterCol(selectedCol === null ? 'end' : selectedCol);
      }
      if (next === 'rename-column') {
        const idx = selectedCol ?? 0;
        setRenameCol(idx);
        setRenameName(columns[idx] ?? '');
      }
      if (next === 'delete-column') {
        setDeleteCol(selectedCol ?? 0);
      }
      return next;
    });
  };

  const editGroups: RibbonGroup[] = [
    {
      group: 'Rows',
      items: [
        {
          label: 'Add Row',
          icon: Plus,
          onClick: () => toggleTool('add-row'),
          disabled: !sheetReady || busy || selectedRow === null,
          active: toolPanel === 'add-row',
          hover:
            selectedRow === null
              ? 'Select a row first, then choose before or after.'
              : 'Insert a row before or after the selected row.',
        },
        {
          label: 'Delete Row',
          icon: Trash2,
          onClick: () => deleteRowAt(selectedRow),
          disabled: selectedRow === null || busy,
          hover: 'Select a row, then delete it.',
        },
        {
          label: 'Clear Row',
          icon: Eraser,
          onClick: clearSelectedRow,
          disabled: selectedRow === null || busy,
          hover: 'Clear all cells in the selected row.',
        },
      ],
    },
    {
      group: 'Columns',
      items: [
        {
          label: 'Add Column',
          icon: Plus,
          onClick: () => toggleTool('add-column'),
          disabled: !sheetReady || busy,
          active: toolPanel === 'add-column',
          hover: 'Insert a new column into the sheet.',
        },
        {
          label: 'Delete Column',
          icon: Trash2,
          onClick: () => toggleTool('delete-column'),
          disabled: !sheetReady || columns.length <= 1 || busy,
          active: toolPanel === 'delete-column',
          hover: 'Remove a column from the sheet.',
        },
        {
          label: 'Rename Column',
          icon: Pencil,
          onClick: () => toggleTool('rename-column'),
          disabled: !sheetReady || busy,
          active: toolPanel === 'rename-column',
          hover: 'Rename an existing column.',
        },
      ],
    },
    {
      group: 'Transform',
      items: [
        {
          label: 'Filter',
          icon: Filter,
          onClick: () => toggleTool('filter'),
          disabled: !sheetReady || busy,
          active: toolPanel === 'filter',
          hover: 'Keep rows that match a column condition.',
        },
        {
          label: 'Replace',
          icon: Replace,
          onClick: () => toggleTool('replace'),
          disabled: !sheetReady || busy,
          active: toolPanel === 'replace',
          hover: 'Find and replace text in a column.',
        },
        {
          label: 'Fill Empty',
          icon: Columns3,
          onClick: () => toggleTool('fill'),
          disabled: !sheetReady || busy,
          active: toolPanel === 'fill',
          hover: 'Fill empty cells with a value or strategy.',
        },
        {
          label: 'Drop Empty',
          icon: Trash2,
          onClick: dropEmptyRows,
          disabled: !sheetReady || busy,
          hover: 'Remove every row that has at least one empty cell.',
        },
        {
          label: 'Sort',
          icon: ArrowUpDown,
          onClick: sortBySelectedColumn,
          disabled: selectedCol === null || busy || !sheetReady,
          hover: 'Sort rows by the selected column.',
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
    {
      group: 'Edits',
      items: [
        {
          label: 'Save',
          icon: Save,
          onClick: () => void saveChanges(),
          disabled: !dirty || busy || !sheetReady,
          hover: dirty ? 'Save edits to AutoViz.' : 'No unsaved edits.',
        },
        {
          label: 'Discard',
          icon: Undo2,
          onClick: discardEdits,
          disabled: !dirty || busy,
          hover: 'Discard unsaved edits.',
        },
      ],
    },
  ];

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
  } else {
    body = (
      <div className="dataset-sheet-scroll" ref={scrollRef} onScroll={handleScroll}>
        <table className="dataset-sheet-table dataset-sheet-table--virtual">
          <thead>
            <tr>
              <th className="dataset-sheet-rownum" scope="col">
                #
              </th>
              {columns.map((col, cIdx) => (
                <th
                  key={`${cIdx}-${col}`}
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
            {padTop > 0 && (
              <tr aria-hidden className="dataset-sheet-spacer">
                <td
                  colSpan={columns.length + 1}
                  style={{ height: padTop, padding: 0, border: 0 }}
                />
              </tr>
            )}
            {rows.slice(startIndex, endIndex).map((row, offset) => {
              const rIdx = startIndex + offset;
              return (
                <SheetRow
                  key={rIdx}
                  row={row}
                  rowIndex={rIdx}
                  columns={columns}
                  selected={selectedRow === rIdx}
                  selectedCol={selectedCol}
                  revision={revision}
                  onCommit={commitCell}
                  onFocusCell={focusCell}
                  onSelectRow={selectRow}
                />
              );
            })}
            {padBottom > 0 && (
              <tr aria-hidden className="dataset-sheet-spacer">
                <td
                  colSpan={columns.length + 1}
                  style={{ height: padBottom, padding: 0, border: 0 }}
                />
              </tr>
            )}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <section className="dataset-sheet" aria-label="Dataset spreadsheet" ref={sheetRef}>
      <header className="dataset-ribbon">
        <div className="dataset-ribbon-meta-bar">
          <div className="dataset-ribbon-meta" title={fileName}>
            <FileSpreadsheet size={14} />
            <strong>{fileName}</strong>
            <span>
              {rows.length.toLocaleString()} × {columns.length || columnCount}
              {dirty ? ' · Unsaved' : ''}
              {truncated
                ? ` · first ${rows.length.toLocaleString()} of ${rowCount.toLocaleString()}`
                : ''}
            </span>
          </div>
        </div>

        <div className="dataset-ribbon-body">
          <RibbonGroups groups={editGroups} />
        </div>
      </header>

      {toolPanel === 'add-row' && selectedRow !== null && (
        <form className="dataset-tool-panel" onSubmit={applyAddRow}>
          <strong>Add Row</strong>
          <p className="dataset-tool-hint">Using selected row {selectedRow + 1}.</p>
          <label>
            Position
            <select
              value={addRowPlace}
              onChange={(e) => setAddRowPlace(e.target.value as 'before' | 'after')}
            >
              <option value="before">Before selected row</option>
              <option value="after">After selected row</option>
            </select>
          </label>
          <div className="dataset-tool-actions">
            <button type="submit" className="dataset-tool-apply">
              Apply
            </button>
            <button type="button" onClick={() => setToolPanel(null)}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {toolPanel === 'add-column' && (
        <form className="dataset-tool-panel" onSubmit={applyAddColumn}>
          <strong>Add Column</strong>
          <label>
            Column name
            <input
              value={addColumnName}
              onChange={(e) => setAddColumnName(e.target.value)}
              placeholder="e.g. region"
              required
            />
          </label>
          <label>
            Insert after
            <select
              value={addAfterCol === 'end' ? 'end' : String(addAfterCol)}
              onChange={(e) =>
                setAddAfterCol(e.target.value === 'end' ? 'end' : Number(e.target.value))
              }
            >
              {columns.map((col, i) => (
                <option key={col} value={i}>
                  {col}
                </option>
              ))}
              <option value="end">End of sheet</option>
            </select>
          </label>
          <div className="dataset-tool-actions">
            <button type="submit" className="dataset-tool-apply" disabled={!addColumnName.trim()}>
              Apply
            </button>
            <button type="button" onClick={() => setToolPanel(null)}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {toolPanel === 'rename-column' && (
        <form className="dataset-tool-panel" onSubmit={applyRenameColumn}>
          <strong>Rename Column</strong>
          <label>
            Column
            <select
              value={renameCol}
              onChange={(e) => {
                const idx = Number(e.target.value);
                setRenameCol(idx);
                setRenameName(columns[idx] ?? '');
              }}
            >
              {columns.map((col, i) => (
                <option key={col} value={i}>
                  {col}
                </option>
              ))}
            </select>
          </label>
          <label>
            New name
            <input
              value={renameName}
              onChange={(e) => setRenameName(e.target.value)}
              required
            />
          </label>
          <div className="dataset-tool-actions">
            <button type="submit" className="dataset-tool-apply" disabled={!renameName.trim()}>
              Apply
            </button>
            <button type="button" onClick={() => setToolPanel(null)}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {toolPanel === 'delete-column' && (
        <form className="dataset-tool-panel" onSubmit={applyDeleteColumn}>
          <strong>Delete Column</strong>
          <label>
            Column
            <select value={deleteCol} onChange={(e) => setDeleteCol(Number(e.target.value))}>
              {columns.map((col, i) => (
                <option key={col} value={i}>
                  {col}
                </option>
              ))}
            </select>
          </label>
          <p className="dataset-tool-hint">This removes the column and its values from the sheet.</p>
          <div className="dataset-tool-actions">
            <button type="submit" className="dataset-tool-apply">
              Apply
            </button>
            <button type="button" onClick={() => setToolPanel(null)}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {toolPanel === 'filter' && (
        <form className="dataset-tool-panel" onSubmit={applyFilter}>
          <strong>Filter</strong>
          <label>
            Column
            <select value={filterCol} onChange={(e) => setFilterCol(Number(e.target.value))}>
              {columns.map((col, i) => (
                <option key={col} value={i}>
                  {col}
                </option>
              ))}
            </select>
          </label>
          <label>
            Condition
            <select
              value={filterOp}
              onChange={(e) => setFilterOp(e.target.value as FilterOp)}
            >
              <option value="contains">Contains</option>
              <option value="eq">Equals</option>
              <option value="neq">Not equals</option>
              <option value="empty">Is empty</option>
              <option value="not_empty">Is not empty</option>
            </select>
          </label>
          {filterOp !== 'empty' && filterOp !== 'not_empty' && (
            <label>
              Value
              <input
                value={filterValue}
                onChange={(e) => setFilterValue(e.target.value)}
                placeholder="Match value"
              />
            </label>
          )}
          <div className="dataset-tool-actions">
            <button type="submit" className="dataset-tool-apply">
              Apply
            </button>
            <button type="button" onClick={() => setToolPanel(null)}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {toolPanel === 'replace' && (
        <form className="dataset-tool-panel" onSubmit={applyReplace}>
          <strong>Replace</strong>
          <label>
            Column
            <select value={replaceCol} onChange={(e) => setReplaceCol(Number(e.target.value))}>
              {columns.map((col, i) => (
                <option key={col} value={i}>
                  {col}
                </option>
              ))}
            </select>
          </label>
          <label>
            Find
            <input
              value={replaceFind}
              onChange={(e) => setReplaceFind(e.target.value)}
              required
            />
          </label>
          <label>
            Replace with
            <input value={replaceWith} onChange={(e) => setReplaceWith(e.target.value)} />
          </label>
          <div className="dataset-tool-actions">
            <button type="submit" className="dataset-tool-apply" disabled={!replaceFind}>
              Apply
            </button>
            <button type="button" onClick={() => setToolPanel(null)}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {toolPanel === 'fill' && (
        <form className="dataset-tool-panel" onSubmit={applyFillEmpty}>
          <strong>Fill Empty</strong>
          <label>
            Column
            <select
              value={fillCol === 'all' ? 'all' : String(fillCol)}
              onChange={(e) =>
                setFillCol(e.target.value === 'all' ? 'all' : Number(e.target.value))
              }
            >
              <option value="all">All columns</option>
              {columns.map((col, i) => (
                <option key={col} value={i}>
                  {col}
                </option>
              ))}
            </select>
          </label>
          <label>
            Strategy
            <select
              value={fillStrategy}
              onChange={(e) => setFillStrategy(e.target.value as FillStrategy)}
            >
              <option value="custom">Custom value</option>
              <option value="mean">Mean</option>
              <option value="median">Median</option>
              <option value="mode">Mode</option>
              <option value="ffill">Forward fill</option>
              <option value="bfill">Backward fill</option>
            </select>
          </label>
          {fillStrategy === 'custom' && (
            <label>
              Fill value
              <input
                value={fillValue}
                onChange={(e) => setFillValue(e.target.value)}
                required
              />
            </label>
          )}
          {(fillStrategy === 'mean' || fillStrategy === 'median' || fillStrategy === 'mode') &&
            fillCol === 'all' && (
              <p className="dataset-tool-hint">
                Mean / median / mode work best on a single column.
              </p>
            )}
          <div className="dataset-tool-actions">
            <button type="submit" className="dataset-tool-apply">
              Apply
            </button>
            <button type="button" onClick={() => setToolPanel(null)}>
              Cancel
            </button>
          </div>
        </form>
      )}

      <div className="dataset-sheet-body">{body}</div>

      <footer className="dataset-sheet-footer">
        <span>
          Click a cell to edit. Select a row or column, then use the toolbar.
        </span>
        {dirty && <span className="dataset-sheet-dirty">Changes not saved</span>}
      </footer>
    </section>
  );
}
