import { useEffect, useMemo, useState } from 'react';
import { Filter, X } from 'lucide-react';
import { ApiError } from '../../lib/api';
import { fetchDatasetSchema, type DatasetColumn } from '../../lib/datasets';
import './ToolSidePanel.css';

export type BoardFilters = Record<string, string>;

interface FilterPanelProps {
  open: boolean;
  datasetId: string | null;
  filters: BoardFilters;
  onClose: () => void;
  onChange: (filters: BoardFilters) => void;
}

export function FilterPanel({
  open,
  datasetId,
  filters,
  onClose,
  onChange,
}: FilterPanelProps) {
  const [columns, setColumns] = useState<DatasetColumn[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [column, setColumn] = useState('');
  const [value, setValue] = useState('');

  useEffect(() => {
    if (!open || !datasetId) {
      setColumns([]);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    void fetchDatasetSchema(datasetId)
      .then((res) => {
        if (cancelled) return;
        setColumns(res.columns ?? []);
        setColumn((prev) => prev || res.columns[0]?.name || '');
      })
      .catch((err) => {
        if (cancelled) return;
        setError(
          err instanceof ApiError
            ? err.message
            : err instanceof Error
              ? err.message
              : 'Could not load columns.',
        );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, datasetId]);

  const entries = useMemo(() => Object.entries(filters), [filters]);

  if (!open) return null;

  const addFilter = () => {
    const col = column.trim();
    const val = value.trim();
    if (!col || !val) return;
    onChange({ ...filters, [col]: val });
    setValue('');
  };

  const removeFilter = (key: string) => {
    const next = { ...filters };
    delete next[key];
    onChange(next);
  };

  return (
    <section className="tool-panel" aria-label="Board filters">
      <header className="tool-panel-header">
        <div className="tool-panel-header-title">
          <Filter size={16} />
          <span>Filter</span>
        </div>
        <button type="button" className="tool-panel-close" onClick={onClose} aria-label="Close filter panel">
          <X size={16} />
        </button>
      </header>

      <div className="tool-panel-body">
        <p className="tool-panel-copy">
          Active filters are included when you ask AI Chat, so answers stay focused on the slice you care about.
        </p>

        {!datasetId ? (
          <div className="tool-empty">Upload a CSV first to filter by column.</div>
        ) : loading ? (
          <div className="tool-empty">Loading columns…</div>
        ) : error ? (
          <div className="tool-empty">{error}</div>
        ) : (
          <>
            <div className="tool-panel-section">
              <h3>Add filter</h3>
              <label className="tool-field">
                <span>Column</span>
                <select value={column} onChange={(e) => setColumn(e.target.value)}>
                  {columns.map((col) => (
                    <option key={col.name} value={col.name}>
                      {col.name} ({col.type})
                    </option>
                  ))}
                </select>
              </label>
              <label className="tool-field">
                <span>Value contains</span>
                <input
                  type="text"
                  value={value}
                  placeholder="e.g. Male, 2020, yes"
                  onChange={(e) => setValue(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') addFilter();
                  }}
                />
              </label>
              <button
                type="button"
                className="tool-action-btn"
                onClick={addFilter}
                disabled={!column || !value.trim()}
              >
                <Filter size={16} />
                <span>Apply filter</span>
              </button>
            </div>

            <div className="tool-panel-section">
              <h3>Active ({entries.length})</h3>
              {entries.length === 0 ? (
                <div className="tool-empty">No filters yet.</div>
              ) : (
                <div className="tool-chip-row">
                  {entries.map(([key, val]) => (
                    <button
                      key={key}
                      type="button"
                      className="tool-chip"
                      onClick={() => removeFilter(key)}
                      title="Remove filter"
                    >
                      {key}: {val}
                      <X size={12} />
                    </button>
                  ))}
                </div>
              )}
              {entries.length > 0 && (
                <button type="button" className="tool-action-btn" onClick={() => onChange({})}>
                  Clear all filters
                </button>
              )}
            </div>

            <div className="tool-panel-section">
              <h3>Columns</h3>
              {columns.slice(0, 12).map((col) => (
                <div key={col.name} className="tool-column-row">
                  <strong>{col.name}</strong>
                  <span>{col.type}</span>
                </div>
              ))}
              {columns.length > 12 && (
                <p className="tool-panel-copy">+{columns.length - 12} more columns</p>
              )}
            </div>
          </>
        )}
      </div>
    </section>
  );
}

export function formatFiltersForPrompt(filters: BoardFilters): string {
  const parts = Object.entries(filters)
    .map(([k, v]) => `${k} contains "${v}"`)
    .filter(Boolean);
  if (parts.length === 0) return '';
  return `Please respect these filters: ${parts.join('; ')}. `;
}
