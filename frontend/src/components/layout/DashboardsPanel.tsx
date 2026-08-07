import { useEffect, useState } from 'react';
import { Calendar, Database, FileSpreadsheet, Layers } from 'lucide-react';
import { useEscapeToClose } from '../../hooks/useEscapeToClose';
import { listDatasets, type DatasetMetadata } from '../../lib/datasets';
import { getChart, listDashboards, type DashboardResult } from '../../lib/dashboards';
import './DashboardsPanel.css';

export interface SavedDatasetEntry {
  dataset: DatasetMetadata;
  dashboard: DashboardResult | null;
  chartCount: number;
}

interface DashboardsPanelProps {
  open: boolean;
  currentDatasetId?: string | null;
  onClose: () => void;
  onSelect: (entry: SavedDatasetEntry) => void;
}

async function resolveEntries(datasets: DatasetMetadata[]): Promise<SavedDatasetEntry[]> {
  const { dashboards } = await listDashboards();
  const byDataset = new Map<string, { dashboard: DashboardResult; chartCount: number }>();

  await Promise.all(
    dashboards.map(async (dash) => {
      if (dash.widgets.length === 0) return;
      try {
        const chart = await getChart(dash.widgets[0].chart_id);
        if (!chart.dataset_id || byDataset.has(chart.dataset_id)) return;
        byDataset.set(chart.dataset_id, {
          dashboard: dash,
          chartCount: dash.widgets.length,
        });
      } catch {
        /* chart may have been deleted */
      }
    }),
  );

  return datasets
    .map((dataset) => {
      const linked = byDataset.get(dataset.dataset_id);
      return {
        dataset,
        dashboard: linked?.dashboard ?? null,
        chartCount: linked?.chartCount ?? 0,
      };
    })
    .sort(
      (a, b) =>
        new Date(b.dataset.created_at).getTime() - new Date(a.dataset.created_at).getTime(),
    );
}

export function DashboardsPanel({
  open,
  currentDatasetId,
  onClose,
  onSelect,
}: DashboardsPanelProps) {
  const [entries, setEntries] = useState<SavedDatasetEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let mounted = true;
    setLoading(true);
    setError(null);
    void listDatasets()
      .then((res) => resolveEntries(res.datasets ?? []))
      .then((next) => {
        if (mounted) setEntries(next);
      })
      .catch(() => {
        if (mounted) setError('Failed to load saved datasets.');
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [open]);

  useEscapeToClose(onClose, open);

  if (!open) return null;

  const formatDate = (isoString: string) => {
    const date = new Date(isoString);
    return date.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  };

  return (
    <section className="dashboards-panel" aria-label="Saved datasets">
      <div className="dashboards-body">
        {loading ? (
          <div className="dashboard-loading">
            <div className="spinner" />
            <span>Loading saved datasets…</span>
          </div>
        ) : error ? (
          <div className="dashboard-loading">
            <span style={{ color: 'var(--danger, #ef4444)' }}>{error}</span>
          </div>
        ) : entries.length === 0 ? (
          <div className="dashboard-empty">
            <Database size={48} strokeWidth={1} />
            <h3>No saved datasets</h3>
            <p>Upload a CSV with Add to see it here.</p>
          </div>
        ) : (
          <div className="dashboard-list">
            {entries.map((entry) => {
              const isCurrent = entry.dataset.dataset_id === currentDatasetId;
              return (
                <div
                  key={entry.dataset.dataset_id}
                  className={`dashboard-item ${isCurrent ? 'is-current' : ''}`}
                  onClick={() => {
                    if (!isCurrent) onSelect(entry);
                  }}
                  style={{ cursor: isCurrent ? 'default' : 'pointer' }}
                >
                  <div className="dashboard-item-info">
                    <div className="dashboard-item-name" title={entry.dataset.logical_name}>
                      <FileSpreadsheet size={14} style={{ marginRight: 6, verticalAlign: -2 }} />
                      {entry.dataset.logical_name}
                      {isCurrent && <span className="current-badge">Current</span>}
                    </div>
                    <div className="dashboard-item-meta">
                      <span title="Charts on canvas">
                        <Layers size={14} />
                        {entry.chartCount} charts
                        {entry.dashboard ? ` · ${entry.dashboard.name}` : ''}
                      </span>
                      <span title="Uploaded">
                        <Calendar size={14} />
                        {formatDate(entry.dataset.created_at)}
                      </span>
                    </div>
                  </div>
                  <div className="dashboard-item-actions">
                    {!isCurrent && (
                      <button
                        className="btn-load"
                        onClick={(e) => {
                          e.stopPropagation();
                          onSelect(entry);
                        }}
                        title="Load this dataset and canvas"
                      >
                        Load
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}
