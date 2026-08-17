import { useEffect, useState, useRef } from 'react';
import { Calendar, Database, FileSpreadsheet, Layers, LayoutDashboard, RotateCcw, X, BarChart } from 'lucide-react';
import { errorMessage } from '../../lib/api';
import { listDatasets, type DatasetMetadata } from '../../lib/datasets';
import { getChart, listDashboards, deleteDashboard, type DashboardResult, type SavedChartResult } from '../../lib/dashboards';
import { inferChartType } from '../../lib/chartType';
import { useEscapeToClose } from '../../hooks/useEscapeToClose';
import { useFocusTrap } from '../../hooks/useFocusTrap';
import { ConfirmDialog } from './ConfirmDialog';
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
  const [previewError, setPreviewError] = useState<string | null>(null);
  // Bumped by the retry button. A counter rather than a boolean so a second
  // attempt after a second failure still re-runs the effect.
  const [attempt, setAttempt] = useState(0);
  /** A failed action on the list — kept apart from `error`, which means the
   *  list itself could not load and replaces the whole panel. */
  const [actionError, setActionError] = useState<string | null>(null);
  /** The dashboard a delete has been requested for, awaiting confirmation. */
  const [pendingDelete, setPendingDelete] = useState<SavedDatasetEntry | null>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  useFocusTrap(dialogRef, open && !pendingDelete);

  const runDelete = async (entry: SavedDatasetEntry) => {
    setPendingDelete(null);
    setActionError(null);
    try {
      await deleteDashboard(entry.dashboard!.id);
      setEntries((current) => current.filter((e) => e.id !== entry.id));
      setExpandedId(null);
    } catch (err) {
      // Was a `window.alert` that guessed at the cause ("It might already be
      // deleted"). The server knows, and now says so.
      setActionError(`Could not delete that dashboard. ${errorMessage(err)}`);
    }
  };

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
      .catch((err: unknown) => {
        // The server's own words, not a generic sentence — "Not signed in" and
        // "Could not reach the server" call for different things from the user.
        if (mounted) setError(errorMessage(err));
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [open, attempt]);

  useEscapeToClose(onClose, open);

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
    setPreviewError(null);
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
      // Without this the pane fell back to "no charts", which is a statement
      // about the dashboard, made because a request failed.
      setPreviewError(errorMessage(err));
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
      <div className="dashboards-modal" role="dialog" aria-modal="true" ref={dialogRef}>
        <header className="dashboards-modal-header">
          <h2 className="dashboards-header-title">
            <LayoutDashboard size={18} />
            Your Dashboards
          </h2>
          <button className="modal-close-btn" onClick={onClose} aria-label="Close">
            <X size={20} />
          </button>
        </header>

        {actionError && (
          <div className="modal-action-error" role="alert">
            <span>{actionError}</span>
            <button type="button" onClick={() => setActionError(null)} aria-label="Dismiss">
              <X size={14} />
            </button>
          </div>
        )}

        <div className="dashboards-modal-body">
          <div className="dashboards-modal-sidebar">
            <div className="dashboards-list-container">
              {loading ? (
                <div className="dashboards-loading">
                  <div className="spinner" />
                  <span>Loading saved datasets…</span>
                </div>
              ) : error ? (
                <div className="dashboards-loading" role="alert">
                  <span style={{ color: 'var(--danger, #ef4444)' }}>{error}</span>
                  <button
                    type="button"
                    className="panel-retry-btn"
                    onClick={() => setAttempt((n) => n + 1)}
                  >
                    <RotateCcw size={13} />
                    Try again
                  </button>
                </div>
              ) : entries.length === 0 ? (
                <div className="dashboards-empty">
                  <Database size={32} strokeWidth={1} />
                  <h3>No saved datasets</h3>
                  <p>Upload a file with Add to see it here.</p>
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
                  ) : previewError ? (
                    <div className="dashboards-loading" style={{ paddingTop: 80 }} role="alert">
                      <span style={{ color: 'var(--danger, #ef4444)' }}>{previewError}</span>
                      <button
                        type="button"
                        className="panel-retry-btn"
                        onClick={() => void handleDashboardClick(selectedEntry)}
                      >
                        <RotateCcw size={13} />
                        Try again
                      </button>
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
                      onClick={() => setPendingDelete(selectedEntry)}
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

      {pendingDelete?.dashboard && (
        <ConfirmDialog
          destructive
          title="Delete this dashboard?"
          body={
            <>
              <p>
                <strong>{pendingDelete.dashboard.name}</strong> —{' '}
                {pendingDelete.chartCount === 1
                  ? '1 chart'
                  : `${pendingDelete.chartCount} charts`}
                .
              </p>
              <p>
                The layout is deleted. The dataset{' '}
                <strong>{pendingDelete.dataset.logical_name}</strong> is kept, so you can
                build a new dashboard from it. This cannot be undone.
              </p>
            </>
          }
          confirmLabel="Delete dashboard"
          onCancel={() => setPendingDelete(null)}
          onConfirm={() => void runDelete(pendingDelete)}
        />
      )}
    </div>
  );
}
