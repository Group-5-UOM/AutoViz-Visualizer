import { useMemo } from 'react';
import { MAX_TABLE_ROWS } from '../../lib/specData';
import './DataTable.css';

/**
 * The result rows behind a chart, as a table.
 *
 * This is the accessibility counterpart to the chart, not a debug view. Three
 * slots of the categorical palette sit below 3:1 contrast on the chart surface;
 * direct labels discharge that for the chart types that can carry one, but
 * scatter (per-point labels are unreadable) and stacked bar (labels collide
 * inside segments) cannot. For those, this table is the relief — the same
 * numbers, readable without depending on colour at all.
 *
 * See Docs/13 §5, §6.1.
 */

const numberFormat = new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 });

function isNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function renderCell(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (isNumber(value)) return numberFormat.format(value);
  return String(value);
}

interface DataTableProps {
  rows: Record<string, unknown>[];
  /** Names the table for screen readers; the widget title is not in this DOM. */
  caption: string;
}

export function DataTable({ rows, caption }: DataTableProps) {
  const columns = useMemo(
    // Union rather than just the first row's keys: a null-bearing result can
    // legitimately omit a key from its first row.
    () => [...new Set(rows.flatMap((row) => Object.keys(row)))],
    [rows],
  );
  const shown = rows.length > MAX_TABLE_ROWS ? rows.slice(0, MAX_TABLE_ROWS) : rows;

  // Right-align a column only if it is numeric throughout, so a mixed column
  // does not get a misleading numeric treatment.
  const numericColumns = useMemo(
    () =>
      new Set(
        columns.filter((col) =>
          rows.every((row) => row[col] == null || isNumber(row[col])),
        ),
      ),
    [columns, rows],
  );

  return (
    <div className="data-table-scroll">
      <table className="data-table">
        <caption className="data-table-caption">{caption}</caption>
        <thead>
          <tr>
            {columns.map((col) => (
              <th
                key={col}
                scope="col"
                className={numericColumns.has(col) ? 'is-numeric' : undefined}
              >
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((row, i) => (
            <tr key={i}>
              {columns.map((col) => (
                <td
                  key={col}
                  className={numericColumns.has(col) ? 'is-numeric' : undefined}
                >
                  {renderCell(row[col])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > shown.length && (
        <p className="data-table-truncation">
          Showing the first {numberFormat.format(shown.length)} of{' '}
          {numberFormat.format(rows.length)} rows.
        </p>
      )}
    </div>
  );
}
