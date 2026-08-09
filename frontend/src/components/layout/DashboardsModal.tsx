import { useEffect, useState, useRef } from 'react';
import { Calendar, Database, FileSpreadsheet, Layers, LayoutDashboard, X, BarChart } from 'lucide-react';
import { listDatasets, type DatasetMetadata } from '../../lib/datasets';
import { getChart, listDashboards, deleteDashboard, type DashboardResult, type SavedChartResult } from '../../lib/dashboards';
import { inferChartType } from '../../lib/chartType';
import './DashboardsModal.css';

export interface SavedDatasetEntry {
  id: string; // Unique key: dashboard.id or dataset.dataset_id
  dataset: DatasetMetadata;
  dashboard: DashboardResult | null;
  chartCount: number;
}

interface DashboardsModalProps {
  open: boolean;
  currentDatasetId?: string | null;
  currentDashboardId?: string | null;
  onClose: () => void;
  onSelect: (entry: SavedDatasetEntry) => void;
}

async function resolveEntries(datasets: DatasetMetadata[]): Promise<SavedDatasetEntry[]> {
  const { dashboards } = await listDashboards();
  const byDataset = new Map<string, { dashboard: DashboardResult; chartCount: number }[]>();

  for (const dataset of datasets) {
    byDataset.set(dataset.dataset_id, []);
  }

  await Promise.all(
    dashboards.map(async (dash) => {
      if (dash.widgets.length === 0) return;
      try {
        const chart = await getChart(dash.widgets[0].chart_id);
        const dataset_id = chart.dataset_id;
        if (!dataset_id) return;
        const list = byDataset.get(dataset_id);
        if (list) {
          list.push({
            dashboard: dash,
            chartCount: dash.widgets.length,
          });
        }
      } catch {
        /* chart may have been deleted */
      }
    }),
  );

  const result: SavedDatasetEntry[] = [];
  for (const dataset of datasets) {
    const list = byDataset.get(dataset.dataset_id) || [];
    if (list.length === 0) {
      result.push({ id: dataset.dataset_id, dataset, dashboard: null, chartCount: 0 });
    } else {
      list.sort((a, b) => new Date(b.dashboard.updated_at).getTime() - new Date(a.dashboard.updated_at).getTime());
      for (const item of list) {
        result.push({ id: item.dashboard.id, dataset, dashboard: item.dashboard, chartCount: item.chartCount });
      }
    }
  }

  return result.sort(
    (a, b) =>
      new Date(b.dataset.created_at).getTime() - new Date(a.dataset.created_at).getTime(),
  );
}

export function DashboardsModal({
  open,
  currentDatasetId,
  currentDashboardId,
  onClose,
  onSelect,
}: DashboardsModalProps) {
  const [entries, setEntries] = useState<SavedDatasetEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [previewCharts, setPreviewCharts] = useState<SavedChartResult[]>([]);
  const [previewLoading, setPreviewLoading] = useState(false);
  const overlayRef = useRef<HTMLDivElement>(null);

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

  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  const handleOverlayClick = (e: React.MouseEvent) => {
    if (e.target === overlayRef.current) onClose();
  };

  const handleDashboardClick = async (entry: SavedDatasetEntry) => {
    setExpandedId(entry.id);
    if (!entry.dashboard) {
      setPreviewCharts([]);
      return;
    }

    setPreviewLoading(true);
    try {
      const charts = await Promise.all(
        entry.dashboard.widgets.map(async (w) => {
          try {
            return await getChart(w.chart_id);
          } catch {
            return null;
          }
        })
      );
      setPreviewCharts(charts.filter(Boolean) as SavedChartResult[]);
    } catch (err) {
      console.error('Failed to load preview charts:', err);
    } finally {
      setPreviewLoading(false);
    }
  };

  if (!open) return null;

  const formatDate = (isoString: string) => {
    const date = new Date(isoString);
    return date.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  };

  const selectedEntry = entries.find(e => e.id === expandedId);
  const isSelectedCurrent = selectedEntry && (
    selectedEntry.dashboard 
      ? selectedEntry.dashboard.id === currentDashboardId 
      : selectedEntry.dataset.dataset_id === currentDatasetId
  );

  return (
    <div className="dashboards-modal-overlay" ref={overlayRef} onClick={handleOverlayClick}>
      <div className="dashboards-modal" role="dialog" aria-modal="true">
        <header className="dashboards-modal-header">
          <h2 className="dashboards-header-title">
            <LayoutDashboard size={18} />
            Your Dashboards
          </h2>
          <button className="modal-close-btn" onClick={onClose} aria-label="Close">
            <X size={20} />
          </button>
        </header>

        <div className="dashboards-modal-body">
          <div className="dashboards-modal-sidebar">
            <div className="dashboards-list-container">
              {loading ? (
                <div className="dashboards-loading">
                  <div className="spinner" />
                  <span>Loading saved datasets…</span>
                </div>
              ) : error ? (
                <div className="dashboards-loading">
                  <span style={{ color: 'var(--danger, #ef4444)' }}>{error}</span>
                </div>
              ) : entries.length === 0 ? (
                <div className="dashboards-empty">
                  <Database size={32} strokeWidth={1} />
                  <h3>No saved datasets</h3>
                  <p>Upload a CSV with Add to see it here.</p>
                </div>
              ) : (
                <div className="dashboards-list">
                  {entries.map((entry) => {
                    const isSelected = expandedId === entry.id;
                    const isCurrent = entry.dashboard 
                      ? entry.dashboard.id === currentDashboardId 
                      : entry.dataset.dataset_id === currentDatasetId;
                    return (
                      <div
                        key={entry.id}
                        className={`dashboard-item ${isSelected ? 'is-selected' : ''} ${isCurrent ? 'is-current' : ''}`}
                        onClick={() => handleDashboardClick(entry)}
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
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>

          <div className="dashboards-modal-content">
            {selectedEntry ? (
              <>
                <div className="dashboard-preview-header">
                  <h3>Preview: {selectedEntry.dashboard ? selectedEntry.dashboard.name : selectedEntry.dataset.logical_name}</h3>
                </div>
                <div className="dashboard-preview-scroll">
                  {previewLoading ? (
                     <div className="dashboards-loading" style={{ paddingTop: 80 }}>
                       <div className="spinner" style={{ width: 32, height: 32 }} />
                       <span>Loading preview...</span>
                     </div>
                  ) : previewCharts.length > 0 ? (
                    <div className="dashboard-preview-grid">
                      {previewCharts.map((chart) => {
                        // We use inferChartType to get a generic type string for the icon/label
                        const chartType = inferChartType({ chartType: chart.chart_spec?.type as any } as any);
                        return (
                          <div key={chart.id} className="dashboard-preview-card">
                            <div className="dashboard-preview-card-icon">
                              <BarChart size={24} />
                            </div>
                            <h4 className="dashboard-preview-card-title" title={chart.name}>{chart.name}</h4>
                            <span style={{ fontSize: 12, color: '#6b7280', textTransform: 'capitalize' }}>
                              {chartType === 'other' ? 'Chart' : chartType}
                            </span>
                          </div>
                        )
                      })}
                    </div>
                  ) : (
                    <div className="dashboard-preview-empty">
                      <LayoutDashboard size={48} strokeWidth={1} style={{ marginBottom: 16 }} />
                      <h3>No charts found</h3>
                      <p>This dataset does not have a saved dashboard.</p>
                    </div>
                  )}
                </div>
                <div className="dashboard-preview-footer" style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                  {selectedEntry.dashboard && (
                    <button
                      className="btn-delete"
                      style={{ backgroundColor: '#ef4444', color: 'white', padding: '8px 16px', borderRadius: '6px', border: 'none', cursor: 'pointer', fontWeight: 500 }}
                      onClick={async () => {
                        if (!window.confirm('Are you sure you want to delete this dashboard? This cannot be undone.')) return;
                        try {
                          await deleteDashboard(selectedEntry.dashboard!.id);
                          setEntries(entries => entries.filter(e => e.id !== selectedEntry.id));
                          setExpandedId(null);
                        } catch (err) {
                          alert('Failed to delete dashboard. It might already be deleted.');
                        }
                      }}
                    >
                      Delete Dashboard
                    </button>
                  )}
                  {!isSelectedCurrent && (
                    <button
                      className="btn-set-active"
                      onClick={() => {
                        onSelect(selectedEntry);
                        onClose();
                      }}
                    >
                      Load Dashboard
                    </button>
                  )}
                </div>
              </>
            ) : (
              <div className="dashboard-preview-empty">
                <LayoutDashboard size={64} strokeWidth={1} style={{ marginBottom: 16 }} />
                <h3>No dashboard selected</h3>
                <p>Select a dataset from the list to preview its dashboard.</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
